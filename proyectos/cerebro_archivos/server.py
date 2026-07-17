"""
Cerebro de Archivos - backend FastAPI

Escanea un directorio, lo expone como un arbol de nodos/conexiones
(estilo cerebro/red neuronal) y vigila cambios en vivo con watchdog,
avisando a los clientes conectados por WebSocket.

CONFIGURACION
--------------
Se puede cambiar la carpeta vigilada de dos formas:
  1) Copiando .env.example a .env y editando CEREBRO_WATCH_DIR
  2) Editando directamente las constantes de abajo (bloque "CONFIG")
"""
import os
import time
import asyncio
import threading
from collections import deque
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

load_dotenv()

# ============================== CONFIG ==============================
WATCH_DIR = Path(os.environ.get("CEREBRO_WATCH_DIR", str(Path.home()))).expanduser().resolve()
HOST = os.environ.get("CEREBRO_HOST", "127.0.0.1")
PORT = int(os.environ.get("CEREBRO_PORT", "8420"))
MAX_DEPTH = int(os.environ.get("CEREBRO_MAX_DEPTH", "20"))
MAX_CHILDREN = int(os.environ.get("CEREBRO_MAX_CHILDREN", "150"))
MAX_NODES = int(os.environ.get("CEREBRO_MAX_NODES", "6000"))
DEBOUNCE_SECONDS = 0.8

# Carpetas que se ignoran siempre (además de cualquier carpeta oculta,
# es decir cuyo nombre empiece con "."): basura de sistema/cachés/deps
# que no aportan nada a "mis archivos" y arruinarían el conteo de nodos.
EXCLUDE_DIR_NAMES = {
    "node_modules", "__pycache__", "venv", ".venv", "snap",
    "Tela-icon-theme",
}
# ======================================================================

BASE_DIR = Path(__file__).parent

EXT_CATEGORY = {
    # documentos
    ".pdf": "pdf",
    ".md": "doc", ".txt": "doc", ".docx": "doc", ".doc": "doc", ".odt": "doc", ".rtf": "doc",
    # imagenes
    ".png": "imagen", ".jpg": "imagen", ".jpeg": "imagen", ".gif": "imagen",
    ".svg": "imagen", ".webp": "imagen", ".bmp": "imagen",
    # codigo
    ".py": "codigo", ".js": "codigo", ".ts": "codigo", ".html": "codigo", ".css": "codigo",
    ".json": "codigo", ".jsx": "codigo", ".tsx": "codigo", ".sh": "codigo", ".c": "codigo",
    ".cpp": "codigo", ".java": "codigo", ".go": "codigo", ".rs": "codigo",
    # video
    ".mp4": "video", ".mkv": "video", ".avi": "video", ".mov": "video", ".webm": "video",
    # audio
    ".mp3": "audio", ".wav": "audio", ".flac": "audio", ".ogg": "audio", ".m4a": "audio",
}


def categorize(path: Path) -> str:
    if path.is_dir():
        return "carpeta"
    return EXT_CATEGORY.get(path.suffix.lower(), "otro")


def _node(node_id, name, parent, tipo, categoria, path, depth, size=0, extra_count=0):
    return {
        "id": node_id,
        "name": name,
        "parent": parent,
        "type": tipo,          # "carpeta" | "archivo" | "more"
        "category": categoria,  # color category
        "path": path,
        "depth": depth,
        "size": size,
        "extra_count": extra_count,
    }


def _excluir_carpeta(nombre: str) -> bool:
    """Toda carpeta oculta (empieza con '.') o listada en EXCLUDE_DIR_NAMES
    se ignora por completo: ni se escanea su contenido ni se vigila con
    watchdog. Cubre basura de sistema (.cache, .config, .local, .git,
    .mozilla, .thunderbird), dependencias (node_modules, venv,
    __pycache__) y paquetes que no son "archivos míos" (Tela-icon-theme)."""
    return nombre.startswith(".") or nombre in EXCLUDE_DIR_NAMES


def _safe_listdir(path: Path):
    try:
        entradas = list(path.iterdir())
    except (PermissionError, FileNotFoundError, OSError):
        return []
    entradas = [p for p in entradas if not (p.is_dir() and _excluir_carpeta(p.name))]
    return sorted(entradas, key=lambda p: (not p.is_dir(), p.name.lower()))


def scan_tree(root: Path, max_depth=MAX_DEPTH, max_children=MAX_CHILDREN, max_nodes=MAX_NODES):
    """Escanea root y devuelve una lista plana de nodos con relacion parent->id.

    Los IDs se derivan de la ruta absoluta (no de un contador secuencial) para
    que se mantengan estables entre escaneos: si se agrega/borra un archivo en
    cualquier parte del árbol, los nodos que no cambiaron conservan su mismo
    ID. Esto es lo que le permite al frontend distinguir "nodo nuevo" (nace)
    de "nodo que ya existía" (solo se re-dibuja) al comparar dos escaneos.

    Recorre en anchura (BFS, no profundidad) para repartir el presupuesto de
    `max_nodes` de forma pareja: así, si el home tiene una carpeta enorme,
    esta no le come todo el presupuesto a las demás carpetas del primer
    nivel (Documentos, Descargas, proyectos, etc. siempre aparecen).
    """
    nodes = []
    count = 0

    root_id = "root"
    nodes.append(_node(root_id, root.name or str(root), None, "carpeta", "carpeta", str(root), 0))
    count += 1

    cola = deque([(root, root_id, 0)])
    while cola and count < max_nodes:
        path, parent_id, depth = cola.popleft()
        if depth >= max_depth:
            continue

        children = _safe_listdir(path)
        shown = children[:max_children]
        rest = children[max_children:]

        for child in shown:
            if count >= max_nodes:
                break
            is_dir = child.is_dir()
            cat = categorize(child)
            size = 0
            if not is_dir:
                try:
                    size = child.stat().st_size
                except OSError:
                    size = 0
            child_id = str(child)
            nodes.append(_node(
                child_id, child.name, parent_id,
                "carpeta" if is_dir else "archivo",
                cat, str(child), depth + 1, size,
            ))
            count += 1
            if is_dir:
                cola.append((child, child_id, depth + 1))

        if rest and count < max_nodes:
            more_id = f"{path}::more"
            nodes.append(_node(
                more_id, f"+{len(rest)} más", parent_id, "more", "more",
                str(path), depth + 1, extra_count=len(rest),
            ))
            count += 1

    return nodes


# ------------------------- estado compartido -------------------------
class Estado:
    def __init__(self):
        self.tree = scan_tree(WATCH_DIR)
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.lock = threading.Lock()


estado = Estado()

# Movimientos/renombres detectados por watchdog desde el último broadcast.
# Watchdog entrega (src_path, dest_path) para un rename/move — sirve para
# que el frontend reconecte el MISMO nodo a su nueva ruta en vez de matar
# el viejo y crear uno nuevo desde cero (perdiendo su posición en pantalla).
movidos_pendientes: list[tuple[str, str]] = []
movidos_lock = threading.Lock()


async def broadcast_tree(movidos=None):
    data = {
        "type": "estructura",
        "root_path": str(WATCH_DIR),
        "nodes": estado.tree,
        "movidos": [{"desde": s, "hacia": d} for s, d in (movidos or [])],
    }
    dead = []
    for ws in list(estado.clients):
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        estado.clients.discard(ws)


def rescan_and_broadcast():
    with movidos_lock:
        movidos = movidos_pendientes.copy()
        movidos_pendientes.clear()
    with estado.lock:
        estado.tree = scan_tree(WATCH_DIR)
    if estado.loop:
        asyncio.run_coroutine_threadsafe(broadcast_tree(movidos), estado.loop)


class DebouncedHandler(FileSystemEventHandler):
    """Junta ráfagas de eventos (ej: copiar muchos archivos) en un solo rescan.

    También se encarga de vigilar carpetas nuevas: los watches de inotify se
    ponen carpeta por carpeta (no recursive=True) para no gastar watches en
    carpetas excluidas, así que cuando aparece una carpeta nueva (creada o
    movida desde otro lado) hay que agregarle su propio watch a mano — si no,
    todo lo que pase DENTRO de ella queda invisible para siempre.
    """

    def __init__(self, observer):
        self._timer: threading.Timer | None = None
        self._timer_lock = threading.Lock()
        self._observer = observer
        # ruta -> ObservedWatch. watchdog dedupe internamente por (path,
        # handler, recursive): si una carpeta se borra y se vuelve a crear
        # con el MISMO nombre, el watch de inotify original ya murió solo
        # (el kernel lo da de baja), pero el bookkeeping interno de
        # watchdog puede seguir pensando que "ya la estamos vigilando" y
        # entonces no crea un watch nuevo de verdad. Llevando nuestro
        # propio registro podemos des-registrar explícitamente antes de
        # volver a registrar, así el rename/recreate de una carpeta con el
        # mismo nombre no deja de vigilarse silenciosamente.
        self._watches: dict[str, object] = {}
        self._watches_lock = threading.Lock()

    def _schedule(self):
        with self._timer_lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, rescan_and_broadcast)
            self._timer.daemon = True
            self._timer.start()

    def on_any_event(self, event):
        self._schedule()

    def on_moved(self, event):
        with movidos_lock:
            movidos_pendientes.append((event.src_path, event.dest_path))
        if event.is_directory:
            self._vigilar_nueva_carpeta(event.dest_path)

    def on_created(self, event):
        if event.is_directory:
            self._vigilar_nueva_carpeta(event.src_path)

    def vigilar(self, ruta: str):
        """Registra (o re-registra desde cero) el watch de una carpeta puntual."""
        with self._watches_lock:
            anterior = self._watches.pop(ruta, None)
            if anterior is not None:
                try:
                    self._observer.unschedule(anterior)
                except Exception:
                    pass
            try:
                self._watches[ruta] = self._observer.schedule(self, ruta, recursive=False)
            except OSError:
                pass

    def _vigilar_nueva_carpeta(self, ruta):
        try:
            nueva = Path(ruta)
            if _excluir_carpeta(nueva.name):
                return
            for carpeta in _iter_carpetas_a_vigilar(nueva):
                self.vigilar(str(carpeta))
        except Exception:
            pass  # nunca dejamos que un error acá tumbe el hilo del observer


def _iter_carpetas_a_vigilar(root: Path):
    """Recorre root y devuelve cada subcarpeta que hay que vigilar, sin
    entrar nunca a las excluidas (ni siquiera para enumerarlas). Evita
    gastar watches de inotify en carpetas como node_modules o
    Tela-icon-theme, que además ni aparecen en el árbol."""
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _excluir_carpeta(d)]
        yield Path(dirpath)


def start_watchdog():
    observer = Observer()
    handler = DebouncedHandler(observer)
    vigiladas = 0
    for carpeta in _iter_carpetas_a_vigilar(WATCH_DIR):
        handler.vigilar(str(carpeta))
        vigiladas += 1
    print(f"Vigilando {vigiladas} carpetas (excluyendo ocultas y basura conocida)")
    observer.start()
    return observer


# ------------------------------- FastAPI -------------------------------
app = FastAPI(title="Cerebro de Archivos")


@app.on_event("startup")
async def on_startup():
    estado.loop = asyncio.get_event_loop()
    app.state.observer = start_watchdog()


@app.on_event("shutdown")
async def on_shutdown():
    observer = getattr(app.state, "observer", None)
    if observer:
        observer.stop()
        observer.join(timeout=2)


@app.get("/api/estructura")
async def api_estructura():
    with estado.lock:
        return {"root_path": str(WATCH_DIR), "nodes": estado.tree}


@app.get("/api/config")
async def api_config():
    return {
        "watch_dir": str(WATCH_DIR),
        "max_depth": MAX_DEPTH,
        "max_children": MAX_CHILDREN,
        "max_nodes": MAX_NODES,
        "exclude_dirs": sorted(EXCLUDE_DIR_NAMES),
    }


@app.get("/api/carpeta")
async def api_carpeta(path: str):
    """Devuelve TODOS los hijos de una carpeta (usado para expandir el nodo '+N más')."""
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(WATCH_DIR)
    except ValueError:
        return JSONResponse({"error": "fuera del directorio vigilado"}, status_code=400)
    if not target.is_dir():
        return JSONResponse({"error": "no es una carpeta"}, status_code=400)

    children = _safe_listdir(target)
    nodes = []
    for child in children:
        is_dir = child.is_dir()
        size = 0
        if not is_dir:
            try:
                size = child.stat().st_size
            except OSError:
                size = 0
        nodes.append(_node(
            str(child), child.name, None,
            "carpeta" if is_dir else "archivo", categorize(child), str(child), 0, size,
        ))
    return {"path": str(target), "nodes": nodes}


@app.post("/api/abrir")
async def api_abrir(payload: dict):
    """Abre un archivo con la app por defecto del sistema (solo dentro de WATCH_DIR)."""
    import subprocess
    import sys

    path = Path(payload.get("path", "")).expanduser().resolve()
    try:
        path.relative_to(WATCH_DIR)
    except ValueError:
        return JSONResponse({"error": "fuera del directorio vigilado"}, status_code=400)
    if not path.exists():
        return JSONResponse({"error": "no existe"}, status_code=404)

    try:
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            os.startfile(str(path))  # type: ignore[attr-defined]
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    estado.clients.add(websocket)
    try:
        with estado.lock:
            await websocket.send_json({"type": "estructura", "root_path": str(WATCH_DIR), "nodes": estado.tree})
        while True:
            # no esperamos mensajes del cliente, solo mantenemos la conexion viva
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        estado.clients.discard(websocket)


# archivos estaticos (deben ir al final para no tapar las rutas /api y /ws)
app.mount("/css", StaticFiles(directory=str(BASE_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(BASE_DIR / "js")), name="js")


@app.get("/")
async def index():
    return FileResponse(str(BASE_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn

    print(f"Vigilando: {WATCH_DIR}")
    print(f"Abrí http://{HOST}:{PORT} en tu navegador")
    uvicorn.run("server:app", host=HOST, port=PORT, reload=False)
