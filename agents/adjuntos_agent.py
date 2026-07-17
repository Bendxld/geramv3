# ============================================================
# GERAM OS v2 · adjuntos_agent.py
# Adjuntos que el usuario pega/sube directo en el chat (imagen con
# Ctrl+V, PDF por botón o drag&drop) — a diferencia de screenshot_agent/
# observador (que capturan pantalla/cámara), esto es contenido que el
# usuario ya tiene y quiere que IRIS vea/lea.
#
# REGLA DE TOKENS: guardar_adjunto() NUNCA gasta tokens, solo guarda el
# archivo y lo deja "pendiente" — el usuario decide cuándo (y si)
# preguntar algo sobre él. Solo procesar_pendiente() gasta tokens, y
# solo corre cuando el usuario le da enviar (ver server.py /chat, que
# la llama en vez de director.procesar_mensaje si hay algo pendiente).
#
# Un solo adjunto pendiente a la vez (estado en memoria, como
# observador._vista_activa) — este es un sistema de un solo usuario,
# no hace falta más.
# ============================================================

import logging
import os

from agents import balancer, groq_agent, offline_agent, research_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("adjuntos_agent")

_RUTA_IMAGEN_BASE = "/tmp/geram_adjunto_imagen"
_RUTA_PDF = "/tmp/geram_adjunto.pdf"

_EXTENSIONES_IMAGEN = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# Groq tiene contexto de sobra, pero no hace falta mandar un PDF
# completo para responder una pregunta puntual (ver research_agent,
# misma constante ahí para el resumen completo).
_MAX_CARACTERES_PDF = 30000

# {"tipo": "imagen"|"pdf", "ruta": ..., "nombre": ...} o None.
_pendiente = None


def guardar_adjunto(nombre_original, contenido_bytes):
    """Guarda el archivo pegado/subido y lo deja como adjunto
    pendiente — NO lo manda a Gemini/Groq todavía. Devuelve
    {"tipo": ..., "nombre": ...} o {"error": "..."}."""
    global _pendiente
    extension = os.path.splitext(nombre_original)[1].lower()

    if extension in _EXTENSIONES_IMAGEN:
        ruta = _RUTA_IMAGEN_BASE + extension
        tipo = "imagen"
    elif extension == ".pdf":
        ruta = _RUTA_PDF
        tipo = "pdf"
    else:
        return {"error": f"no sé leer archivos '{extension}' todavía (solo imágenes y PDF por ahora)."}

    try:
        with open(ruta, "wb") as f:
            f.write(contenido_bytes)
    except Exception as e:
        log.error("adjuntos_agent: no se pudo guardar '%s' (%s)", nombre_original, e)
        return {"error": str(e)}

    _pendiente = {"tipo": tipo, "ruta": ruta, "nombre": nombre_original}
    log.info("adjuntos_agent: adjunto pendiente '%s' (%s)", nombre_original, tipo)
    return {"tipo": tipo, "nombre": nombre_original}


def hay_pendiente():
    return _pendiente is not None


def descartar_pendiente():
    global _pendiente
    _pendiente = None


_PROMPT_IMAGEN_DEFAULT = "Describe brevemente lo que ves en esta imagen."

# Mismo texto que research_agent._PROMPT_RESUMEN_PDF (duplicado a
# propósito, no importado): acá necesita pasar por _responder_sobre_texto
# para tener el fallback a Ollama, cosa que research_agent.resumir_documento
# no hace (esa función es solo para el flujo de investigación web, que
# siempre asume que hay internet de entrada).
_PROMPT_RESUMEN_PDF = """Lee el siguiente contenido (extraído de un PDF) y genera un resumen completo y detallado.
Incluye: idea principal, puntos clave, datos importantes y conclusión. En español, claro y bien organizado.

Contenido:
{contenido}"""

_PROMPT_PREGUNTA_PDF = """Basándote en el siguiente contenido extraído de un PDF, responde esta pregunta: {pregunta}

Contenido:
{contenido}"""


def _responder_sobre_texto(prompt):
    """Groq primero; si no hay internet (o el modo offline está
    forzado) o Groq falla, cae a Ollama local — mismo patrón que
    director._procesar_chat_normal, así el PDF se puede seguir leyendo
    sin internet en vez de solo devolver error."""
    if offline_agent.modo_offline_forzado() or not offline_agent.hay_internet():
        log.info("adjuntos_agent: sin internet (o forzado), usando Ollama directo para el PDF")
        return offline_agent.obtener_respuesta_offline(prompt=prompt)

    respuesta = groq_agent.generar_contenido(prompt)
    if respuesta.startswith("ERROR:"):
        log.warning("adjuntos_agent: Groq falló pese a haber internet, probando Ollama para el PDF")
        respuesta = offline_agent.obtener_respuesta_offline(prompt=prompt)
    return respuesta


def procesar_pendiente(pregunta=None):
    """Manda el adjunto pendiente a Gemini Vision (imagen) o Groq (PDF)
    y LIMPIA el pendiente de una vez (una sola pregunta por adjunto; si
    el usuario quiere preguntar otra cosa, tiene que volver a
    adjuntarlo). ESTA SÍ gasta tokens. Devuelve el texto de la
    respuesta, o None si no había nada pendiente (para que server.py
    sepa que debe seguir el flujo normal de director.procesar_mensaje)."""
    global _pendiente
    if _pendiente is None:
        return None

    adjunto = _pendiente
    _pendiente = None

    if adjunto["tipo"] == "imagen":
        prompt = pregunta.strip() if pregunta and pregunta.strip() else _PROMPT_IMAGEN_DEFAULT
        return balancer.enviar_mensaje_con_imagen(prompt, adjunto["ruta"])

    # PDF: sin pregunta -> resumen completo; con pregunta -> responde
    # puntual sobre el texto extraído. Ambos pasan por
    # _responder_sobre_texto (Groq con fallback a Ollama sin internet).
    try:
        texto = research_agent.extraer_texto_pdf(adjunto["ruta"])
    except Exception as e:
        log.error("adjuntos_agent: no se pudo leer el PDF '%s' (%s)", adjunto["ruta"], e)
        return f"No pude leer el PDF: {e}"

    if not texto.strip():
        return "No encontré texto legible en ese PDF (¿es un escaneo de imágenes sin OCR?)."

    if not pregunta or not pregunta.strip():
        prompt = _PROMPT_RESUMEN_PDF.format(contenido=texto[:_MAX_CARACTERES_PDF])
    else:
        prompt = _PROMPT_PREGUNTA_PDF.format(pregunta=pregunta.strip(), contenido=texto[:_MAX_CARACTERES_PDF])

    return _responder_sobre_texto(prompt)
