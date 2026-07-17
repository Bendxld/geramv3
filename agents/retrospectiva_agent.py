# ============================================================
# GERAM OS v2 · retrospectiva_agent.py
# Retrospectiva semanal: a diferencia de daily_briefing_agent.py (que
# es operativo, "esto tienes hoy"), esta es reflexiva — qué se habló/
# hizo esta semana (memory.py), qué se completó (pendientes_agent.py)
# y cómo van las finanzas (finance_agent.py, ya semanal). Redactada en
# lenguaje natural por Gemini y hablada con habla.py si se dispara por
# el scheduler de server.py. Deliberadamente SIN calendario:
# calendar_agent.obtener_eventos_semana() mira hacia adelante, no hay
# equivalente retrospectivo, y no es el foco de un resumen reflexivo.
# ============================================================

import logging
from datetime import date, timedelta

from agents import balancer, finance_agent, habla, memory, pendientes_agent, personality

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("retrospectiva_agent")

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _fecha_natural():
    from datetime import datetime
    ahora = datetime.now()
    return f"{_DIAS[ahora.weekday()]} {ahora.day} de {_MESES[ahora.month - 1]}"


def _inicio_semana():
    """Lunes de la semana actual, en ISO (mismo cálculo que
    finance_agent._rango_semana, duplicado a propósito — no hay un
    módulo de utils compartido en este proyecto)."""
    hoy = date.today()
    return (hoy - timedelta(days=hoy.weekday())).isoformat()


def _resumen_memoria(inicio):
    """Lo que el jefe pidió/dijo esta semana (memory.py, tipo="usuario"
    a propósito: mezclar con tipo="iris" duplicaría el prompt con el
    eco de las propias respuestas, y con tipo="patron" metería ruido de
    una sola palabra por fila)."""
    memorias = memory.obtener_memorias_desde(inicio, tipo="usuario", limite=200)
    if not memorias:
        return "no hubo actividad registrada esta semana"

    textos = [m["texto"] for m in memorias if m.get("texto")][:40]
    return f"{len(memorias)} interacciones esta semana, algunas de ellas: " + "; ".join(textos)


def _resumen_pendientes_completados(inicio):
    """Pendientes de Notion completados esta semana (proxy por
    last_edited_time, ver pendientes_agent.listar_completados_desde)."""
    completados = pendientes_agent.listar_completados_desde(inicio)
    if isinstance(completados, dict) and completados.get("error"):
        return f"no se pudo leer Notion ({completados['error']})"
    if not completados:
        return "no se completó ningún pendiente esta semana"

    titulos = ", ".join(p["titulo"] for p in completados[:5])
    return f"{len(completados)} pendientes completados: {titulos}"


def _resumen_finanzas():
    """Gasto de la semana + balance del mes (ya semanal/mensual, mismo
    resumen que usa daily_briefing_agent para lo operativo)."""
    return finance_agent.resumen_para_briefing()


def generar_retrospectiva(hablar_en_voz=False):
    """Arma la retrospectiva de la semana y la devuelve como texto
    (nunca lanza excepción: cualquier fuente que falle se refleja en el
    prompt en vez de tronar la retrospectiva completa).

    `hablar_en_voz=True` además la reproduce con habla.hablar() —
    pensado para el disparo automático por scheduler (server.py, los
    domingos), que no tiene un navegador esperando la respuesta."""
    inicio = _inicio_semana()
    fecha = _fecha_natural()
    resumen_memoria = _resumen_memoria(inicio)
    resumen_pendientes = _resumen_pendientes_completados(inicio)
    resumen_finanzas = _resumen_finanzas()

    prompt = (
        "Arma la retrospectiva semanal para mauri (jefe) — HOY es "
        f"{fecha}, cierre de la semana que empezó el {inicio}. Datos REALES, "
        "no inventes nada más:\n"
        f"- Lo que se habló/pidió esta semana: {resumen_memoria}\n"
        f"- Pendientes completados: {resumen_pendientes}\n"
        f"- Finanzas: {resumen_finanzas}\n\n"
        "Esto NO es el briefing operativo de todos los días — es una "
        "retrospectiva reflexiva de cierre de semana: qué se logró, qué "
        "patrones notas en lo que estuvo haciendo/pidiendo el jefe, cómo "
        "se ve el panorama general. Tono narrativo, no una lista de "
        "tareas. En tu personalidad (sarcástica pero servicial), como "
        "quien voltea a ver la semana completa en vez de solo el día. "
        "No inventes logros, cifras ni eventos que no te di. Si alguna "
        "fuente dice 'no se pudo'/'no hubo actividad', no la menciones "
        "en absoluto en vez de explicar por qué falta."
    )

    texto = balancer.enviar_mensaje(
        prompt=prompt, historial=[], system_instruction=personality.obtener_system_prompt(),
    )

    if hablar_en_voz:
        try:
            habla.hablar(texto)
        except Exception as e:
            log.error("retrospectiva_agent: no se pudo hablar la retrospectiva (%s)", e)

    return texto
