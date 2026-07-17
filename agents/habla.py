# ============================================================
# GERAM OS v2 · habla.py
# Text-to-speech con dos motores:
#   - edge-tts (voces neuronales de Microsoft, requiere internet):
#     primera opción, mejor calidad.
#   - Piper (local, ligero, ideal para un i3): respaldo offline, o
#     si edge-tts falla por cualquier razón.
#
# generar_audio() siempre entrega un .wav real sin importar cuál de
# los dos motores se usó (edge-tts en realidad devuelve MP3 aunque se
# le pida .wav, así que se convierte con ffmpeg) — el resto del
# sistema (server.py, _reproducir() de aquí abajo) no necesita saber
# cuál se usó.
# ============================================================

import asyncio
import logging
import os
import re
import subprocess
import tempfile
import wave

import config
from agents import offline_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("habla")

# ARREGLO 5: personality.py ya le pide a Gemini que no use markdown,
# pero no siempre obedece — esto es el respaldo por regex para que
# ningún **/*/_/#/`/"- " suelto se cuele ni al chat (ver director.
# procesar_mensaje) ni a la voz (ver generar_audio más abajo). No es un
# parser de markdown real, es best-effort: mejor perder un símbolo raro
# que dejar pasar asteriscos sonando como "asterisco asterisco" en TTS.
_PATRON_ENCABEZADO = re.compile(r"(?m)^\s*#{1,6}\s*")
_PATRON_VINETA = re.compile(r"(?m)^\s*[-*]\s+")
_PATRON_CURSIVA_GUION_BAJO = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")
_PATRON_CURSIVA_ASTERISCO = re.compile(r"(?<!\w)\*([^*\n]+)\*(?!\w)")


def limpiar_markdown(texto):
    """Quita símbolos de markdown (negritas, cursivas, encabezados,
    viñetas, backticks) de `texto` en texto plano. Se aplica tanto al
    texto que se manda a hablar (generar_audio) como al que ve el jefe
    en el chat (ver director.procesar_mensaje)."""
    if not texto:
        return texto
    texto = texto.replace("**", "")
    texto = _PATRON_ENCABEZADO.sub("", texto)
    texto = _PATRON_VINETA.sub("", texto)
    texto = texto.replace("`", "")
    texto = _PATRON_CURSIVA_GUION_BAJO.sub(r"\1", texto)
    texto = _PATRON_CURSIVA_ASTERISCO.sub(r"\1", texto)
    return texto

try:
    from piper import PiperVoice
    _PIPER_DISPONIBLE = True
except ImportError:
    _PIPER_DISPONIBLE = False

try:
    import edge_tts
    _EDGE_TTS_DISPONIBLE = True
except ImportError:
    _EDGE_TTS_DISPONIBLE = False

# Ruta al modelo de voz de Piper (.onnx). Se define en .env como
# PIPER_VOICE_PATH; si no está, se usa esta ruta por defecto (el
# archivo tendrá que descargarse aparte, Piper no lo trae incluido).
_RUTA_VOZ = getattr(config, "PIPER_VOICE_PATH", "modelos/piper/es_MX-claude-medium.onnx")

# Voz neuronal de edge-tts por instancia: IRIS con voz de mujer
# (Paloma, español latino genérico) para su personalidad sarcástica,
# ARES con voz de mujer (Dalia, español mexicano) para su personalidad
# seria propia (ver personality.py). Si EDGE_TTS_VOICE está seteado en
# .env, eso manda sobre esta tabla (para poder forzar cualquier voz a mano).
_VOZ_POR_INSTANCIA = {
    "IRIS": "es-US-PalomaNeural",
    "ARES": "es-MX-DaliaNeural",
}
EDGE_TTS_VOICE = getattr(config, "EDGE_TTS_VOICE", None) or _VOZ_POR_INSTANCIA.get(
    config.INSTANCE_NAME, "es-US-PalomaNeural",
)

_voz_piper = None


def _obtener_voz_piper():
    global _voz_piper
    if not _PIPER_DISPONIBLE:
        raise RuntimeError(
            "habla.py: falta 'piper-tts'. Instálalo con: pip install piper-tts "
            "(y descarga un modelo de voz en español, ej. es_MX o es_ES, desde "
            "https://github.com/rhasspy/piper/blob/master/VOICES.md)"
        )
    if not os.path.exists(_RUTA_VOZ):
        raise RuntimeError(
            f"habla.py: no se encontró el modelo de voz en '{_RUTA_VOZ}'. "
            "Descarga un archivo .onnx de voz en español de Piper y define "
            "PIPER_VOICE_PATH en el .env apuntando a él."
        )
    if _voz_piper is None:
        log.info("habla: cargando voz Piper desde %s", _RUTA_VOZ)
        _voz_piper = PiperVoice.load(_RUTA_VOZ)
    return _voz_piper


def _generar_audio_piper(texto, ruta_salida):
    voz = _obtener_voz_piper()
    with wave.open(ruta_salida, "wb") as wf:
        # synthesize_wav (no synthesize) es el método que escribe
        # directo a un wave.Wave_write y configura el formato solo.
        voz.synthesize_wav(texto, wf)
    return ruta_salida


def _generar_audio_edge_tts(texto, ruta_salida, voz=None):
    """Genera audio con edge-tts y lo convierte a .wav real con ffmpeg
    (edge-tts entrega MP3 aunque se le pida .wav — confirmado con
    `file` sobre los archivos de prueba: "MPEG ADTS, layer III")."""
    if not _EDGE_TTS_DISPONIBLE:
        raise RuntimeError("habla.py: falta 'edge-tts'. Instálalo con: pip install edge-tts")

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        ruta_mp3 = tmp.name

    try:
        comunicador = edge_tts.Communicate(texto, voz or EDGE_TTS_VOICE)
        asyncio.run(comunicador.save(ruta_mp3))

        resultado = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", ruta_mp3, ruta_salida],
            capture_output=True, text=True, timeout=30,
        )
        if resultado.returncode != 0:
            raise RuntimeError(f"ffmpeg no pudo convertir a wav: {resultado.stderr.strip()}")
    finally:
        os.remove(ruta_mp3)

    return ruta_salida


def generar_audio(texto, ruta_salida):
    """Sintetiza `texto` y guarda el audio como .wav real en `ruta_salida`.

    Usa edge-tts (voces neuronales) si hay internet; si no hay, o si
    edge-tts falla por cualquier razón (sin ffmpeg, rate limit, etc),
    cae a Piper (local, offline)."""
    texto = limpiar_markdown(texto)
    if offline_agent.hay_internet():
        try:
            return _generar_audio_edge_tts(texto, ruta_salida)
        except Exception as e:
            log.warning("habla: edge-tts falló, cayendo a Piper (%s)", e)
    else:
        log.info("habla: sin internet, usando Piper directo")

    return _generar_audio_piper(texto, ruta_salida)


def hablar(texto):
    """Convierte `texto` a audio y lo reproduce por las bocinas."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        ruta_temporal = tmp.name

    try:
        generar_audio(texto, ruta_temporal)
        _reproducir(ruta_temporal)
    finally:
        os.remove(ruta_temporal)


def _reproducir(ruta_wav):
    """Reproduce un .wav usando sounddevice (ya es dependencia del
    proyecto para el micrófono, así evitamos otra librería más)."""
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        raise RuntimeError(
            "habla.py: falta 'sounddevice' o 'numpy' para reproducir audio. "
            "Instálalos con: pip install sounddevice numpy"
        )

    with wave.open(ruta_wav, "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        datos = np.frombuffer(frames, dtype=np.int16)
        if wf.getnchannels() > 1:
            datos = datos.reshape(-1, wf.getnchannels())
        sd.play(datos, samplerate=wf.getframerate())
        sd.wait()
