# ============================================================
# GERAM OS v2 · web_agent.py
# Búsqueda web (DuckDuckGo, sin API key) y lectura de páginas. No pasa
# por Gemini, es puro httpx + regex — separado de control_agent.py
# porque no tiene nada que ver con controlar el equipo.
# ============================================================

import html
import logging
import re
from urllib.parse import unquote

import httpx

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("web_agent")

_CABECERAS_WEB = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) GeramOS/2.0"}

# Estructura real de html.duckduckgo.com/html/ verificada contra
# respuestas reales (no es una suposición): cada resultado tiene un
# <a class="result__a" href="...uddg=URL..."> con el título, y más
# abajo un <a class="result__snippet" href="..."> con la descripción.
_PATRON_TITULO = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_PATRON_SNIPPET = re.compile(r'<a[^>]*class="result__snippet"[^>]*href="[^"]*"[^>]*>(.*?)</a>', re.S)


def _limpiar_html(texto):
    """Quita tags y decodifica entidades HTML (&amp;, &aacute;, etc)."""
    sin_tags = re.sub(r"<[^>]+>", "", texto)
    return html.unescape(sin_tags).strip()


def _limpiar_url(url_redirigida):
    """DuckDuckGo redirige via /l/?uddg=<url-encoded>&rut=...; esto
    saca la URL real de destino."""
    coincidencia = re.search(r"uddg=([^&]+)", url_redirigida)
    if coincidencia:
        return unquote(coincidencia.group(1))
    return url_redirigida


def buscar_web(query, limite=5):
    """Busca `query` en DuckDuckGo y devuelve una lista de dicts
    {titulo, url, descripcion} (máximo `limite`). Si algo falla,
    devuelve {"error": "..."} en vez de la lista."""
    try:
        respuesta = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=_CABECERAS_WEB,
            timeout=10,
            follow_redirects=True,
        )
        respuesta.raise_for_status()
    except Exception as e:
        log.error("web_agent: falló la búsqueda web (%s)", e)
        return {"error": str(e)}

    titulos = _PATRON_TITULO.findall(respuesta.text)
    snippets = _PATRON_SNIPPET.findall(respuesta.text)

    resultados = []
    for i, (url_cruda, titulo_crudo) in enumerate(titulos[:limite]):
        descripcion = _limpiar_html(snippets[i]) if i < len(snippets) else ""
        resultados.append({
            "titulo": _limpiar_html(titulo_crudo),
            "url": _limpiar_url(url_cruda),
            "descripcion": descripcion,
        })

    return resultados


def _extraer_texto_principal(html_crudo):
    """Extracción simple: quita scripts/estilos/comentarios y tags,
    deja solo texto plano. No es un algoritmo de 'readability' real,
    así que puede incluir menús/pies de página, pero sirve para dar
    contexto a Gemini para que resuma."""
    limpio = re.sub(r"<script.*?</script>", " ", html_crudo, flags=re.S | re.I)
    limpio = re.sub(r"<style.*?</style>", " ", limpio, flags=re.S | re.I)
    limpio = re.sub(r"<!--.*?-->", " ", limpio, flags=re.S)
    solo_texto = re.sub(r"<[^>]+>", " ", limpio)
    solo_texto = html.unescape(solo_texto)
    return re.sub(r"\s+", " ", solo_texto).strip()


def obtener_pagina(url, max_caracteres=3000):
    """Descarga `url` y devuelve {"url": ..., "contenido": "..."}
    con el texto principal recortado a `max_caracteres`. Si falla,
    devuelve {"error": "..."}."""
    try:
        respuesta = httpx.get(url, headers=_CABECERAS_WEB, timeout=10, follow_redirects=True)
        respuesta.raise_for_status()
    except Exception as e:
        log.error("web_agent: no se pudo descargar %s (%s)", url, e)
        return {"error": str(e)}

    texto = _extraer_texto_principal(respuesta.text)
    return {"url": str(respuesta.url), "contenido": texto[:max_caracteres]}
