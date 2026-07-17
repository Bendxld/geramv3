# ============================================================
# GERAM OS v2 · proyectos_agent.py
# Proyectos personales/escolares en su PROPIO database de Notion
# (NOTION_PROYECTOS_DB_ID) — distinto de NOTION_PENDIENTES_DB_ID: un
# pendiente es una acción suelta que se marca hecha una vez, un
# proyecto vive días/semanas y se le van agregando AVANCES (bloques de
# contenido con fecha) sobre la misma página, para poder ver el
# progreso a lo largo del tiempo. Las properties "Estado"/"Tipo" se
# crean solas en ese database si no existen (ver _asegurar_propiedades).
# ============================================================

import logging
import re
from datetime import date

import config
from agents import notion_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("proyectos_agent")

ESTADOS = ("no iniciado", "en progreso", "pausado", "completado")
TIPOS = ("escolar", "personal")

_PROPIEDADES_REQUERIDAS = {
    "Estado": {
        "select": {
            "options": [
                {"name": "no iniciado", "color": "gray"},
                {"name": "en progreso", "color": "blue"},
                {"name": "pausado", "color": "yellow"},
                {"name": "completado", "color": "green"},
            ]
        }
    },
    "Tipo": {
        "select": {
            "options": [
                {"name": "escolar", "color": "purple"},
                {"name": "personal", "color": "pink"},
            ]
        }
    },
}

_PATRON_ID_NOTION = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$", re.I)


def _asegurar_propiedades():
    resultado = notion_agent.asegurar_propiedades_database(config.NOTION_PROYECTOS_DB_ID, _PROPIEDADES_REQUERIDAS)
    if resultado.get("error"):
        log.error("proyectos_agent: no se pudieron preparar las properties Estado/Tipo (%s)", resultado["error"])
    return resultado


def _parece_id_notion(texto):
    return bool(_PATRON_ID_NOTION.match(texto.strip()))


def _propiedad_select(pagina, nombre, default=""):
    valor = (pagina.get("properties", {}).get(nombre) or {}).get("select")
    return valor["name"] if valor else default


def crear_proyecto(titulo, tipo="personal"):
    """Crea un proyecto nuevo en Notion con Estado="no iniciado".
    Devuelve {"id","url"} o {"error": "..."}."""
    if not config.NOTION_PROYECTOS_DB_ID:
        return {"error": "falta NOTION_PROYECTOS_DB_ID en .env"}

    tipo = tipo if tipo in TIPOS else "personal"

    aseguradas = _asegurar_propiedades()
    if aseguradas.get("error"):
        return {"error": f"no pude preparar el database de Notion: {aseguradas['error']}"}

    propiedades_extra = {
        "Estado": {"select": {"name": "no iniciado"}},
        "Tipo": {"select": {"name": tipo}},
    }
    return notion_agent.crear_pagina_con_propiedades(
        config.NOTION_PROYECTOS_DB_ID, titulo=titulo.strip(), propiedades_extra=propiedades_extra,
    )


def _listar(filtro=None):
    resultados = notion_agent.consultar_database(config.NOTION_PROYECTOS_DB_ID, filtro=filtro)
    if isinstance(resultados, dict) and resultados.get("error"):
        return resultados

    return [
        {
            "id": pagina["id"],
            "titulo": notion_agent.titulo_de_pagina(pagina),
            "estado": _propiedad_select(pagina, "Estado", "no iniciado"),
            "tipo": _propiedad_select(pagina, "Tipo", "personal"),
        }
        for pagina in resultados
    ]


def listar_proyectos(filtro_estado=None, filtro_tipo=None):
    """Sin filtro_estado, devuelve los proyectos ACTIVOS (todo menos
    "completado") — para "qué proyectos tengo". Con filtro_estado se
    puede pedir un estado explícito (ej. "completado" para ver los ya
    terminados). filtro_tipo opcional ("escolar"/"personal"). Devuelve
    lista de {"id","titulo","estado","tipo"} o {"error": "..."}."""
    if filtro_estado in ESTADOS:
        filtro = {"property": "Estado", "select": {"equals": filtro_estado}}
    else:
        filtro = {"property": "Estado", "select": {"does_not_equal": "completado"}}

    if filtro_tipo in TIPOS:
        filtro = {"and": [filtro, {"property": "Tipo", "select": {"equals": filtro_tipo}}]}

    return _listar(filtro)


def listar_proyectos_texto(filtro_estado=None, filtro_tipo=None):
    """Versión en texto legible de listar_proyectos(), para "qué proyectos tengo"."""
    proyectos = listar_proyectos(filtro_estado, filtro_tipo)
    if isinstance(proyectos, dict) and proyectos.get("error"):
        return f"No pude leer tus proyectos de Notion: {proyectos['error']}"
    if not proyectos:
        return "No tienes proyectos activos, jefe."

    lineas = [f"- [{p['tipo']}/{p['estado']}] {p['titulo']}" for p in proyectos]
    return "Tus proyectos:\n" + "\n".join(lineas)


_STOPWORDS = {"el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "a", "al", "y", "proyecto"}


def resolver_proyecto(identificador):
    """Encuentra un proyecto por su id de Notion o por texto
    aproximado de su título, entre TODOS los proyectos (activos,
    pausados o completados — a diferencia de resolver_pendiente, aquí
    sí importa poder agregar un avance o reabrir uno ya marcado
    completado/pausado). Devuelve {"id","titulo","estado","tipo"} o
    None. Público para que director.py arme la confirmación de
    "eliminar" sin hablar directo con Notion.

    Misma estrategia de dos pasadas que resolver_pendiente: (1)
    substring literal en cualquier dirección; (2) si no hubo match,
    por palabras significativas sin artículos/preposiciones."""
    identificador = identificador.strip()
    if _parece_id_notion(identificador):
        return {"id": identificador, "titulo": identificador, "estado": "no iniciado", "tipo": "personal"}

    proyectos = _listar()
    if isinstance(proyectos, dict):
        return None

    identificador_bajo = identificador.lower()
    for p in proyectos:
        titulo_bajo = p["titulo"].lower()
        if identificador_bajo in titulo_bajo or titulo_bajo in identificador_bajo:
            return p

    palabras_identificador = {w for w in identificador_bajo.split() if w not in _STOPWORDS}
    mejor, mejor_coincidencias = None, 0
    for p in proyectos:
        palabras_titulo = {w for w in p["titulo"].lower().split() if w not in _STOPWORDS}
        coincidencias = len(palabras_identificador & palabras_titulo)
        if coincidencias > mejor_coincidencias:
            mejor, mejor_coincidencias = p, coincidencias
    return mejor


def agregar_avance(identificador, texto_avance):
    """Anota un avance (con fecha) al final de la página del proyecto.
    Si el proyecto estaba "no iniciado", lo pasa a "en progreso"
    automáticamente (agregar un avance implica que ya arrancó).
    Devuelve {"ok": True, "titulo": ...} o {"error": "..."}."""
    proyecto = resolver_proyecto(identificador)
    if not proyecto:
        return {"error": f"no encontré un proyecto que coincida con '{identificador}'."}

    hoy = date.today().isoformat()
    resultado = notion_agent.agregar_contenido_pagina(proyecto["id"], f"- {hoy}: {texto_avance.strip()}")
    if resultado.get("error"):
        return {"error": resultado["error"]}

    if proyecto["estado"] == "no iniciado":
        notion_agent.actualizar_propiedades_pagina(proyecto["id"], {"Estado": {"select": {"name": "en progreso"}}})

    return {"ok": True, "titulo": proyecto["titulo"]}


def listar_avances(identificador):
    """Devuelve el historial de avances (contenido de la página) de un
    proyecto como texto, o {"error": "..."}."""
    proyecto = resolver_proyecto(identificador)
    if not proyecto:
        return {"error": f"no encontré un proyecto que coincida con '{identificador}'."}

    contenido = notion_agent.obtener_contenido_pagina(proyecto["id"])
    if isinstance(contenido, dict) and contenido.get("error"):
        return {"error": contenido["error"]}

    return {"titulo": proyecto["titulo"], "avances": contenido or "(todavía no tiene avances anotados)"}


def cambiar_estado(identificador, nuevo_estado):
    """Cambia el Estado de un proyecto (ej. a "pausado" o "completado").
    Devuelve {"ok": True, "titulo": ...} o {"error": "..."}."""
    if nuevo_estado not in ESTADOS:
        return {"error": f"estado inválido '{nuevo_estado}' (usa: {', '.join(ESTADOS)})"}

    proyecto = resolver_proyecto(identificador)
    if not proyecto:
        return {"error": f"no encontré un proyecto que coincida con '{identificador}'."}

    resultado = notion_agent.actualizar_propiedades_pagina(proyecto["id"], {"Estado": {"select": {"name": nuevo_estado}}})
    if resultado.get("error"):
        return {"error": resultado["error"]}
    return {"ok": True, "titulo": proyecto["titulo"]}


def eliminar_proyecto(id_o_nombre):
    """Archiva (elimina) un proyecto en Notion. SOLO se debe llamar
    después de que el usuario ya escribió CONFIRMAR (ver director.py,
    misma lógica que pendientes_agent). Devuelve {"ok": True, "titulo": ...}
    o {"error": "..."}."""
    proyecto = resolver_proyecto(id_o_nombre)
    if not proyecto:
        return {"error": f"no encontré un proyecto que coincida con '{id_o_nombre}'."}

    resultado = notion_agent.archivar_pagina(proyecto["id"])
    if resultado.get("error"):
        return {"error": resultado["error"]}
    return {"ok": True, "titulo": proyecto["titulo"]}
