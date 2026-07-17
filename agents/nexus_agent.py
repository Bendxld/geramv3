# ============================================================
# GERAM OS v2 · nexus_agent.py
# Acceso rápido al portal UANL Nexus. Las credenciales se guardan
# ENCRIPTADAS en disco (nunca en .env ni en Supabase) usando
# cryptography.Fernet, con la clave derivada de LOCK_PASSWORD_HASH
# (mismo secreto que ya protege el standby/lock_agent.py, así no se
# introduce un segundo secreto que administrar).
#
# CÓMO FUNCIONA EL AUTO-LOGIN (verificado contra el sitio real):
# plataformanexus.uanl.mx es una SPA de Angular sin <form action=...>
# real — un POST clásico a esa página no sirve de nada. El login de
# verdad pasa por el SSO clásico de UANL en
# deimos.dgi.uanl.mx/cgi-bin/wspd_cgi.sh/ (el mismo backend que
# unifica correo institucional, SIASE, CODICE y Nexus con "una sola
# cuenta"): se manda usuario/password ahí, y la respuesta trae un link
# de un solo uso a Nexus con un token de sesión ya autenticado
# (".../#/LoginSIASE?Usu=...&Ctrl=...&HTMLUsuario=...&HTMLTipCve=...").
# Abrir ESA url en el navegador entra ya logueado. Dos requests HTTP
# con httpx antes de abrir el navegador — no hace falta Selenium ni
# ninguna automatización de navegador para esto.
# ============================================================

import base64
import hashlib
import json
import logging
import os
import re

import httpx
from cryptography.fernet import Fernet, InvalidToken

import config
from agents import control_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nexus_agent")

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RUTA_ENC = config.NEXUS_ENC_PATH or os.path.join(_RAIZ, "credenciales", "nexus.enc")
if not os.path.isabs(_RUTA_ENC):
    _RUTA_ENC = os.path.join(_RAIZ, _RUTA_ENC)

# URL "de vitrina" de Nexus, usada solo como fallback cuando no hay
# credenciales guardadas o el SSO falla (el usuario entra a mano ahí).
NEXUS_URL = config.NEXUS_URL or "https://plataformanexus.uanl.mx/"

# SSO real de UANL ("una sola cuenta" para correo/SIASE/CODICE/Nexus).
_SSO_LOGIN_URL = "https://deimos.dgi.uanl.mx/cgi-bin/wspd_cgi.sh/login.htm"
_SSO_ESELCARRERA_URL = "https://deimos.dgi.uanl.mx/cgi-bin/wspd_cgi.sh/eselcarrera.htm"
# "01" = Alumno, "02" = Empleado (ver <select name="HTMLTipCve"> del
# login real). Configurable por si algún día se usa con cuenta de empleado.
_TIPO_CUENTA = config.NEXUS_TIPO_CUENTA or "01"

_CABECERAS_UANL = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) GeramOS/2.0"}
_PATRON_TOKEN = re.compile(r'HTMLToken"\s+value="([^"]*)"')
_PATRON_URL_NEXUS_SSO = re.compile(r'https://plataformanexus\.uanl\.mx/#/LoginSIASE\?[^"\'<>\s]+')


def _derivar_clave():
    """Deriva una clave Fernet (32 bytes url-safe base64) a partir de
    LOCK_PASSWORD_HASH, para no tener que administrar un segundo
    secreto además del que ya protege el standby."""
    if not config.LOCK_PASSWORD_HASH:
        raise RuntimeError("nexus_agent: falta LOCK_PASSWORD_HASH en el .env (se usa para derivar la clave de encriptación).")
    digest = hashlib.sha256(config.LOCK_PASSWORD_HASH.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def configurar_nexus(usuario, password):
    """Encripta y guarda usuario/password de Nexus en NEXUS_ENC_PATH.
    Sobreescribe cualquier configuración anterior. Devuelve True/False."""
    try:
        clave = _derivar_clave()
        datos = json.dumps({"usuario": usuario, "password": password}).encode("utf-8")
        token = Fernet(clave).encrypt(datos)

        os.makedirs(os.path.dirname(_RUTA_ENC), exist_ok=True)
        with open(_RUTA_ENC, "wb") as f:
            f.write(token)
        os.chmod(_RUTA_ENC, 0o600)

        log.info("nexus_agent: credenciales guardadas encriptadas en %s", _RUTA_ENC)
        return True
    except Exception as e:
        log.error("nexus_agent: no se pudieron guardar las credenciales (%s)", e)
        return False


def _leer_credenciales():
    """Desencripta y devuelve {"usuario","password"}, o None si no hay
    nada configurado o la clave/token no coinciden (ej. cambiaste el
    LOCK_PASSWORD_HASH después de configurar Nexus)."""
    if not os.path.exists(_RUTA_ENC):
        return None
    try:
        clave = _derivar_clave()
        with open(_RUTA_ENC, "rb") as f:
            token = f.read()
        datos = Fernet(clave).decrypt(token)
        return json.loads(datos.decode("utf-8"))
    except InvalidToken:
        log.error("nexus_agent: no se pudo desencriptar nexus.enc (¿cambió LOCK_PASSWORD_HASH?)")
        return None
    except Exception as e:
        log.error("nexus_agent: no se pudieron leer las credenciales (%s)", e)
        return None


def nexus_configurado():
    """True si ya hay credenciales guardadas (independiente de si se
    pueden desencriptar con la clave actual)."""
    return os.path.exists(_RUTA_ENC)


def _obtener_url_sso_nexus(usuario, password):
    """Hace el login real contra el SSO de UANL y saca la URL de
    acceso directo (con token de sesión) a Nexus. Devuelve la URL, o
    None si algo falla (usuario/password incorrectos, o cambió el
    sitio de UANL y el HTML ya no matchea los patrones esperados)."""
    try:
        with httpx.Client(follow_redirects=True, timeout=15, headers=_CABECERAS_UANL) as cliente:
            html_login = cliente.get(_SSO_LOGIN_URL).text
            coincidencia_token = _PATRON_TOKEN.search(html_login)
            if not coincidencia_token:
                log.error("nexus_agent: no encontré el HTMLToken en el login de UANL (¿cambió el sitio?)")
                return None

            datos = {
                "HTMLTipCve": _TIPO_CUENTA,
                "HTMLUsuCve": usuario,
                "HTMLPassword": password,
                "HTMLPrograma": "",
                "HTMLToken": coincidencia_token.group(1),
            }
            html_resultado = cliente.post(_SSO_ESELCARRERA_URL, data=datos).text
    except Exception as e:
        log.error("nexus_agent: no se pudo hacer login contra el SSO de UANL (%s)", e)
        return None

    coincidencia_url = _PATRON_URL_NEXUS_SSO.search(html_resultado)
    if not coincidencia_url:
        log.warning("nexus_agent: el SSO no devolvió un link de Nexus (¿usuario/contraseña incorrectos?)")
        return None
    return coincidencia_url.group(0)


def abrir_nexus():
    """Abre Nexus en el navegador YA logueado (hace el login real
    contra el SSO de UANL con las credenciales guardadas y abre el
    link de sesión que devuelve). Si no hay credenciales guardadas o
    el login falla (usuario/password incorrectos, o el sitio de UANL
    cambió), cae a abrir la URL de Nexus tal cual para que el usuario
    entre a mano. Devuelve un mensaje de texto para el usuario."""
    credenciales = _leer_credenciales()

    if not credenciales:
        if control_agent.abrir_url(NEXUS_URL):
            return "Abrí Nexus, jefe. No tengo tus credenciales guardadas, así que tendrás que loguearte a mano (di 'configura Nexus' para que no tengas que volver a hacerlo)."
        return "No pude abrir el navegador para Nexus."

    url_sso = _obtener_url_sso_nexus(credenciales["usuario"], credenciales["password"])
    if url_sso and control_agent.abrir_url(url_sso):
        return "Listo jefe, te abrí Nexus ya logueado."

    log.warning("nexus_agent: el login automático contra el SSO de UANL falló, abriendo Nexus sin loguear")
    if control_agent.abrir_url(NEXUS_URL):
        return "Abrí Nexus, jefe, pero el login automático falló esta vez (¿la contraseña sigue siendo correcta?) — te toca loguearte a mano."
    return "No pude abrir el navegador para Nexus."
