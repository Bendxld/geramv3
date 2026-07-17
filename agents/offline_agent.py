# ============================================================
# GERAM OS v2 · offline_agent.py
# Detecta si hay internet y, si no, atiende con Ollama local en
# vez de Gemini. director.py decide cuándo llamar a este módulo.
# ============================================================

import logging
import socket

import httpx

import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("offline_agent")

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = getattr(config, "OLLAMA_MODEL", "llama3.2:1b")

# Se usa solo para loggear cuando cambia el estado online/offline,
# no para tomar decisiones (cada llamada a hay_internet() es fresca).
_ultimo_estado = None

# Modo offline forzado a mano (para pruebas, sin tener que desconectar
# el WiFi de verdad). Mientras esté activo, director.py ni siquiera
# intenta Gemini.
_forzado_manual = False


def activar_modo_offline():
    """Fuerza el modo offline manualmente, sin importar si hay internet."""
    global _forzado_manual
    _forzado_manual = True
    log.info("offline_agent: modo offline FORZADO manualmente")


def desactivar_modo_offline():
    """Quita el forzado manual; vuelve a la detección automática."""
    global _forzado_manual
    _forzado_manual = False
    log.info("offline_agent: modo offline forzado DESACTIVADO (vuelve a automático)")


def modo_offline_forzado():
    """True si el modo offline está forzado a mano."""
    return _forzado_manual


def hay_internet(timeout=2):
    """Chequeo rápido de conectividad: intenta conectar por TCP al
    DNS público de Google (8.8.8.8:53). No depende de ICMP (que
    algunas redes bloquean), así que es más confiable que un ping
    tradicional."""
    global _ultimo_estado

    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        conectado = True
    except OSError:
        conectado = False

    nuevo_estado = "online" if conectado else "offline"
    if nuevo_estado != _ultimo_estado:
        log.info("offline_agent: cambio de estado -> %s", nuevo_estado.upper())
        _ultimo_estado = nuevo_estado

    return conectado


def _mapear_historial(historial):
    """Convierte el historial de context_engine (rol: usuario/iris)
    al formato de mensajes de la API de chat de Ollama."""
    mensajes = []
    for turno in historial:
        rol = "user" if turno.get("rol") == "usuario" else "assistant"
        mensajes.append({"role": rol, "content": turno.get("texto", "")})
    return mensajes


def obtener_respuesta_offline(prompt, historial=None, system_instruction=None):
    """Genera una respuesta usando Ollama local (sin internet)."""
    historial = historial or []
    mensajes = []
    if system_instruction:
        mensajes.append({"role": "system", "content": system_instruction})
    mensajes.extend(_mapear_historial(historial))
    mensajes.append({"role": "user", "content": prompt})

    try:
        respuesta = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": mensajes, "stream": False},
            # 60s: en un i3 real, cargar el modelo en frío + generar
            # con el system prompt completo puede tardar 15-30s.
            timeout=60,
        )
        respuesta.raise_for_status()
        return respuesta.json()["message"]["content"]
    except Exception as e:
        log.error("offline_agent: Ollama tampoco respondió (%s)", e)
        return "ERROR: no hay internet y Ollama local tampoco respondió."
