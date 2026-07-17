# ============================================================
# GERAM OS v2 · classroom_agent.py
#
# PLAN B: el administrador de la cuenta escolar bloqueó el acceso de
# la API de Google Classroom (confirmado corriendo el flujo OAuth de
# verdad — ver _google_auth.py, ya NO tiene scopes de Classroom).
# En vez de leer cursos/tareas por API, este agente:
#   - Abre Classroom (o un curso específico) en el navegador para que
#     Mauri lo revise/entregue a mano (igual que nexus_agent.py antes
#     de tener el SSO real: aquí sí es el caso simple de "abrir y ya").
#   - Trackea las tareas manualmente: Mauri se las dicta por voz/texto
#     ("tengo tarea de mate, resolver página 50, para el viernes") y
#     se guardan en Supabase (tabla "tareas", ver el SQL al final del
#     reporte de esta fase) — no hay API de por medio, así que nunca
#     se puede bloquear.
# ============================================================

import logging
import os
import shutil
from datetime import date, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from supabase import create_client

import config
from agents import control_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("classroom_agent")

CLASSROOM_URL = "https://classroom.google.com"
# URL real de "todo lo no entregado, todas las materias" (confirmada
# contra el sitio real: Google redirige a login reconociendo
# service=classroom y un continue= de vuelta a esta misma URL, no es
# un 404 inventado).
ASSIGNMENTS_URL = f"{CLASSROOM_URL}/a/not-turned-in/all"

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Perfil de navegador DEDICADO para Classroom (separado del perfil que
# uses normalmente): Mauri se loguea aquí UNA SOLA VEZ a mano con la
# cuenta escolar (ver preparar_sesion_classroom) y la sesión queda
# guardada en este directorio — resumen_pendientes() la reusa después
# sin volver a pedir login.
_RUTA_PERFIL_NAVEGADOR = os.path.join(_RAIZ, "credenciales", "classroom_browser_profile")
_NAVEGADORES_CONOCIDOS = ("brave-browser", "google-chrome", "chromium-browser", "chromium")

# Cursos conocidos de Mauri: llena aquí el slug -> URL copiando la
# barra de direcciones cuando entres a cada curso en Classroom (algo
# como "https://classroom.google.com/c/XXXXXXXXXXX"). El nombre del
# lado izquierdo es el que se usa para hacer match con lo que diga
# Mauri ("abre el curso de matemáticas" matchea la clave "matematicas").
CURSOS = {
    "matematicas": "https://classroom.google.com/c/XXXX",
    "historia": "https://classroom.google.com/c/XXXX",
}

_cliente = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
TABLA = "tareas"


def _forzar_cuenta_escolar(url):
    """Le agrega ?authuser=<CLASSROOM_ACCOUNT> (o &authuser= si la URL
    ya trae query string) para que Google abra el link con la cuenta
    escolar en vez de la que esté activa por default en el navegador
    (si Mauri tiene varias sesiones de Google abiertas a la vez)."""
    if not config.CLASSROOM_ACCOUNT:
        return url
    separador = "&" if "?" in url else "?"
    return f"{url}{separador}authuser={config.CLASSROOM_ACCOUNT}"


def abrir_classroom():
    """Abre Classroom en el navegador (forzando la cuenta escolar) para
    que Mauri lo revise/entregue a mano (la API está bloqueada por el
    admin de la escuela). Devuelve un mensaje de texto para el usuario."""
    if control_agent.abrir_url(_forzar_cuenta_escolar(CLASSROOM_URL)):
        return "Abrí Classroom, jefe. Recuerda que ahí adentro tienes que navegar tú — el admin de la escuela bloqueó la API."
    return "No pude abrir el navegador para Classroom."


def _buscar_url_curso(nombre):
    """Match flexible contra las claves de CURSOS (case-insensitive,
    substring en cualquier dirección, ej. "mate" matchea "matematicas"
    y viceversa). Devuelve (clave, url) o (None, None) si no hay match."""
    nombre_bajo = nombre.strip().lower()
    for clave, url in CURSOS.items():
        clave_bajo = clave.lower()
        if nombre_bajo in clave_bajo or clave_bajo in nombre_bajo:
            return clave, url
    return None, None


def abrir_curso(nombre):
    """Abre el curso de Classroom que más se parezca a `nombre` (ver
    CURSOS arriba), forzando la cuenta escolar. Devuelve un mensaje de
    texto para el usuario."""
    clave, url = _buscar_url_curso(nombre)
    if not clave:
        return (
            f"No tengo guardada la URL del curso '{nombre}'. Entra a ese curso en Classroom, "
            "copia la URL de la barra de direcciones, y agrégala al diccionario CURSOS en "
            "agents/classroom_agent.py."
        )
    if control_agent.abrir_url(_forzar_cuenta_escolar(url)):
        return f"Abrí {clave} en Classroom, jefe."
    return f"No pude abrir el navegador para {clave}."


# ------------------------------------------------------------
# LECTOR AUTOMÁTICO (Selenium): Classroom carga todo con JavaScript,
# así que un simple httpx no ve nada — esto SÍ renderiza la página de
# verdad, reusando el perfil de navegador ya logueado (ver
# preparar_sesion_classroom). Es el plan PRINCIPAL para "qué tareas
# tengo"; si falla por lo que sea (sesión vencida, Classroom cambió de
# diseño, no hay navegador instalado, etc.) cae solo al tracker manual
# de Supabase (ver listar_tareas_texto en director._procesar_classroom).
# ------------------------------------------------------------

def _ruta_navegador():
    for nombre in _NAVEGADORES_CONOCIDOS:
        ruta = shutil.which(nombre)
        if ruta:
            return ruta
    return None


def _crear_driver(headless=True):
    """WebDriver de Selenium sobre el perfil DEDICADO de Classroom
    (nunca el perfil normal de Mauri). Lanza RuntimeError con mensaje
    claro si no hay un navegador Chromium instalado."""
    ruta_navegador = _ruta_navegador()
    if not ruta_navegador:
        raise RuntimeError(
            "no encontré un navegador Chromium instalado (brave-browser/chromium/google-chrome) "
            "para automatizar Classroom."
        )

    os.makedirs(_RUTA_PERFIL_NAVEGADOR, exist_ok=True)
    opciones = Options()
    opciones.binary_location = ruta_navegador
    opciones.add_argument(f"--user-data-dir={_RUTA_PERFIL_NAVEGADOR}")
    opciones.add_argument("--profile-directory=Default")
    opciones.add_argument("--window-size=1280,1024")
    if headless:
        opciones.add_argument("--headless=new")
    opciones.add_argument("--no-sandbox")
    opciones.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=opciones)


def preparar_sesion_classroom():
    """Abre un navegador VISIBLE con el perfil dedicado para que Mauri
    inicie sesión UNA SOLA VEZ a mano con la cuenta escolar. La sesión
    queda guardada en ese perfil para siempre (hasta que Google la
    invalide) — de ahí en adelante, resumen_pendientes() la reusa sin
    volver a pedir login. Devuelve un mensaje de texto para el usuario
    (nunca lanza excepción)."""
    try:
        driver = _crear_driver(headless=False)
        driver.get(_forzar_cuenta_escolar(ASSIGNMENTS_URL))
    except Exception as e:
        log.error("classroom_agent: no se pudo abrir el perfil de Classroom para login (%s)", e)
        return f"No pude abrir el navegador para loguear Classroom: {e}"

    # A propósito NO se llama driver.quit(): la ventana debe quedarse
    # abierta para que Mauri termine de loguearse a su ritmo (el
    # proceso de chromedriver/Chrome sigue vivo aunque este script
    # termine, no son hijos que mueran con el padre).
    cuenta = config.CLASSROOM_ACCOUNT or "tu cuenta escolar"
    return (
        f"Te abrí una ventana de Brave dedicada para Classroom. Inicia sesión ahí con {cuenta} "
        "y déjala en la página de tareas pendientes. No hace falta que hagas nada más — puedes "
        "cerrar la ventana cuando termines, la sesión ya queda guardada para la próxima vez."
    )


# Nombres reales de los 4 grupos en los que Classroom separa "Asignado"
# (confirmado contra el DOM real, atributo data-id de cada grupo).
# No existe un grupo separado de "vencidas": si algún día aparece uno
# nuevo que no esté en este diccionario, se muestra tal cual (ver
# _ETIQUETAS_GRUPO.get(data_id, data_id) más abajo) en vez de fallar.
_ETIQUETAS_GRUPO = {
    "NO_DUE_DATE": "Sin fecha de entrega",
    "THIS_WEEK": "Esta semana",
    "NEXT_WEEK": "Próxima semana",
    "LATER": "Más tarde",
}


def _leer_items_grupo(grupo_el):
    items = []
    for li in grupo_el.find_elements(By.CSS_SELECTOR, "li"):
        try:
            titulo = li.find_element(By.CSS_SELECTOR, "p.VjRxGc").text
            curso = li.find_element(By.CSS_SELECTOR, "p.tWeh6.YVvGBb").text
        except Exception:
            continue
        items.append({"titulo": titulo, "curso": curso})
    return items


def _expandir_grupo(driver, grupo_el, cuenta, items):
    """Si el grupo tiene más items de los que Classroom renderizó de
    entrada (cuenta > len(items)), clickea su botón "Ver todo" y
    vuelve a leer. Mejor esfuerzo: si no encuentra el botón o el click
    no trae más items, devuelve lo que ya tenía (nunca lanza excepción,
    un grupo que no se pudo expandir no debe tumbar la lectura de los demás)."""
    if cuenta <= len(items):
        return items
    try:
        boton = grupo_el.find_element(By.XPATH, ".//*[contains(text(), 'Ver todo')]")
        driver.execute_script("arguments[0].click();", boton)
        WebDriverWait(driver, 10).until(lambda d: len(grupo_el.find_elements(By.CSS_SELECTOR, "li")) > len(items))
    except Exception as e:
        log.warning("classroom_agent: no pude expandir un grupo para ver todos los items (%s)", e)
        return items
    return _leer_items_grupo(grupo_el)


def resumen_pendientes():
    """Lee DIRECTO de Classroom (navegador headless, perfil ya
    logueado por preparar_sesion_classroom) los grupos de tareas
    "Asignado" (pendientes) tal como los agrupa Classroom mismo.
    Classroom solo renderiza los primeros 5 items de cada grupo de
    entrada; si hay más, se clickea "Ver todo" para traerlos todos
    (ver _expandir_grupo) — "cuenta" siempre es el total real del
    grupo, pero "items" puede traer menos si ese click falla.

    Devuelve {"grupos": [{"grupo","cuenta","items":[{"titulo","curso"}]}], "total": N}
    o {"error": "..."} si algo falla (sesión vencida, Classroom cambió
    de diseño, no hay navegador, etc.) — quien llame debe caer al
    tracker manual en ese caso (ver director._procesar_classroom)."""
    try:
        driver = _crear_driver(headless=True)
    except Exception as e:
        return {"error": str(e)}

    try:
        driver.get(_forzar_cuenta_escolar(ASSIGNMENTS_URL))
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[jsshadow][data-id]"))
            )
        except Exception:
            if "accounts.google.com" in driver.current_url:
                return {"error": "la sesión de Classroom venció o nunca se logueó. Corre preparar_sesion_classroom() e inicia sesión de nuevo."}
            return {"error": "no encontré la vista de tareas pendientes (¿cambió el diseño de Classroom?)."}

        grupos = []
        total = 0
        for grupo_el in driver.find_elements(By.CSS_SELECTOR, "div[jsshadow][data-id]"):
            data_id = grupo_el.get_attribute("data-id")
            try:
                cuenta = int(grupo_el.find_element(By.CSS_SELECTOR, "div.I2pI").text or "0")
            except Exception:
                cuenta = 0

            items = _leer_items_grupo(grupo_el)
            items = _expandir_grupo(driver, grupo_el, cuenta, items)

            grupos.append({"grupo": _ETIQUETAS_GRUPO.get(data_id, data_id), "cuenta": cuenta, "items": items})
            total += cuenta

        return {"grupos": grupos, "total": total}
    except Exception as e:
        log.error("classroom_agent: no se pudo leer Classroom por navegador (%s)", e)
        return {"error": str(e)}
    finally:
        driver.quit()


def resumen_pendientes_texto():
    """Versión en texto de resumen_pendientes(). Devuelve None (en vez
    de un mensaje de error) si el lector automático falló, para que
    director._procesar_classroom pueda caer al tracker manual sin
    mostrarle al usuario un error técnico de Selenium/Classroom."""
    resultado = resumen_pendientes()
    if resultado.get("error"):
        log.warning("classroom_agent: lector automático falló (%s), quien llame debe usar el tracker manual", resultado["error"])
        return None

    if resultado["total"] == 0:
        return "No tienes tareas pendientes en Classroom, jefe."

    lineas = [f"Tienes {resultado['total']} tareas pendientes en Classroom:"]
    for g in resultado["grupos"]:
        if g["cuenta"] == 0:
            continue
        lineas.append(f"\n{g['grupo']} ({g['cuenta']}):")
        for it in g["items"]:
            lineas.append(f"  - {it['curso']}: {it['titulo']}")
        ocultas = g["cuenta"] - len(g["items"])
        if ocultas > 0:
            lineas.append(f"  ...y {ocultas} más ahí mismo (di 'abre classroom' para verlas todas).")
    return "\n".join(lineas)


def recordar_tarea(materia, descripcion, fecha_entrega=None):
    """Guarda una tarea dictada por Mauri (no viene de la API, la
    guarda porque él la dictó). `fecha_entrega`: "YYYY-MM-DD" o None si
    no la mencionó. Devuelve la fila creada (con "id") o {"error": "..."}."""
    fila = {
        "materia": materia,
        "descripcion": descripcion,
        "fecha_entrega": fecha_entrega,
        "completada": False,
        "instancia": config.INSTANCE_NAME,
    }
    try:
        resultado = _cliente.table(TABLA).insert(fila).execute()
        return resultado.data[0] if resultado.data else {"error": "Supabase no devolvió la fila creada."}
    except Exception as e:
        log.error("classroom_agent: no se pudo guardar la tarea (%s)", e)
        return {"error": str(e)}


def listar_tareas(solo_pendientes=True, materia=None):
    """Devuelve las tareas guardadas en Supabase (lista de dicts,
    ordenadas por fecha de entrega más próxima primero, las sin fecha
    al final), o {"error": "..."}. Si `solo_pendientes`, excluye las ya
    marcadas como completadas. Si `materia`, filtra por coincidencia
    parcial case-insensitive (ver _normalizar_materia — con 500+
    tareas por semestre, filtrar por materia es lo que evita que se
    revuelvan todas en una sola lista)."""
    try:
        consulta = _cliente.table(TABLA).select("*")
        if solo_pendientes:
            consulta = consulta.eq("completada", False)
        if materia:
            consulta = consulta.ilike("materia", f"%{materia}%")
        resultado = consulta.execute()
    except Exception as e:
        log.error("classroom_agent: no se pudieron leer las tareas (%s)", e)
        return {"error": str(e)}

    tareas = resultado.data or []
    tareas.sort(key=lambda t: t.get("fecha_entrega") or "9999-99-99")
    return tareas


def listar_tareas_texto(solo_pendientes=True, materia=None, dias=7, limite=15):
    """Versión en texto legible de listar_tareas(), para "qué tareas
    tengo". Agrupada por materia y, si no se pide una materia puntual
    ni "todas", RECORTADA a lo que vence en los próximos `dias` días
    (más lo vencido sin completar, que siempre se muestra) — con
    cientos de tareas por semestre, mandarlas todas de un jalón por
    voz/texto es inútil. `dias=None` = sin recorte (todas)."""
    tareas = listar_tareas(solo_pendientes=solo_pendientes, materia=materia)
    if isinstance(tareas, dict) and tareas.get("error"):
        return f"No pude leer tus tareas: {tareas['error']}"
    if not tareas:
        return "No tienes tareas pendientes, jefe." if not materia else f"No tienes tareas pendientes de '{materia}', jefe."

    if dias is not None:
        limite_fecha = (date.today() + timedelta(days=dias)).isoformat()
        # Sin fecha_entrega: se asume relevante (no hay forma de saber si
        # es lejana), así que también se muestra en la vista recortada.
        visibles = [t for t in tareas if not t.get("fecha_entrega") or t["fecha_entrega"] <= limite_fecha]
    else:
        visibles = tareas

    ocultas_por_fecha = len(tareas) - len(visibles)
    ocultas_por_limite = max(0, len(visibles) - limite)
    visibles = visibles[:limite]

    agrupadas = {}
    for t in visibles:
        agrupadas.setdefault(t["materia"], []).append(t)

    hoy = date.today().isoformat()
    bloques = []
    for materia_grupo, items in agrupadas.items():
        lineas = []
        for t in items:
            if t.get("fecha_entrega"):
                etiqueta = " (VENCIDA)" if t["fecha_entrega"] < hoy else f" (vence {t['fecha_entrega']})"
            else:
                etiqueta = ""
            lineas.append(f"  #{t['id']} {t['descripcion']}{etiqueta}")
        bloques.append(f"{materia_grupo}:\n" + "\n".join(lineas))

    titulo = "Tus tareas pendientes" + (f" de {materia}" if materia else " (próximos {} días)".format(dias) if dias else "")
    texto = titulo + ":\n\n" + "\n\n".join(bloques)

    total_ocultas = ocultas_por_fecha + ocultas_por_limite
    if total_ocultas > 0:
        texto += (
            f"\n\nTienes {total_ocultas} tareas más que no te muestro aquí. "
            "Pregunta por una materia en particular o di 'todas mis tareas' para verlas todas."
        )
    return texto


def completar_tarea(id_tarea):
    """Marca la tarea `id_tarea` como completada. Devuelve True/False."""
    try:
        _cliente.table(TABLA).update({"completada": True}).eq("id", id_tarea).execute()
        return True
    except Exception as e:
        log.error("classroom_agent: no se pudo marcar la tarea %s como completada (%s)", id_tarea, e)
        return False
