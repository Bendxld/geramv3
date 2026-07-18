# ============================================================
# GERAM OS v2 · file_organizer_agent.py
# Organiza archivos y busca por nombre. CERO tokens, todo lógica local
# (os.walk/shutil.move, sin Gemini de por medio).
# ============================================================

import difflib
import logging
import os
import re
import shutil
import time

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("file_organizer_agent")

DESCARGAS_DIR = os.path.expanduser("~/Descargas")

# Carpetas donde vale la pena buscar cuando el jefe pide abrir un
# archivo por nombre y no existe tal cual (typo de voz/texto) — ver
# buscar_similar(). Se incluyen ambos nombres (español/inglés) porque
# este equipo tiene las dos (Descargas y Downloads conviven).
_CARPETAS_BUSQUEDA_APROXIMADA = (
    os.path.expanduser("~/Documents"),
    os.path.expanduser("~/Downloads"),
    DESCARGAS_DIR,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "experimentos"),
)

_CATEGORIAS = {
    "PDFs": (".pdf",),
    "Imagenes": (".jpg", ".jpeg", ".png", ".gif", ".webp"),
    "Documentos": (".doc", ".docx", ".txt", ".xlsx", ".pptx"),
    "Videos": (".mp4", ".mkv", ".avi"),
    "Musica": (".mp3", ".wav", ".flac"),
}
_CARPETA_OTROS = "Otros"


def _categoria_de(nombre_archivo):
    extension = os.path.splitext(nombre_archivo)[1].lower()
    for carpeta, extensiones in _CATEGORIAS.items():
        if extension in extensiones:
            return carpeta
    return _CARPETA_OTROS


def organizar_descargas():
    """Mueve los archivos SUELTOS en la raíz de ~/Descargas (no toca
    lo que ya esté dentro de una subcarpeta) a subcarpetas por tipo,
    creándolas si hace falta. No requiere confirmación: es reversible
    (mover de vuelta es igual de fácil) y no borra nada. CERO tokens.
    Devuelve {"movidos": {"PDFs": 3, ...}, "total": N} o {"error": "..."}."""
    if not os.path.isdir(DESCARGAS_DIR):
        return {"error": f"no encontré la carpeta {DESCARGAS_DIR}"}

    movidos = {}
    try:
        for nombre in os.listdir(DESCARGAS_DIR):
            ruta = os.path.join(DESCARGAS_DIR, nombre)
            if not os.path.isfile(ruta):
                continue  # ya es una subcarpeta, no tocarla

            carpeta = _categoria_de(nombre)
            destino_dir = os.path.join(DESCARGAS_DIR, carpeta)
            os.makedirs(destino_dir, exist_ok=True)

            destino = os.path.join(destino_dir, nombre)
            if os.path.exists(destino):
                # Ya hay un archivo con ese nombre ahí: se le pega el
                # mtime para no perder ninguno en vez de sobreescribir.
                base, ext = os.path.splitext(nombre)
                destino = os.path.join(destino_dir, f"{base}_{int(os.path.getmtime(ruta))}{ext}")

            shutil.move(ruta, destino)
            movidos[carpeta] = movidos.get(carpeta, 0) + 1
    except Exception as e:
        log.error("file_organizer_agent: no se pudo organizar Descargas (%s)", e)
        return {"error": str(e)}

    return {"movidos": movidos, "total": sum(movidos.values())}


def organizar_descargas_texto():
    resultado = organizar_descargas()
    if resultado.get("error"):
        return f"No pude organizar tus descargas: {resultado['error']}"
    if resultado["total"] == 0:
        return "Tus descargas ya estaban organizadas, jefe, no había nada suelto."
    partes = [f"{cantidad} en {carpeta}" for carpeta, cantidad in resultado["movidos"].items()]
    return f"Organicé {resultado['total']} archivos: " + ", ".join(partes) + "."


# Tope de tiempo real: un "busca mi tarea de historia" sin carpeta
# específica recorre TODO el home por default, y en la práctica ese
# home puede tener varias carpetas de proyectos pesadas (venvs con
# nombres que no sea literal "venv", .cache de GBs, etc) — confirmado
# a mano: sin este tope, una búsqueda así se quedó colgada varios
# minutos. Mejor devolver lo que encontró hasta el corte que colgar el
# chat indefinidamente.
_LIMITE_SEGUNDOS_BUSQUEDA = 8
_CARPETAS_IGNORADAS = ("venv", "env", ".venv", "node_modules", "__pycache__")


def buscar_archivo(nombre, directorio=None):
    """Busca archivos cuyo nombre contenga `nombre` (case-insensitive),
    recursivo desde `directorio` (default ~/). Ignora carpetas ocultas
    y las típicas pesadas/irrelevantes (venv, node_modules, __pycache__),
    y corta a los _LIMITE_SEGUNDOS_BUSQUEDA segundos aunque no haya
    terminado de recorrer todo (devuelve lo que encontró hasta ahí, no
    es un error). Devuelve las primeras 10 coincidencias (ruta completa)
    o {"error": "..."}. CERO tokens."""
    directorio = directorio or os.path.expanduser("~")
    nombre_bajo = nombre.lower()
    coincidencias = []
    inicio = time.time()

    try:
        for raiz, carpetas, archivos in os.walk(directorio):
            carpetas[:] = [c for c in carpetas if not c.startswith(".") and c not in _CARPETAS_IGNORADAS]
            for archivo in archivos:
                if nombre_bajo in archivo.lower():
                    coincidencias.append(os.path.join(raiz, archivo))
                    if len(coincidencias) >= 10:
                        return coincidencias
            if time.time() - inicio > _LIMITE_SEGUNDOS_BUSQUEDA:
                log.warning(
                    "file_organizer_agent: búsqueda de '%s' cortada a los %ss (encontré %s hasta ahí)",
                    nombre, _LIMITE_SEGUNDOS_BUSQUEDA, len(coincidencias),
                )
                break
    except Exception as e:
        log.error("file_organizer_agent: no se pudo buscar '%s' (%s)", nombre, e)
        return {"error": str(e)}

    return coincidencias


def buscar_carpeta(nombre, directorio=None):
    """Igual que buscar_archivo() pero para DIRECTORIOS: busca carpetas
    cuyo nombre contenga `nombre` (case-insensitive). Mismas reglas de
    corte/ignorados que buscar_archivo — CERO tokens."""
    directorio = directorio or os.path.expanduser("~")
    nombre_bajo = nombre.lower()
    coincidencias = []
    inicio = time.time()

    try:
        for raiz, carpetas, _archivos in os.walk(directorio):
            carpetas[:] = [c for c in carpetas if not c.startswith(".") and c not in _CARPETAS_IGNORADAS]
            for carpeta in list(carpetas):
                if nombre_bajo in carpeta.lower():
                    coincidencias.append(os.path.join(raiz, carpeta))
                    if len(coincidencias) >= 10:
                        return coincidencias
            if time.time() - inicio > _LIMITE_SEGUNDOS_BUSQUEDA:
                log.warning(
                    "file_organizer_agent: búsqueda de carpeta '%s' cortada a los %ss (encontré %s hasta ahí)",
                    nombre, _LIMITE_SEGUNDOS_BUSQUEDA, len(coincidencias),
                )
                break
    except Exception as e:
        log.error("file_organizer_agent: no se pudo buscar carpeta '%s' (%s)", nombre, e)
        return {"error": str(e)}

    return coincidencias


def buscar_archivo_texto(nombre, directorio=None):
    resultados = buscar_archivo(nombre, directorio)
    if isinstance(resultados, dict) and resultados.get("error"):
        return f"No pude buscar: {resultados['error']}"
    if not resultados:
        return f"No encontré ningún archivo con '{nombre}' en el nombre, jefe."
    return f"Encontré {len(resultados)} archivo(s):\n" + "\n".join(resultados)


def buscar_similar(nombre, cutoff=0.6, max_resultados=3):
    """Busca coincidencias APROXIMADAS de `nombre` (típicamente un typo
    de voz/texto) entre los archivos sueltos de las carpetas más
    relevantes del jefe (Documentos, Descargas/Downloads, experimentos/)
    usando difflib.get_close_matches — CERO tokens, no recorre todo el
    home (para eso está buscar_archivo, que es exacto y sí recorre todo).
    Devuelve una lista de rutas completas (0, 1 o varias), de más a
    menos parecida; un match exacto de nombre también cae acá (similitud
    1.0), así que también resuelve el caso "nombre correcto pero sin
    ruta completa"."""
    candidatos = {}
    for carpeta in _CARPETAS_BUSQUEDA_APROXIMADA:
        if not os.path.isdir(carpeta):
            continue
        try:
            for nombre_archivo in os.listdir(carpeta):
                ruta = os.path.join(carpeta, nombre_archivo)
                if os.path.isfile(ruta):
                    # Si el mismo nombre aparece en más de una carpeta, gana
                    # la primera de _CARPETAS_BUSQUEDA_APROXIMADA (orden de
                    # prioridad), no se sobreescribe.
                    candidatos.setdefault(nombre_archivo, ruta)
        except OSError:
            continue

    coincidencias = difflib.get_close_matches(nombre, candidatos.keys(), n=max_resultados, cutoff=cutoff)
    return [candidatos[c] for c in coincidencias]


def info_descargas():
    """Cuenta los archivos SUELTOS en la raíz de ~/Descargas (sin
    organizar) por categoría. Devuelve {"conteo": {...}, "total": N}
    o {"error": "..."}. CERO tokens."""
    if not os.path.isdir(DESCARGAS_DIR):
        return {"error": f"no encontré la carpeta {DESCARGAS_DIR}"}

    conteo = {}
    try:
        for nombre in os.listdir(DESCARGAS_DIR):
            ruta = os.path.join(DESCARGAS_DIR, nombre)
            if not os.path.isfile(ruta):
                continue
            carpeta = _categoria_de(nombre)
            conteo[carpeta] = conteo.get(carpeta, 0) + 1
    except Exception as e:
        log.error("file_organizer_agent: no se pudo revisar Descargas (%s)", e)
        return {"error": str(e)}

    return {"conteo": conteo, "total": sum(conteo.values())}


def info_descargas_texto():
    resultado = info_descargas()
    if resultado.get("error"):
        return f"No pude revisar tus descargas: {resultado['error']}"
    if resultado["total"] == 0:
        return "No tienes archivos sueltos en Descargas, jefe — o está vacía, o ya está todo organizado."
    partes = [f"{cantidad} en {carpeta}" for carpeta, cantidad in resultado["conteo"].items()]
    return f"Tienes {resultado['total']} archivos sin organizar: " + ", ".join(partes) + "."


# BUG4: "busca en mis archivos uno de X y ábrelo" — combina búsqueda
# exacta (buscar_archivo, substring) con un fallback APROXIMADO por
# difflib para tolerar typos de voz/texto (ej. "yermodinamixa" debe
# encontrar "termodinamica"). Carpetas por default: Descargas primero
# (ahí caen la mayoría de PDFs bajados) y luego todo el home.
_CARPETAS_BUSQUEDA_TOLERANTE = (DESCARGAS_DIR, os.path.expanduser("~"))

_PATRON_PALABRA = re.compile(r"[a-zA-Z0-9áéíóúñÁÉÍÓÚÑ]+")

# Palabras de 1-3 letras (extensiones, conectores) dan demasiados falsos
# positivos en la comparación difflib por palabra — se ignoran al armar
# el índice de palabras del fallback aproximado.
_LONGITUD_MINIMA_PALABRA_APROXIMADA = 4


def _palabras_de_archivos(directorios):
    """Recorre `directorios` (con el mismo tope de tiempo/carpetas
    ignoradas que buscar_archivo) y arma {palabra: ruta_completa} a
    partir de cada palabra (ver _PATRON_PALABRA) de cada nombre de
    archivo encontrado — la base para la comparación difflib de
    buscar_archivo_tolerante."""
    candidatos_por_palabra = {}
    inicio = time.time()
    for directorio in directorios:
        if not os.path.isdir(directorio):
            continue
        try:
            for raiz, carpetas, archivos in os.walk(directorio):
                carpetas[:] = [c for c in carpetas if not c.startswith(".") and c not in _CARPETAS_IGNORADAS]
                for archivo in archivos:
                    ruta = os.path.join(raiz, archivo)
                    for palabra in _PATRON_PALABRA.findall(archivo.lower()):
                        if len(palabra) >= _LONGITUD_MINIMA_PALABRA_APROXIMADA:
                            candidatos_por_palabra.setdefault(palabra, ruta)
                if time.time() - inicio > _LIMITE_SEGUNDOS_BUSQUEDA:
                    log.warning(
                        "file_organizer_agent: búsqueda aproximada cortada a los %ss en '%s'",
                        _LIMITE_SEGUNDOS_BUSQUEDA, directorio,
                    )
                    return candidatos_por_palabra
        except OSError:
            continue
    return candidatos_por_palabra


def buscar_archivo_tolerante(nombre, directorios=None, cutoff=0.6):
    """Busca archivos parecidos a `nombre`: primero substring EXACTO
    (ver buscar_archivo) en cada carpeta de `directorios` (default:
    Descargas y el home completo, ver _CARPETAS_BUSQUEDA_TOLERANTE); si
    no encuentra nada, cae a una comparación APROXIMADA con difflib
    entre `nombre` y cada PALABRA de los nombres de archivo encontrados
    (no el nombre completo, para que un typo dentro de un nombre largo
    tipo "Termodinamica_Cengel_8ed.pdf" también matchee). CERO tokens.
    Devuelve una lista de rutas completas (puede estar vacía, nunca
    lanza ni es un dict de error salvo fallo real de filesystem)."""
    directorios = directorios or _CARPETAS_BUSQUEDA_TOLERANTE

    exactas = []
    vistas = set()
    for directorio in directorios:
        resultado = buscar_archivo(nombre, directorio)
        if isinstance(resultado, dict):
            continue  # error de esa carpeta puntual, se sigue con las demás
        for ruta in resultado:
            if ruta not in vistas:
                vistas.add(ruta)
                exactas.append(ruta)
    if exactas:
        return exactas

    candidatos_por_palabra = _palabras_de_archivos(directorios)
    coincidencias_palabra = difflib.get_close_matches(nombre.lower(), candidatos_por_palabra.keys(), n=5, cutoff=cutoff)

    rutas = []
    vistas = set()
    for palabra in coincidencias_palabra:
        ruta = candidatos_por_palabra[palabra]
        if ruta not in vistas:
            vistas.add(ruta)
            rutas.append(ruta)
    return rutas
