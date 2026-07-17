# ============================================================
# GERAM OS v2 · escuchar.py
# Speech-to-text con faster-whisper. Modelo "small": buen punto
# medio entre precisión y velocidad para correr en un i3.
# ============================================================

import logging

import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("escuchar")

try:
    from faster_whisper import WhisperModel
    _FASTER_WHISPER_DISPONIBLE = True
except ImportError:
    _FASTER_WHISPER_DISPONIBLE = False

_TAMANO_MODELO = getattr(config, "WHISPER_MODEL_SIZE", "small")

# El modelo se carga una sola vez (perezoso) y se reutiliza entre llamadas:
# cargarlo por cada transcripción sería muy pesado para un i3.
_modelo = None


def _obtener_modelo():
    global _modelo
    if not _FASTER_WHISPER_DISPONIBLE:
        raise RuntimeError(
            "escuchar.py: falta 'faster-whisper'. Instálalo con: "
            "pip install faster-whisper"
        )
    if _modelo is None:
        log.info("escuchar: cargando modelo Whisper '%s' (cpu, int8)...", _TAMANO_MODELO)
        _modelo = WhisperModel(_TAMANO_MODELO, device="cpu", compute_type="int8")
        log.info("escuchar: modelo cargado")
    return _modelo


def transcribir_audio(ruta_archivo):
    """Transcribe un archivo .wav a texto, en español."""
    modelo = _obtener_modelo()
    segmentos, _info = modelo.transcribe(ruta_archivo, language="es")
    texto = " ".join(seg.text.strip() for seg in segmentos)
    return texto.strip()


def escuchar_microfono(
    duracion_maxima=15,
    umbral_silencio=300,
    segundos_silencio_para_parar=1.5,
    samplerate=16000,
):
    """Graba del micrófono hasta detectar silencio (o hasta
    `duracion_maxima` segundos) y devuelve el texto transcrito.

    `umbral_silencio` es el nivel de amplitud (RMS) por debajo del
    cual se considera silencio. Puede necesitar ajuste según el
    micrófono real que se use.
    """
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        raise RuntimeError(
            "escuchar.py: falta 'sounddevice' o 'numpy'. Instálalos con: "
            "pip install sounddevice numpy"
        )

    tam_bloque = int(samplerate * 0.25)  # bloques de 250ms
    bloques = []
    bloques_silencio_seguidos = 0
    bloques_para_parar = int(segundos_silencio_para_parar / 0.25)
    max_bloques = int(duracion_maxima / 0.25)

    log.info("escuchar: grabando del micrófono...")
    with sd.InputStream(samplerate=samplerate, channels=1, dtype="int16") as stream:
        for _ in range(max_bloques):
            bloque, _overflow = stream.read(tam_bloque)
            bloques.append(bloque.copy())

            rms = np.sqrt(np.mean(bloque.astype(np.float32) ** 2))
            if rms < umbral_silencio:
                bloques_silencio_seguidos += 1
            else:
                bloques_silencio_seguidos = 0

            if bloques_silencio_seguidos >= bloques_para_parar and len(bloques) > bloques_para_parar:
                break

    log.info("escuchar: grabación terminada, transcribiendo...")
    audio = np.concatenate(bloques, axis=0)

    import tempfile
    import wave

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16 = 2 bytes
            wf.setframerate(samplerate)
            wf.writeframes(audio.tobytes())
        ruta_temporal = tmp.name

    try:
        return transcribir_audio(ruta_temporal)
    finally:
        import os
        os.remove(ruta_temporal)
