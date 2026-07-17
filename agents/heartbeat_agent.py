# ============================================================
# GERAM OS v2 · heartbeat_agent.py
# La instancia LOCAL (server.py) escribe la hora actual cada ~15s en
# la tabla "heartbeat" de Supabase (ver latir()). cloud_bot.py (el bot
# de Telegram desplegado en la nube, ver ese archivo) lo consulta antes
# de cada ciclo de polling (ver esta_vivo()) para saber si la laptop
# está prendida: si lo está, se queda callado (la laptop ya está
# respondiendo Telegram con TODAS las funciones); si no, toma el
# relevo con lo que sí puede (ver director.MODO_NUBE/INTENTS_SOLO_LOCAL).
#
# Deliberadamente su PROPIA tabla (no reusa "memorias" de memory.py):
# esto es estado efímero de "¿está prendida la compu ahorita?", no una
# memoria que valga la pena conservar en el historial.
#
# IMPORTANTE: la tabla "heartbeat" debe crearse manualmente en
# Supabase antes de usar este módulo (ver el SQL en el reporte de
# esta fase).
# ============================================================

import logging
from datetime import datetime, timezone

from supabase import create_client

import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("heartbeat_agent")

_cliente = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

TABLA = "heartbeat"


def latir():
    """Actualiza el latido de ESTA instancia (config.INSTANCE_NAME) a
    AHORA MISMO. Llamado periódicamente por server.py (ver el
    scheduler ahí) — SOLO tiene sentido en la instancia local, nunca
    en cloud_bot.py. Nunca lanza excepción: si Supabase falla, el peor
    caso es que cloud_bot.py crea que la laptop está apagada y tome el
    relevo de más, no es grave."""
    try:
        _cliente.table(TABLA).upsert({
            "instancia": config.INSTANCE_NAME,
            "ultimo_latido": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        log.error("heartbeat_agent: no se pudo actualizar el latido (%s)", e)


def esta_vivo(umbral_segundos=None):
    """True si la instancia LOCAL (config.INSTANCE_NAME) tiene un
    latido más reciente que `umbral_segundos` (default
    config.HEARTBEAT_UMBRAL_SEGUNDOS). Si Supabase falla o nunca hubo
    un latido registrado, se asume que NO está viva — mejor que
    cloud_bot.py tome el relevo de más a que se quede mudo por un
    error de red pasajero."""
    umbral = umbral_segundos if umbral_segundos is not None else config.HEARTBEAT_UMBRAL_SEGUNDOS
    try:
        resultado = (
            _cliente.table(TABLA)
            .select("ultimo_latido")
            .eq("instancia", config.INSTANCE_NAME)
            .limit(1)
            .execute()
        )
        if not resultado.data:
            return False
        ultimo = datetime.fromisoformat(resultado.data[0]["ultimo_latido"].replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ultimo).total_seconds() < umbral
    except Exception as e:
        log.error("heartbeat_agent: no se pudo leer el latido (%s)", e)
        return False
