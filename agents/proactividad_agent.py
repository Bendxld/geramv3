# ============================================================
# GERAM OS v2 · proactividad_agent.py
# IRIS/ARES hablando sin que se le pregunte: seis señales (gastos
# semanales, batería baja, evento de calendario por empezar, sesión
# larga sin parar, pendientes de Notion olvidados, patrones semanales
# repetidos) revisadas por dos checkers en background (ver server.py)
# que llaman habla.hablar() directo, igual que
# reminder_agent.revisar_recordatorios_vencidos(). Los avisos también
# se encolan en _avisos_pendientes para que el HUD los muestre en el
# chat vía GET /proactividad/avisos.
#
# Apagable por completo con config.PROACTIVIDAD_ACTIVA=false (.env),
# sin tocar código, mientras se ajustan los umbrales de cada señal.
# ============================================================

import logging
import time
from collections import defaultdict
from datetime import date, datetime

import psutil

import config
from agents import balancer, calendar_agent, finance_agent, habla, lock_agent, memory, pendientes_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("proactividad_agent")

_NOMBRE_DIA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

_avisos_pendientes = []

# Batería: bandera de "ya avisé esta racha de batería baja". Se limpia
# con histéresis (umbral + 5%, o cargando) para no parpadear justo en
# el umbral.
_bateria_avisada = False

# Calendario: qué día son los ids ya avisados, para poder vaciar el set
# solo (y gratis) cuando cambia el día.
_dia_eventos_actual = None
_eventos_avisados = set()

# Sesión: inicio de la racha activa actual (None = no hay racha activa
# en curso) y si ya se avisó esa racha.
_sesion_inicio = None
_sesion_avisada = False

# Pendientes olvidados: último aviso por id de pendiente, para el
# cooldown de re-insistencia (se poda cada corrida contra la lista
# vigente de listar_pendientes()).
_pendientes_avisados = {}

# Patrones: qué intents ya se sugirieron hoy, para no repetir la misma
# sugerencia varias veces en un rato (se vacía sola al cambiar el día).
_dia_patrones_actual = None
_patrones_sugeridos_hoy = set()

# Frase natural por intent, para la sugerencia de patrones ("cada lunes
# sueles {frase}, ¿te lo adelanto?"). Mismo universo que
# director._INTENTS_PATRON.
_INTENTS_A_FRASE = {
    "control": "controlar el sistema",
    "recordatorio": "poner un recordatorio",
    "calendario": "ver tu agenda",
    "correo": "revisar tu correo",
    "classroom": "revisar tus tareas de la escuela",
    "nexus": "entrar a Nexus",
    "finanzas": "revisar tus finanzas",
    "pendientes": "revisar tus pendientes",
    "briefing": "pedir tu resumen del día",
    "clipboard": "revisar el portapapeles",
    "archivos": "buscar un archivo",
    "whatsapp": "mandar un WhatsApp",
    "investigacion": "investigar algo",
}


def _en_horario_silencio():
    """True si la hora actual cae dentro de la ventana de silencio
    (config.PROACTIVIDAD_SILENCIO_INICIO/FIN, formato HHMM). La ventana
    por default cruza medianoche (23:00 -> 07:00), así que la
    comparación no es un rango simple."""
    inicio = (config.PROACTIVIDAD_SILENCIO_INICIO or "2300").strip()
    fin = (config.PROACTIVIDAD_SILENCIO_FIN or "0700").strip()
    ahora = datetime.now().strftime("%H%M")
    if inicio <= fin:
        return inicio <= ahora < fin
    return ahora >= inicio or ahora < fin


def _avisar(texto):
    """Dice el aviso en voz (sin depender de que el HUD esté abierto) y
    lo encola para que el HUD lo muestre en el chat. Un fallo de TTS no
    debe tumbar el resto del chequeo."""
    log.info("proactividad_agent: aviso -> %s", texto)
    _avisos_pendientes.append(texto)
    try:
        habla.hablar(texto)
    except Exception as e:
        log.error("proactividad_agent: no se pudo decir el aviso en voz (%s)", e)
    try:
        # Import diferido, mismo motivo que reminder_agent._avisar (ver
        # ahí) — aunque proactividad_agent no forme parte del ciclo
        # director->reminder_agent, se usa el mismo patrón por
        # consistencia entre los dos disparadores de avisos.
        from agents import telegram_agent
        telegram_agent.enviar_notificacion(texto)
    except Exception as e:
        log.error("proactividad_agent: no se pudo mandar el aviso por Telegram (%s)", e)


def _revisar_gasto_semanal():
    """El dedup por semana ya vive en finance_agent.alerta_gastos()
    (compartido con la vía reactiva de director.py), aquí solo se
    dispara si hay texto."""
    try:
        aviso = finance_agent.alerta_gastos()
    except Exception as e:
        log.error("proactividad_agent: falló la revisión de gastos (%s)", e)
        return
    if aviso:
        _avisar(aviso)


def _revisar_bateria():
    global _bateria_avisada
    try:
        bateria = psutil.sensors_battery()
    except Exception as e:
        log.error("proactividad_agent: falló la lectura de batería (%s)", e)
        return

    if bateria is None:
        # Equipo de escritorio sin batería (ej. el i3 de este proyecto).
        return

    umbral = config.ALERTA_BATERIA_PORCENTAJE
    conectada = bool(bateria.power_plugged)

    if bateria.percent >= umbral + 5 or conectada:
        _bateria_avisada = False
        return

    if bateria.percent <= umbral and not conectada and not _bateria_avisada:
        _bateria_avisada = True
        _avisar(
            f"Jefe, la batería anda en {bateria.percent:.0f}% y no está "
            "cargando. Conéctala antes de que te deje a medias."
        )


# Uso de Gemini: qué umbrales (80/90/95%) ya se avisaron HOY por key,
# para no repetir el mismo aviso en cada poll de 60s — se limpia solo
# al cambiar de día (mismo criterio que _dia_eventos_actual). El jefe
# pidió esto explícitamente: avisos según se acerca al 100%, y SIEMPRE
# que se use la key de pago (esa es "solo último recurso", cuesta
# dinero real).
_UMBRALES_USO_GEMINI = (80, 90, 95)
_dia_uso_gemini_actual = None
_umbrales_avisados_por_key = {}
_pago_usos_avisados = 0


def _revisar_uso_gemini():
    """Avisa cuando alguna key gratuita de Gemini se acerca a su límite
    diario ESTIMADO (ver balancer.obtener_uso_hoy — conteo LOCAL de
    llamadas de este proceso, no la cuota real de Google) y SIEMPRE que
    se usó la key de PAGO desde el último chequeo."""
    global _dia_uso_gemini_actual, _umbrales_avisados_por_key, _pago_usos_avisados
    hoy = date.today()
    if _dia_uso_gemini_actual != hoy:
        _dia_uso_gemini_actual = hoy
        _umbrales_avisados_por_key = {}
        _pago_usos_avisados = 0

    try:
        uso = balancer.obtener_uso_hoy()
    except Exception as e:
        log.error("proactividad_agent: no se pudo leer el uso de Gemini (%s)", e)
        return

    for numero_key, porcentaje in uso["porcentajes"].items():
        ya_avisados = _umbrales_avisados_por_key.setdefault(numero_key, set())
        for umbral in _UMBRALES_USO_GEMINI:
            if porcentaje >= umbral and umbral not in ya_avisados:
                ya_avisados.add(umbral)
                _avisar(
                    f"Jefe, la key {numero_key} de Gemini ya lleva ~{porcentaje:.0f}% de su uso "
                    f"estimado de hoy ({uso['por_key'][numero_key]}/{config.GEMINI_LIMITE_DIARIO_POR_KEY})."
                )

    if uso["pago_usos"] > _pago_usos_avisados:
        nuevos = uso["pago_usos"] - _pago_usos_avisados
        _pago_usos_avisados = uso["pago_usos"]
        _avisar(
            f"Ojo jefe: se usó la key de PAGO de Gemini {nuevos} vez(es) porque las 5 gratis fallaron o ya "
            "se agotaron. Esa es solo último recurso — puede que tus cuotas gratis de hoy ya casi se acaben."
        )


def _revisar_calendario():
    global _dia_eventos_actual, _eventos_avisados
    hoy = date.today()
    if hoy != _dia_eventos_actual:
        _dia_eventos_actual = hoy
        _eventos_avisados = set()

    try:
        eventos = calendar_agent.obtener_eventos_hoy()
    except Exception as e:
        log.error("proactividad_agent: falló la revisión de calendario (%s)", e)
        return

    if isinstance(eventos, dict):
        # {"error": "..."} — Google Calendar no disponible ahora mismo.
        return

    umbral = config.ALERTA_CALENDARIO_MINUTOS
    ahora = datetime.now().astimezone()
    for evento in eventos:
        id_evento = evento.get("id")
        if not id_evento or id_evento in _eventos_avisados:
            continue
        try:
            inicio = datetime.fromisoformat(evento["inicio"])
        except (KeyError, TypeError, ValueError):
            # Eventos de todo el día solo traen "date" (sin hora), o el
            # campo viene mal formado: no truena el resto del tick.
            continue

        minutos_para_empezar = (inicio - ahora).total_seconds() / 60
        if 0 <= minutos_para_empezar <= umbral:
            _eventos_avisados.add(id_evento)
            _avisar(f'Jefe, en {round(minutos_para_empezar)} minutos empieza "{evento["titulo"]}".')


def _revisar_sesion():
    global _sesion_inicio, _sesion_avisada
    inactivo_min = lock_agent.minutos_inactivo()

    if inactivo_min >= config.SESION_DESCANSO_MINUTOS:
        _sesion_inicio = None
        _sesion_avisada = False
        return

    if _sesion_inicio is None:
        _sesion_inicio = time.time()
        return

    duracion_min = (time.time() - _sesion_inicio) / 60
    if duracion_min >= config.SESION_LARGA_MINUTOS and not _sesion_avisada:
        _sesion_avisada = True
        _avisar(
            f"Jefe, llevas {int(duracion_min)} minutos seguidos sin parar. "
            "Tómate un respiro, no te lo voy a repetir dos veces."
        )


def _revisar_pendientes_olvidados():
    """Pendientes de Notion con más de config.PENDIENTE_OLVIDADO_DIAS
    días desde su creación. Si hay varios vencidos en el mismo chequeo
    (típico justo después de reiniciar el server), se habla UN SOLO
    aviso combinado, no uno por pendiente — las demás señales de este
    archivo también disparan una sola vez por tick."""
    global _pendientes_avisados
    try:
        pendientes = pendientes_agent.listar_pendientes()
    except Exception as e:
        log.error("proactividad_agent: falló la revisión de pendientes olvidados (%s)", e)
        return

    if isinstance(pendientes, dict):
        # {"error": "..."} — Notion no disponible ahora mismo.
        return

    ids_actuales = {p["id"] for p in pendientes}
    _pendientes_avisados = {pid: ts for pid, ts in _pendientes_avisados.items() if pid in ids_actuales}

    ahora = datetime.now().astimezone()
    umbral_dias = config.PENDIENTE_OLVIDADO_DIAS
    cooldown_dias = config.PENDIENTE_RENAGGED_COOLDOWN_DIAS

    olvidados = []
    for p in pendientes:
        if not p.get("creado"):
            continue
        try:
            creado = datetime.fromisoformat(p["creado"])
        except ValueError:
            continue

        antiguedad_dias = (ahora - creado).days
        if antiguedad_dias < umbral_dias:
            continue

        ultimo_aviso = _pendientes_avisados.get(p["id"])
        if ultimo_aviso is not None and (ahora - ultimo_aviso).days < cooldown_dias:
            continue

        olvidados.append((p, antiguedad_dias))

    if not olvidados:
        return

    for p, _dias in olvidados:
        _pendientes_avisados[p["id"]] = ahora

    if len(olvidados) == 1:
        p, dias = olvidados[0]
        texto = f"Jefe, tienes '{p['titulo']}' pendiente desde hace {dias} días, ¿lo resuelves o lo tiro?"
    else:
        detalle = "; ".join(f"'{p['titulo']}' ({dias} días)" for p, dias in olvidados)
        texto = f"Jefe, tienes {len(olvidados)} pendientes olvidados: {detalle}."

    _avisar(texto)


def _revisar_patrones():
    """Busca intents que se repiten el mismo día de la semana en varias
    semanas ISO distintas (memorias tipo="patron", ver
    director._rutear_por_intencion) y sugiere adelantarse. Contar
    SEMANAS DISTINTAS y no filas crudas es a propósito: un mensaje
    compuesto puede generar 2-3 filas del mismo intent en un solo día,
    lo que no es un patrón semanal todavía."""
    global _dia_patrones_actual, _patrones_sugeridos_hoy
    hoy = date.today()
    if hoy != _dia_patrones_actual:
        _dia_patrones_actual = hoy
        _patrones_sugeridos_hoy = set()

    try:
        memorias = memory.obtener_memorias_por_tipo("patron", limite=config.PATRON_MEMORIAS_LIMITE)
    except Exception as e:
        log.error("proactividad_agent: falló la revisión de patrones (%s)", e)
        return

    dia_semana_hoy = hoy.weekday()
    grupos = defaultdict(set)  # (intencion, dia_semana) -> {(año_iso, semana_iso), ...}
    ocurrio_hoy = set()

    for m in memorias:
        intencion = m.get("texto")
        creado_raw = m.get("created_at")
        if not intencion or not creado_raw:
            continue
        try:
            creado = datetime.fromisoformat(creado_raw)
        except ValueError:
            continue

        grupos[(intencion, creado.weekday())].add(creado.isocalendar()[:2])
        if creado.date() == hoy:
            ocurrio_hoy.add(intencion)

    umbral = config.PATRON_MINIMO_OCURRENCIAS
    for (intencion, dia_semana), semanas in grupos.items():
        if dia_semana != dia_semana_hoy or len(semanas) < umbral:
            continue
        if intencion in ocurrio_hoy or intencion in _patrones_sugeridos_hoy:
            continue

        _patrones_sugeridos_hoy.add(intencion)
        frase = _INTENTS_A_FRASE.get(intencion, intencion)
        _avisar(f"Jefe, cada {_NOMBRE_DIA[dia_semana]} sueles {frase}, ¿te lo adelanto?")


def revisar_local():
    """Checker de 60s (server.py): señales locales/gratis, sin pegarle
    a APIs externas. El uso de Gemini también cuenta como "local":
    balancer.obtener_uso_hoy() es puro conteo en memoria, no llama a
    ninguna API."""
    if not config.PROACTIVIDAD_ACTIVA or _en_horario_silencio():
        return
    _revisar_bateria()
    _revisar_sesion()
    _revisar_uso_gemini()


def revisar_externo():
    """Checker de 5 min (server.py): señales que dependen de Supabase,
    Notion o Google Calendar, no hace falta pollearlas tan seguido."""
    if not config.PROACTIVIDAD_ACTIVA or _en_horario_silencio():
        return
    _revisar_gasto_semanal()
    _revisar_calendario()
    _revisar_pendientes_olvidados()
    _revisar_patrones()


def obtener_avisos_pendientes():
    """Saca (y vacía) la cola de avisos ya disparados, para que
    server.py se los entregue al HUD sin repetirlos."""
    global _avisos_pendientes
    avisos = _avisos_pendientes
    _avisos_pendientes = []
    return avisos
