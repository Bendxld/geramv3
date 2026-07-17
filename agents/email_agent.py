# ============================================================
# GERAM OS v2 · email_agent.py
# Gmail API: leer/buscar/resumir/enviar correos. Usa las mismas
# credenciales OAuth2 compartidas de _google_auth.py (mismo login
# que calendar_agent.py).
#
# enviar_correo() de verdad manda el correo: SOLO se llama después de
# que el usuario ya escribió CONFIRMAR (ver director.py, misma lógica
# de confirmación que control_agent.py para acciones riesgosas).
# ============================================================

import base64
import logging
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from agents import _google_auth, balancer, personality

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("email_agent")

_servicio = None


def _obtener_servicio():
    global _servicio
    if _servicio is None:
        creds = _google_auth.obtener_credenciales()
        _servicio = build("gmail", "v1", credentials=creds)
    return _servicio


def _extraer_encabezado(mensaje, nombre):
    for h in mensaje.get("payload", {}).get("headers", []):
        if h["name"].lower() == nombre.lower():
            return h["value"]
    return ""


def _resumen_mensaje(mensaje):
    return {
        "id": mensaje["id"],
        "de": _extraer_encabezado(mensaje, "From"),
        "asunto": _extraer_encabezado(mensaje, "Subject"),
        "fecha": _extraer_encabezado(mensaje, "Date"),
        "snippet": mensaje.get("snippet", ""),
    }


def _listar_resumenes(servicio, referencias):
    resumenes = []
    for ref in referencias:
        mensaje = servicio.users().messages().get(
            userId="me", id=ref["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        resumenes.append(_resumen_mensaje(mensaje))
    return resumenes


def obtener_correos_recientes(limite=10):
    """Devuelve los `limite` correos más recientes del inbox (lista de
    dicts de/asunto/fecha/snippet) o {"error": "..."}."""
    try:
        servicio = _obtener_servicio()
        lista = servicio.users().messages().list(
            userId="me", labelIds=["INBOX"], maxResults=limite,
        ).execute()
        return _listar_resumenes(servicio, lista.get("messages", []))
    except Exception as e:
        log.error("email_agent: no se pudieron leer los correos recientes (%s)", e)
        return {"error": str(e)}


def _decodificar_cuerpo(payload):
    """Extrae el texto plano del cuerpo (recorre las partes si es
    multipart, prioriza text/plain; si no hay, usa lo que encuentre)."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for parte in payload.get("parts", []) or []:
        texto = _decodificar_cuerpo(parte)
        if texto:
            return texto

    datos = payload.get("body", {}).get("data")
    if datos:
        return base64.urlsafe_b64decode(datos).decode("utf-8", errors="replace")
    return ""


def leer_correo(id_correo):
    """Devuelve {"de","asunto","fecha","cuerpo"} de un correo
    específico, o {"error": "..."}."""
    try:
        servicio = _obtener_servicio()
        mensaje = servicio.users().messages().get(userId="me", id=id_correo, format="full").execute()
        resumen = _resumen_mensaje(mensaje)
        resumen["cuerpo"] = _decodificar_cuerpo(mensaje.get("payload", {}))[:5000]
        return resumen
    except Exception as e:
        log.error("email_agent: no se pudo leer el correo %s (%s)", id_correo, e)
        return {"error": str(e)}


def buscar_correos(query, limite=10):
    """Busca correos con la sintaxis de búsqueda de Gmail (ej.
    "from:juan", "factura"). Devuelve lista de resúmenes o {"error": "..."}."""
    try:
        servicio = _obtener_servicio()
        lista = servicio.users().messages().list(userId="me", q=query, maxResults=limite).execute()
        return _listar_resumenes(servicio, lista.get("messages", []))
    except Exception as e:
        log.error("email_agent: no se pudo buscar correos (%s)", e)
        return {"error": str(e)}


def enviar_correo(destinatario, asunto, cuerpo):
    """Envía un correo DE VERDAD. Devuelve {"id": ...} o {"error": "..."}.

    SOLO se llama después de que el usuario ya escribió CONFIRMAR —
    ver director.py, misma lógica de confirmación que
    control_agent.py usa para acciones riesgosas."""
    try:
        servicio = _obtener_servicio()
        mime = MIMEText(cuerpo)
        mime["to"] = destinatario
        mime["subject"] = asunto
        crudo = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")

        enviado = servicio.users().messages().send(userId="me", body={"raw": crudo}).execute()
        return {"id": enviado["id"]}
    except Exception as e:
        log.error("email_agent: no se pudo enviar el correo a %s (%s)", destinatario, e)
        return {"error": str(e)}


def resumir_bandeja():
    """Resume los correos NO LEÍDOS con Gemini. Devuelve texto (nunca
    lanza excepción)."""
    try:
        servicio = _obtener_servicio()
        lista = servicio.users().messages().list(
            userId="me", labelIds=["INBOX", "UNREAD"], maxResults=15,
        ).execute()
    except Exception as e:
        log.error("email_agent: no se pudo leer la bandeja (%s)", e)
        return f"No pude leer tu bandeja: {e}"

    referencias = lista.get("messages", [])
    if not referencias:
        return "No tienes correos sin leer, jefe."

    resumenes = _listar_resumenes(servicio, referencias)
    lineas = [f"- De: {r['de']} | Asunto: {r['asunto']} | {r['snippet']}" for r in resumenes]

    prompt = (
        f"El usuario (mauri) tiene {len(resumenes)} correos sin leer:\n"
        + "\n".join(lineas)
        + "\n\nResume esto en una respuesta breve y útil, agrupando por "
        "tema/urgencia si aplica. No inventes contenido que no esté arriba."
    )
    return balancer.enviar_mensaje(
        prompt=prompt, historial=[], system_instruction=personality.obtener_system_prompt(),
    )
