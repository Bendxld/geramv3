# ============================================================
# GERAM OS v2 · screenshot_agent.py
# Captura la pantalla y (solo si el usuario lo pide) la analiza con
# Gemini Vision.
#
# REGLA DE TOKENS (Fase F): capturar_pantalla() NUNCA gasta tokens,
# solo toma la captura y la guarda — a analizar_pantalla()/
# comparar_opciones() es a las únicas que hay que llamar cuando el
# usuario de verdad quiere que IRIS "piense" sobre lo que ve.
# ============================================================

import logging
import os
import shutil
import subprocess

from agents import balancer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("screenshot_agent")

RUTA_SCREENSHOT = "/tmp/geram_screenshot.png"


def capturar_pantalla():
    """Toma un screenshot (scrot, o gnome-screenshot si scrot no está
    instalado) y lo guarda en RUTA_SCREENSHOT. NO usa tokens, solo
    captura. Devuelve {"ruta": ...} o {"error": "..."}."""
    if shutil.which("scrot"):
        comando = ["scrot", "--overwrite", RUTA_SCREENSHOT]
    elif shutil.which("gnome-screenshot"):
        comando = ["gnome-screenshot", "-f", RUTA_SCREENSHOT]
    else:
        return {"error": "no encontré scrot ni gnome-screenshot instalados. Instala uno con: sudo apt install scrot"}

    try:
        resultado = subprocess.run(comando, capture_output=True, text=True, timeout=10)
        if resultado.returncode != 0:
            return {"error": f"no se pudo capturar la pantalla ({resultado.stderr.strip()[:200]})"}
        if not os.path.exists(RUTA_SCREENSHOT):
            return {"error": "el comando de captura corrió pero no generó el archivo."}
        return {"ruta": RUTA_SCREENSHOT}
    except Exception as e:
        log.error("screenshot_agent: no se pudo capturar la pantalla (%s)", e)
        return {"error": str(e)}


_PROMPT_ANALIZAR = "Describe brevemente lo que ves en esta captura de pantalla."


def analizar_pantalla(pregunta=None):
    """Captura la pantalla Y la manda a Gemini Vision — ESTA SÍ gasta
    tokens (a diferencia de capturar_pantalla()). Si `pregunta` viene,
    se usa como prompt; si no, Gemini describe la pantalla en general.
    Devuelve el texto de la respuesta (nunca lanza excepción)."""
    captura = capturar_pantalla()
    if captura.get("error"):
        return f"No pude capturar tu pantalla: {captura['error']}"

    prompt = pregunta.strip() if pregunta and pregunta.strip() else _PROMPT_ANALIZAR
    return balancer.enviar_mensaje_con_imagen(prompt, captura["ruta"])


_PROMPT_COMPARAR = (
    "El usuario está comparando opciones en pantalla. Analiza lo que ves "
    "y recomienda la mejor opción, explicando brevemente por qué."
)


def comparar_opciones():
    """Captura pantalla + le pide a Gemini que recomiende la mejor
    opción de lo que ve (para "ayúdame a elegir"). ESTA SÍ gasta tokens."""
    captura = capturar_pantalla()
    if captura.get("error"):
        return f"No pude capturar tu pantalla: {captura['error']}"
    return balancer.enviar_mensaje_con_imagen(_PROMPT_COMPARAR, captura["ruta"])
