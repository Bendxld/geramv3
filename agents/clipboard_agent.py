# ============================================================
# GERAM OS v2 · clipboard_agent.py
# Historial de portapapeles. CERO tokens, todo local (xclip/xsel +
# una lista en memoria de proceso — se resetea al reiniciar server.py,
# a propósito no vive en Supabase, es info efímera de sesión).
# ============================================================

import logging
import shutil
import subprocess
import threading
import time

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("clipboard_agent")

MAX_HISTORIAL = 50

# Lista de {"texto": ..., "hora": "HH:MM:SS"}, más reciente al final.
_historial = []
_lock = threading.Lock()


def _comando_leer():
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard", "-o"]
    if shutil.which("xsel"):
        return ["xsel", "--clipboard", "--output"]
    return None


def _comando_escribir():
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard"]
    if shutil.which("xsel"):
        return ["xsel", "--clipboard", "--input"]
    return None


def _registrar(texto):
    """Agrega `texto` al historial si es distinto del último
    registrado (evita duplicar la misma entrada en cada poll)."""
    if not texto or not texto.strip():
        return
    with _lock:
        if _historial and _historial[-1]["texto"] == texto:
            return
        _historial.append({"texto": texto, "hora": time.strftime("%H:%M:%S")})
        if len(_historial) > MAX_HISTORIAL:
            del _historial[0]


def obtener_actual():
    """Lee el portapapeles ahora mismo (xclip/xsel) y de paso lo
    agrega al historial si cambió. Devuelve el texto, o {"error": "..."}
    si no hay xclip/xsel instalado o falla la lectura. NUNCA usa Gemini."""
    comando = _comando_leer()
    if not comando:
        return {"error": "no encontré xclip ni xsel instalados. Instala uno con: sudo apt install xclip"}

    try:
        resultado = subprocess.run(comando, capture_output=True, text=True, timeout=5)
        texto = resultado.stdout
    except Exception as e:
        log.error("clipboard_agent: no se pudo leer el portapapeles (%s)", e)
        return {"error": str(e)}

    _registrar(texto)
    return texto


def copiar(texto):
    """Pone `texto` en el portapapeles (y lo agrega al historial).
    Devuelve True/False. NUNCA usa Gemini."""
    comando = _comando_escribir()
    if not comando:
        log.error("clipboard_agent: no hay xclip/xsel instalado, no puedo copiar")
        return False
    try:
        subprocess.run(comando, input=texto, text=True, timeout=5)
    except Exception as e:
        log.error("clipboard_agent: no se pudo copiar al portapapeles (%s)", e)
        return False
    _registrar(texto)
    return True


def historial(limite=10):
    """Últimas `limite` entradas del historial, más reciente primero."""
    with _lock:
        return list(reversed(_historial[-limite:]))


def buscar(texto):
    """Entradas del historial que contengan `texto` (case-insensitive),
    más reciente primero."""
    texto_bajo = texto.lower()
    with _lock:
        return [h for h in reversed(_historial) if texto_bajo in h["texto"].lower()]


def iniciar_monitor(intervalo=2):
    """Hilo en background que revisa el portapapeles cada `intervalo`
    segundos y lo agrega al historial si cambió — así "qué copié hace
    rato" tiene algo que mostrar aunque el usuario nunca haya
    preguntado "qué copié" mientras tanto. CERO tokens (xclip +
    comparar strings). Se llama UNA vez desde server.py al arrancar.
    No hace nada si no hay xclip/xsel instalado."""
    if not _comando_leer():
        log.warning("clipboard_agent: no hay xclip/xsel instalado, el monitor de portapapeles no arranca")
        return

    def _bucle():
        while True:
            obtener_actual()
            time.sleep(intervalo)

    threading.Thread(target=_bucle, daemon=True).start()
    log.info("clipboard_agent: monitor de portapapeles arrancado (cada %ss)", intervalo)
