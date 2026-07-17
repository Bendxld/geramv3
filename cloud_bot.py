# ============================================================
# GERAM OS v2 · cloud_bot.py
# Punto de entrada para el despliegue en la nube (Render/Fly.io/
# Railway/Raspberry Pi/lo que sea): Telegram sin que la laptop esté
# prendida (ver conversación que motivó esto — "quiero que telegram
# funcione sin prender la compu").
#
# A diferencia de server.py (HUD completo + bot de Telegram vía
# python-telegram-bot Application.run_polling en un thread), esto es
# SOLO el bot, con un loop de polling MANUAL escrito a mano (raw HTTP a
# la Bot API de Telegram, mismo patrón que telegram_agent.
# enviar_notificacion) — a propósito, para poder meter el chequeo de
# heartbeat ANTES de cada llamada a getUpdates:
#
#   - Si la laptop local está prendida (heartbeat_agent.esta_vivo(),
#     que lee el latido que server.py escribe cada 15s en Supabase):
#     este proceso NO llama a getUpdates en absoluto y se queda en
#     espera. La laptop YA está respondiendo Telegram con TODAS las
#     funciones — dos procesos llamando getUpdates con el MISMO token
#     al mismo tiempo chocan (Telegram solo permite un long-poll activo
#     por token, el segundo tira error 409).
#   - Si la laptop está apagada (o nunca prendió): este proceso SÍ
#     hace polling y procesa los mensajes — pero con
#     config.MODO_NUBE=True (ver .env de ESTE despliegue,
#     GERAM_MODO_NUBE=true), director.py bloquea cualquier intent que
#     necesite hardware local (ver director.INTENTS_SOLO_LOCAL) con un
#     mensaje claro en vez de tronar.
#
# Al prender la laptop de nuevo, hay una ventana de traslape de hasta
# HEARTBEAT_UMBRAL_SEGUNDOS (60s default) donde AMBOS podrían intentar
# pollear a la vez — se resuelve solo (Telegram regresa 409 a uno de
# los dos, ambos reintentan con backoff, en el siguiente ciclo el
# heartbeat ya está fresco y este proceso se calla). No es un handoff
# perfecto, pero es más que suficiente para un proyecto personal.
#
# Requiere el MISMO .env que la laptop (mismo INSTANCE_NAME — así
# heartbeat_agent.esta_vivo() consulta el latido correcto — mismas
# keys de Gemini/Groq/Supabase/Notion/Telegram), MÁS
# GERAM_MODO_NUBE=true. Ver requirements-cloud.txt para las
# dependencias (mucho más liviano que requirements.txt: no necesita
# selenium/playwright/pyautogui/sounddevice, esos agentes ni
# se importan con MODO_NUBE=true).
#
# TRUCO DEL PLAN GRATIS DE RENDER: los "Background Worker" de Render
# SIEMPRE cuestan (no están en su tier gratis) — pero los "Web Service"
# sí son gratis, con la condición de escuchar un puerto HTTP real. Este
# archivo arranca un servidor HTTP mínimo (_servidor_salud) SOLO para
# cumplir ese requisito — no sirve nada del HUD, únicamente responde
# 200 OK a cualquier GET, así Render (y un pin externo tipo
# cron-job.org, necesario porque los Web Service gratis se DUERMEN tras
# 15 min sin tráfico HTTP) lo ven como "vivo". El trabajo real (polling
# de Telegram) corre en el thread principal, sin tocar ese servidor
# para nada.
# ============================================================

import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

import config
from agents import context_engine, director, heartbeat_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cloud_bot")

if not config.MODO_NUBE:
    raise RuntimeError(
        "cloud_bot.py: falta GERAM_MODO_NUBE=true en el .env de este despliegue. "
        "Sin eso, director.py intentaría importar agentes que dependen de hardware "
        "local (cámara, mouse/teclado, navegador) que este proceso no tiene."
    )

BOT_TOKEN = config.TELEGRAM_BOT_TOKEN
CHAT_ID_AUTORIZADO = str(config.TELEGRAM_CHAT_ID or "")
SESION = "telegram"

_API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
_LIMITE_TELEGRAM = 4000

# Cada cuánto se revisa el heartbeat cuando la laptop SÍ está prendida
# (no hay caso pollear Telegram, solo esperar y volver a checar).
_ESPERA_LAPTOP_PRENDIDA_SEGUNDOS = 10
# Timeout del long-poll de getUpdates cuando SÍ toma el relevo — 20s es
# el estándar recomendado por Telegram (long-polling real, no busy-wait).
_TIMEOUT_GETUPDATES_SEGUNDOS = 20


class _ManejadorSalud(BaseHTTPRequestHandler):
    """Responde 200 OK a CUALQUIER GET — no sirve nada de contenido
    real, solo existe para que Render (y el pin externo que evita que
    el Web Service gratis se duerma) vean que el proceso sigue vivo."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GERAM cloud_bot activo")

    def log_message(self, formato, *args):
        pass  # silencia el log default de BaseHTTPRequestHandler (ya logueamos lo que importa aparte)


def _iniciar_servidor_salud():
    puerto = int(os.getenv("PORT", "8000"))
    servidor = HTTPServer(("0.0.0.0", puerto), _ManejadorSalud)
    log.info("cloud_bot: servidor de salud escuchando en el puerto %s (solo para Render/el pin, no sirve el HUD)", puerto)
    servidor.serve_forever()


def _partir_en_trozos(texto, limite=_LIMITE_TELEGRAM):
    """Telegram rechaza mensajes de más de 4096 caracteres — mismo
    criterio que telegram_agent._partir_en_trozos, corta en el último
    salto de línea doble antes del límite para no cortar a media frase
    si se puede evitar."""
    if len(texto) <= limite:
        return [texto]
    trozos = []
    restante = texto
    while len(restante) > limite:
        corte = restante.rfind("\n\n", 0, limite)
        if corte == -1:
            corte = limite
        trozos.append(restante[:corte])
        restante = restante[corte:].lstrip("\n")
    if restante:
        trozos.append(restante)
    return trozos


def _mandar_mensaje(chat_id, texto):
    for trozo in _partir_en_trozos(texto):
        try:
            httpx.post(f"{_API_BASE}/sendMessage", json={"chat_id": chat_id, "text": trozo}, timeout=15)
        except Exception as e:
            log.error("cloud_bot: no se pudo mandar el mensaje (%s)", e)


def _procesar_actualizacion(actualizacion):
    mensaje = actualizacion.get("message") or {}
    chat = mensaje.get("chat") or {}
    texto = mensaje.get("text")

    if not texto or str(chat.get("id")) != CHAT_ID_AUTORIZADO:
        return  # ignora chats no autorizados y mensajes sin texto (fotos, stickers, etc.)

    log.info("cloud_bot: mensaje recibido (modo nube)")
    try:
        respuesta = director.procesar_mensaje(texto, sesion=SESION)
    except Exception as e:
        log.error("cloud_bot: falló al procesar el mensaje (%s)", e)
        respuesta = "Tronó algo de mi lado, jefe. Intenta de nuevo en un momento."
    _mandar_mensaje(chat["id"], respuesta)


def _ciclo_polling():
    """Loop principal: si la laptop está prendida, espera sin pollear;
    si no, hace UN ciclo de getUpdates (con offset para no reprocesar)
    y procesa cada mensaje. Nunca lanza excepción hacia afuera — un
    fallo puntual (red caída, Telegram 409 por el traslape del handoff)
    se loguea y se reintenta en el siguiente ciclo."""
    offset = None
    context_engine.limpiar(SESION)
    log.info(
        "cloud_bot: arrancando en modo nube (instancia=%s, umbral de latido=%ss)",
        config.INSTANCE_NAME, config.HEARTBEAT_UMBRAL_SEGUNDOS,
    )

    while True:
        try:
            if heartbeat_agent.esta_vivo():
                time.sleep(_ESPERA_LAPTOP_PRENDIDA_SEGUNDOS)
                continue

            parametros = {"timeout": _TIMEOUT_GETUPDATES_SEGUNDOS}
            if offset is not None:
                parametros["offset"] = offset
            respuesta = httpx.get(
                f"{_API_BASE}/getUpdates", params=parametros,
                timeout=_TIMEOUT_GETUPDATES_SEGUNDOS + 10,
            )
            respuesta.raise_for_status()
            actualizaciones = respuesta.json().get("result", [])

            for actualizacion in actualizaciones:
                offset = actualizacion["update_id"] + 1
                _procesar_actualizacion(actualizacion)
        except Exception as e:
            log.warning("cloud_bot: falló un ciclo de polling (%s), reintento en 5s", type(e).__name__)
            time.sleep(5)


if __name__ == "__main__":
    if not BOT_TOKEN or not CHAT_ID_AUTORIZADO:
        raise RuntimeError("cloud_bot.py: faltan TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID en .env.")
    threading.Thread(target=_iniciar_servidor_salud, daemon=True).start()
    _ciclo_polling()
