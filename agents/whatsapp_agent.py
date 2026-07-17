# ============================================================
# GERAM OS v2 · whatsapp_agent.py
# Interacción básica con WhatsApp Web. CERO tokens: solo abre URLs
# (wa.me / api.whatsapp.com) en el navegador, nunca manda nada por su
# cuenta — el "enviar" final siempre lo da el usuario a mano en la
# pestaña que se abre.
# ============================================================

import json
import logging
import os
import re
import unicodedata
from urllib.parse import quote

from agents import control_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("whatsapp_agent")

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RUTA_CONTACTOS = os.path.join(_RAIZ, "credenciales", "contactos.json")

WHATSAPP_WEB_URL = "https://web.whatsapp.com"


def _cargar_contactos():
    if not os.path.exists(_RUTA_CONTACTOS):
        return {}
    try:
        with open(_RUTA_CONTACTOS) as f:
            return json.load(f)
    except Exception as e:
        log.error("whatsapp_agent: no se pudo leer contactos.json (%s)", e)
        return {}


def _guardar_contactos(contactos):
    os.makedirs(os.path.dirname(_RUTA_CONTACTOS), exist_ok=True)
    with open(_RUTA_CONTACTOS, "w") as f:
        json.dump(contactos, f, indent=2, ensure_ascii=False)


def _normalizar_numero(numero):
    """Deja solo dígitos (+ el "+" inicial si lo trae) — wa.me y
    api.whatsapp.com quieren el número en formato internacional, sin
    espacios/guiones/paréntesis."""
    numero = numero.strip()
    signo = "+" if numero.startswith("+") else ""
    return signo + re.sub(r"\D", "", numero)


def guardar_contacto(nombre, numero):
    """Guarda/actualiza un contacto frecuente en contactos.json (ej.
    "guarda el número de mamá: 8112345678"). Devuelve True/False."""
    try:
        contactos = _cargar_contactos()
        contactos[nombre.strip().lower()] = _normalizar_numero(numero)
        _guardar_contactos(contactos)
        return True
    except Exception as e:
        log.error("whatsapp_agent: no se pudo guardar el contacto '%s' (%s)", nombre, e)
        return False


def _sin_acentos(texto):
    """"mama" debe encontrar un contacto guardado como "mamá" — muy
    probable que la transcripción de voz (faster-whisper) no siempre
    ponga el acento igual que como se guardó la primera vez."""
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def buscar_contacto(nombre):
    """Busca `nombre` en contactos.json (case-insensitive, sin
    distinguir acentos, substring en cualquier dirección). Devuelve
    el número guardado o None."""
    contactos = _cargar_contactos()
    nombre_norm = _sin_acentos(nombre.strip().lower())
    for clave, numero in contactos.items():
        clave_norm = _sin_acentos(clave.lower())
        if nombre_norm == clave_norm or nombre_norm in clave_norm or clave_norm in nombre_norm:
            return numero
    return None


def _resolver_numero(contacto_o_numero):
    """Contacto guardado tiene prioridad; si no hay match y el texto
    ya trae dígitos, se asume que es un número directo."""
    numero = buscar_contacto(contacto_o_numero)
    if numero:
        return numero
    if any(c.isdigit() for c in contacto_o_numero):
        return _normalizar_numero(contacto_o_numero)
    return None


def abrir_whatsapp():
    """Abre WhatsApp Web tal cual. Devuelve un mensaje de texto."""
    if control_agent.abrir_url(WHATSAPP_WEB_URL):
        return "Abrí WhatsApp Web, jefe."
    return "No pude abrir el navegador para WhatsApp."


def abrir_chat(contacto_o_numero):
    """Abre el chat de un contacto guardado o de un número directo.
    Devuelve un mensaje de texto para el usuario."""
    numero = _resolver_numero(contacto_o_numero)
    if not numero:
        return (
            f"No tengo guardado el número de '{contacto_o_numero}'. Dime el número, o dime "
            f"'guarda el número de {contacto_o_numero}: <numero>' para la próxima."
        )

    # web.whatsapp.com/send (no wa.me/api.whatsapp.com): esos dos
    # muestran un intersticial "¿abrir en la app o seguir en la web?"
    # antes de llegar al chat — este va directo a WhatsApp Web.
    if control_agent.abrir_url(f"https://web.whatsapp.com/send?phone={numero.lstrip('+')}"):
        return f"Abrí el chat de {contacto_o_numero}, jefe."
    return "No pude abrir el navegador para WhatsApp."


def enviar_mensaje_rapido(contacto_o_numero, texto):
    """Abre el chat de WhatsApp con `texto` YA ESCRITO en el cuadro —
    el usuario todavía tiene que darle enviar a mano, esto NUNCA manda
    el mensaje por su cuenta. Devuelve {"ok": True} o {"error": "..."}."""
    numero = _resolver_numero(contacto_o_numero)
    if not numero:
        return {"error": f"no tengo guardado el número de '{contacto_o_numero}'."}

    url = f"https://web.whatsapp.com/send?phone={numero.lstrip('+')}&text={quote(texto)}"
    if control_agent.abrir_url(url):
        return {"ok": True}
    return {"error": "no pude abrir el navegador."}
