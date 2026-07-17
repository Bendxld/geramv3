"""
Telegram Long-Polling — GERAM CORE OS

Canal de control remoto vía Telegram usando getUpdates (long polling),
no webhook — evita tener que exponer HTTPS público (Tailscale Funnel)
para el hackathon. Ver TODO en app/main.py sobre el endpoint de webhook,
que se deja intacto para una migración posterior.

Reuses procesar_orquestacion() from app/api/orchestrator.py without
duplicating role classification or provider dispatch.
"""

import asyncio
import logging

import httpx

from app.core.config import settings
from app.api.orchestrator import OrchestratorRequest, procesar_orquestacion

logger = logging.getLogger("geram_core")

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"

# timeout=30 en getUpdates es long-polling real del lado de Telegram: la
# request se queda abierta hasta que hay un update o pasan 30s, así que
# NO hace falta un sleep entre iteraciones exitosas — Telegram mismo
# marca el ritmo. El timeout de httpx tiene que ser mayor a eso para no
# cortar la conexión antes de que Telegram responda.
GETUPDATES_TIMEOUT_S = 30
HTTPX_TIMEOUT_S = GETUPDATES_TIMEOUT_S + 10
ESPERA_TRAS_ERROR_S = 3  # evita busy-loop si Telegram/la red están caídos


async def _enviar_respuesta(client: httpx.AsyncClient, base_url: str, chat_id: int, texto: str) -> None:
    try:
        resp = await client.post(f"{base_url}/sendMessage", json={"chat_id": chat_id, "text": texto})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(f"Telegram: error al mandar respuesta a chat_id={chat_id}: {e}")


async def _procesar_mensaje(client: httpx.AsyncClient, base_url: str, mensaje: dict) -> None:
    chat = mensaje.get("chat") or {}
    chat_id = chat.get("id")
    texto = mensaje.get("text")

    if chat_id is None or not texto:
        return  # no es un mensaje de texto (foto, sticker, etc.) — se ignora por ahora

    if settings.TELEGRAM_ALLOWED_CHAT_IDS and str(chat_id) not in settings.TELEGRAM_ALLOWED_CHAT_IDS:
        logger.warning(f"Telegram: ACCESO DENEGADO — chat_id {chat_id} no está en TELEGRAM_ALLOWED_CHAT_IDS.")
        return

    payload = OrchestratorRequest(prompt=texto, source="telegram")
    respuesta = await procesar_orquestacion(payload.prompt, payload.source.value, payload.force_mode)

    result = respuesta.result
    texto_respuesta = (
        result.get("text")
        or result.get("message")
        or "ERROR: the orchestrator did not return a usable response."
    )

    await _enviar_respuesta(client, base_url, chat_id, texto_respuesta)


async def poll_telegram_updates() -> None:
    """Loop infinito de long-polling. Se lanza con asyncio.create_task en
    el startup de main.py — no bloquea el arranque del resto de la app."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.info("Telegram deshabilitado, no hay token configurado.")
        return

    base_url = TELEGRAM_API_BASE.format(token=settings.TELEGRAM_BOT_TOKEN)
    offset = None

    logger.info("Telegram: long-polling arrancado.")

    async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT_S) as client:
        while True:
            try:
                params = {"timeout": GETUPDATES_TIMEOUT_S}
                if offset is not None:
                    params["offset"] = offset

                resp = await client.get(f"{base_url}/getUpdates", params=params)
                resp.raise_for_status()
                data = resp.json()

                for update in data.get("result", []):
                    # Offset = último update_id + 1, se manda en la SIGUIENTE
                    # llamada para que Telegram no reenvíe updates ya vistos
                    # (se avanza en cuanto se lee el update, no hasta
                    # terminar de procesarlo, para no atorarse reintentando
                    # un mensaje que ya truena siempre).
                    offset = update["update_id"] + 1

                    mensaje = update.get("message")
                    if mensaje:
                        await _procesar_mensaje(client, base_url, mensaje)

            except Exception as e:
                logger.error(f"Telegram: error en el loop de polling: {e}")
                await asyncio.sleep(ESPERA_TRAS_ERROR_S)
