# ============================================================
# GERAM OS v2 · server.py
# Servidor liviano (FastAPI + psutil) que expone estadísticas
# REALES del sistema (CPU, RAM, red, temperatura, disco, uptime)
# y sirve la interfaz web estática.
#
# Pensado para hardware modesto (i3 / 8GB RAM): no usa hilos
# extra, ni polling en segundo plano; cada request a /stats
# hace una lectura puntual y barata del sistema.
# ============================================================

import ipaddress
import logging
import os
import tempfile
import threading
import time
from datetime import datetime

import psutil
import schedule
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from agents import (
    adjuntos_agent, agentes_estado, clipboard_agent, control_agent, daily_briefing_agent,
    director, escuchar,
    examen_agent, figura_agent, habla, heartbeat_agent, lock_agent,
    observador, offline_agent, proactividad_agent, reminder_agent, retrospectiva_agent,
    screenshot_agent, telegram_agent,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

app = FastAPI(title="GERAM OS v2 · API")

# Momento en que arrancó este proceso del servidor (para /info).
_inicio_servidor = time.time()

# Agentes ya implementados y en uso en esta fase del proyecto.
AGENTES_ACTIVOS = [
    "director", "balancer", "memory", "context_engine", "personality",
    "escuchar", "habla", "offline_agent", "lock_agent",
    "control_agent", "web_agent", "groq_agent", "notion_agent",
    "daily_briefing_agent", "reminder_agent", "calendar_agent", "email_agent",
    "classroom_agent", "nexus_agent", "research_agent",
    "finance_agent", "pendientes_agent",
    "screenshot_agent", "observador", "clipboard_agent", "file_organizer_agent", "whatsapp_agent",
    "adjuntos_agent", "proactividad_agent", "retrospectiva_agent", "telegram_agent",
    "obsidian_agent", "examen_agent",
]

# ============================================================
# ACCESO REMOTO: solo localhost y la red de Tailscale (100.64.0.0/10).
# Pensado para cuando server.py escuche en 0.0.0.0 en vez de solo
# 127.0.0.1 (ver PASO 2 de Fase B) — mientras el bind siga en
# 127.0.0.1, esto nunca ve tráfico externo, pero ya queda listo y
# probado para el día que se cambie.
# ============================================================
_RED_TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


def _ip_permitida(ip_str):
    """True si `ip_str` es localhost o cae dentro de la red de
    Tailscale. Separada de la middleware para poder probarla directo
    con IPs de prueba, sin necesitar un request real."""
    if not ip_str:
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip.is_loopback or ip in _RED_TAILSCALE


@app.middleware("http")
async def restringir_acceso_remoto(request: Request, call_next):
    ip_cliente = request.client.host if request.client else None
    marca_tiempo = datetime.now().isoformat(timespec="seconds")

    if not _ip_permitida(ip_cliente):
        log.warning("server: acceso BLOQUEADO desde %s a %s (%s)", ip_cliente, request.url.path, marca_tiempo)
        return JSONResponse(status_code=403, content={"detail": "Acceso no permitido desde esta IP."})

    log.info("server: acceso desde %s a %s (%s)", ip_cliente, request.url.path, marca_tiempo)
    return await call_next(request)


# CORS habilitado para desarrollo (la interfaz podría abrirse desde
# otro puerto/origen mientras se prueba, ej. Live Server).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# SIN CACHE para el HTML/CSS/JS de la interfaz: StaticFiles no manda
# Cache-Control por su cuenta, así que el navegador usa caché
# heurístico y un F5 normal no siempre revalida — el HUD se quedaba
# mostrando el script.js/style.css de ANTES de la última edición hasta
# un hard-refresh manual (Ctrl+Shift+R). "no-cache" (no "no-store") es
# barato igual: el navegador revalida con el ETag/Last-Modified que
# StaticFiles ya manda, y si no cambió el servidor responde 304 sin
# volver a mandar el archivo completo.
# ============================================================
_EXTENSIONES_SIN_CACHE = (".css", ".js", ".html")


@app.middleware("http")
async def sin_cache_interfaz(request: Request, call_next):
    respuesta = await call_next(request)
    ruta = request.url.path
    if ruta == "/" or ruta.endswith(_EXTENSIONES_SIN_CACHE):
        respuesta.headers["Cache-Control"] = "no-cache"
    return respuesta

# Contadores de red guardados para poder calcular KB/s entre lecturas
# (psutil solo entrega bytes acumulados desde el arranque del SO).
_red_prev = psutil.net_io_counters()
_red_prev_t = time.time()


def _obtener_velocidad_red():
    """Calcula la velocidad de red actual en KB/s comparando el
    contador acumulado de bytes contra la lectura anterior."""
    global _red_prev, _red_prev_t

    ahora = time.time()
    actual = psutil.net_io_counters()
    delta_t = max(ahora - _red_prev_t, 0.001)  # evita división entre 0

    bytes_totales = (actual.bytes_sent + actual.bytes_recv) - (
        _red_prev.bytes_sent + _red_prev.bytes_recv
    )
    kb_por_seg = (bytes_totales / 1024) / delta_t

    _red_prev = actual
    _red_prev_t = ahora

    return round(max(kb_por_seg, 0), 1)


def _obtener_temperatura():
    """Intenta leer la temperatura real del CPU. Si el sensor no
    está disponible (común en laptops/VMs sin acceso a sensores),
    se estima a partir del uso de CPU como aproximación visual."""
    try:
        temps = psutil.sensors_temperatures()
        for etiqueta in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            if etiqueta in temps and temps[etiqueta]:
                return round(temps[etiqueta][0].current, 1)
        # Si existe cualquier otro sensor, usar el primero disponible
        for lecturas in temps.values():
            if lecturas:
                return round(lecturas[0].current, 1)
    except (AttributeError, OSError):
        pass  # sensors_temperatures no existe en algunos sistemas (ej. Windows/macOS)

    # Estimación simple: temperatura base + factor por uso de CPU
    uso_cpu = psutil.cpu_percent(interval=None)
    return round(38 + (uso_cpu * 0.25), 1)


def _obtener_uptime():
    """Devuelve el uptime del sistema como texto HH:MM:SS."""
    segundos = int(time.time() - psutil.boot_time())
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _obtener_pwr(uso_cpu, uso_ram):
    """Nivel de 'energía' del sistema (gauge PWR/gEner del HUD).

    Si hay batería (laptop) se usa su porcentaje real. En un
    equipo de escritorio sin batería, se estima como la capacidad
    de reserva del sistema a partir del uso real de CPU/RAM.
    """
    bateria = psutil.sensors_battery()
    if bateria is not None:
        return round(bateria.percent, 1)

    reserva = 100 - ((uso_cpu + uso_ram) / 2) * 0.3
    return round(max(90, min(100, reserva)), 1)


@app.get("/stats")
def stats():
    """Estadísticas reales del sistema, listas para el HUD."""
    uso_cpu = psutil.cpu_percent(interval=0.2)
    uso_ram = psutil.virtual_memory().percent

    return {
        "cpu": uso_cpu,
        "ram": uso_ram,
        "red_kbs": _obtener_velocidad_red(),
        "temp": _obtener_temperatura(),
        "disco": psutil.disk_usage("/").percent,
        "uptime": _obtener_uptime(),
        "pwr": _obtener_pwr(uso_cpu, uso_ram),
    }


class MensajeChat(BaseModel):
    mensaje: str


@app.post("/chat")
def chat(cuerpo: MensajeChat):
    """Recibe un mensaje del usuario y devuelve la respuesta de IRIS.
    Bloqueado si el sistema está en standby (ver lock_agent). Si hay un
    adjunto pendiente (imagen pegada o PDF subido, ver /adjuntar), el
    mensaje se trata como la pregunta sobre ESE adjunto en vez de pasar
    por el enrutador normal de intenciones — puede venir vacío (el
    usuario dio enviar sin escribir nada, pide análisis/resumen genérico)."""
    if lock_agent.esta_bloqueado():
        raise HTTPException(status_code=423, detail="Sistema bloqueado. Envía la contraseña a /unlock.")

    if adjuntos_agent.hay_pendiente():
        respuesta = adjuntos_agent.procesar_pendiente(cuerpo.mensaje or None)
    else:
        respuesta = director.procesar_mensaje(cuerpo.mensaje)
    lock_agent.registrar_actividad()
    return {"respuesta": respuesta}


@app.post("/adjuntar")
async def adjuntar(archivo: UploadFile):
    """Recibe una imagen (pegada con Ctrl+V) o un PDF (botón de
    adjuntar o drag&drop) y lo deja como adjunto pendiente — NO lo
    manda a Gemini/Groq todavía, eso pasa recién cuando el usuario le
    da enviar en /chat (con o sin pregunta escrita)."""
    if lock_agent.esta_bloqueado():
        raise HTTPException(status_code=423, detail="Sistema bloqueado. Envía la contraseña a /unlock.")

    contenido = await archivo.read()
    resultado = adjuntos_agent.guardar_adjunto(archivo.filename or "adjunto", contenido)
    if resultado.get("error"):
        raise HTTPException(status_code=400, detail=resultado["error"])

    lock_agent.registrar_actividad()
    return resultado


@app.post("/adjuntar/cancelar")
def cancelar_adjunto():
    """Descarta el adjunto pendiente sin procesarlo (botón "✕" del chip
    en el HUD)."""
    adjuntos_agent.descartar_pendiente()
    return {"ok": True}


@app.post("/subir-pdf")
async def subir_pdf(archivo: UploadFile):
    """Sube un PDF desde el botón dedicado del HUD (distinto del
    adjuntar normal de /adjuntar: este NO se manda a Gemini/Groq de
    entrada, solo queda guardado en examen_agent.RUTA_PDF_SUBIDO para
    que "examen de este pdf" lo use después, ver
    director._procesar_examen)."""
    if lock_agent.esta_bloqueado():
        raise HTTPException(status_code=423, detail="Sistema bloqueado. Envía la contraseña a /unlock.")
    if not (archivo.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo acepto archivos PDF en este botón.")

    contenido = await archivo.read()
    try:
        with open(examen_agent.RUTA_PDF_SUBIDO, "wb") as f:
            f.write(contenido)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    lock_agent.registrar_actividad()
    return {"ok": True, "nombre": archivo.filename}


@app.get("/examen/actual")
def examen_actual():
    """Pregunta ACTUAL del examen activo (ver examen_agent.pregunta_actual,
    sin la respuesta_correcta/explicacion — eso solo se manda en la
    respuesta de /examen/responder, DESPUÉS de que el jefe ya contestó).
    {"activo": False} si no hay ningún examen en curso o ya terminó —
    el HUD hace poll de esto mientras muestra la vista de examen."""
    pregunta = examen_agent.pregunta_actual()
    if pregunta is None:
        return {"activo": False}
    return {"activo": True, **pregunta}


class RespuestaExamen(BaseModel):
    respuesta: str


@app.post("/examen/responder")
def examen_responder(cuerpo: RespuestaExamen):
    """Registra la respuesta a la pregunta actual del examen activo y
    devuelve el feedback (correcto/incorrecto + explicación). Si era la
    última pregunta, además guarda el resultado en Supabase (ver
    examen_agent.responder) y la respuesta trae "terminado": true +
    "aciertos"/"total" para la pantalla de calificación final."""
    resultado = examen_agent.responder(cuerpo.respuesta)
    if resultado.get("error"):
        raise HTTPException(status_code=400, detail=resultado["error"])
    return resultado


@app.post("/examen/cancelar")
def examen_cancelar():
    """Sale de la vista de examen sin terminarlo (botón "✕" del HUD) —
    NO guarda ningún resultado parcial en Supabase."""
    examen_agent.cancelar_examen()
    return {"ok": True}


@app.post("/audio")
async def audio(archivo: UploadFile):
    """Recibe un audio grabado en el navegador y devuelve su
    transcripción a texto (faster-whisper)."""
    if lock_agent.esta_bloqueado():
        raise HTTPException(status_code=423, detail="Sistema bloqueado. Envía la contraseña a /unlock.")

    sufijo = os.path.splitext(archivo.filename or "")[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=sufijo, delete=False) as tmp:
        tmp.write(await archivo.read())
        ruta_temporal = tmp.name

    try:
        texto = escuchar.transcribir_audio(ruta_temporal)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    finally:
        os.remove(ruta_temporal)

    lock_agent.registrar_actividad()
    return {"texto": texto}


class TextoHablar(BaseModel):
    texto: str


@app.post("/hablar")
def hablar_endpoint(cuerpo: TextoHablar, background_tasks: BackgroundTasks):
    """Convierte texto a audio (Piper) y devuelve el archivo .wav."""
    ruta_temporal = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    try:
        habla.generar_audio(cuerpo.texto, ruta_temporal)
    except RuntimeError as e:
        os.remove(ruta_temporal)
        raise HTTPException(status_code=503, detail=str(e))

    background_tasks.add_task(os.remove, ruta_temporal)
    return FileResponse(ruta_temporal, media_type="audio/wav", filename="iris.wav")


@app.get("/figura")
def figura_endpoint():
    """Sirve la última figura generada por figura_agent.py ("dibújame
    X"). 404 si todavía no se ha generado ninguna en esta sesión."""
    if not os.path.exists(figura_agent.RUTA_FIGURA):
        raise HTTPException(status_code=404, detail="Todavía no he generado ninguna figura.")
    return FileResponse(figura_agent.RUTA_FIGURA, media_type="image/png")


@app.get("/figura-animada")
def figura_animada_endpoint():
    """Sirve la última figura ANIMADA (GIF) generada por figura_agent.py
    ("hazme una animación de X"). 404 si todavía no se ha generado
    ninguna en esta sesión."""
    if not os.path.exists(figura_agent.RUTA_FIGURA_GIF):
        raise HTTPException(status_code=404, detail="Todavía no he generado ninguna animación.")
    return FileResponse(figura_agent.RUTA_FIGURA_GIF, media_type="image/gif")


@app.get("/foto")
def foto_endpoint():
    """Sirve la última foto de webcam ("toma foto", ver observador.py).
    404 si todavía no se ha tomado ninguna en esta sesión."""
    if not os.path.exists(observador.RUTA_FOTO):
        raise HTTPException(status_code=404, detail="Todavía no he tomado ninguna foto.")
    return FileResponse(observador.RUTA_FOTO, media_type="image/png")


@app.get("/captura")
def captura_endpoint():
    """Sirve la última captura de pantalla ("screenshot"/"captura"/"ve
    mi pantalla", ver screenshot_agent.py). 404 si todavía no se ha
    tomado ninguna en esta sesión."""
    if not os.path.exists(screenshot_agent.RUTA_SCREENSHOT):
        raise HTTPException(status_code=404, detail="Todavía no he tomado ninguna captura.")
    return FileResponse(screenshot_agent.RUTA_SCREENSHOT, media_type="image/png")


@app.get("/lock-status")
def lock_status():
    """Dice si el sistema está en standby (bloqueado) o no."""
    return {
        "bloqueado": lock_agent.esta_bloqueado(),
        "minutos_inactivo": lock_agent.minutos_inactivo(),
    }


class Password(BaseModel):
    password: str


@app.post("/unlock")
def unlock(cuerpo: Password):
    """Verifica la contraseña y desbloquea el sistema si es correcta."""
    ok = lock_agent.verificar_password(cuerpo.password)
    return {"ok": ok}


class ModoOffline(BaseModel):
    forzar: bool


@app.get("/modo-offline")
def obtener_modo_offline():
    """Estado del modo offline: si está forzado a mano y si hay
    internet de verdad ahorita."""
    return {
        "forzado_manual": offline_agent.modo_offline_forzado(),
        "hay_internet": offline_agent.hay_internet(),
    }


@app.post("/modo-offline")
def establecer_modo_offline(cuerpo: ModoOffline):
    """Fuerza (o quita el forzado de) el modo offline manualmente,
    sin tener que desconectar el WiFi de verdad."""
    if cuerpo.forzar:
        offline_agent.activar_modo_offline()
    else:
        offline_agent.desactivar_modo_offline()
    return {"forzado_manual": offline_agent.modo_offline_forzado()}


class EstadoVista(BaseModel):
    activo: bool


@app.post("/vista")
def establecer_vista(cuerpo: EstadoVista):
    """Sincroniza el botón VISTA del HUD con observador.py — sin esto,
    el backend no tiene forma de saber si la cámara está "prendida"
    (el toggle de VISTA es puramente visual en script.js) y no podría
    responder "Activa mi vista primero, jefe" cuando corresponde."""
    observador.set_vista_activa(cuerpo.activo)
    return {"vista_activa": observador.vista_esta_activa()}


class EstadoVoz(BaseModel):
    activo: bool


@app.post("/voz")
def establecer_voz(cuerpo: EstadoVoz):
    """Sincroniza el botón VOZ del HUD con control_agent.py — así un
    click local en el HUD también queda reflejado en /control/estado-ui
    para cualquier otra pestaña/dispositivo, igual que "cállate"/"activa
    tu voz" dichos por voz/texto o desde Telegram."""
    if cuerpo.activo:
        control_agent.activar_voz()
    else:
        control_agent.desactivar_voz()
    return {"voz_activa": control_agent.obtener_voz_activa()}


class EstadoModoDia(BaseModel):
    activo: bool


@app.post("/modo-dia")
def establecer_modo_dia(cuerpo: EstadoModoDia):
    """Sincroniza el botón sol/luna del HUD con control_agent.py —
    mismo criterio que /voz. Sin esto, el click era puramente local
    (localStorage) y sincronizarEstadoUI() lo revertía a los 2s como
    máximo porque /control/estado-ui seguía devolviendo el valor viejo."""
    control_agent.establecer_modo_dia(cuerpo.activo)
    return {"modo_dia": control_agent.obtener_modo_dia()}


@app.get("/control/estado-ui")
def control_estado_ui():
    """Estado de UI que puede cambiar desde CUALQUIER canal (voz/texto
    del HUD, Telegram) — modo_dia/expandido/voz_activa viven como
    variables reales en control_agent.py, así el HUD los refleja sin
    importar de dónde vino el cambio. mic_solicitud es "leer y limpia":
    se entrega una sola vez y el frontend simula el click en el botón
    MIC si trae "activar"/"desactivar"."""
    return {
        "modo_dia": control_agent.obtener_modo_dia(),
        "expandido": control_agent.obtener_expandido(),
        "voz_activa": control_agent.obtener_voz_activa(),
        "mic_solicitud": control_agent.obtener_y_limpiar_solicitud_mic(),
    }


@app.get("/info")
def info():
    """Información general de esta instancia, para que el HUD la
    muestre en vez de tener el nombre hardcodeado."""
    segundos = int(time.time() - _inicio_servidor)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return {
        "instancia": config.INSTANCE_NAME,
        "agentes_activos": AGENTES_ACTIVOS,
        "uptime": f"{h:02d}:{m:02d}:{s:02d}",
    }


# ============================================================
# AGENTES: listar + suspender/reactivar desde el dashboard del HUD.
# El estado vive en agents/agentes_estado.py (JSON local). "Suspender"
# apaga lo AUTOMÁTICO del agente (proactividad, schedulers, monitores);
# las peticiones explícitas por chat siguen funcionando.
# ============================================================
def _etiqueta_agente(nombre: str) -> str:
    """Nombre legible para el HUD: 'daily_briefing_agent' -> 'Daily Briefing'."""
    limpio = nombre.replace("_agent", "").replace("_", " ").strip()
    return limpio.title() if limpio else nombre


class _AgenteToggle(BaseModel):
    suspendido: bool


@app.get("/agentes")
def listar_agentes():
    """Lista todos los agentes con su estado, para el dashboard del HUD."""
    suspendidos = agentes_estado.listar_suspendidos()
    return {
        "agentes": [
            {
                "nombre": nombre,
                "etiqueta": _etiqueta_agente(nombre),
                "nucleo": nombre in agentes_estado.NUCLEO,
                "suspendido": nombre in suspendidos,
            }
            for nombre in AGENTES_ACTIVOS
        ]
    }


@app.post("/agentes/{nombre}")
def toggle_agente(nombre: str, payload: _AgenteToggle):
    """Suspende o reactiva un agente. Los de núcleo no se pueden suspender."""
    if nombre not in AGENTES_ACTIVOS:
        raise HTTPException(status_code=404, detail=f"Agente desconocido: {nombre}")
    if nombre in agentes_estado.NUCLEO:
        raise HTTPException(
            status_code=409,
            detail=f"'{nombre}' es un agente de núcleo y no puede suspenderse.",
        )
    nuevo = agentes_estado.fijar(nombre, payload.suspendido)
    log.info("server: agente %s -> %s", nombre, "suspendido" if nuevo else "activo")
    return {"nombre": nombre, "suspendido": nuevo}


# ============================================================
# SCHEDULER: briefing matutino automático (BRIEFING_HOUR en .env)
# ============================================================
def _ejecutar_briefing_programado():
    if agentes_estado.esta_suspendido("daily_briefing_agent"):
        return
    log.info("server: ejecutando briefing matutino programado")
    try:
        texto = daily_briefing_agent.generar_briefing(hablar_en_voz=True)
        telegram_agent.enviar_notificacion(texto)
    except Exception as e:
        log.error("server: falló el briefing programado (%s)", e)


def _hilo_scheduler():
    while True:
        schedule.run_pending()
        # 30s de margen: de sobra para no perder el minuto exacto del
        # briefing sin gastar CPU en un i3 revisando a cada segundo.
        time.sleep(30)


def _revisar_recordatorios():
    if agentes_estado.esta_suspendido("reminder_agent"):
        return
    try:
        reminder_agent.revisar_recordatorios_vencidos()
    except Exception as e:
        log.error("server: falló la revisión de recordatorios (%s)", e)


def _revisar_proactividad_local():
    if agentes_estado.esta_suspendido("proactividad_agent"):
        return
    try:
        proactividad_agent.revisar_local()
    except Exception as e:
        log.error("server: falló la revisión de proactividad local (%s)", e)


def _revisar_proactividad_externa():
    if agentes_estado.esta_suspendido("proactividad_agent"):
        return
    try:
        proactividad_agent.revisar_externo()
    except Exception as e:
        log.error("server: falló la revisión de proactividad externa (%s)", e)


def _ejecutar_retrospectiva_programada():
    if agentes_estado.esta_suspendido("retrospectiva_agent"):
        return
    log.info("server: ejecutando retrospectiva semanal programada")
    try:
        retrospectiva_agent.generar_retrospectiva(hablar_en_voz=True)
    except Exception as e:
        log.error("server: falló la retrospectiva programada (%s)", e)


def _actualizar_latido():
    """Le avisa a cloud_bot.py (si está desplegado) que la laptop
    sigue prendida — ver heartbeat_agent.py. Cada 15s: suficiente
    margen contra el umbral de 60s (config.HEARTBEAT_UMBRAL_SEGUNDOS)
    sin escribir a Supabase más seguido de lo necesario."""
    try:
        heartbeat_agent.latir()
    except Exception as e:
        log.error("server: falló la actualización del latido (%s)", e)


_hora_briefing = (config.BRIEFING_HOUR or "0630").strip()
_hora_formateada = f"{_hora_briefing[:2]}:{_hora_briefing[2:]}"
_hora_retro = (config.RETROSPECTIVA_HORA or "1900").strip()
_hora_retro_formateada = f"{_hora_retro[:2]}:{_hora_retro[2:]}"
schedule.every().day.at(_hora_formateada).do(_ejecutar_briefing_programado)
schedule.every(60).seconds.do(_revisar_recordatorios)
schedule.every(60).seconds.do(_revisar_proactividad_local)
schedule.every(5).minutes.do(_revisar_proactividad_externa)
schedule.every().sunday.at(_hora_retro_formateada).do(_ejecutar_retrospectiva_programada)
schedule.every(15).seconds.do(_actualizar_latido)
threading.Thread(target=_hilo_scheduler, daemon=True).start()
log.info(
    "server: briefing automático programado para las %s, checker de recordatorios cada 60s, "
    "proactividad local cada 60s y externa cada 5 min, retrospectiva semanal los domingos a las %s, "
    "latido cada 15s",
    _hora_formateada, _hora_retro_formateada,
)

# Bot de Telegram (Fase G): thread aparte, no bloquea el arranque del
# HUD si falta el token/chat_id en .env o no hay internet ahorita
# mismo (ver telegram_agent.iniciar_bot).
telegram_agent.iniciar_en_thread()

# Historial de portapapeles (Fase F): CERO tokens, solo xclip/xsel +
# comparar strings cada 2s (ver clipboard_agent.iniciar_monitor).
clipboard_agent.iniciar_monitor()


@app.get("/recordatorios/avisos")
def recordatorios_avisos():
    """El HUD hace poll de esto para mostrar en el chat los
    recordatorios que ya se dispararon (la voz ya se dijo sola desde
    el checker en background, esto es solo para el texto en pantalla)."""
    return {"avisos": reminder_agent.obtener_avisos_pendientes()}


@app.get("/proactividad/avisos")
def proactividad_avisos():
    """Mismo patrón que /recordatorios/avisos pero para los avisos de
    proactividad_agent (gastos, batería, calendario, sesión larga)."""
    return {"avisos": proactividad_agent.obtener_avisos_pendientes()}


# Servir la interfaz (index.html, style.css, script.js) en la raíz "/".
# Debe registrarse AL FINAL: StaticFiles con html=True captura "/",
# y si va antes que /stats, tapa esa ruta.
app.mount("/", StaticFiles(directory=".", html=True), name="interfaz")


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0: escucha en todas las interfaces (necesario para acceso
    # remoto vía Tailscale), pero restringir_acceso_remoto() de arriba
    # ya bloquea con 403 todo lo que no sea localhost o 100.64.0.0/10
    # antes de que la request llegue a cualquier endpoint.
    # Un solo worker: de sobra para uso local en un i3 con 8GB RAM.
    # Puerto de IRIS. Se movió del 8000 al 8010 para dejar el 8000 a
    # GERAM CORE OS (el entorno de desarrollo, la app principal del
    # proyecto), que corre en su propia app Electron en ese puerto.
    # IRIS es el complemento y vive en 8010. Configurable por env PORT.
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8010")))
