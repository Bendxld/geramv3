# ============================================================
# GERAM OS v2 · pendientes_agent.py
# Pendientes del día a día conectados a Notion, en su PROPIO database
# (NOTION_PENDIENTES_DB_ID) — separado del NOTION_DATABASE_ID que usa
# research_agent/director._generar_documento_notion para documentos,
# para no mezclar "tengo que comprar jamaica" con ensayos generados.
# Las properties "Estado"/"Prioridad" se crean solas en ese database
# si no existen (ver _asegurar_propiedades).
# ============================================================

import logging
import re

import config
from agents import notion_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pendientes_agent")

PRIORIDADES = ("alta", "normal", "baja")

# Definición de las properties que este agente necesita en el
# database de Notion. asegurar_propiedades_database() solo agrega las
# que falten, nunca pisa una que el usuario ya tenga configurada.
_PROPIEDADES_REQUERIDAS = {
    "Estado": {
        "select": {
            "options": [
                {"name": "pendiente", "color": "yellow"},
                {"name": "completado", "color": "green"},
            ]
        }
    },
    "Prioridad": {
        "select": {
            "options": [
                {"name": "alta", "color": "red"},
                {"name": "normal", "color": "blue"},
                {"name": "baja", "color": "gray"},
            ]
        }
    },
}

_PATRON_ID_NOTION = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$", re.I)


def _asegurar_propiedades():
    resultado = notion_agent.asegurar_propiedades_database(config.NOTION_PENDIENTES_DB_ID, _PROPIEDADES_REQUERIDAS)
    if resultado.get("error"):
        log.error("pendientes_agent: no se pudieron preparar las properties Estado/Prioridad (%s)", resultado["error"])
    return resultado


def _parece_id_notion(texto):
    return bool(_PATRON_ID_NOTION.match(texto.strip()))


def _propiedad_select(pagina, nombre, default=""):
    valor = (pagina.get("properties", {}).get(nombre) or {}).get("select")
    return valor["name"] if valor else default


def agregar_pendiente(texto, prioridad="normal"):
    """Crea un pendiente nuevo en Notion con Estado="pendiente".
    Devuelve {"id","url"} o {"error": "..."}."""
    if not config.NOTION_PENDIENTES_DB_ID:
        return {"error": "falta NOTION_PENDIENTES_DB_ID en .env"}

    prioridad = prioridad if prioridad in PRIORIDADES else "normal"

    aseguradas = _asegurar_propiedades()
    if aseguradas.get("error"):
        return {"error": f"no pude preparar el database de Notion: {aseguradas['error']}"}

    propiedades_extra = {
        "Estado": {"select": {"name": "pendiente"}},
        "Prioridad": {"select": {"name": prioridad}},
    }
    return notion_agent.crear_pagina_con_propiedades(
        config.NOTION_PENDIENTES_DB_ID, titulo=texto.strip(), propiedades_extra=propiedades_extra,
    )


def listar_pendientes(filtro_prioridad=None):
    """Pendientes con Estado="pendiente" (no completados), más
    prioritarios primero. `filtro_prioridad` opcional ("alta"/"normal"/
    "baja"). Devuelve lista de {"id","titulo","prioridad","creado"} o
    {"error": "..."}. "creado" es el created_time crudo de Notion
    (metadata estándar de la página, no una property del schema) —
    usado por proactividad_agent para detectar pendientes olvidados."""
    filtro = {"property": "Estado", "select": {"equals": "pendiente"}}
    if filtro_prioridad in PRIORIDADES:
        filtro = {"and": [filtro, {"property": "Prioridad", "select": {"equals": filtro_prioridad}}]}

    resultados = notion_agent.consultar_database(config.NOTION_PENDIENTES_DB_ID, filtro=filtro)
    if isinstance(resultados, dict) and resultados.get("error"):
        return resultados

    pendientes = [
        {
            "id": pagina["id"],
            "titulo": notion_agent.titulo_de_pagina(pagina),
            "prioridad": _propiedad_select(pagina, "Prioridad", "normal"),
            "creado": pagina.get("created_time"),
        }
        for pagina in resultados
    ]

    orden = {"alta": 0, "normal": 1, "baja": 2}
    pendientes.sort(key=lambda p: orden.get(p["prioridad"], 1))
    return pendientes


def listar_completados_desde(fecha_iso):
    """Pendientes con Estado="completado" cuya última edición (proxy
    confiable de "cuándo se completó": completar_pendiente() es la
    ÚNICA función que edita un pendiente ya completado, nada más lo
    vuelve a tocar) cae en o después de `fecha_iso`. El filtro de fecha
    se hace del lado de Notion (filtro "timestamp"), no trayendo todo
    el historial y recortando en Python — consultar_database() no
    pagina, así que filtrar aquí evita depender de que el histórico de
    completados quepa en una sola página de resultados. Devuelve lista
    de {"id","titulo","prioridad","editado"} o {"error": "..."}."""
    filtro = {
        "and": [
            {"property": "Estado", "select": {"equals": "completado"}},
            {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": fecha_iso}},
        ]
    }
    ordenar_por = [{"timestamp": "last_edited_time", "direction": "descending"}]

    resultados = notion_agent.consultar_database(config.NOTION_PENDIENTES_DB_ID, filtro=filtro, ordenar_por=ordenar_por)
    if isinstance(resultados, dict) and resultados.get("error"):
        return resultados

    return [
        {
            "id": pagina["id"],
            "titulo": notion_agent.titulo_de_pagina(pagina),
            "prioridad": _propiedad_select(pagina, "Prioridad", "normal"),
            "editado": pagina.get("last_edited_time"),
        }
        for pagina in resultados
    ]


def listar_pendientes_texto(filtro_prioridad=None):
    """Versión en texto legible de listar_pendientes(), para "qué pendientes tengo"."""
    pendientes = listar_pendientes(filtro_prioridad)
    if isinstance(pendientes, dict) and pendientes.get("error"):
        return f"No pude leer tus pendientes de Notion: {pendientes['error']}"
    if not pendientes:
        return f"No tienes pendientes de prioridad {filtro_prioridad}, jefe." if filtro_prioridad else "No tienes pendientes, jefe."

    lineas = [f"- [{p['prioridad']}] {p['titulo']}" for p in pendientes]
    return "Tus pendientes:\n" + "\n".join(lineas)


_STOPWORDS = {"el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "a", "al", "y"}


def resolver_pendiente(identificador):
    """Encuentra un pendiente por su id de Notion o por texto
    aproximado de su título, entre los NO completados. Devuelve
    {"id","titulo","prioridad"} o None. Público para que director.py
    arme la confirmación de "eliminar" sin hablar directo con Notion.

    Dos pasadas: (1) substring literal en cualquier dirección (rápido,
    cubre el caso común); (2) si no hubo match, por palabras
    significativas sin artículos/preposiciones — necesario porque
    Gemini a veces extrae el identificador con palabras de más (ej.
    "ya compré LA jamaica" -> identificador "la jamaica", que no es
    substring literal de un título como "comprar jamaica mañana")."""
    identificador = identificador.strip()
    if _parece_id_notion(identificador):
        return {"id": identificador, "titulo": identificador, "prioridad": "normal"}

    pendientes = listar_pendientes()
    if isinstance(pendientes, dict):
        return None

    identificador_bajo = identificador.lower()
    for p in pendientes:
        titulo_bajo = p["titulo"].lower()
        if identificador_bajo in titulo_bajo or titulo_bajo in identificador_bajo:
            return p

    palabras_identificador = {w for w in identificador_bajo.split() if w not in _STOPWORDS}
    mejor, mejor_coincidencias = None, 0
    for p in pendientes:
        palabras_titulo = {w for w in p["titulo"].lower().split() if w not in _STOPWORDS}
        coincidencias = len(palabras_identificador & palabras_titulo)
        if coincidencias > mejor_coincidencias:
            mejor, mejor_coincidencias = p, coincidencias
    return mejor


def completar_pendiente(id_o_nombre):
    """Marca como completado (Estado="completado") un pendiente,
    encontrado por id de Notion o texto aproximado del título.
    Devuelve {"ok": True, "titulo": ...} o {"error": "..."}."""
    pendiente = resolver_pendiente(id_o_nombre)
    if not pendiente:
        return {"error": f"no encontré un pendiente que coincida con '{id_o_nombre}'."}

    resultado = notion_agent.actualizar_propiedades_pagina(pendiente["id"], {"Estado": {"select": {"name": "completado"}}})
    if resultado.get("error"):
        return {"error": resultado["error"]}
    return {"ok": True, "titulo": pendiente["titulo"]}


def eliminar_pendiente(id_o_nombre):
    """Archiva (elimina) un pendiente en Notion. SOLO se debe llamar
    después de que el usuario ya escribió CONFIRMAR (ver director.py,
    misma lógica que email_agent/classroom_agent para acciones
    riesgosas). Devuelve {"ok": True, "titulo": ...} o {"error": "..."}."""
    pendiente = resolver_pendiente(id_o_nombre)
    if not pendiente:
        return {"error": f"no encontré un pendiente que coincida con '{id_o_nombre}'."}

    resultado = notion_agent.archivar_pagina(pendiente["id"])
    if resultado.get("error"):
        return {"error": resultado["error"]}
    return {"ok": True, "titulo": pendiente["titulo"]}


def contar_pendientes():
    """Cuenta de pendientes sin completar, para daily_briefing_agent.
    Devuelve un int, o None si Notion falla (para que el briefing lo
    omita en vez de mostrar un error técnico)."""
    pendientes = listar_pendientes()
    if isinstance(pendientes, dict):
        return None
    return len(pendientes)
