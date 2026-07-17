# ============================================================
# GERAM OS v2 · config.py
# Carga el .env y expone las variables como constantes.
# Cualquier módulo del proyecto importa desde aquí en vez de
# leer os.environ directamente, para centralizar la validación.
# ============================================================

import os

from dotenv import load_dotenv

# Busca el .env en la raíz del proyecto (dos niveles arriba de este
# archivo: geram-os/config/config.py -> geram-os/.env)
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_RAIZ, ".env"))

# Variables críticas: sin ellas el sistema no puede arrancar.
_VARIABLES_CRITICAS = [
    "INSTANCE_NAME",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "GEMINI_FREE_1",
    "GEMINI_FREE_2",
    "GEMINI_FREE_3",
    "GEMINI_FREE_4",
    "GEMINI_FREE_5",
    "GEMINI_PAY_KEY",
]

_faltantes = [v for v in _VARIABLES_CRITICAS if not os.getenv(v)]
if _faltantes:
    raise RuntimeError(
        "config.py: faltan variables críticas en .env: " + ", ".join(_faltantes)
    )

INSTANCE_NAME = os.getenv("INSTANCE_NAME")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

GEMINI_FREE_1 = os.getenv("GEMINI_FREE_1")
GEMINI_FREE_2 = os.getenv("GEMINI_FREE_2")
GEMINI_FREE_3 = os.getenv("GEMINI_FREE_3")
GEMINI_FREE_4 = os.getenv("GEMINI_FREE_4")
GEMINI_FREE_5 = os.getenv("GEMINI_FREE_5")
GEMINI_PAY_KEY = os.getenv("GEMINI_PAY_KEY")

# Lista ordenada de las keys gratuitas, útil para el round-robin del balancer.
GEMINI_FREE_KEYS = [
    GEMINI_FREE_1,
    GEMINI_FREE_2,
    GEMINI_FREE_3,
    GEMINI_FREE_4,
    GEMINI_FREE_5,
]

# Límite diario ESTIMADO por key gratuita, para calcular el % de uso de
# hoy (ver balancer.obtener_uso_hoy / proactividad_agent._revisar_uso_
# gemini, que avisa cuando alguna key se acerca a esto). Gemini no
# expone un endpoint de cuota restante — esto es un conteo LOCAL de
# cuántas llamadas hizo ESTE proceso hoy, no la cuota real de Google.
# Si el número no coincide con lo que ves en tu dashboard de Google AI
# Studio (aistudio.google.com), ajústalo aquí en .env.
GEMINI_LIMITE_DIARIO_POR_KEY = int(os.getenv("GEMINI_LIMITE_DIARIO_POR_KEY", "200"))

# --- Modo nube (Telegram sin la laptop prendida, ver cloud_bot.py) ---
# True SOLO en el despliegue en la nube — se activa con
# GERAM_MODO_NUBE=true en ESE .env, NUNCA en el de la laptop local.
# Cuando está activo, director.py no importa los agentes que dependen
# del hardware local (cámara, mouse/teclado, navegador visible, correr
# código arbitrario) y bloquea esos intents con un mensaje claro en vez
# de tronar (ver director.INTENTS_SOLO_LOCAL/_ModuloLocal).
MODO_NUBE = os.getenv("GERAM_MODO_NUBE", "false").strip().lower() == "true"

# Segundos sin latido de la laptop local (ver heartbeat_agent.py, que
# server.py actualiza cada 15s) antes de que cloud_bot.py asuma que
# está apagada y tome el relevo de Telegram. Con latidos cada 15s, 60s
# da margen de sobra para que un tráfico de red lento no dispare un
# relevo en falso mientras la laptop sigue prendida.
HEARTBEAT_UMBRAL_SEGUNDOS = int(os.getenv("HEARTBEAT_UMBRAL_SEGUNDOS", "60"))

# --- Fase 2: sentidos, offline y seguridad ---
# No son críticas para arrancar (Fase 1 debe seguir funcionando sin
# ellas), por eso no están en _VARIABLES_CRITICAS: cada módulo que
# las usa aplica su propio valor por defecto si faltan.
LOCK_PASSWORD_HASH = os.getenv("LOCK_PASSWORD_HASH")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")
STANDBY_MINUTES = int(os.getenv("STANDBY_MINUTES", "5"))

# Ruta al modelo de voz de Piper. Si es relativa, se resuelve contra
# la raíz del proyecto (para que funcione sin importar desde dónde
# se lance el servidor).
PIPER_VOICE_PATH = os.getenv("PIPER_VOICE_PATH")
if PIPER_VOICE_PATH and not os.path.isabs(PIPER_VOICE_PATH):
    PIPER_VOICE_PATH = os.path.join(_RAIZ, PIPER_VOICE_PATH)

# Voz neuronal de edge-tts (opción primaria de habla.py con internet).
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE")

# --- Fase 3: Groq (contenido largo) y Notion (documentos) ---
# Tampoco críticas: groq_agent/notion_agent devuelven su propio
# mensaje de error si faltan, en vez de tumbar el arranque del server.
# Round-robin de 5 keys gratuitas (mismo patrón que GEMINI_FREE_KEYS
# arriba) — a diferencia de Gemini, aquí SÍ puede faltar alguna (ej. la
# 5ta todavía sin conseguir): groq_agent.py filtra las vacías antes de
# rotar, así que no hace falta que las 5 estén llenas para funcionar.
GROQ_FREE_1 = os.getenv("GROQ_FREE_1")
GROQ_FREE_2 = os.getenv("GROQ_FREE_2")
GROQ_FREE_3 = os.getenv("GROQ_FREE_3")
GROQ_FREE_4 = os.getenv("GROQ_FREE_4")
GROQ_FREE_5 = os.getenv("GROQ_FREE_5")

GROQ_FREE_KEYS = [
    GROQ_FREE_1,
    GROQ_FREE_2,
    GROQ_FREE_3,
    GROQ_FREE_4,
    GROQ_FREE_5,
]

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Base de Notion aparte para pendientes del día a día (Fase D) —
# distinta a NOTION_DATABASE_ID de arriba, que es para documentos/
# investigaciones de research_agent.py. Ver pendientes_agent.py.
NOTION_PENDIENTES_DB_ID = os.getenv("NOTION_PENDIENTES_DB_ID")

# Base de Notion para finanzas personales (Fase D) — reemplaza la
# tabla "finanzas" de Supabase (memory.py/reminder_agent.py siguen ahí,
# solo finanzas y pendientes viven en Notion). Ver finance_agent.py.
NOTION_FINANZAS_DB_ID = os.getenv("NOTION_FINANZAS_DB_ID")

# Base de Notion para proyectos personales/escolares — distinta a
# NOTION_PENDIENTES_DB_ID: un proyecto vive varios días/semanas y se le
# van agregando avances, no es un pendiente que se marca hecho una vez.
# Ver proyectos_agent.py.
NOTION_PROYECTOS_DB_ID = os.getenv("NOTION_PROYECTOS_DB_ID")

# --- Fase B: fundación diaria (briefing, recordatorios, calendario, correo) ---
# Hora del briefing automático, formato "HHMM" (ej. "0630" = 6:30 AM).
BRIEFING_HOUR = os.getenv("BRIEFING_HOUR", "0630")

# Credenciales OAuth2 de Google (Calendar + Gmail comparten el mismo
# archivo/alcance). Ruta relativa se resuelve contra la raíz del proyecto.
GOOGLE_CALENDAR_CREDENTIALS_PATH = os.getenv("GOOGLE_CALENDAR_CREDENTIALS_PATH")
if GOOGLE_CALENDAR_CREDENTIALS_PATH and not os.path.isabs(GOOGLE_CALENDAR_CREDENTIALS_PATH):
    GOOGLE_CALENDAR_CREDENTIALS_PATH = os.path.join(_RAIZ, GOOGLE_CALENDAR_CREDENTIALS_PATH)

# --- Fase C: escuela (Classroom, Nexus, investigación) ---
# Cuenta de Google Workspace escolar (NO es la cuenta personal de
# arriba). El admin de la escuela bloqueó la API de Classroom, así que
# esto YA NO es para OAuth2 — classroom_agent.py la usa para forzar
# ?authuser=<esto> en las URLs que abre, para que el navegador entre
# con la cuenta correcta aunque haya otra sesión de Google activa.
CLASSROOM_ACCOUNT = os.getenv("CLASSROOM_ACCOUNT")

# Ruta del archivo de credenciales de Nexus, ENCRIPTADAS con Fernet
# (nunca en texto plano, nunca en Supabase). Ruta relativa se resuelve
# contra la raíz del proyecto.
NEXUS_ENC_PATH = os.getenv("NEXUS_ENC_PATH")
if NEXUS_ENC_PATH and not os.path.isabs(NEXUS_ENC_PATH):
    NEXUS_ENC_PATH = os.path.join(_RAIZ, NEXUS_ENC_PATH)

# URL "de vitrina" de Nexus (fallback si no hay credenciales guardadas
# o el login automático falla). El login de verdad NO pasa por aquí,
# sino por el SSO de deimos.dgi.uanl.mx (ver nexus_agent.py).
NEXUS_URL = os.getenv("NEXUS_URL", "https://plataformanexus.uanl.mx/")

# Tipo de cuenta para el SSO de UANL: "01" = Alumno, "02" = Empleado
# (ver <select name="HTMLTipCve"> del login real).
NEXUS_TIPO_CUENTA = os.getenv("NEXUS_TIPO_CUENTA", "01")

# --- Fase D: finanzas personales + pendientes ---
# Umbral semanal de gasto para que finance_agent.alerta_gastos() avise
# proactivamente. float() y no int(): permite umbrales con centavos.
ALERTA_GASTO_SEMANAL = float(os.getenv("ALERTA_GASTO_SEMANAL", "500"))

# --- Fase G: bot de Telegram (HUD remoto) ---
# No críticas (el server debe seguir arrancando sin ellas, el bot
# simplemente no se prende — ver telegram_agent.iniciar_bot()).
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- Fase proactividad: avisos sin que el jefe pregunte ---
# Kill switch: en "false" apaga las 4 señales de proactividad_agent sin
# tocar código. Primer booleano-por-string de este archivo (todo lo
# demás es string/int/float), de ahí el .strip().lower() == "true".
PROACTIVIDAD_ACTIVA = os.getenv("PROACTIVIDAD_ACTIVA", "true").strip().lower() == "true"

# Ventana de silencio (HHMM, mismo formato que BRIEFING_HOUR) durante la
# que proactividad_agent no habla aunque alguna señal se dispare. Cruza
# medianoche por default (23:00 -> 07:00).
PROACTIVIDAD_SILENCIO_INICIO = os.getenv("PROACTIVIDAD_SILENCIO_INICIO", "2300")
PROACTIVIDAD_SILENCIO_FIN = os.getenv("PROACTIVIDAD_SILENCIO_FIN", "0700")

# Umbral de batería (%) para avisar que no está cargando.
ALERTA_BATERIA_PORCENTAJE = float(os.getenv("ALERTA_BATERIA_PORCENTAJE", "20"))

# Minutos de anticipación para avisar que un evento de calendario está
# por empezar.
ALERTA_CALENDARIO_MINUTOS = int(os.getenv("ALERTA_CALENDARIO_MINUTOS", "15"))

# Minutos de inactividad que cuentan como "ya descansó" (reinicia el
# conteo de sesión activa) y minutos de sesión activa continua que
# disparan el aviso de "llevas mucho sin parar".
SESION_DESCANSO_MINUTOS = int(os.getenv("SESION_DESCANSO_MINUTOS", "20"))
SESION_LARGA_MINUTOS = int(os.getenv("SESION_LARGA_MINUTOS", "90"))

# --- Fase pendientes olvidados / retrospectiva / patrones ---
# Días de antigüedad para que un pendiente de Notion cuente como
# "olvidado" y días de enfriamiento antes de volver a insistir con el
# mismo (ver proactividad_agent._revisar_pendientes_olvidados).
PENDIENTE_OLVIDADO_DIAS = int(os.getenv("PENDIENTE_OLVIDADO_DIAS", "5"))
PENDIENTE_RENAGGED_COOLDOWN_DIAS = int(os.getenv("PENDIENTE_RENAGGED_COOLDOWN_DIAS", "3"))

# Hora (HHMM, mismo formato que BRIEFING_HOUR) de la retrospectiva
# semanal, programada los domingos (ver retrospectiva_agent.py).
RETROSPECTIVA_HORA = os.getenv("RETROSPECTIVA_HORA", "1900")

# Cuántas memorias tipo="patron" se revisan (limite ~8 semanas a volumen
# normal) y cuántas semanas ISO distintas deben repetir el mismo
# intent/día para contar como patrón (ver
# proactividad_agent._revisar_patrones).
PATRON_MEMORIAS_LIMITE = int(os.getenv("PATRON_MEMORIAS_LIMITE", "400"))
PATRON_MINIMO_OCURRENCIAS = int(os.getenv("PATRON_MINIMO_OCURRENCIAS", "3"))

# --- Spotify (solo lectura: canción actual + historial, ver spotify_agent.py) ---
# No críticas: sin ellas spotify_agent.esta_configurado() da False y
# los comandos de Spotify avisan que falta configurar, sin tumbar el
# arranque del server. Client ID/Secret los da developer.spotify.com al
# crear la app (a diferencia de Nexus, esto NO es un secreto tipo
# usuario/contraseña que amerite el wizard de chat + Fernet — sigue el
# mismo patrón que el resto de API keys del proyecto, directo en .env).
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

# El TOKEN de acceso (ese sí sensible, se genera solo tras la
# autorización) se cachea aquí — mismo folder credenciales/ que ya usan
# Nexus y Google.
SPOTIFY_TOKEN_PATH = os.getenv("SPOTIFY_TOKEN_PATH", "credenciales/spotify_token.json")
if not os.path.isabs(SPOTIFY_TOKEN_PATH):
    SPOTIFY_TOKEN_PATH = os.path.join(_RAIZ, SPOTIFY_TOKEN_PATH)

# --- Obsidian (notas .md directo en el vault, sin API, ver
# obsidian_agent.py) ---
# No crítica: si falta, se usa esta ruta por default. obsidian_agent.py
# crea la carpeta sola si no existe todavía.
OBSIDIAN_VAULT_PATH = os.path.expanduser(
    os.getenv("OBSIDIAN_VAULT_PATH", "~/Documentos/Obsidian")
)
