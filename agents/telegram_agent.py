# ============================================================
# GERAM OS v2 · telegram_agent.py
# Bot de Telegram: el mismo cerebro que el HUD (director.py) más
# control remoto de la compu y notificaciones proactivas. Corre en un
# thread aparte con su propio loop asyncio (ver iniciar_en_thread(),
# llamado desde server.py) para no bloquear el servidor ni el HUD si
# Telegram falla o no hay internet — si TELEGRAM_BOT_TOKEN/
# TELEGRAM_CHAT_ID faltan o el arranque falla, iniciar_bot() solo
# loggea y regresa, nunca tumba el proceso.
#
# SEGURIDAD: solo responde al chat_id en TELEGRAM_CHAT_ID (.env).
# Cualquier otro chat recibe "Acceso denegado, jefe incorrecto." y no
# se procesa nada más (ver _autorizado/_acceso_ok).
#
# REGLA DE TOKENS: el chat libre, la voz, las fotos, /recordar y
# /abrir pasan por director.py/balancer.py (Gemini) — mismos tokens
# que el HUD, solo cuando IRIS de verdad tiene que "pensar". Todo lo
# demás (/status, /balance, /pendientes, /tareas, /screenshot,
# /organizar, /archivos, /volumen, /lock, /unlock, /cerrar,
# /suspender, /apagar, /comando) son acciones fijas de datos locales o
# subprocess directo: CERO tokens, nunca llaman a Gemini/Ollama.
# ============================================================

import asyncio
import logging
import os
import re
import subprocess
import threading
import time

import httpx
import psutil
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import config
from agents import (
    balancer, classroom_agent, control_agent, director, escuchar, examen_agent, figura_agent,
    file_organizer_agent, finance_agent, lock_agent, observador, offline_agent, pendientes_agent,
    reminder_agent, screenshot_agent,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("telegram_agent")

# httpx (usado internamente por PTB para pegarle a la API de Telegram)
# loggea a INFO la URL COMPLETA de cada request — y esa URL trae el
# token del bot embebido (https://api.telegram.org/bot<TOKEN>/...).
# Sin esto, el token terminaría en iniciar.log en texto plano en cada
# mensaje que llega o notificación que se manda.
logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_TOKEN = getattr(config, "TELEGRAM_BOT_TOKEN", None)
CHAT_ID_AUTORIZADO = str(getattr(config, "TELEGRAM_CHAT_ID", "") or "")

# Sesión propia en context_engine (ver director.procesar_mensaje) para
# que el historial inmediato de Telegram no se mezcle con el del HUD —
# ambos siguen compartiendo la memoria de largo plazo en Supabase.
SESION = "telegram"

# Confirmación pendiente para /cerrar, /suspender, /apagar y /comando —
# CERO tokens, ejecución directa (pkill/systemctl/shell), INDEPENDIENTE
# del wizard "CONFIRMAR" de director.py (ese es para control por
# lenguaje natural vía Gemini, ver control_agent.interpretar).
# Solo puede haber una a la vez: un jefe, un chat autorizado.
# {"tipo": ..., "datos": {...}, "expira": time.time()+120}
_confirmacion_pendiente = None

_RUTA_FOTO_TELEGRAM = "/tmp/geram_telegram_foto.jpg"
_PROMPT_FOTO_DEFAULT = "Describe brevemente lo que ves en esta foto."


# ------------------------------------------------------------
# Seguridad + estado (lock)
# ------------------------------------------------------------
def _autorizado(update: Update) -> bool:
    chat = update.effective_chat
    return bool(CHAT_ID_AUTORIZADO) and chat is not None and str(chat.id) == CHAT_ID_AUTORIZADO


async def _acceso_ok(update: Update) -> bool:
    """Solo autorización (sin chequear lock) — usado por /start, /lock
    y /unlock, que deben responder aunque IRIS esté bloqueada."""
    if _autorizado(update):
        return True
    chat = update.effective_chat
    log.warning("telegram_agent: acceso BLOQUEADO de chat_id=%s", chat.id if chat else "?")
    await update.message.reply_text("Acceso denegado, jefe incorrecto.")
    return False


async def _listo(update: Update) -> bool:
    """Autorización + no bloqueada — usado por TODO lo demás (cualquier
    comando que consulte o actúe sobre el sistema). Registra actividad
    (reinicia el standby) igual que /chat en server.py, para que usar
    el bot no deje a IRIS bloqueándose sola a media conversación."""
    if not await _acceso_ok(update):
        return False
    if lock_agent.esta_bloqueado():
        await update.message.reply_text("Estoy bloqueada, jefe. Mándame /unlock <contraseña> primero.")
        return False
    lock_agent.registrar_actividad()
    return True


# ------------------------------------------------------------
# Comandos directos, CERO tokens
# ------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _acceso_ok(update):
        return
    await update.message.reply_text("I.R.I.S en línea, jefe. ¿En qué le ayudo?")


def _temperatura():
    """Mismo patrón que server.py._obtener_temperatura (duplicado
    aquí a propósito: es una función chica y server.py no se debe
    importar desde un agente para evitar acoplar el bot al proceso
    HTTP)."""
    try:
        temps = psutil.sensors_temperatures()
        for etiqueta in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            if etiqueta in temps and temps[etiqueta]:
                return round(temps[etiqueta][0].current, 1)
        for lecturas in temps.values():
            if lecturas:
                return round(lecturas[0].current, 1)
    except (AttributeError, OSError):
        pass
    uso_cpu = psutil.cpu_percent(interval=None)
    return round(38 + (uso_cpu * 0.25), 1)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    cpu = psutil.cpu_percent(interval=0.3)
    ram = psutil.virtual_memory().percent
    segundos = int(time.time() - psutil.boot_time())
    h, resto = divmod(segundos, 3600)
    m, _s = divmod(resto, 60)
    internet = "sí" if offline_agent.hay_internet() else "no (usando Ollama local)"
    texto = (
        f"CPU: {cpu}%\n"
        f"RAM: {ram}%\n"
        f"Temperatura: {_temperatura()}°C\n"
        f"Uptime del sistema: {h}h {m}m\n"
        f"Internet: {internet}"
    )
    await update.message.reply_text(texto)


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    await update.message.reply_text(finance_agent.resumen_mes_texto())


async def cmd_pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    await update.message.reply_text(pendientes_agent.listar_pendientes_texto())


async def cmd_tareas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    # Mismo patrón que director._procesar_classroom: lector automático
    # primero (cuenta real de Classroom), tracker manual como respaldo.
    texto = classroom_agent.resumen_pendientes_texto()
    if texto is None:
        texto = classroom_agent.listar_tareas_texto(dias=7)
    await update.message.reply_text(texto)


async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _acceso_ok(update):
        return
    lock_agent.forzar_bloqueo()
    await update.message.reply_text("Bloqueada, jefe.")


async def cmd_unlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _acceso_ok(update):
        return
    password = " ".join(context.args)
    if not password:
        await update.message.reply_text("Dame la contraseña: /unlock <password>")
        return
    ok = lock_agent.verificar_password(password)
    await update.message.reply_text("Desbloqueada, jefe." if ok else "Contraseña incorrecta.")


async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    captura = screenshot_agent.capturar_pantalla()
    if captura.get("error"):
        await update.message.reply_text(f"No pude capturar tu pantalla: {captura['error']}")
        return
    ruta = captura["ruta"]
    try:
        with open(ruta, "rb") as f:
            await update.message.reply_photo(photo=f)
    finally:
        # Seguridad: la captura no se queda en el servidor una vez mandada.
        try:
            os.remove(ruta)
        except OSError:
            pass


async def cmd_organizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    await update.message.reply_text(file_organizer_agent.organizar_descargas_texto())


async def cmd_archivos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    nombre = " ".join(context.args)
    if not nombre:
        await update.message.reply_text("¿Qué archivo busco, jefe? Ej: /archivos tarea_historia")
        return
    await update.message.reply_text(file_organizer_agent.buscar_archivo_texto(nombre))


async def cmd_volumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    if not context.args:
        await update.message.reply_text("Dime: /volumen subir, /volumen bajar, o /volumen <0-100>")
        return
    arg = context.args[0].strip().lower()
    if arg == "subir":
        resultado = control_agent.subir_volumen()
    elif arg == "bajar":
        resultado = control_agent.bajar_volumen()
    elif arg.isdigit():
        resultado = control_agent.set_volumen(int(arg))
    else:
        await update.message.reply_text("No entendí, usa: subir, bajar, o un número de 0 a 100.")
        return
    await update.message.reply_text(resultado)


# ------------------------------------------------------------
# Comandos que sí piensan (pasan por director.py/Gemini, mismos
# tokens que el HUD)
# ------------------------------------------------------------
async def cmd_recordar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    texto = " ".join(context.args)
    if not texto:
        await update.message.reply_text("¿Qué quieres que te recuerde, jefe? Ej: /recordar comprar jamaica mañana")
        return
    await update.message.reply_text(reminder_agent.crear_recordatorio_desde_texto(texto))


async def cmd_abrir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    objetivo = " ".join(context.args)
    if not objetivo:
        await update.message.reply_text("¿Qué quieres que abra, jefe? Ej: /abrir youtube")
        return
    respuesta = director.procesar_mensaje(f"abre {objetivo}", sesion=SESION)
    await _responder(update, respuesta)


# ------------------------------------------------------------
# Comandos peligrosos: confirmación propia de Telegram (CERO tokens,
# NO pasan por director._accion_pendiente/CONFIRMAR — ver cabecera).
# ------------------------------------------------------------
def _pedir_confirmacion(tipo, datos, descripcion):
    global _confirmacion_pendiente
    _confirmacion_pendiente = {"tipo": tipo, "datos": datos, "expira": time.time() + 120}
    return f"¿Seguro jefe? {descripcion}\nResponde sí para continuar o cualquier otra cosa para cancelar."


def _cerrar_app(app):
    try:
        resultado = subprocess.run(["pkill", "-i", "-f", app], capture_output=True, text=True, timeout=10)
        if resultado.returncode == 0:
            return f"Listo, cerré {app}."
        if resultado.returncode == 1:
            return f"No encontré ningún proceso corriendo con '{app}', jefe."
        return f"No pude cerrar {app}: {resultado.stderr.strip()[:200]}"
    except Exception as e:
        return f"No pude cerrar {app}: {e}"


def _accion_energia(comando, mensaje_ok):
    try:
        control_agent.asegurar_entorno_grafico()
        subprocess.Popen(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return mensaje_ok
    except Exception as e:
        return f"No pude ejecutar la acción: {e}"


def _ejecutar_comando_raw(comando):
    try:
        resultado = subprocess.run(comando, shell=True, capture_output=True, text=True, timeout=30)
        texto = f"Código de salida: {resultado.returncode}"
        if resultado.stdout.strip():
            texto += f"\n{resultado.stdout.strip()[:1500]}"
        if resultado.stderr.strip():
            texto += f"\nError:\n{resultado.stderr.strip()[:1500]}"
        return texto
    except subprocess.TimeoutExpired:
        return "El comando tardó más de 30s y se canceló."
    except Exception as e:
        return f"No pude ejecutar el comando: {e}"


def _ejecutar_confirmada(pendiente):
    tipo = pendiente["tipo"]
    datos = pendiente["datos"]
    if tipo == "cerrar":
        return _cerrar_app(datos["app"])
    if tipo == "suspender":
        return _accion_energia(["systemctl", "suspend"], "Suspendiendo, jefe.")
    if tipo == "apagar":
        return _accion_energia(["systemctl", "poweroff"], "Apagando, jefe. Nos vemos.")
    if tipo == "comando":
        return _ejecutar_comando_raw(datos["comando"])
    return "ERROR: confirmación de tipo desconocido."


async def cmd_cerrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    app = " ".join(context.args)
    if not app:
        await update.message.reply_text("¿Qué app cierro, jefe? Ej: /cerrar firefox")
        return
    await update.message.reply_text(_pedir_confirmacion("cerrar", {"app": app}, f"Voy a cerrar '{app}'."))


async def cmd_suspender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    await update.message.reply_text(_pedir_confirmacion("suspender", {}, "Voy a suspender la computadora."))


async def cmd_apagar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    await update.message.reply_text(_pedir_confirmacion("apagar", {}, "Voy a apagar la computadora."))


async def cmd_comando(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return
    comando = " ".join(context.args)
    if not comando:
        await update.message.reply_text("¿Qué comando ejecuto, jefe? Ej: /comando df -h")
        return
    await update.message.reply_text(_pedir_confirmacion("comando", {"comando": comando}, f"Voy a ejecutar: {comando}"))


# ------------------------------------------------------------
# Chat libre, voz y fotos
# ------------------------------------------------------------
_PATRON_MARCADOR_IMAGEN = re.compile(r"\[IMAGEN:([^\]]+)\]")

# Telegram rechaza cualquier mensaje de más de 4096 caracteres (ej. el
# manual completo, ~10k) — sin esto, reply_text() truena con un error
# que _manejar_error solo loggea server-side, y el jefe se queda sin
# ver NADA en el chat. Se corta en saltos de línea dobles (separadores
# de sección en manual.py) cuando se puede, para no partir una sección
# a la mitad.
_LIMITE_TELEGRAM = 4096


def _partir_en_trozos(texto, limite=_LIMITE_TELEGRAM):
    if len(texto) <= limite:
        return [texto]

    trozos = []
    restante = texto
    while len(restante) > limite:
        corte = restante.rfind("\n\n", 0, limite)
        if corte == -1:
            corte = restante.rfind("\n", 0, limite)
        if corte == -1:
            corte = limite
        trozos.append(restante[:corte].strip())
        restante = restante[corte:].strip()
    if restante:
        trozos.append(restante)
    return trozos

# Mismo endpoint que server.py expone para el HUD (ver director.
# marcador_imagen) -> archivo local de donde mandarla como foto de
# Telegram. Si se agrega un endpoint de imagen nuevo, se registra acá.
_RUTAS_POR_ENDPOINT_IMAGEN = {
    "/figura": figura_agent.RUTA_FIGURA,
    "/figura-animada": figura_agent.RUTA_FIGURA_GIF,
    "/foto": observador.RUTA_FOTO,
    "/captura": screenshot_agent.RUTA_SCREENSHOT,
}


async def _responder(update: Update, texto_respuesta: str):
    """Manda la respuesta del director de vuelta al chat de Telegram.
    Si trae el marcador genérico de imagen (ver director.marcador_imagen/
    _PATRON_MARCADOR_IMAGEN), manda la imagen correspondiente como foto
    en vez de solo texto — mismo criterio que agregarMensaje() en
    script.js usa para el HUD. Los .gif se mandan como animación
    (reply_animation) — mandados como foto, Telegram no los anima."""
    coincidencia = _PATRON_MARCADOR_IMAGEN.search(texto_respuesta)
    ruta_archivo = _RUTAS_POR_ENDPOINT_IMAGEN.get(coincidencia.group(1)) if coincidencia else None

    if ruta_archivo:
        caption = _PATRON_MARCADOR_IMAGEN.sub("", texto_respuesta).strip() or None
        try:
            with open(ruta_archivo, "rb") as f:
                if ruta_archivo.endswith(".gif"):
                    await update.message.reply_animation(animation=f, caption=caption)
                else:
                    await update.message.reply_photo(photo=f, caption=caption)
            return
        except OSError:
            pass  # no estaba el archivo por lo que sea: cae a mandar el texto tal cual
    for trozo in _partir_en_trozos(texto_respuesta):
        await update.message.reply_text(trozo)


# ------------------------------------------------------------
# Examen interactivo (ver examen_agent.py) — versión texto para
# Telegram: pregunta con opciones numeradas/con letra, el jefe responde
# con la letra o el número, IRIS dice si acertó + explica, y lleva el
# score (ver examen_agent.responder, que además guarda el resultado
# final en Supabase). Mismo examen ACTIVO que consume el HUD (ver
# server.py /examen/actual) — un solo examen a la vez, sin importar el
# canal desde el que se contesta.
# ------------------------------------------------------------
_PATRON_MARCADOR_EXAMEN = re.compile(r"\[EXAMEN\]")
_LETRA_A_INDICE = {"A": 0, "B": 1, "C": 2, "D": 3}


def _texto_pregunta_examen(pregunta):
    lineas = [f"Pregunta {pregunta['indice'] + 1} de {pregunta['total']} — {pregunta['tema']}:", "", pregunta["pregunta"], ""]
    lineas += pregunta["opciones"]
    lineas.append("\nResponde con la letra (A/B/C/D) o el número de la opción.")
    return "\n".join(lineas)


async def _enviar_pregunta_examen(update: Update):
    pregunta = examen_agent.pregunta_actual()
    if pregunta is not None:
        await update.message.reply_text(_texto_pregunta_examen(pregunta))


def _parsear_letra_respuesta(texto):
    """"B" / "b)" / "2" -> "B" (ver _LETRA_A_INDICE). None si el
    mensaje no es reconocible como una respuesta de opción múltiple."""
    primero = texto.strip().upper()[:1]
    if primero in _LETRA_A_INDICE:
        return primero
    if primero in "1234":
        return "ABCD"[int(primero) - 1]
    return None


async def _manejar_respuesta_examen(update: Update, texto: str):
    letra = _parsear_letra_respuesta(texto)
    if letra is None:
        await update.message.reply_text("Respóndeme con la letra (A/B/C/D) o el número de la opción, jefe.")
        return

    resultado = examen_agent.responder(letra)
    if resultado.get("error"):
        await update.message.reply_text(resultado["error"])
        return

    feedback = "✅ ¡Correcto!" if resultado["correcto"] else f"❌ Incorrecto, la respuesta correcta era {resultado['respuesta_correcta']}."
    if resultado.get("explicacion"):
        feedback += f"\n{resultado['explicacion']}"
    await update.message.reply_text(feedback)

    if resultado["terminado"]:
        cierre = f"Examen terminado: {resultado['aciertos']}/{resultado['total']} aciertos."
        if resultado.get("fallos"):
            cierre += "\n\nRepasa esto:\n" + "\n".join(f"- {f}" for f in resultado["fallos"])
        await update.message.reply_text(cierre)
    else:
        await _enviar_pregunta_examen(update)


async def manejar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return

    global _confirmacion_pendiente
    texto = update.message.text or ""

    # Examen activo: CUALQUIER mensaje se interpreta como la respuesta
    # a la pregunta actual, en vez de pasar por director.py — una letra
    # suelta ("B") o un número (1-4) no debe interpretarse como
    # lenguaje natural. Va ANTES que _confirmacion_pendiente: ambos
    # wizards son mutuamente excluyentes en la práctica (no hay
    # confirmación de /cerrar-/comando pendiente a mitad de un examen).
    if examen_agent.examen_activo() is not None:
        await _manejar_respuesta_examen(update, texto)
        return

    if _confirmacion_pendiente is not None:
        pendiente = _confirmacion_pendiente
        _confirmacion_pendiente = None
        if time.time() > pendiente["expira"]:
            respuesta = "Esa confirmación ya expiró, jefe. Vuelve a mandar el comando."
        elif texto.strip().lower() in ("sí", "si", "confirmar"):
            respuesta = _ejecutar_confirmada(pendiente)
        else:
            respuesta = "Cancelado, jefe."
        for trozo in _partir_en_trozos(respuesta):
            await update.message.reply_text(trozo)
        return

    # Chat normal: mismo cerebro que el HUD, mismos tokens.
    respuesta = director.procesar_mensaje(texto, sesion=SESION)

    # "[EXAMEN]" (ver director._procesar_examen): el examen ya arrancó
    # server-side (examen_agent.iniciar_examen) — se manda el mensaje de
    # confirmación y de una vez la primera pregunta, mismo criterio que
    # el HUD (que abre la vista de examen al ver este marcador).
    if _PATRON_MARCADOR_EXAMEN.search(respuesta):
        respuesta = _PATRON_MARCADOR_EXAMEN.sub("", respuesta).strip()
        await _responder(update, respuesta)
        await _enviar_pregunta_examen(update)
        return

    await _responder(update, respuesta)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return

    archivo_voz = await update.message.voice.get_file()
    ruta_temporal = f"/tmp/geram_telegram_voz_{update.message.message_id}.oga"
    await archivo_voz.download_to_drive(ruta_temporal)

    try:
        texto = escuchar.transcribir_audio(ruta_temporal)
    except RuntimeError as e:
        await update.message.reply_text(f"No pude transcribir el audio: {e}")
        return
    finally:
        try:
            os.remove(ruta_temporal)
        except OSError:
            pass

    if not texto.strip():
        await update.message.reply_text("No entendí el audio, jefe.")
        return

    respuesta = director.procesar_mensaje(texto, sesion=SESION)
    await _responder(update, f'Escuché: "{texto}"\n\n{respuesta}')


async def manejar_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _listo(update):
        return

    # observador.py está cableado a la webcam local (fswebcam) y no
    # acepta una ruta de imagen arbitraria, así que aquí se le manda la
    # foto que YA mandó el jefe directo a Gemini Vision via balancer —
    # esto sí gasta tokens, pero solo porque el usuario mandó una foto,
    # cumple la regla de tokens tal cual.
    foto = update.message.photo[-1]  # última = mayor resolución
    archivo = await foto.get_file()
    await archivo.download_to_drive(_RUTA_FOTO_TELEGRAM)

    try:
        prompt = (update.message.caption or "").strip() or _PROMPT_FOTO_DEFAULT
        respuesta = balancer.enviar_mensaje_con_imagen(prompt, _RUTA_FOTO_TELEGRAM, mime_type="image/jpeg")
    finally:
        try:
            os.remove(_RUTA_FOTO_TELEGRAM)
        except OSError:
            pass

    for trozo in _partir_en_trozos(respuesta):
        await update.message.reply_text(trozo)


async def _manejar_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("telegram_agent: error no manejado (%s)", context.error)


# ------------------------------------------------------------
# Notificaciones proactivas (llamado desde reminder_agent.py,
# proactividad_agent.py y server.py — nunca desde el hilo del bot).
# Usa la API HTTP de Telegram directo, no el Application ni su loop de
# asyncio, para poder llamarse desde CUALQUIER hilo sin coordinar
# asyncio entre hilos. CERO tokens: solo manda texto ya generado.
# ------------------------------------------------------------
def enviar_notificacion(texto):
    if not BOT_TOKEN or not CHAT_ID_AUTORIZADO:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID_AUTORIZADO, "text": texto},
            timeout=10,
        )
    except Exception as e:
        log.error("telegram_agent: no se pudo mandar la notificación proactiva (%s)", e)


# ------------------------------------------------------------
# Arranque
# ------------------------------------------------------------
def _construir_app():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("balance", cmd_balance))
    application.add_handler(CommandHandler("pendientes", cmd_pendientes))
    application.add_handler(CommandHandler("tareas", cmd_tareas))
    application.add_handler(CommandHandler("recordar", cmd_recordar))
    application.add_handler(CommandHandler("lock", cmd_lock))
    application.add_handler(CommandHandler("unlock", cmd_unlock))
    application.add_handler(CommandHandler("screenshot", cmd_screenshot))
    application.add_handler(CommandHandler("abrir", cmd_abrir))
    application.add_handler(CommandHandler("cerrar", cmd_cerrar))
    application.add_handler(CommandHandler("volumen", cmd_volumen))
    application.add_handler(CommandHandler("suspender", cmd_suspender))
    application.add_handler(CommandHandler("apagar", cmd_apagar))
    application.add_handler(CommandHandler("organizar", cmd_organizar))
    application.add_handler(CommandHandler("archivos", cmd_archivos))
    application.add_handler(CommandHandler("comando", cmd_comando))
    application.add_handler(MessageHandler(filters.VOICE, manejar_voz))
    application.add_handler(MessageHandler(filters.PHOTO, manejar_foto))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto))
    application.add_error_handler(_manejar_error)

    return application


def iniciar_bot():
    """Arranca el bot en polling, BLOQUEANTE — se llama desde un thread
    aparte (ver iniciar_en_thread/server.py), nunca desde el hilo
    principal. Si falla (sin internet, token inválido, etc.) solo
    loggea: el HUD local sigue funcionando normal, el bot es 100%
    opcional. PTB reintenta la conexión sola cuando vuelve el internet
    (long polling con backoff incorporado)."""
    if not BOT_TOKEN or not CHAT_ID_AUTORIZADO:
        log.warning("telegram_agent: falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en .env, el bot no arranca")
        return

    # Patrón estándar para correr PTB fuera del hilo principal: crea su
    # propio loop asyncio en este thread (run_polling internamente lo
    # necesita, y solo asume que ya hay uno si se lo damos nosotros).
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        application = _construir_app()
        log.info("telegram_agent: bot arrancando (polling)...")
        # stop_signals=None: add_signal_handler solo funciona en el hilo
        # principal, y este bot corre en un thread aparte.
        application.run_polling(stop_signals=None)
    except Exception as e:
        log.error("telegram_agent: el bot de Telegram falló (%s)", e)


def iniciar_en_thread():
    """Lanza iniciar_bot() en un daemon thread — no bloquea el arranque
    de server.py ni el HUD. Devuelve el thread (por si el caller quiere
    inspeccionarlo, no hace falta para el uso normal)."""
    hilo = threading.Thread(target=iniciar_bot, daemon=True, name="telegram-bot")
    hilo.start()
    return hilo
