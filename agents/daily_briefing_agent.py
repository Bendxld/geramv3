# ============================================================
# GERAM OS v2 · daily_briefing_agent.py
# Resumen matutino: tareas/páginas pendientes en Notion + estado real
# del sistema + eventos del día de Google Calendar (si ya está
# autenticado; si no, se omite sin tronar el briefing), redactado en
# lenguaje natural por Gemini y hablado con habla.py si la voz está activa.
# ============================================================

import logging
import random
import time

import psutil

import config
from agents import balancer, calendar_agent, finance_agent, habla, notion_agent, offline_agent, pendientes_agent, personality, spotify_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("daily_briefing_agent")

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _fecha_natural():
    from datetime import datetime
    ahora = datetime.now()
    return f"{_DIAS[ahora.weekday()]} {ahora.day} de {_MESES[ahora.month - 1]}"


def _resumen_notion():
    """Notion no tiene un concepto genérico de 'completado' sin saber
    el schema exacto de properties del usuario, así que por ahora se
    listan las páginas más recientes del database como 'pendientes'.
    Devuelve (texto_para_el_prompt, lista_de_paginas_o_None)."""
    paginas = notion_agent.listar_paginas(limite=20)

    if isinstance(paginas, dict) and paginas.get("error"):
        return f"no se pudo leer Notion ({paginas['error']})", None
    if not paginas:
        return "no hay páginas recientes en Notion", []

    titulos = ", ".join(p["titulo"] for p in paginas[:5])
    return f"{len(paginas)} páginas recientes en Notion: {titulos}", paginas


def _resumen_calendario():
    """Eventos de HOY en Google Calendar. Si calendar_agent todavía no
    está autenticado (falta el OAuth2), degrada con un texto claro en
    vez de tronar el briefing — el prompt de generar_briefing() ya
    sabe no mencionar el calendario cuando dice eso."""
    eventos = calendar_agent.obtener_eventos_hoy()

    if isinstance(eventos, dict) and eventos.get("error"):
        return "no disponible todavía (calendar_agent sin autenticar)"
    if not eventos:
        return "no tienes nada agendado hoy"

    titulos = ", ".join(e["titulo"] for e in eventos[:5])
    return f"{len(eventos)} eventos hoy: {titulos}"


def _resumen_sistema():
    """Estado real del equipo (CPU/RAM ahorita, uptime del SISTEMA
    operativo, no del proceso de server.py) y si Gemini/Ollama
    responden, para el "todas las APIs están funcionando" del briefing."""
    uso_cpu = psutil.cpu_percent(interval=0.3)
    uso_ram = psutil.virtual_memory().percent

    segundos_uptime = int(time.time() - psutil.boot_time())
    h, resto = divmod(segundos_uptime, 3600)
    m, _ = divmod(resto, 60)

    hay_internet = offline_agent.hay_internet()

    return {
        "cpu": uso_cpu,
        "ram": uso_ram,
        "uptime": f"{h}h {m}m",
        "internet": hay_internet,
    }


def _resumen_finanzas():
    """Gasto de la semana + balance del mes (finance_agent.py, Fase D).
    Nunca lanza excepción: degrada con texto claro si Supabase falla."""
    return finance_agent.resumen_para_briefing()


def _resumen_pendientes_personales():
    """Cuenta de pendientes sin completar (pendientes_agent.py, Fase D,
    Notion). None -> Notion falló, el briefing lo omite sin explicar por qué."""
    cantidad = pendientes_agent.contar_pendientes()
    if cantidad is None:
        return "no disponible (Notion con error)"
    if cantidad == 0:
        return "no tienes pendientes sin completar"
    return f"tienes {cantidad} pendientes sin completar"


def _resumen_musica():
    """Últimas canciones en Spotify (spotify_agent.py, solo lectura),
    si ya está configurado Y autorizado. Nunca lanza excepción: "no
    disponible" en cualquier caso donde falte algo — el prompt de
    generar_briefing() ya sabe no mencionar música cuando dice eso."""
    if not spotify_agent.esta_configurado():
        return "no disponible (Spotify sin configurar)"
    resultado = spotify_agent.recientes_texto(limite=5)
    if resultado.startswith("No pude"):
        return "no disponible (Spotify sin autorizar todavía)"
    return resultado


# Frase fija (no generada por Gemini, a propósito — así director.py
# puede detectarla de forma confiable, ver MARCA_SUGERENCIA_EXAMEN/
# director._procesar_briefing) que a veces se agrega al final del
# briefing ofreciendo un examen rápido de repaso (ver examen_agent.py).
# "a veces": una probabilidad fija en vez de siempre, para que no se
# sienta repetitivo cada mañana.
MARCA_SUGERENCIA_EXAMEN = "examen rápido de repaso"
_PROB_SUGERENCIA_EXAMEN = 0.3


def _sugerencia_examen():
    if random.random() < _PROB_SUGERENCIA_EXAMEN:
        return f"\n\n¿Quieres que te haga un {MARCA_SUGERENCIA_EXAMEN} de lo que estudiaste ayer?"
    return ""


def generar_briefing(hablar_en_voz=False):
    """Arma el resumen del día y lo devuelve como texto (nunca lanza
    excepción: cualquier fuente que falle se refleja en el prompt en
    vez de tronar el briefing completo).

    `hablar_en_voz=True` además lo reproduce con habla.hablar() —
    pensado para el disparo automático por scheduler (server.py), que
    no tiene un navegador esperando la respuesta como el chat sí."""
    fecha = _fecha_natural()
    resumen_notion, _ = _resumen_notion()
    resumen_calendario = _resumen_calendario()
    resumen_finanzas = _resumen_finanzas()
    resumen_pendientes_personales = _resumen_pendientes_personales()
    resumen_musica = _resumen_musica()
    estado = _resumen_sistema()

    estado_apis = "con internet, Gemini disponible" if estado["internet"] else "sin internet, usando Ollama local"

    prompt = (
        "Arma el briefing matutino para mauri (jefe). Datos REALES, no inventes nada más:\n"
        f"- Fecha: {fecha}\n"
        f"- Notion: {resumen_notion}\n"
        f"- Calendario: {resumen_calendario}\n"
        f"- Finanzas: {resumen_finanzas}\n"
        f"- Pendientes personales: {resumen_pendientes_personales}\n"
        f"- Música (Spotify): {resumen_musica}\n"
        f"- Sistema: uptime {estado['uptime']}, CPU {estado['cpu']}%, RAM {estado['ram']}%, {estado_apis}\n\n"
        "Redacta un resumen breve y natural en tu personalidad (sarcástica "
        "pero servicial), como si fuera lo primero que le dices al jefe en "
        "la mañana. Menciona la fecha, las páginas de Notion, el calendario "
        "SOLO si dice que hay eventos (si dice 'no disponible todavía' no lo "
        "menciones en absoluto, no expliques por qué), las finanzas y los "
        "pendientes personales SOLO si dicen 'no disponible' no los menciones "
        "en absoluto tampoco, la música SOLO si dice 'no disponible' no la "
        "menciones en absoluto tampoco, y que el sistema está estable. No "
        "inventes tareas, eventos, cifras ni canciones que no te di."
    )

    texto = balancer.enviar_mensaje(
        prompt=prompt, historial=[], system_instruction=personality.obtener_system_prompt(),
    )
    texto += _sugerencia_examen()

    if hablar_en_voz:
        try:
            habla.hablar(texto)
        except Exception as e:
            log.error("daily_briefing_agent: no se pudo hablar el briefing (%s)", e)

    return texto
