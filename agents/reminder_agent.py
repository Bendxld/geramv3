# ============================================================
# GERAM OS v2 · reminder_agent.py
# Recordatorios proactivos: se guardan en Supabase (tabla
# "recordatorios", compartida entre IRIS/ARES igual que memory.py)
# y un checker en background (ver server.py) revisa cada 60s si
# alguno ya llegó a su hora, para avisar por voz y dejarlo encolado
# para que el HUD lo muestre en el chat la próxima vez que consulte.
#
# IMPORTANTE: la tabla "recordatorios" debe crearse manualmente en
# Supabase antes de usar este módulo (ver el SQL al final del reporte
# de esta fase).
# ============================================================

import json
import logging
import re
from datetime import datetime

from supabase import create_client

import config
from agents import balancer, habla

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("reminder_agent")

_cliente = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

TABLA = "recordatorios"

# Avisos ya disparados por el checker, esperando a que el HUD los
# recoja (ver /recordatorios/avisos en server.py) y los muestre en el
# chat. La voz ya se dice sola desde el checker (no depende de que
# haya un navegador abierto escuchando).
_avisos_pendientes = []

_PROMPT_PARSEAR_RECORDATORIO = """Eres un parser de recordatorios. El usuario te pide que le recuerdes algo, con una fecha/hora en lenguaje natural. Devuelve SOLO un JSON así, nada más:
{{
  "texto": "qué hay que recordar (la acción, sin la fecha/hora)",
  "fecha_hora": "YYYY-MM-DDTHH:MM:SS"
}}

Reglas:
- Calcula la fecha/hora real a partir de la fecha y hora ACTUAL de abajo.
- Si no hay hora específica en el mensaje, usa las 09:00.
- Si no hay fecha específica, asume el próximo momento razonable (hoy
  si esa hora todavía no pasó; si ya pasó, mañana).
- SOLO responde el JSON, nada más.

Fecha y hora actual: {ahora}
Mensaje del usuario: {mensaje}"""


def _parsear_json(texto):
    """Extrae el JSON de la respuesta del modelo, tolerando fences de
    markdown (```json ... ```) igual que control_agent.py."""
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.I)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        coincidencia = re.search(r"\{.*\}", texto, re.S)
        if coincidencia:
            try:
                return json.loads(coincidencia.group(0))
            except json.JSONDecodeError:
                pass
    return None


def crear_recordatorio(texto, fecha_hora):
    """Crea un recordatorio nuevo. `fecha_hora` puede ser un datetime
    o un string ISO 8601 (YYYY-MM-DDTHH:MM:SS)."""
    if isinstance(fecha_hora, datetime):
        fecha_iso = fecha_hora.isoformat()
    else:
        fecha_iso = str(fecha_hora)
        datetime.fromisoformat(fecha_iso)  # valida el formato, lanza si es inválido

    fila = {
        "texto": texto,
        "fecha_hora": fecha_iso,
        "completado": False,
        "instancia": config.INSTANCE_NAME,
    }
    try:
        resultado = _cliente.table(TABLA).insert(fila).execute()
        return resultado.data[0] if resultado.data else None
    except Exception as e:
        log.error("reminder_agent: no se pudo guardar el recordatorio (%s)", e)
        return None


def crear_recordatorio_desde_texto(mensaje_usuario):
    """Punto de entrada desde director.py: le pide a Gemini que separe
    el mensaje natural del usuario ("recuérdame comprar jamaica mañana
    a las 10") en texto + fecha_hora, y crea el recordatorio.

    Devuelve el mensaje final para el usuario (nunca lanza excepción)."""
    prompt = _PROMPT_PARSEAR_RECORDATORIO.format(
        ahora=datetime.now().isoformat(timespec="seconds"), mensaje=mensaje_usuario,
    )
    crudo = balancer.enviar_mensaje(prompt=prompt, historial=[], system_instruction=None)

    if crudo.startswith("ERROR:"):
        return f"No pude crear el recordatorio: {crudo}"

    datos = _parsear_json(crudo)
    if not datos or not datos.get("texto") or not datos.get("fecha_hora"):
        log.error("reminder_agent: JSON inválido del modelo: %r", crudo)
        return "No entendí bien la fecha/hora del recordatorio, ¿me lo repites más claro?"

    try:
        fecha_dt = datetime.fromisoformat(datos["fecha_hora"])
    except ValueError:
        return f"Gemini me dio una fecha rara ({datos['fecha_hora']}), intenta de nuevo."

    creado = crear_recordatorio(datos["texto"], fecha_dt)
    if not creado:
        return "No pude guardar el recordatorio (falló Supabase, revisa los logs)."

    fecha_legible = fecha_dt.strftime("%d/%m a las %H:%M")
    return f"Va, te recuerdo '{datos['texto']}' el {fecha_legible}."


def listar_recordatorios(incluir_completados=False):
    """Lista los recordatorios (de cualquier instancia), más próximos
    primero. Devuelve [] si Supabase falla, nunca lanza excepción."""
    try:
        consulta = _cliente.table(TABLA).select("*").order("fecha_hora", desc=False)
        if not incluir_completados:
            consulta = consulta.eq("completado", False)
        return consulta.execute().data
    except Exception as e:
        log.error("reminder_agent: no se pudieron listar recordatorios (%s)", e)
        return []


def eliminar_recordatorio(id_recordatorio):
    """Borra un recordatorio por id. Devuelve True/False según si pudo."""
    try:
        _cliente.table(TABLA).delete().eq("id", id_recordatorio).execute()
        return True
    except Exception as e:
        log.error("reminder_agent: no se pudo eliminar el recordatorio %s (%s)", id_recordatorio, e)
        return False


def _marcar_completado(id_recordatorio):
    _cliente.table(TABLA).update({"completado": True}).eq("id", id_recordatorio).execute()


def revisar_recordatorios_vencidos():
    """Llamado cada 60s por el scheduler de server.py: busca
    recordatorios con fecha_hora <= ahora que no se hayan avisado
    todavía, los marca como completados (para no repetir el aviso), y
    por cada uno: lo dice en voz alta (habla.hablar, no depende de que
    haya un navegador abierto) y lo encola para que el HUD lo muestre
    en el chat la próxima vez que consulte /recordatorios/avisos."""
    ahora_iso = datetime.now().isoformat(timespec="seconds")
    try:
        vencidos = (
            _cliente.table(TABLA)
            .select("*")
            .eq("completado", False)
            .lte("fecha_hora", ahora_iso)
            .execute()
        ).data
    except Exception as e:
        log.error("reminder_agent: no se pudo revisar recordatorios (%s)", e)
        return []

    for r in vencidos:
        _marcar_completado(r["id"])
        mensaje = f"Recordatorio, jefe: {r['texto']}"
        log.info("reminder_agent: recordatorio vencido -> %s", mensaje)
        _avisos_pendientes.append(mensaje)
        try:
            habla.hablar(mensaje)
        except Exception as e:
            log.error("reminder_agent: no se pudo decir el recordatorio en voz (%s)", e)
        try:
            # Import diferido (no al inicio del archivo): director.py
            # importa reminder_agent, y telegram_agent importa director,
            # así que un import de telegram_agent aquí arriba crearía un
            # ciclo. Resuelto en tiempo de llamada, cuando todos los
            # módulos ya terminaron de cargar.
            from agents import telegram_agent
            telegram_agent.enviar_notificacion(mensaje)
        except Exception as e:
            log.error("reminder_agent: no se pudo mandar el recordatorio por Telegram (%s)", e)

    return vencidos


def obtener_avisos_pendientes():
    """Saca (y vacía) la cola de avisos ya disparados, para que
    server.py se los entregue al HUD sin repetirlos."""
    global _avisos_pendientes
    avisos = _avisos_pendientes
    _avisos_pendientes = []
    return avisos
