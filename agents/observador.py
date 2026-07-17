# ============================================================
# GERAM OS v2 · observador.py
# Usa la webcam para ver y (solo si el usuario lo pide) analizar con
# Gemini Vision. Requiere que el botón VISTA del HUD esté activo (ver
# set_vista_activa/vista_esta_activa, actualizado por server.py
# POST /vista cuando el usuario togglea el botón) — si no, director.py
# responde "Activa mi vista primero, jefe" sin siquiera intentar la
# cámara.
#
# REGLA DE TOKENS (Fase F): capturar_foto() NUNCA gasta tokens, solo
# toma la foto y la guarda — analizar_foto()/ver_objeto() son las
# únicas que gastan, y solo corren cuando el usuario pide explícitamente
# "ve esto"/"qué es esto"/"mírame".
# ============================================================

import logging
import os
import shutil
import subprocess

from agents import balancer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("observador")

RUTA_FOTO = "/tmp/geram_webcam.png"

# Estado de la "vista" (cámara), en memoria del proceso — arranca
# apagado, igual que el botón VISTA en el HTML (sin clase "activo").
_vista_activa = False


def set_vista_activa(activo):
    global _vista_activa
    _vista_activa = bool(activo)
    log.info("observador: vista %s", "activada" if _vista_activa else "desactivada")


def vista_esta_activa():
    return _vista_activa


def capturar_foto():
    """Toma una foto con la webcam (fswebcam) y la guarda en
    RUTA_FOTO. NO usa tokens, solo captura. Devuelve {"ruta": ...} o
    {"error": "..."}."""
    if not shutil.which("fswebcam"):
        return {"error": "no encontré fswebcam instalado. Instálalo con: sudo apt install fswebcam"}

    try:
        resultado = subprocess.run(
            ["fswebcam", "--no-banner", "-r", "1280x720", "-q", RUTA_FOTO],
            capture_output=True, text=True, timeout=10,
        )
        if resultado.returncode != 0 or not os.path.exists(RUTA_FOTO):
            return {"error": f"no se pudo tomar la foto ({resultado.stderr.strip()[:200]})"}
        return {"ruta": RUTA_FOTO}
    except Exception as e:
        log.error("observador: no se pudo tomar la foto (%s)", e)
        return {"error": str(e)}


_PROMPT_ANALIZAR = "Describe brevemente lo que ves en esta foto."


def analizar_foto(pregunta=None):
    """Captura foto + la manda a Gemini Vision. ESTA SÍ gasta tokens.
    No revisa el estado de VISTA — eso lo hace director.py ANTES de
    llamar, para poder responder "activa mi vista primero" sin ni
    siquiera intentar la cámara."""
    captura = capturar_foto()
    if captura.get("error"):
        return f"No pude usar la cámara: {captura['error']}"

    prompt = pregunta.strip() if pregunta and pregunta.strip() else _PROMPT_ANALIZAR
    return balancer.enviar_mensaje_con_imagen(prompt, captura["ruta"])


_PROMPT_OBJETO = "¿Qué objeto o cosa me estoy mostrando a la cámara? Sé breve y directo."


def ver_objeto():
    """Captura foto + le pregunta a Gemini qué objeto le muestran (para
    "qué es esto"). ESTA SÍ gasta tokens."""
    captura = capturar_foto()
    if captura.get("error"):
        return f"No pude usar la cámara: {captura['error']}"
    return balancer.enviar_mensaje_con_imagen(_PROMPT_OBJETO, captura["ruta"])
