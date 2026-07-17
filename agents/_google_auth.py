# ============================================================
# GERAM OS v2 · _google_auth.py
# Helper compartido de autenticación OAuth2 de Google para
# calendar_agent.py y email_agent.py — mismo credentials.json, mismo
# token cacheado en disco, UN solo consentimiento cubre ambos agentes
# (Calendar + Gmail) en vez de pedir login dos veces.
#
# NOTA: hubo un intento de extender esto a una segunda cuenta escolar
# para classroom_agent.py (scopes de Classroom + token_escuela.json),
# pero el admin de la organización bloqueó la API de Classroom para
# esa cuenta — classroom_agent.py ahora usa Plan B (navegador manual +
# tareas trackeadas a mano en Supabase, ver ese archivo), así que ya no
# necesita OAuth2 y ese segundo alcance se quitó de aquí.
#
# Prefijo "_": no es un agente en sí (no va en AGENTES_ACTIVOS de
# server.py), es un módulo interno que otros agentes importan.
# ============================================================

import logging
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("google_auth")

# Alcance combinado: Calendar (leer/crear/borrar eventos) + Gmail
# (leer + enviar). Ver instrucciones de Google Cloud Console en el
# reporte de esta fase para saber qué APIs habilitar.
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RUTA_TOKEN = os.path.join(_RAIZ, "credenciales", "token_personal.json")


def obtener_credenciales():
    """Devuelve credenciales OAuth2 válidas.

    - Si ya hay un token guardado y sigue vivo, lo reusa.
    - Si expiró pero tiene refresh_token, lo renueva solo.
    - Si no hay nada, dispara el flujo de consentimiento: abre una
      pestaña del navegador para que el usuario autorice UNA sola vez
      (requiere sesión gráfica real, no funciona en un servidor
      headless puro — pensado para correr la primera vez a mano).

    Lanza RuntimeError con mensaje claro si falta el credentials.json."""
    ruta_credenciales = config.GOOGLE_CALENDAR_CREDENTIALS_PATH
    if not ruta_credenciales or not os.path.exists(ruta_credenciales):
        raise RuntimeError(
            "falta el credentials.json de Google OAuth2. Define "
            "GOOGLE_CALENDAR_CREDENTIALS_PATH en .env apuntando a él "
            "(ver instrucciones de Google Cloud Console en el reporte de esta fase)."
        )

    creds = None
    if os.path.exists(_RUTA_TOKEN):
        creds = Credentials.from_authorized_user_file(_RUTA_TOKEN, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("google_auth: token vencido, renovando...")
            creds.refresh(Request())
        else:
            log.info("google_auth: no hay token válido, abriendo flujo de consentimiento en el navegador...")
            flujo = InstalledAppFlow.from_client_secrets_file(ruta_credenciales, SCOPES)
            creds = flujo.run_local_server(port=0)

        os.makedirs(os.path.dirname(_RUTA_TOKEN), exist_ok=True)
        with open(_RUTA_TOKEN, "w") as f:
            f.write(creds.to_json())
        log.info("google_auth: token guardado en %s", _RUTA_TOKEN)

    return creds
