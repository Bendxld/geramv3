# ============================================================
# GERAM OS v2 · cerebro_archivos_agent.py
# Puente entre IRIS/ARES y proyectos/cerebro_archivos: consulta
# estadísticas del árbol de archivos (cuántos archivos/carpetas hay en
# total o en un lóbulo puntual) pegándole a la API de su servidor
# FastAPI. Lo arranca solo si hace falta (sin abrir el navegador —
# para eso está el .desktop registrado, ver control_agent.abrir_app).
# CERO tokens, sin Gemini de por medio.
# ============================================================

import logging
import os
import subprocess
import time

import requests

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cerebro_archivos_agent")

_BASE_URL = "http://127.0.0.1:8420"
_RUTA_PROYECTO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "proyectos", "cerebro_archivos"
)
_RUTA_PYTHON_VENV = os.path.join(_RUTA_PROYECTO, "venv", "bin", "python")
_RUTA_SERVER = os.path.join(_RUTA_PROYECTO, "server.py")

_PALABRAS_VACIAS_CARPETA = {"el", "la", "los", "las", "mi", "mis", "del", "de", "total", "general", ""}


def _esta_corriendo():
    try:
        r = requests.get(f"{_BASE_URL}/api/config", timeout=0.6)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _asegurar_servidor_corriendo(espera_maxima=8):
    """Si el servidor ya está corriendo (por ejemplo porque el jefe lo
    abrió con el .desktop) lo reusa tal cual. Si no, lo arranca en
    background SIN abrir el navegador y espera a que conteste."""
    if _esta_corriendo():
        return True
    if not os.path.exists(_RUTA_PYTHON_VENV):
        log.error("cerebro_archivos_agent: no encontré el venv del proyecto en %s", _RUTA_PYTHON_VENV)
        return False
    try:
        subprocess.Popen(
            [_RUTA_PYTHON_VENV, _RUTA_SERVER],
            cwd=_RUTA_PROYECTO,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        log.error("cerebro_archivos_agent: no pude arrancar el servidor: %s", e)
        return False

    inicio = time.time()
    while time.time() - inicio < espera_maxima:
        if _esta_corriendo():
            return True
        time.sleep(0.4)
    return False


def _pertenece_a(nodo_id, raiz_ids, padres):
    actual = nodo_id
    saltos = 0
    while actual and saltos < 64:
        if actual in raiz_ids:
            return True
        actual = padres.get(actual)
        saltos += 1
    return False


def obtener_estadisticas(nombre_carpeta=None):
    """Devuelve {"carpeta": None|str, "archivos": int, "carpetas": int}
    con el total del home, o filtrado a la carpeta principal (lóbulo)
    que coincida con `nombre_carpeta` (substring, insensible a
    mayúsculas). Si no puede consultar, devuelve {"error": str}."""
    if not _asegurar_servidor_corriendo():
        return {"error": "no pude arrancar el servidor del cerebro de archivos"}
    try:
        r = requests.get(f"{_BASE_URL}/api/estructura", timeout=6)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return {"error": str(e)}

    nodos = data.get("nodes", [])

    if nombre_carpeta:
        nombre_bajo = nombre_carpeta.strip().lower()
        raiz_ids = {
            n["id"] for n in nodos
            if n.get("type") == "carpeta" and n.get("depth") == 1 and nombre_bajo in n["name"].lower()
        }
        if not raiz_ids:
            return {"error": f"no encontré ninguna carpeta principal llamada '{nombre_carpeta}'"}
        padres = {n["id"]: n.get("parent") for n in nodos}
        archivos = sum(1 for n in nodos if n.get("type") == "archivo" and _pertenece_a(n["id"], raiz_ids, padres))
        carpetas = sum(
            1 for n in nodos
            if n.get("type") == "carpeta" and n["id"] not in raiz_ids and _pertenece_a(n["id"], raiz_ids, padres)
        )
        nombre_real = next(n["name"] for n in nodos if n["id"] in raiz_ids)
        return {"carpeta": nombre_real, "archivos": archivos, "carpetas": carpetas}

    archivos = sum(1 for n in nodos if n.get("type") == "archivo")
    carpetas = sum(1 for n in nodos if n.get("type") == "carpeta")
    return {"carpeta": None, "archivos": archivos, "carpetas": carpetas}
