# ============================================================
# GERAM OS v2 · calendar_agent.py
# Google Calendar API: eventos del día/semana, crear/eliminar
# eventos. Usa las credenciales OAuth2 compartidas de _google_auth.py
# (mismo login que email_agent.py).
# ============================================================

import logging
from datetime import datetime, timedelta

from googleapiclient.discovery import build

from agents import _google_auth, balancer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("calendar_agent")

_servicio = None

_PROMPT_PARSEAR_EVENTO = """Eres un parser de eventos de calendario. El usuario te pide agendar algo, en lenguaje natural. Devuelve SOLO un JSON así, nada más:
{{
  "titulo": "título corto del evento",
  "fecha_inicio": "YYYY-MM-DDTHH:MM:SS",
  "fecha_fin": "YYYY-MM-DDTHH:MM:SS",
  "descripcion": ""
}}

Reglas:
- Calcula las fechas reales a partir de la fecha y hora ACTUAL de abajo.
- Si no da duración, asume 1 hora de fecha_inicio a fecha_fin.
- Si no hay hora específica, usa las 09:00.
- Si no hay fecha específica, asume el próximo momento razonable (hoy
  si esa hora todavía no pasó; si ya pasó, mañana).
- SOLO responde el JSON, nada más.

Fecha y hora actual: {ahora}
Mensaje del usuario: {mensaje}"""


def _obtener_servicio():
    global _servicio
    if _servicio is None:
        creds = _google_auth.obtener_credenciales()
        _servicio = build("calendar", "v3", credentials=creds)
    return _servicio


def _formatear_eventos(eventos_crudos):
    formateados = []
    for e in eventos_crudos:
        inicio = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date")
        formateados.append({
            "id": e["id"],
            "titulo": e.get("summary", "(sin título)"),
            "inicio": inicio,
            "descripcion": e.get("description", ""),
            "link": e.get("htmlLink"),
        })
    return formateados


def _listar_eventos(desde, hasta):
    servicio = _obtener_servicio()
    resultado = servicio.events().list(
        calendarId="primary",
        timeMin=desde.isoformat(),
        timeMax=hasta.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return _formatear_eventos(resultado.get("items", []))


def obtener_eventos_hoy():
    """Devuelve los eventos de HOY (lista de dicts) o {"error": "..."}."""
    try:
        ahora = datetime.now().astimezone()
        inicio_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        fin_dia = inicio_dia + timedelta(days=1)
        return _listar_eventos(inicio_dia, fin_dia)
    except Exception as e:
        log.error("calendar_agent: no se pudieron leer los eventos de hoy (%s)", e)
        return {"error": str(e)}


def obtener_eventos_semana():
    """Devuelve los eventos de los próximos 7 días o {"error": "..."}."""
    try:
        ahora = datetime.now().astimezone()
        inicio_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        fin_semana = inicio_dia + timedelta(days=7)
        return _listar_eventos(inicio_dia, fin_semana)
    except Exception as e:
        log.error("calendar_agent: no se pudieron leer los eventos de la semana (%s)", e)
        return {"error": str(e)}


def crear_evento(titulo, fecha_inicio, fecha_fin, descripcion=""):
    """fecha_inicio/fecha_fin: datetime. Si no traen tzinfo, se asume
    la zona horaria local del sistema. Devuelve {"id","link"} o
    {"error": "..."}."""
    try:
        servicio = _obtener_servicio()

        if fecha_inicio.tzinfo is None:
            fecha_inicio = fecha_inicio.astimezone()
        if fecha_fin.tzinfo is None:
            fecha_fin = fecha_fin.astimezone()

        evento = {
            "summary": titulo,
            "description": descripcion,
            "start": {"dateTime": fecha_inicio.isoformat()},
            "end": {"dateTime": fecha_fin.isoformat()},
        }
        creado = servicio.events().insert(calendarId="primary", body=evento).execute()
        return {"id": creado["id"], "link": creado.get("htmlLink")}
    except Exception as e:
        log.error("calendar_agent: no se pudo crear el evento (%s)", e)
        return {"error": str(e)}


def eliminar_evento(id_evento):
    """Devuelve True/False según si se pudo borrar."""
    try:
        servicio = _obtener_servicio()
        servicio.events().delete(calendarId="primary", eventId=id_evento).execute()
        return True
    except Exception as e:
        log.error("calendar_agent: no se pudo eliminar el evento %s (%s)", id_evento, e)
        return False


def crear_evento_desde_texto(mensaje_usuario):
    """Punto de entrada desde director.py: le pide a Gemini que separe
    el mensaje natural ("agenda box a las 5") en título + fechas, y
    crea el evento. Devuelve el mensaje final para el usuario (nunca
    lanza excepción)."""
    import json
    import re

    prompt = _PROMPT_PARSEAR_EVENTO.format(
        ahora=datetime.now().isoformat(timespec="seconds"), mensaje=mensaje_usuario,
    )
    crudo = balancer.enviar_mensaje(prompt=prompt, historial=[], system_instruction=None)
    if crudo.startswith("ERROR:"):
        return f"No pude agendar el evento: {crudo}"

    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", crudo.strip(), flags=re.I)
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        coincidencia = re.search(r"\{.*\}", texto, re.S)
        datos = json.loads(coincidencia.group(0)) if coincidencia else None

    if not datos or not datos.get("titulo") or not datos.get("fecha_inicio"):
        log.error("calendar_agent: JSON inválido del modelo: %r", crudo)
        return "No entendí bien el evento, ¿me lo repites más claro?"

    try:
        inicio = datetime.fromisoformat(datos["fecha_inicio"])
        fin = datetime.fromisoformat(datos.get("fecha_fin") or datos["fecha_inicio"])
    except ValueError:
        return "Gemini me dio una fecha rara para el evento, intenta de nuevo."

    resultado = crear_evento(datos["titulo"], inicio, fin, datos.get("descripcion", ""))
    if resultado.get("error"):
        return f"No pude crear el evento en Google Calendar: {resultado['error']}"

    fecha_legible = inicio.strftime("%d/%m a las %H:%M")
    return f"Listo, agendé '{datos['titulo']}' el {fecha_legible}."


def resumen_eventos_hoy_texto():
    """Texto legible de los eventos de hoy, para "qué tengo hoy"."""
    eventos = obtener_eventos_hoy()
    if isinstance(eventos, dict) and eventos.get("error"):
        return f"No pude leer tu calendario: {eventos['error']}"
    if not eventos:
        return "No tienes nada agendado hoy, jefe."

    lineas = []
    for e in eventos:
        try:
            hora = datetime.fromisoformat(e["inicio"]).strftime("%H:%M")
        except (ValueError, TypeError):
            hora = "todo el día"
        lineas.append(f"{hora} — {e['titulo']}")
    return "Hoy tienes:\n" + "\n".join(lineas)
