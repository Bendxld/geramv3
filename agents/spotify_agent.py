# ============================================================
# GERAM OS v2 · spotify_agent.py
# Integración de SOLO LECTURA con Spotify (Web API vía spotipy): qué
# canción está sonando y el historial reciente — nada de controlar
# reproducción (para eso ya están las teclas multimedia de
# control_agent.py). Scopes deliberadamente mínimos.
#
# OAuth2 real (authorization code + refresh token), mismo criterio que
# _google_auth.py (Calendar/Gmail): la primera vez abre el navegador
# para que el jefe autorice, después el token se cachea y se refresca
# solo. A diferencia de Nexus (usuario/contraseña encriptados con
# Fernet), el Client ID/Secret de Spotify NO son ese tipo de secreto —
# van en .env como el resto de API keys del proyecto; solo el TOKEN de
# acceso (generado tras la autorización) se cachea en
# credenciales/spotify_token.json (config.SPOTIFY_TOKEN_PATH).
# ============================================================

import logging

import spotipy
from spotipy.oauth2 import SpotifyOAuth

import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("spotify_agent")

_SCOPES = "user-read-currently-playing user-read-recently-played user-top-read"

_cliente = None


def esta_configurado():
    """True si hay Client ID/Secret en .env — NO implica que ya se haya
    autorizado (eso lo dice el primer intento real de usar la API)."""
    return bool(config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET)


def _obtener_cliente():
    global _cliente
    if _cliente is not None:
        return _cliente
    if not esta_configurado():
        return None

    auth_manager = SpotifyOAuth(
        client_id=config.SPOTIFY_CLIENT_ID,
        client_secret=config.SPOTIFY_CLIENT_SECRET,
        redirect_uri=config.SPOTIFY_REDIRECT_URI,
        scope=_SCOPES,
        cache_path=config.SPOTIFY_TOKEN_PATH,
        open_browser=True,
    )
    _cliente = spotipy.Spotify(auth_manager=auth_manager)
    return _cliente


def iniciar_configuracion():
    """Dispara el flujo de autorización — abre el navegador si no hay
    un token cacheado todavía. Debe correrse con el jefe presente en la
    laptop (necesita aprobar en el navegador la primera vez)."""
    if not esta_configurado():
        return (
            "Antes necesito que agregues SPOTIFY_CLIENT_ID y SPOTIFY_CLIENT_SECRET "
            "a tu .env (te los da developer.spotify.com al crear tu app) y reinicies."
        )
    try:
        cliente = _obtener_cliente()
        perfil = cliente.current_user()
        nombre = perfil.get("display_name") or "tu cuenta"
        return f"Listo, Spotify quedó conectado con {nombre}."
    except Exception as e:
        log.error("spotify_agent: no se pudo completar la configuración (%s)", e)
        return f"No pude conectar Spotify: {e}"


def cancion_actual():
    """Devuelve {"cancion","artista","album","reproduciendo"} o
    {"error": "..."}."""
    cliente = _obtener_cliente()
    if cliente is None:
        return {"error": 'Spotify no está configurado. Dime "configura spotify" primero.'}
    try:
        actual = cliente.current_playback()
        if not actual or not actual.get("item"):
            return {"error": "no estás escuchando nada ahorita en Spotify."}
        item = actual["item"]
        return {
            "cancion": item["name"],
            "artista": ", ".join(a["name"] for a in item["artists"]),
            "album": item["album"]["name"],
            "reproduciendo": actual.get("is_playing", False),
        }
    except Exception as e:
        log.error("spotify_agent: no se pudo obtener la canción actual (%s)", e)
        return {"error": str(e)}


def cancion_actual_texto():
    resultado = cancion_actual()
    if resultado.get("error"):
        return resultado["error"]
    estado = "Estás escuchando" if resultado["reproduciendo"] else "Tenías puesta (en pausa)"
    return f"{estado} \"{resultado['cancion']}\" de {resultado['artista']} ({resultado['album']})."


def recientes_texto(limite=10):
    cliente = _obtener_cliente()
    if cliente is None:
        return 'Spotify no está configurado. Dime "configura spotify" primero.'
    try:
        resultado = cliente.current_user_recently_played(limit=limite)
    except Exception as e:
        log.error("spotify_agent: no se pudo obtener el historial (%s)", e)
        return f"No pude consultar tu historial de Spotify: {e}"

    items = resultado.get("items", [])
    if not items:
        return "No tengo historial reciente de Spotify."

    vistos = set()
    lineas = []
    for item in items:
        nombre = item["track"]["name"]
        artista = ", ".join(a["name"] for a in item["track"]["artists"])
        clave = (nombre, artista)
        if clave in vistos:
            continue
        vistos.add(clave)
        lineas.append(f"{nombre} - {artista}")
        if len(lineas) >= limite:
            break

    return "Últimas canciones:\n" + "\n".join(lineas)
