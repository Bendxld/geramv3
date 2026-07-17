# ============================================================
# GERAM OS v2 · code_memoria.py
# Memoria de patrones de código que YA se verificaron exitosos (ver
# code_agent.py/code_proyectos.py) — tabla "codigo_exitoso" en
# Supabase, aparte de la tabla "memorias" genérica de memory.py porque
# esto guarda CÓDIGO completo (potencialmente largo) categorizado, no
# texto de conversación.
#
# Mismo patrón que memory.py: cliente de Supabase propio a nivel de
# módulo, cada función atrapa sus excepciones y nunca las deja
# escapar (si Supabase falla o la tabla no existe, el pipeline de
# code_agent.py se degrada — sin guardar/buscar patrones — en vez de
# tronar).
#
# IMPORTANTE: la tabla "codigo_exitoso" debe crearse manualmente en
# Supabase antes de usar este módulo (ver el SQL en el reporte de
# esta fase).
# ============================================================

import logging
import re

from supabase import create_client

import config
from agents import balancer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("code_memoria")

_cliente = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

TABLA = "codigo_exitoso"


def guardar_patron_exitoso(categoria, descripcion, codigo):
    """Guarda `codigo` como patrón exitoso de `categoria` (ej.
    "automatizacion", "3d", "2d", "proyecto") — SOLO debe llamarse
    después de una verificación real (ejecución sin tronar + pruebas
    ok, o verificación visual aprobada). `funciono_bien` siempre True
    aquí a propósito: si algo falló, nunca se llega a llamar esto."""
    fila = {
        "categoria": categoria,
        "descripcion": descripcion,
        "codigo": codigo,
        "funciono_bien": True,
    }
    try:
        resultado = _cliente.table(TABLA).insert(fila).execute()
        return resultado.data[0] if resultado.data else None
    except Exception as e:
        log.error("code_memoria: no se pudo guardar el patrón exitoso (%s)", e)
        return None


def _candidatos_por_categoria(categoria, limite):
    try:
        resultado = (
            _cliente.table(TABLA)
            .select("*")
            .eq("categoria", categoria)
            .eq("funciono_bien", True)
            .order("created_at", desc=True)
            .limit(limite)
            .execute()
        )
        return resultado.data
    except Exception as e:
        log.error("code_memoria: no se pudieron leer patrones de categoría '%s' (%s)", categoria, e)
        return []


_PROMPT_SIMILITUD = """El jefe pidió: "{descripcion}"

Aquí hay una lista de peticiones parecidas que YA se resolvieron con éxito antes:
{lista}

¿Alguna de la lista se parece lo bastante a la petición actual como para servir de referencia/plantilla (mismo tipo de resultado, aunque los detalles concretos cambien)? Responde ÚNICAMENTE con el NÚMERO de la más parecida, o la palabra NINGUNA si ninguna se parece de verdad. Nada más, sin explicaciones."""


def buscar_patron_similar(categoria, descripcion, limite=15):
    """Trae hasta `limite` patrones ya exitosos de `categoria` y le
    pide a Gemini que juzgue cuál (si alguno) se parece lo bastante a
    `descripcion` como para servir de referencia. Devuelve el `codigo`
    de ese patrón, o None si no hay candidatos, Gemini no respondió, o
    ninguno se pareció de verdad — nunca lanza excepción."""
    candidatos = _candidatos_por_categoria(categoria, limite)
    if not candidatos:
        return None

    lista = "\n".join(f"{i + 1}. {c['descripcion']}" for i, c in enumerate(candidatos))
    respuesta = balancer.enviar_mensaje(_PROMPT_SIMILITUD.format(descripcion=descripcion, lista=lista))
    if respuesta.startswith("ERROR:"):
        log.warning("code_memoria: Gemini no respondió al buscar patrón similar (%s)", respuesta)
        return None

    coincidencia = re.search(r"\d+", respuesta)
    if not coincidencia:
        return None
    indice = int(coincidencia.group(0))
    if not (1 <= indice <= len(candidatos)):
        return None
    return candidatos[indice - 1]["codigo"]
