# ============================================================
# GERAM OS v2 · notion_agent.py
# Crea y consulta páginas en un database de Notion vía la API
# oficial (https://api.notion.com/v1/). El contenido en texto plano
# (con "## Título" y "- item") se convierte a bloques de Notion.
# ============================================================

import logging

import httpx

import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("notion_agent")

NOTION_URL = "https://api.notion.com/v1"
# Fecha de versión de la API, no la fecha de hoy: fija el contrato
# request/response para que futuros cambios de Notion no rompan esto.
NOTION_VERSION = "2022-06-28"

# Límite real de la API: máximo 100 bloques por request (tanto al
# crear la página como al agregarle bloques después).
_LOTE_MAX_BLOQUES = 100

# El nombre real de la propiedad "title" de un database lo define el
# usuario en Notion (puede ser "Name", "Título", etc.), así que no se
# puede asumir un literal fijo. Se resuelve una vez por database vía
# _obtener_nombre_prop_titulo() y se cachea aquí.
_cache_prop_titulo = {}


def _cabeceras():
    return {
        "Authorization": f"Bearer {config.NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _credenciales_faltantes():
    if not config.NOTION_API_KEY:
        return "falta NOTION_API_KEY en .env"
    if not config.NOTION_DATABASE_ID:
        return "falta NOTION_DATABASE_ID en .env"
    return None


def _texto_a_bloques(contenido):
    """Convierte texto plano a bloques de Notion:
    '## Título' -> heading_2, '- item' / '* item' -> bulleted_list_item,
    cualquier otra línea no vacía -> paragraph."""
    bloques = []
    for linea in contenido.splitlines():
        linea = linea.strip()
        if not linea:
            continue

        if linea.startswith("## "):
            texto = linea[3:].strip()
            tipo = "heading_2"
        elif linea.startswith("# "):
            texto = linea[2:].strip()
            tipo = "heading_1"
        elif linea.startswith("- ") or linea.startswith("* "):
            texto = linea[2:].strip()
            tipo = "bulleted_list_item"
        else:
            texto = linea
            tipo = "paragraph"

        # Notion limita cada rich_text a 2000 caracteres.
        bloques.append({
            "object": "block",
            "type": tipo,
            tipo: {"rich_text": [{"type": "text", "text": {"content": texto[:2000]}}]},
        })

    return bloques


def _obtener_nombre_prop_titulo(database_id):
    """Encuentra el nombre real de la propiedad tipo "title" del
    database (Notion no siempre la llama "title" — el usuario pudo
    haberla renombrado a "Name", "Título", etc). Se cachea por proceso."""
    if database_id in _cache_prop_titulo:
        return _cache_prop_titulo[database_id]

    try:
        respuesta = httpx.get(f"{NOTION_URL}/databases/{database_id}", headers=_cabeceras(), timeout=20)
        respuesta.raise_for_status()
        for nombre, definicion in respuesta.json().get("properties", {}).items():
            if definicion.get("type") == "title":
                _cache_prop_titulo[database_id] = nombre
                return nombre
    except Exception as e:
        log.error("notion_agent: no se pudo leer el schema del database (%s)", e)

    # Nombre por defecto que Notion le pone a la columna título
    # cuando creas un database nuevo desde la UI.
    return "Name"


def titulo_de_pagina(pagina):
    """Extrae el título de un objeto 'page' crudo de la API (busca la
    property tipo "title", sea cual sea su nombre real). Público:
    lo usa también pendientes_agent.py, que arma sus propios resúmenes
    de página (con Prioridad/Estado) en vez de _extraer_resumen."""
    for prop in pagina.get("properties", {}).values():
        if prop.get("type") == "title":
            fragmentos = prop.get("title", [])
            if fragmentos:
                return "".join(f.get("plain_text", "") for f in fragmentos)
    return "(sin título)"


def _extraer_resumen(pagina):
    """De un objeto 'page' de la API, saca {"titulo", "url"}."""
    return {"titulo": titulo_de_pagina(pagina), "url": pagina.get("url")}


def crear_pagina(titulo, contenido):
    """Crea una página nueva en el database configurado (NOTION_DATABASE_ID)
    con `titulo` y `contenido` (texto plano, admite "## " y "- ")
    convertido a bloques. Devuelve {"url": ..., "id": ...} o {"error": "..."}."""
    faltante = _credenciales_faltantes()
    if faltante:
        return {"error": faltante}

    nombre_prop_titulo = _obtener_nombre_prop_titulo(config.NOTION_DATABASE_ID)
    bloques = _texto_a_bloques(contenido)
    primer_lote, resto = bloques[:_LOTE_MAX_BLOQUES], bloques[_LOTE_MAX_BLOQUES:]

    payload = {
        "parent": {"database_id": config.NOTION_DATABASE_ID},
        "properties": {
            nombre_prop_titulo: {"title": [{"type": "text", "text": {"content": titulo[:200]}}]},
        },
        "children": primer_lote,
    }

    try:
        respuesta = httpx.post(f"{NOTION_URL}/pages", headers=_cabeceras(), json=payload, timeout=20)
        respuesta.raise_for_status()
        datos = respuesta.json()
    except httpx.HTTPStatusError as e:
        log.error("notion_agent: Notion respondió %s (%s)", e.response.status_code, e.response.text[:300])
        return {"error": f"Notion respondió {e.response.status_code} ({e.response.text[:200]})"}
    except Exception as e:
        log.error("notion_agent: no se pudo crear la página (%s)", e)
        return {"error": str(e)}

    pagina_id = datos.get("id")

    # Si el contenido tenía más de 100 bloques, el resto se agrega
    # después en lotes (la página ya existe con lo primero aunque
    # algún lote falle, por eso no se propaga error aquí).
    for i in range(0, len(resto), _LOTE_MAX_BLOQUES):
        lote = resto[i:i + _LOTE_MAX_BLOQUES]
        try:
            r = httpx.patch(
                f"{NOTION_URL}/blocks/{pagina_id}/children",
                headers=_cabeceras(), json={"children": lote}, timeout=20,
            )
            r.raise_for_status()
        except Exception as e:
            log.error("notion_agent: no se pudo agregar el resto del contenido (%s)", e)
            break

    return {"url": datos.get("url"), "id": pagina_id}


def listar_paginas(limite=10):
    """Devuelve las `limite` páginas más recientes del database
    (por última edición) como lista de {"titulo", "url"}, o
    {"error": "..."} si algo falla."""
    faltante = _credenciales_faltantes()
    if faltante:
        return {"error": faltante}

    payload = {
        "page_size": limite,
        "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
    }

    try:
        respuesta = httpx.post(
            f"{NOTION_URL}/databases/{config.NOTION_DATABASE_ID}/query",
            headers=_cabeceras(), json=payload, timeout=20,
        )
        respuesta.raise_for_status()
    except httpx.HTTPStatusError as e:
        log.error("notion_agent: Notion respondió %s (%s)", e.response.status_code, e.response.text[:300])
        return {"error": f"Notion respondió {e.response.status_code}"}
    except Exception as e:
        log.error("notion_agent: no se pudo listar páginas (%s)", e)
        return {"error": str(e)}

    return [_extraer_resumen(p) for p in respuesta.json().get("results", [])]


def buscar_pagina(query):
    """Busca páginas por título con el buscador global de Notion
    (alcanza solo lo que la integration tenga compartido, que en la
    práctica es el database configurado). Devuelve una lista de
    {"titulo", "url"} o {"error": "..."}."""
    if not config.NOTION_API_KEY:
        return {"error": "falta NOTION_API_KEY en .env"}

    payload = {"query": query, "filter": {"property": "object", "value": "page"}}

    try:
        respuesta = httpx.post(f"{NOTION_URL}/search", headers=_cabeceras(), json=payload, timeout=20)
        respuesta.raise_for_status()
    except httpx.HTTPStatusError as e:
        log.error("notion_agent: Notion respondió %s (%s)", e.response.status_code, e.response.text[:300])
        return {"error": f"Notion respondió {e.response.status_code}"}
    except Exception as e:
        log.error("notion_agent: no se pudo buscar en Notion (%s)", e)
        return {"error": str(e)}

    return [_extraer_resumen(p) for p in respuesta.json().get("results", [])]


# ------------------------------------------------------------
# Genéricos de schema/propiedades — agregados para pendientes_agent.py,
# que necesita properties reales (Estado/Prioridad tipo "select"), no
# solo título + bloques de contenido como crear_pagina().
# ------------------------------------------------------------

def obtener_propiedades_database(database_id):
    """Devuelve (properties_dict, None) o (None, "mensaje de error")."""
    try:
        respuesta = httpx.get(f"{NOTION_URL}/databases/{database_id}", headers=_cabeceras(), timeout=20)
        respuesta.raise_for_status()
        return respuesta.json().get("properties", {}), None
    except httpx.HTTPStatusError as e:
        log.error("notion_agent: Notion respondió %s (%s)", e.response.status_code, e.response.text[:300])
        return None, f"Notion respondió {e.response.status_code}"
    except Exception as e:
        log.error("notion_agent: no se pudo leer el schema del database (%s)", e)
        return None, str(e)


def asegurar_propiedades_database(database_id, propiedades_nuevas):
    """Agrega a `database_id` SOLO las properties de `propiedades_nuevas`
    (dict {"NombreProp": {definición del tipo, ej. "select": {...}}})
    que todavía no existan — nunca pisa una property existente.
    Devuelve {"ok": True} o {"error": "..."}."""
    existentes, error = obtener_propiedades_database(database_id)
    if error:
        return {"error": error}

    faltantes = {nombre: definicion for nombre, definicion in propiedades_nuevas.items() if nombre not in existentes}
    if not faltantes:
        return {"ok": True}

    try:
        respuesta = httpx.patch(
            f"{NOTION_URL}/databases/{database_id}",
            headers=_cabeceras(), json={"properties": faltantes}, timeout=20,
        )
        respuesta.raise_for_status()
        return {"ok": True}
    except httpx.HTTPStatusError as e:
        log.error("notion_agent: Notion respondió %s (%s)", e.response.status_code, e.response.text[:300])
        return {"error": f"Notion respondió {e.response.status_code} ({e.response.text[:200]})"}
    except Exception as e:
        log.error("notion_agent: no se pudieron agregar las properties (%s)", e)
        return {"error": str(e)}


def crear_pagina_con_propiedades(database_id, titulo, propiedades_extra=None, contenido=""):
    """Como crear_pagina(), pero en `database_id` explícito (no
    necesariamente NOTION_DATABASE_ID — pendientes_agent.py usa su
    propio NOTION_PENDIENTES_DB_ID) y permite además setear properties
    reales del schema (ej. {"Estado": {"select": {"name": "pendiente"}}})
    en vez de solo título + bloques de contenido. Devuelve {"id","url"}
    o {"error": "..."}."""
    if not config.NOTION_API_KEY:
        return {"error": "falta NOTION_API_KEY en .env"}
    if not database_id:
        return {"error": "falta el database_id (revisa NOTION_DATABASE_ID/NOTION_PENDIENTES_DB_ID en .env)"}

    nombre_prop_titulo = _obtener_nombre_prop_titulo(database_id)
    propiedades = {nombre_prop_titulo: {"title": [{"type": "text", "text": {"content": titulo[:200]}}]}}
    if propiedades_extra:
        propiedades.update(propiedades_extra)

    payload = {
        "parent": {"database_id": database_id},
        "properties": propiedades,
        "children": _texto_a_bloques(contenido)[:_LOTE_MAX_BLOQUES] if contenido else [],
    }

    try:
        respuesta = httpx.post(f"{NOTION_URL}/pages", headers=_cabeceras(), json=payload, timeout=20)
        respuesta.raise_for_status()
        datos = respuesta.json()
    except httpx.HTTPStatusError as e:
        log.error("notion_agent: Notion respondió %s (%s)", e.response.status_code, e.response.text[:300])
        return {"error": f"Notion respondió {e.response.status_code} ({e.response.text[:200]})"}
    except Exception as e:
        log.error("notion_agent: no se pudo crear la página (%s)", e)
        return {"error": str(e)}

    return {"id": datos.get("id"), "url": datos.get("url")}


def actualizar_propiedades_pagina(pagina_id, propiedades):
    """PATCH de properties de una página existente (ej. cambiar Estado
    a "completado"). Devuelve {"ok": True} o {"error": "..."}."""
    try:
        respuesta = httpx.patch(
            f"{NOTION_URL}/pages/{pagina_id}",
            headers=_cabeceras(), json={"properties": propiedades}, timeout=20,
        )
        respuesta.raise_for_status()
        return {"ok": True}
    except httpx.HTTPStatusError as e:
        log.error("notion_agent: Notion respondió %s (%s)", e.response.status_code, e.response.text[:300])
        return {"error": f"Notion respondió {e.response.status_code} ({e.response.text[:200]})"}
    except Exception as e:
        log.error("notion_agent: no se pudo actualizar la página %s (%s)", pagina_id, e)
        return {"error": str(e)}


def archivar_pagina(pagina_id):
    """Notion no tiene un DELETE real vía API — "archivar" es el
    equivalente (la página deja de aparecer en el database, pero sigue
    existiendo en la papelera de Notion por si acaso). Devuelve
    {"ok": True} o {"error": "..."}."""
    try:
        respuesta = httpx.patch(
            f"{NOTION_URL}/pages/{pagina_id}",
            headers=_cabeceras(), json={"archived": True}, timeout=20,
        )
        respuesta.raise_for_status()
        return {"ok": True}
    except httpx.HTTPStatusError as e:
        log.error("notion_agent: Notion respondió %s (%s)", e.response.status_code, e.response.text[:300])
        return {"error": f"Notion respondió {e.response.status_code} ({e.response.text[:200]})"}
    except Exception as e:
        log.error("notion_agent: no se pudo archivar la página %s (%s)", pagina_id, e)
        return {"error": str(e)}


def agregar_contenido_pagina(pagina_id, contenido):
    """Agrega `contenido` (texto plano, admite "## " y "- ", ver
    _texto_a_bloques) al FINAL de una página ya existente — para
    proyectos_agent.py, que va anotando avances sueltos sobre una
    misma página en vez de crear una página nueva por avance. Devuelve
    {"ok": True} o {"error": "..."}."""
    bloques = _texto_a_bloques(contenido)
    if not bloques:
        return {"ok": True}

    for i in range(0, len(bloques), _LOTE_MAX_BLOQUES):
        lote = bloques[i:i + _LOTE_MAX_BLOQUES]
        try:
            respuesta = httpx.patch(
                f"{NOTION_URL}/blocks/{pagina_id}/children",
                headers=_cabeceras(), json={"children": lote}, timeout=20,
            )
            respuesta.raise_for_status()
        except httpx.HTTPStatusError as e:
            log.error("notion_agent: Notion respondió %s (%s)", e.response.status_code, e.response.text[:300])
            return {"error": f"Notion respondió {e.response.status_code} ({e.response.text[:200]})"}
        except Exception as e:
            log.error("notion_agent: no se pudo agregar contenido a la página %s (%s)", pagina_id, e)
            return {"error": str(e)}

    return {"ok": True}


def obtener_contenido_pagina(pagina_id):
    """Lee los bloques de una página y los devuelve como texto plano
    (una línea por bloque, "- " para bulleted_list_item), más reciente
    al final — para "qué avances lleva X". No pagina más allá del
    primer lote (100 bloques), suficiente para un historial de avances
    de un proyecto. Devuelve un str, o {"error": "..."}."""
    try:
        respuesta = httpx.get(f"{NOTION_URL}/blocks/{pagina_id}/children", headers=_cabeceras(), timeout=20)
        respuesta.raise_for_status()
    except httpx.HTTPStatusError as e:
        log.error("notion_agent: Notion respondió %s (%s)", e.response.status_code, e.response.text[:300])
        return {"error": f"Notion respondió {e.response.status_code}"}
    except Exception as e:
        log.error("notion_agent: no se pudo leer el contenido de la página %s (%s)", pagina_id, e)
        return {"error": str(e)}

    lineas = []
    for bloque in respuesta.json().get("results", []):
        tipo = bloque.get("type")
        rich_text = bloque.get(tipo, {}).get("rich_text", [])
        texto = "".join(f.get("plain_text", "") for f in rich_text)
        if not texto:
            continue
        lineas.append(f"- {texto}" if tipo == "bulleted_list_item" else texto)

    return "\n".join(lineas)


def consultar_database(database_id, filtro=None, ordenar_por=None):
    """POST a /databases/{id}/query con un filter/sorts arbitrario (ver
    la documentación de filtros de Notion). Devuelve la lista cruda de
    'page' objects, o {"error": "..."}."""
    payload = {}
    if filtro:
        payload["filter"] = filtro
    if ordenar_por:
        payload["sorts"] = ordenar_por

    try:
        respuesta = httpx.post(
            f"{NOTION_URL}/databases/{database_id}/query",
            headers=_cabeceras(), json=payload, timeout=20,
        )
        respuesta.raise_for_status()
        return respuesta.json().get("results", [])
    except httpx.HTTPStatusError as e:
        log.error("notion_agent: Notion respondió %s (%s)", e.response.status_code, e.response.text[:300])
        return {"error": f"Notion respondió {e.response.status_code} ({e.response.text[:200]})"}
    except Exception as e:
        log.error("notion_agent: no se pudo consultar el database (%s)", e)
        return {"error": str(e)}
