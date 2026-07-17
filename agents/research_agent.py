# ============================================================
# GERAM OS v2 · research_agent.py
# Investigador: busca documentos/artículos/videos en internet
# (reusa el buscador de DuckDuckGo de web_agent.py, sin
# API key), descarga PDFs y los resume con Groq (contenido largo,
# igual que director._generar_documento_notion), con oferta de
# guardar el resumen en Notion.
# ============================================================

import logging
import os
import re

import httpx
import pdfplumber

from agents import groq_agent, web_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("research_agent")

_DESCARGAS_DIR = os.path.expanduser("~/Descargas")

# Groq (llama-3.3-70b) tiene contexto de sobra, pero un PDF largo no
# necesita mandarse completo para un buen resumen — esto evita prompts
# gigantes que tardan más y cuestan más sin mejorar el resultado.
_MAX_CARACTERES_PDF = 30000
_MAX_CARACTERES_VIDEO = 30000

_PROMPT_RESUMEN_PDF = """Lee el siguiente contenido (extraído de un PDF) y genera un resumen completo y detallado.
Incluye: idea principal, puntos clave, datos importantes y conclusión. En español, claro y bien organizado.

Contenido:
{contenido}"""

_PROMPT_RESUMEN_VIDEO = """Lee la siguiente transcripción de un video de YouTube y genera un resumen completo y detallado.
Incluye: idea principal, puntos clave, datos importantes y conclusión. En español, claro y bien organizado.

Transcripción:
{contenido}"""


def _cabeceras_descarga():
    return {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) GeramOS/2.0"}


def buscar_documentos(tema, tipo="pdf", limite=5):
    """Busca `tema` en DuckDuckGo restringido a archivos de `tipo`
    (usa el operador filetype:, ej. "termodinámica filetype:pdf").
    Devuelve lista de {"titulo","url","descripcion"} o {"error": "..."}."""
    resultados = web_agent.buscar_web(f"{tema} filetype:{tipo}", limite=limite * 2)
    if isinstance(resultados, dict) and resultados.get("error"):
        return resultados

    filtrados = [r for r in resultados if r["url"].lower().split("?")[0].endswith(f".{tipo}")]
    return (filtrados or resultados)[:limite]


def buscar_articulos(tema, limite=5):
    """Busca artículos/páginas web sobre `tema` (búsqueda web genérica,
    sin restringir tipo de archivo). Devuelve top `limite` como lista
    de {"titulo","url","descripcion"} o {"error": "..."}."""
    return web_agent.buscar_web(tema, limite=limite)


def _oembed_youtube(url):
    """Endpoint oEmbed oficial de YouTube (público, sin API key): da
    título y canal reales sin tener que parsear la SPA de YouTube.
    None si el video ya no existe o el request falla."""
    try:
        respuesta = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            headers=_cabeceras_descarga(), timeout=10,
        )
        respuesta.raise_for_status()
        datos = respuesta.json()
        return {"titulo": datos.get("title", ""), "canal": datos.get("author_name", "")}
    except Exception:
        return None


_PATRON_VIDEO_ID = re.compile(r"youtube\.com/watch/?(?:\?v=)?([a-zA-Z0-9_-]{11})", re.I)

# Más general que _PATRON_VIDEO_ID (que solo normaliza resultados de
# DuckDuckGo, ver _url_canonica_video): reconoce cualquier link real de
# YouTube (watch, youtu.be corto, embed) — usado por resumir_video_
# youtube/procesar_seleccion para sacar el ID de un link que el jefe
# pegó directo, no solo de un resultado de búsqueda.
_PATRON_VIDEO_ID_GENERAL = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})", re.I)


def _es_youtube(url):
    """True si `url` es un link de YouTube (watch, youtu.be corto, o
    embed) — usado por procesar_seleccion para decidir si resume vía
    transcripción (ver resumir_video_youtube) en vez de descargar un
    archivo como si fuera un documento."""
    return bool(_PATRON_VIDEO_ID_GENERAL.search(url or ""))


def _id_video(url):
    coincidencia = _PATRON_VIDEO_ID_GENERAL.search(url or "")
    return coincidencia.group(1) if coincidencia else None


def _url_canonica_video(url):
    """DuckDuckGo a veces devuelve el link de YouTube en formatos raros
    (ej. "youtube.com/watch/<id>" sin "?v=", o "/WATCH/" en mayúsculas)
    que el oEmbed oficial rechaza con 404. Esto saca el ID de 11
    caracteres de cualquier variante y arma la URL canónica
    "watch?v=<id>", que sí es válida siempre."""
    coincidencia = _PATRON_VIDEO_ID.search(url)
    if not coincidencia:
        return None
    return f"https://www.youtube.com/watch?v={coincidencia.group(1)}"


def buscar_youtube(tema, limite=5):
    """Busca videos de YouTube sobre `tema` (DuckDuckGo restringido a
    youtube.com/watch, título/canal confirmados vía oEmbed oficial de
    YouTube). Devuelve lista de {"titulo","url","canal"} o {"error": "..."}."""
    resultados = web_agent.buscar_web(f"{tema} site:youtube.com/watch", limite=limite * 3)
    if isinstance(resultados, dict) and resultados.get("error"):
        return resultados

    videos = []
    vistos = set()
    for r in resultados:
        url_canonica = _url_canonica_video(r["url"])
        if not url_canonica or url_canonica in vistos:
            continue
        vistos.add(url_canonica)

        datos_oembed = _oembed_youtube(url_canonica)
        if not datos_oembed:
            continue  # video borrado/privado: oEmbed 404, mejor no mostrarlo con datos inventados
        videos.append({"titulo": datos_oembed["titulo"], "url": url_canonica, "canal": datos_oembed["canal"]})
        if len(videos) >= limite:
            break

    return videos


def descargar_documento(url, nombre_archivo):
    """Descarga `url` a ~/Descargas/`nombre_archivo`. Devuelve
    {"ruta": "..."} o {"error": "..."}."""
    try:
        os.makedirs(_DESCARGAS_DIR, exist_ok=True)
        ruta = os.path.join(_DESCARGAS_DIR, nombre_archivo)

        with httpx.stream("GET", url, headers=_cabeceras_descarga(), timeout=30, follow_redirects=True) as respuesta:
            respuesta.raise_for_status()
            with open(ruta, "wb") as f:
                for chunk in respuesta.iter_bytes():
                    f.write(chunk)

        return {"ruta": ruta}
    except Exception as e:
        log.error("research_agent: no se pudo descargar '%s' (%s)", url, e)
        return {"error": str(e)}


def extraer_texto_pdf(ruta_archivo):
    """Público (además de resumir_documento más abajo, adjuntos_agent.py
    también la usa para responder preguntas puntuales sobre un PDF que
    el usuario sube directo, sin pasar por un resumen completo)."""
    partes = []
    with pdfplumber.open(ruta_archivo) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if texto:
                partes.append(texto)
    return "\n".join(partes)


def resumir_documento(ruta_archivo):
    """Lee el PDF en `ruta_archivo` y lo manda a Groq para un resumen
    completo. Devuelve el texto del resumen (empieza con "ERROR:" si
    algo falla, nunca lanza excepción) con la oferta de guardarlo en
    Notion al final."""
    if not os.path.exists(ruta_archivo):
        return f"ERROR: no encuentro el archivo '{ruta_archivo}'."

    try:
        texto = extraer_texto_pdf(ruta_archivo)
    except Exception as e:
        log.error("research_agent: no se pudo leer el PDF '%s' (%s)", ruta_archivo, e)
        return f"ERROR: no pude leer el PDF ({e})."

    if not texto.strip():
        return "ERROR: no encontré texto legible en ese PDF (¿es un escaneo de imágenes sin OCR?)."

    resumen = groq_agent.generar_contenido(_PROMPT_RESUMEN_PDF.format(contenido=texto[:_MAX_CARACTERES_PDF]))
    if resumen.startswith("ERROR:"):
        return resumen

    return resumen


# Idiomas de transcripción preferidos, de mejor a peor: español (varias
# variantes regionales) primero, inglés si no hay español, y si tampoco
# hay inglés se toma CUALQUIER transcripción disponible (incluidos
# subtítulos autogenerados) — mejor un resumen en otro idioma que nada.
_IDIOMAS_TRANSCRIPCION_ES = ("es", "es-419", "es-ES", "es-MX")
_IDIOMAS_TRANSCRIPCION_EN = ("en", "en-US", "en-GB")


def obtener_transcripcion_youtube(url):
    """Extrae la transcripción/subtítulos de un video de YouTube (sin
    API key, vía youtube-transcript-api — funciona con subtítulos
    manuales Y autogenerados). Prueba español primero, cae a inglés, y
    si tampoco hay cae a lo que sea que esté disponible. Devuelve el
    texto plano concatenado, o None si el video no tiene NINGÚN
    subtítulo/transcripción (deshabilitados, o video privado/borrado)."""
    video_id = _id_video(url)
    if not video_id:
        return None

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        lista = api.list(video_id)
        try:
            transcripcion = lista.find_transcript(_IDIOMAS_TRANSCRIPCION_ES)
        except Exception:
            try:
                transcripcion = lista.find_transcript(_IDIOMAS_TRANSCRIPCION_EN)
            except Exception:
                transcripcion = next(iter(lista))

        fragmentos = transcripcion.fetch()
        return " ".join(fragmento.text for fragmento in fragmentos if fragmento.text).strip()
    except Exception as e:
        log.warning("research_agent: no se pudo obtener transcripción de '%s' (%s)", url, e)
        return None


def resumir_video_youtube(url):
    """Extrae la transcripción de `url` (YouTube, ver
    obtener_transcripcion_youtube) y la manda a Groq para un resumen
    completo — mismo criterio que resumir_documento() para PDFs, pero
    sin descargar ningún archivo (no hace falta: la transcripción ya
    es texto). Devuelve el resumen (string), o un mensaje que empieza
    con "ERROR:" si el video no tiene transcripción o Groq falló."""
    texto = obtener_transcripcion_youtube(url)
    if not texto:
        return "ERROR: este video no tiene subtítulos/transcripción disponible (ni en español, inglés, ni autogenerados)."

    resumen = groq_agent.generar_contenido(_PROMPT_RESUMEN_VIDEO.format(contenido=texto[:_MAX_CARACTERES_VIDEO]))
    if resumen.startswith("ERROR:"):
        return resumen

    return resumen


def _nombre_archivo_desde_url(url, indice):
    nombre = os.path.basename(url.split("?")[0]) or f"documento_{indice}.pdf"
    return re.sub(r'[^\w\.\-]', '_', nombre)


def investigar(tema, limite=3):
    """Paso 1-2 del flujo de investigación: busca PDFs + artículos
    sobre `tema` y arma la lista combinada + el mensaje para
    presentarle al usuario (que elige por número — ver
    procesar_seleccion, el paso 3-4 corre después de que el usuario
    responde, por eso vive en director.py y no aquí).

    Devuelve {"documentos": [...], "mensaje": "..."} o {"error": "..."}."""
    pdfs = buscar_documentos(tema, limite=limite)
    if isinstance(pdfs, dict) and pdfs.get("error"):
        pdfs = []

    articulos = buscar_articulos(tema, limite=limite)
    if isinstance(articulos, dict) and articulos.get("error"):
        articulos = []

    documentos = list(pdfs) + list(articulos)
    if not documentos:
        return {"error": f"no encontré nada sobre '{tema}'."}

    lineas = [f"{i + 1}. {d['titulo']} - {d['url']}" for i, d in enumerate(documentos)]
    mensaje = f"Encontré estos documentos:\n" + "\n".join(lineas) + "\n¿Cuál quieres que descargue y resuma?"
    return {"documentos": documentos, "mensaje": mensaje}


def procesar_seleccion(documento, indice=1):
    """Paso 4 del flujo: si `documento["url"]` es un video de YouTube
    (ver _es_youtube), resume la transcripción SIN descargar ningún
    archivo (ver resumir_video_youtube); si no, descarga el documento
    (PDF/artículo) y lo resume como siempre. Mismo dict de entrada que
    investigar() devuelve ("titulo"/"url").

    Devuelve {"titulo","resumen","ruta"} o {"error": "..."} — "ruta" es
    la ruta completa donde quedó guardado el archivo (ver BUG1:
    director.py la usa para recordar "el último archivo descargado",
    así "ábrelo" después funciona sin pedir el nombre), o None para
    videos (no hay archivo local que recordar)."""
    if _es_youtube(documento["url"]):
        resumen = resumir_video_youtube(documento["url"])
        if resumen.startswith("ERROR:"):
            return {"error": f"no pude resumir el video '{documento['titulo']}': {resumen}"}
        return {"titulo": documento["titulo"], "resumen": resumen, "ruta": None}

    descarga = descargar_documento(documento["url"], _nombre_archivo_desde_url(documento["url"], indice))
    if descarga.get("error"):
        return {"error": f"no pude descargar '{documento['titulo']}': {descarga['error']}"}

    resumen = resumir_documento(descarga["ruta"])
    if resumen.startswith("ERROR:"):
        return {"error": f"descargué '{documento['titulo']}' pero no lo pude resumir: {resumen}", "ruta": descarga["ruta"]}

    return {"titulo": documento["titulo"], "resumen": resumen, "ruta": descarga["ruta"]}
