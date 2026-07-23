# ============================================================
# GERAM OS v2 · memory.py
# Memoria a largo plazo compartida entre IRIS y ARES via
# Supabase. Cada memoria queda marcada con la instancia que la
# creó (config.INSTANCE_NAME), pero cualquier instancia puede
# leer todas las memorias.
#
# IMPORTANTE: la tabla "memorias" debe crearse manualmente en
# Supabase antes de usar este módulo (ver el SQL al final del
# reporte de esta fase).
# ============================================================

import logging

from supabase import create_client

import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("memory")

# La memoria a largo plazo es OPCIONAL. Si no configuras Supabase
# (SUPABASE_URL / SUPABASE_KEY en .env), el asistente funciona igual: solo
# no recuerda entre sesiones. Sin credenciales dejamos el cliente en None y
# cada función degrada a vacío, en vez de romper el arranque de IRIS.
# Cada persona pone su PROPIO Supabase (plan gratis) si quiere memoria.
_cliente = None
if config.SUPABASE_URL and config.SUPABASE_KEY:
    try:
        _cliente = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    except Exception as e:
        log.warning("memory: Supabase no disponible; memoria persistente desactivada (%s)", e)
else:
    log.info("memory: Supabase sin configurar; memoria persistente desactivada (opcional)")

TABLA = "memorias"


def guardar_memoria(texto, tipo):
    """Guarda una memoria nueva. `tipo` es una etiqueta libre, ej.
    'chat', 'evento', 'preferencia', etc. La instancia (IRIS/ARES)
    se agrega automáticamente."""
    if _cliente is None:
        return None
    fila = {
        "texto": texto,
        "tipo": tipo,
        "instancia": config.INSTANCE_NAME,
    }
    try:
        resultado = _cliente.table(TABLA).insert(fila).execute()
        return resultado.data[0] if resultado.data else None
    except Exception as e:
        log.error("memory: no se pudo guardar la memoria (%s)", e)
        return None


def obtener_memorias_recientes(limite=10):
    """Devuelve las últimas `limite` memorias (de cualquier instancia),
    más nuevas primero."""
    if _cliente is None:
        return []
    try:
        resultado = (
            _cliente.table(TABLA)
            .select("*")
            .order("created_at", desc=True)
            .limit(limite)
            .execute()
        )
        return resultado.data
    except Exception as e:
        log.error("memory: no se pudieron obtener memorias recientes (%s)", e)
        return []


def buscar_memoria_relevante(query, limite=5):
    """Búsqueda simple por coincidencia de texto (ILIKE). No es
    búsqueda semántica todavía (eso requeriría embeddings, fuera
    del alcance de la Fase 1)."""
    if _cliente is None:
        return []
    try:
        resultado = (
            _cliente.table(TABLA)
            .select("*")
            .ilike("texto", f"%{query}%")
            .order("created_at", desc=True)
            .limit(limite)
            .execute()
        )
        return resultado.data
    except Exception as e:
        log.error("memory: no se pudo buscar memoria relevante (%s)", e)
        return []


def obtener_memorias_desde(fecha_iso, tipo=None, limite=100):
    """Memorias con created_at >= fecha_iso (más nuevas primero), para
    resúmenes con ventana de tiempo (ej. retrospectiva_agent). `tipo`
    opcional filtra además por etiqueta (ej. "usuario", para no traer
    también el eco de las respuestas de IRIS)."""
    if _cliente is None:
        return []
    try:
        consulta = (
            _cliente.table(TABLA)
            .select("*")
            .gte("created_at", fecha_iso)
        )
        if tipo is not None:
            consulta = consulta.eq("tipo", tipo)
        resultado = consulta.order("created_at", desc=True).limit(limite).execute()
        return resultado.data
    except Exception as e:
        log.error("memory: no se pudieron obtener memorias desde %s (%s)", fecha_iso, e)
        return []


def obtener_memorias_por_tipo(tipo, limite=400):
    """Todas las memorias de un `tipo` exacto (más nuevas primero), sin
    filtro de fecha — usado por proactividad_agent._revisar_patrones
    para leer las migajas tipo="patron" y agruparlas por semana."""
    if _cliente is None:
        return []
    try:
        resultado = (
            _cliente.table(TABLA)
            .select("*")
            .eq("tipo", tipo)
            .order("created_at", desc=True)
            .limit(limite)
            .execute()
        )
        return resultado.data
    except Exception as e:
        log.error("memory: no se pudieron obtener memorias de tipo %s (%s)", tipo, e)
        return []
