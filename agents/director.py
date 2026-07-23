# ============================================================
# GERAM OS v2 · director.py
# Orquestador central: detecta la intención del mensaje (control
# del sistema, búsqueda web, o chat normal) y rutea al agente
# correspondiente. Chat normal sigue yendo a Gemini (o Ollama si no
# hay internet); todo lo demás usa los agentes especializados.
# ============================================================

import json
import logging
import os
import re
import threading
from datetime import datetime

import config
from agents import (
    balancer, calendar_agent, context_engine, control_agent, daily_briefing_agent, email_agent,
    examen_agent, finance_agent, groq_agent, habla, manual, memory, notion_agent, notion_memoria,
    obsidian_agent,
    offline_agent, pendientes_agent, personality, proyectos_agent, reminder_agent, research_agent,
    spotify_agent, web_agent,
)

# control_agent SIEMPRE se importa de verdad (arriba, no en el bloque
# condicional de abajo) aunque varias de sus acciones sean solo-local:
# no tiene dependencias pesadas (puro subprocess/xdotool/wmctrl, nada
# de selenium/playwright), y más abajo en este archivo hay
# TABLAS a nivel de módulo (ej. _ACCIONES_CONTROL_REMOTO_SIMPLES) que
# referencian funciones de control_agent directo al cargar el archivo
# — envenenarlo tronaría el import completo antes de que
# INTENTS_SOLO_LOCAL pudiera bloquear nada. El bloqueo real de sus
# acciones sigue siendo INTENTS_SOLO_LOCAL (más abajo), no la ausencia
# del módulo.

# --- Agentes que SÍ dependen de algo pesado/local (cámara, navegador
# real, correr código arbitrario) — NO se importan en modo nube (ver
# config.MODO_NUBE, cloud_bot.py) para que ese despliegue sea liviano
# (sin selenium/playwright) y porque de todas formas
# INTENTS_SOLO_LOCAL (más abajo) bloquea sus intents antes de llegar a
# usarlos. Si algo se cuela sin pasar por ese bloqueo, _ModuloLocal
# truena con un error CLARO en vez de un AttributeError críptico o,
# peor, fallar en silencio.
class _ModuloLocal:
    """Poison object para los agentes de abajo en modo nube: cualquier
    atributo que se le pida truena explicando que ese módulo no está
    disponible ahí — así un intent mal clasificado se detecta de
    inmediato en vez de fallar confuso a medio camino."""

    def __init__(self, nombre):
        self._nombre = nombre

    def __getattr__(self, atributo):
        raise RuntimeError(
            f"director: se intentó usar '{self._nombre}.{atributo}' en modo nube — "
            "ese intent debería estar bloqueado por INTENTS_SOLO_LOCAL, revisa ahí."
        )


if config.MODO_NUBE:
    cerebro_archivos_agent = _ModuloLocal("cerebro_archivos_agent")
    classroom_agent = _ModuloLocal("classroom_agent")
    clipboard_agent = _ModuloLocal("clipboard_agent")
    code_agent = _ModuloLocal("code_agent")
    code_proyectos = _ModuloLocal("code_proyectos")
    figura_agent = _ModuloLocal("figura_agent")
    file_organizer_agent = _ModuloLocal("file_organizer_agent")
    nexus_agent = _ModuloLocal("nexus_agent")
    observador = _ModuloLocal("observador")
    screenshot_agent = _ModuloLocal("screenshot_agent")
    whatsapp_agent = _ModuloLocal("whatsapp_agent")
else:
    from agents import (
        cerebro_archivos_agent, classroom_agent, clipboard_agent, code_agent, code_proyectos, figura_agent,
        file_organizer_agent, nexus_agent, observador, screenshot_agent, whatsapp_agent,
    )

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("director")

# Acción de control del sistema esperando que el usuario escriba
# CONFIRMAR. Guarda el dict de acción devuelto por
# control_agent.interpretar() (tipo/comando/descripcion). Vive
# en memoria del proceso; se resetea si el servidor se reinicia.
# Mientras haya una pendiente, el siguiente mensaje del usuario SOLO
# decide su destino (no se rutea normalmente).
_accion_pendiente = None

# "¿Seguro que quieres que me apague?" — wizard propio (no el genérico
# de _accion_pendiente) porque tiene una tercera salida además de
# CONFIRMAR/cancelar: si el jefe dice "descansa"/"reposo", se suspende
# en vez de apagar. Ver _procesar_apagar / _despachar caso 0.5.
_apagar_pendiente = False

# Tema esperando que el usuario confirme si quiere el documento largo
# en Notion (ver _procesar_conocimiento). A diferencia de
# _accion_pendiente, esto es de baja fricción: si el siguiente mensaje
# no es una afirmación clara, no se cancela nada, simplemente se
# procesa ese mensaje normalmente (ver procesar_mensaje).
_tema_pendiente_notion = None

# Resumen de un PDF (research_agent) esperando que el usuario confirme
# si quiere guardarlo en Notion. Misma lógica de baja fricción que
# _tema_pendiente_notion, pero guarda {"titulo","contenido"} en vez de
# un tema (el contenido ya está generado, no hay que regenerarlo).
_resumen_pendiente_notion = None

# Lista de documentos (dicts título/url) que investigar() le presentó
# al usuario, esperando que responda con el NÚMERO de cuál quiere que
# se descargue y resuma (ver _procesar_investigacion/procesar_mensaje).
_investigacion_pendiente = None

# Wizard de 2 pasos para "configura Nexus": guarda {"etapa": "usuario"|
# "password", "usuario": str|None}. La contraseña que llega en el paso
# "password" NUNCA se guarda en context_engine/memory (ver
# procesar_mensaje) — persistirla violaría el requisito de que las
# credenciales de Nexus solo vivan encriptadas en nexus.enc.
_nexus_config_pendiente = None

# Registro de finanzas esperando que el usuario diga CUÁNTO fue,
# porque el primer mensaje no traía una cantidad reconocible (ver
# _procesar_finanzas). Guarda {"accion","categoria","descripcion"}.
# Baja fricción igual que _tema_pendiente_notion: si el siguiente
# mensaje no trae un número, no se cancela nada, se procesa normal
# (ver _despachar) — así "agregar dinero" seguido de "500" en dos
# mensajes separados sí registra el movimiento, en vez de perderse
# silenciosamente como pasaba antes.
_finanzas_pendiente = None

# Lista de carpetas (rutas completas) que buscar_carpeta() encontró para
# un nombre ambiguo, esperando que el usuario responda con el NÚMERO de
# cuál — mismo patrón que _investigacion_pendiente. Guarda {"candidatos":
# [...], "abrir": bool} — "abrir" recuerda si el mensaje original pedía
# buscar Y abrir de un jalón ("busca la carpeta X y ábrela") para saber
# qué hacer una vez resuelta la ambigüedad (ver _procesar_buscar_carpeta/
# _despachar).
_carpeta_pendiente = None

# Última carpeta que se resolvió a una sola coincidencia (buscada o ya
# abierta) — para que un "ábrela" SUELTO en un mensaje aparte sepa a cuál
# carpeta se refiere sin tener que repetir el nombre (ver
# _procesar_abrir_ultimo).
_ultima_carpeta = None

# True si el último briefing incluyó la sugerencia de un examen rápido
# de repaso (ver daily_briefing_agent.MARCA_SUGERENCIA_EXAMEN/
# _procesar_briefing) y está esperando que el usuario confirme. Baja
# fricción igual que _tema_pendiente_notion: un mensaje que no es
# afirmación no se pierde, se procesa normal (ver _despachar).
_examen_sugerido_pendiente = False

# Respaldo vía Gemini/Ollama (control_agent.interpretar) — SOLO lo que
# no tiene función determinística propia (ver Fase H2 más abajo):
# crear/borrar/mover/copiar/renombrar archivos y carpetas, instalar/
# desinstalar paquetes, "ejecuta X" arbitrario, cerrar una app por
# NOMBRE ("cierra spotify", distinto de "cierra ventana"/"cierra
# pestaña", que abajo tienen su propia función CERO tokens). "abre"/
# "abrir" SALIÓ de este grupo — ahora resuelve determinístico, ver
# PALABRAS_ABRIR/_procesar_abrir.
PALABRAS_CONTROL = (
    "ejecuta", "ejecutar", "cierra", "cerrar",
    "reinicia", "reiniciar", "instala", "instalar", "desinstala", "desinstalar",
    "crea", "crear",
    "borra", "borrar", "elimina", "eliminar",
    "mueve", "mover", "copia", "copiar", "renombra", "renombrar",
)
# Preguntas de conocimiento: Gemini responde con lo que ya sabe (sin
# DuckDuckGo) y se le ofrece al usuario expandirlo a un documento en
# Notion (ver _procesar_conocimiento). Van ANTES que PALABRAS_WEB en
# _detectar_intencion porque si no, "qué es" / "quién es" caerían en
# "web" (búsqueda en internet) en vez de esto.
PALABRAS_CONOCIMIENTO = (
    "quién es", "quien es", "qué es", "que es", "qué son", "que son",
    "explícame", "explicame", "explica", "cuéntame sobre", "cuentame sobre",
    "define", "definición de", "definicion de", "qué significa", "que significa",
)
PALABRAS_WEB = ("busca", "búscame", "buscame", "encuentra", "googlea", "búscalo", "buscalo")
# Palabras que, junto con alguna de PALABRAS_WEB, indican que el
# usuario quiere BUSCAR ARCHIVOS EN SU EQUIPO (control) y no una
# búsqueda en internet (web). P.ej. "busca archivos pdf en mi carpeta
# de descargas" vs. "busca quién ganó el mundial".
_PISTAS_ARCHIVO = ("archivo", "archivos", "carpeta", "documentos", "descargas", "escritorio")

# Cuando la búsqueda va dirigida a un sitio concreto ("búscalo en google",
# "en amazon", "googlea X"), IRIS ABRE EL NAVEGADOR en ese sitio (ver
# control_agent.buscar_en_navegador) en vez de traer un resumen de texto al
# chat (web_agent.buscar_web, el comportamiento de "búscame X" a secas).
# YouTube NO está aquí: "en youtube" ya lo captura control_remoto antes
# (PALABRAS_YOUTUBE_PON -> control_agent.abrir_en_youtube). El orden importa:
# el primer sitio cuyo disparador aparezca gana (ver _detectar_sitio_busqueda).
_SITIOS_BUSQUEDA_NAVEGADOR = {
    "amazon": ("en amazon",),
    "github": ("en github", "en git hub"),
    "wikipedia": ("en wikipedia", "en la wikipedia"),
    "maps": ("en google maps", "en maps", "en mapas"),
    "mercadolibre": ("en mercado libre", "en mercadolibre"),
    "bing": ("en bing",),
    "spotify": ("en spotify",),
    "google": ("en google", "googlea", "en el navegador", "en internet", "en la web"),
}

# Respuestas cortas que cuentan como "sí" a la oferta de armar el
# documento en Notion. Se compara por token (no por substring) para
# que "va" no matchee dentro de otra palabra (ej. "nova").
_PALABRAS_AFIRMATIVAS = {
    "sí", "si", "dale", "va", "porfa", "claro", "simon", "simón",
    "ok", "okay", "sale", "hazlo", "obvio", "afirmativo",
}

# --- Fase B: fundación diaria ---
PALABRAS_BRIEFING = (
    "buenos días", "buenos dias", "resumen del día", "resumen del dia", "briefing", "resumen de hoy",
    "dame el resumen", "resumen diario", "cómo va mi día", "como va mi dia",
    "qué me perdí", "que me perdi",
)
PALABRAS_RECORDATORIO = (
    "recuérdame", "recuerdame", "recordatorio", "recordatorios", "avísame", "avisame",
    "ponme un recordatorio", "avísame cuando", "avisame cuando",
)
# "qué tengo hoy"/"qué tengo esta semana" caen aquí (no en briefing):
# es una consulta directa al calendario, no un resumen multi-fuente.
PALABRAS_CALENDARIO = (
    "agenda", "agéndame", "agendame", "calendario", "qué tengo hoy", "que tengo hoy",
    "qué tengo esta semana", "que tengo esta semana", "mi agenda", "qué tengo mañana",
    "que tengo manana", "agrega un evento", "agregar evento", "checa mi calendario",
    "checa mi agenda",
)
PALABRAS_CORREO = (
    "correo", "correos", "email", "emails", "bandeja", "manda un mensaje a",
    "revisa mi correo", "checa mi correo", "gmail", "inbox",
)

# --- Fase C: escuela (Classroom, Nexus, investigación) ---
# Plan B (classroom_agent.py): sin API, Mauri dicta sus tareas a mano
# y IRIS abre Classroom/un curso en el navegador cuando se lo pide.
PALABRAS_CLASSROOM = (
    "tarea", "tareas", "classroom", "curso", "cursos", "pendientes escuela", "qué dejaron", "que dejaron",
    "deberes", "checa mis tareas", "tengo tareas pendientes",
)
PALABRAS_NEXUS = ("nexus", "portal", "uanl", "plataforma de la escuela")
# "investiga" dispara el flujo completo (buscar + presentar opciones +
# el usuario elige). "busca pdf(s)"/"busca video(s)" son búsquedas de
# UN solo tipo (a diferencia de investigar(), que mezcla PDFs+artículos)
# pero SÍ dejan lista numerada para elegir (ver _investigacion_pendiente
# en _procesar_investigacion) — "descarga/resume el número 2" funciona
# igual sea la lista de PDFs o de videos. Van ANTES que PALABRAS_WEB en
# _detectar_intencion porque "busca" ya está en PALABRAS_WEB y si no,
# "busca pdfs de X" caería en "web" (búsqueda genérica) en vez de
# research_agent.
PALABRAS_PDF = ("pdf", "pdfs")
PALABRAS_VIDEO = ("video", "videos", "youtube")
PALABRAS_RESUMIR_PDF = (
    "resume el pdf", "resume este pdf", "resume ese pdf",
    "resume el documento", "resume este documento", "resume ese documento",
    "resumir pdf",
)
# "resume este video https://..." resume la transcripción directo, sin
# pasar por buscar primero (ver research_agent.resumir_video_youtube).
PALABRAS_RESUMIR_VIDEO = (
    "resume el video", "resume este video", "resume ese video",
    "resume este youtube", "resume ese youtube", "resumir video",
)

# --- Fase D: finanzas personales + pendientes ---
PALABRAS_FINANZAS = (
    "gasté", "gaste", "gasto", "gastos", "vendí", "vendi", "ingreso", "ingresos",
    "ganancia", "ganado", "gané", "gane", "balance", "cuánto llevo", "cuanto llevo",
    "cuánto tengo", "cuanto tengo", "resumen financiero", "finanzas", "dinero",
    "pagué", "pague", "cobré", "cobre",
)
# "pendiente(s)" personales (Notion) vs "tarea(s)" escolares
# (classroom_agent): PALABRAS_CLASSROOM se revisa ANTES en
# _detectar_intencion, así que "pendientes escuela"/"tarea"/"tareas" ya
# quedan resueltas ahí primero — esto solo atrapa lo que quede.
PALABRAS_PENDIENTES = (
    "pendiente", "pendientes", "tengo que", "agregar pendiente",
    "ya hice", "ya compré", "ya compre", "elimina pendiente", "elimina el pendiente", "borra el pendiente",
    "no se me olvide", "que no se me olvide", "márcalo como hecho", "marca como hecho",
    "ya terminé", "ya termine",
)
# "proyecto(s)" (Notion, seguimiento de AVANCE a lo largo del tiempo)
# vs "pendiente(s)" (acción suelta que se marca hecha una vez) y
# "tarea(s)" (deberes escolares de classroom_agent, PALABRAS_CLASSROOM
# se revisa ANTES en _detectar_intencion así que ya no colisiona).
PALABRAS_PROYECTOS = (
    "proyecto", "proyectos", "avance en", "avance de", "avances de", "avances en",
    "cómo voy con", "como voy con", "crea un proyecto", "nuevo proyecto",
    "pausa el proyecto", "elimina el proyecto", "borra el proyecto",
)

# --- Fase F: agentes avanzados (screenshot, observador, clipboard,
# organizador de archivos, WhatsApp). Ver reglas de tokens al inicio
# del reporte de esta fase: screenshot_agent/observador SOLO gastan
# tokens en analizar/comparar (nunca en capturar); clipboard/archivos/
# whatsapp NUNCA gastan tokens, cero excepciones.
# "screenshot"/"captura"/"ve mi pantalla"/"qué hay en mi pantalla" ya
# NO están acá — ahora son parte del grupo de control remoto (Fase H2,
# ver PALABRAS_CAPTURA/PALABRAS_VER_PANTALLA más abajo). "ayúdame a
# elegir" es la única que queda aparte (comparar_opciones, no tiene
# equivalente en control_agent).
PALABRAS_AYUDAME_ELEGIR = ("ayúdame a elegir", "ayudame a elegir")
# "qué es esto" colisiona con PALABRAS_CONOCIMIENTO ("qué es") — se
# revisa ANTES en _detectar_intencion a propósito, ver ahí.
PALABRAS_OBSERVADOR = ("ve esto", "qué es esto", "que es esto", "mírame", "mirame", "muestra cámara", "muestra camara")
PALABRAS_CLIPBOARD = (
    "qué copié", "que copie", "portapapeles", "historial copiado",
    "busca en lo que copié", "busca en lo que copie",
)
# "busca mi"/"busca archivo" colisionan con PALABRAS_WEB ("busca") —
# se revisan ANTES en _detectar_intencion a propósito, ver ahí.
PALABRAS_ARCHIVOS = (
    "organiza descargas", "organiza mis descargas", "organiza las descargas",
    "qué hay en mis descargas", "que hay en mis descargas",
    "busca mi", "busca archivo",
    # BUG4: "busca en mis archivos/documentos de X (y ábrelo)" — búsqueda
    # TOLERANTE a typos (ver file_organizer_agent.buscar_archivo_tolerante),
    # a propósito una frase distinta de "busca mi"/"busca archivo" de
    # arriba (esas son substring exacto, sin fallback difflib).
    "busca en mis archivos", "busca en mis documentos", "busca entre mis archivos",
)
# "busca la carpeta X (y ábrela)": va en el mismo lugar/prioridad que
# PALABRAS_ARCHIVOS (antes de que "carpeta" + PALABRAS_WEB caigan al
# intent genérico "control", que hoy resuelve esto con un find() vía
# Gemini en vez de la búsqueda determinística de file_organizer_agent).
PALABRAS_BUSCAR_CARPETA = ("busca la carpeta", "busca carpeta", "encuentra la carpeta", "busca el directorio")
PALABRAS_WHATSAPP = (
    "whatsapp", "escríbele a", "escribele a",
    "guarda el número de", "guarda el numero de", "guardar el número de", "guardar el numero de",
    "wasap", "guasap", "manda whatsapp a", "mandale whatsapp a",
)

# Botones VOZ/MIC del HUD (arriba del chat): son
# estado real en control_agent.py (no solo un evento efímero) para que
# se puedan prender/apagar desde CUALQUIER canal — incluido Telegram —
# y el HUD lo refleje via /control/estado-ui (ver server.py). MIC en
# particular solo tiene efecto si hay un HUD abierto en algún lado: el
# MediaRecorder real vive en el navegador, no en el servidor.
PALABRAS_VOZ_ACTIVAR = (
    "activa tu voz", "activa la voz", "prende tu voz", "prende la voz",
    "ya puedes hablar", "empieza a hablar", "quiero que hables",
)
PALABRAS_VOZ_DESACTIVAR = (
    "desactiva tu voz", "desactiva la voz", "apaga tu voz", "apaga la voz",
    "cállate", "callate", "deja de hablar", "no hables",
)
PALABRAS_MIC_ACTIVAR = (
    "activa el micrófono", "activa el microfono", "enciende el micrófono", "enciende el microfono",
    "préndeme el mic", "prendeme el mic", "activa mic", "activa tu micrófono", "activa tu microfono",
)
PALABRAS_MIC_DESACTIVAR = (
    "desactiva el micrófono", "desactiva el microfono", "apaga el micrófono", "apaga el microfono",
    "para el micrófono", "para el microfono", "desactiva mic", "apaga mic",
)
# Manual de usuario (ver manual.py) — respuesta enlatada, CERO tokens.
# Va ANTES que PALABRAS_CONOCIMIENTO porque si no, "qué puedes hacer"
# terminaría respondido por Gemini en vez del manual real.
PALABRAS_AYUDA = (
    "manual", "ayuda", "comandos", "qué puedes hacer", "que puedes hacer",
    "cómo te uso", "como te uso", "qué opciones tienes",
    "que opciones tienes", "menú de ayuda", "menu de ayuda",
    "qué sabes hacer", "que sabes hacer", "guía de uso", "guia de uso",
    "cómo funcionas", "como funcionas",
)

# --- Fase H2: control remoto por voz o texto (ver control_agent.py,
# xdotool/wmctrl/amixer/brightnessctl/xclip/ffmpeg) — CERO tokens salvo
# "ve mi pantalla" (screenshot_analizar). Todos estos grupos van ANTES
# que PALABRAS_CONTROL en _detectar_intencion (que tiene "cierra"/
# "cerrar"/"copia"/"borra" genéricos) para que le ganen a la ruta de
# "generar comando con Gemini" — mismo criterio que ya usa Classroom/
# Nexus/Finanzas/Pendientes en este archivo.

# Pestañas.
PALABRAS_PESTANA_SIGUIENTE = (
    "siguiente pestaña", "siguiente pestana", "cambia pestaña", "cambia pestana", "next tab",
    "otra pestaña", "otra pestana", "cambia de pestaña", "cambia de pestana",
)
PALABRAS_PESTANA_ANTERIOR = ("pestaña anterior", "pestana anterior", "anterior pestaña", "anterior pestana")
PALABRAS_PESTANA_CERRAR = ("cierra pestaña", "cierra pestana", "cierra tab", "cierra el tab")
PALABRAS_PESTANA_NUEVA = ("nueva pestaña", "nueva pestana", "abre una pestaña", "abre una pestana")
PALABRAS_PANTALLA_COMPLETA = ("pantalla completa", "fullscreen", "modo pantalla completa")

# Ventanas.
PALABRAS_VENTANA_SIGUIENTE = ("cambia de app", "siguiente ventana", "alt tab", "otra ventana", "cambia de ventana")
PALABRAS_VENTANA_ANTERIOR = ("ventana anterior", "anterior ventana")
PALABRAS_VENTANA_MINIMIZAR = ("minimiza", "quita eso")
PALABRAS_VENTANA_MAXIMIZAR = ("maximiza", "maximizar ventana", "agranda la ventana", "ponla en grande")
PALABRAS_VENTANA_CERRAR = ("cierra app", "cierra la app", "cierra ventana", "cierra la ventana")
PALABRAS_CERRAR_TODO = ("cierra todo", "cierra todas las ventanas", "apaga todo menos tú", "apaga todo menos tu")
PALABRAS_VENTANAS_LISTAR = (
    "qué tengo abierto", "que tengo abierto", "ventanas abiertas",
    "qué apps tengo abiertas", "que apps tengo abiertas",
    "muéstrame las ventanas", "muestrame las ventanas",
)

# Media.
PALABRAS_MEDIA_PLAY_PAUSE = ("pausa", "play", "resume", "pausar", "dale play", "reanuda")
PALABRAS_MEDIA_SIGUIENTE = ("siguiente canción", "siguiente cancion", "otra canción", "otra cancion")
PALABRAS_MEDIA_ANTERIOR = ("canción anterior", "cancion anterior")
PALABRAS_YOUTUBE_PON = ("en youtube",)  # "pon X en youtube" / "busca X en youtube"

# Audio y pantalla.
PALABRAS_SILENCIA = ("silencia", "mutea", "mute", "quítale el sonido", "quitale el sonido", "sin sonido")
PALABRAS_VOLUMEN_SUBIR = ("sube el volumen", "sube volumen", "más volumen", "mas volumen", "súbele", "subele", "sube el sonido")
PALABRAS_VOLUMEN_BAJAR = ("baja el volumen", "baja volumen", "menos volumen", "bájale", "bajale", "baja el sonido")
PALABRAS_BRILLO_SUBIR = ("sube el brillo", "sube brillo")
PALABRAS_BRILLO_BAJAR = ("baja el brillo", "baja brillo")
PALABRAS_APAGA_PANTALLA = ("apaga pantalla", "apaga la pantalla")
PALABRAS_PRENDE_PANTALLA = ("prende pantalla", "prende la pantalla", "enciende pantalla", "enciende la pantalla")

# Escritura — "copia"/"pega"/"guarda"/"deshacer" son atajos de teclado
# SOLO si el mensaje no menciona un archivo/carpeta (si lo menciona,
# gana la operación de archivo de PALABRAS_CONTROL, ver _PISTAS_ARCHIVO
# más abajo y _detectar_intencion).
PALABRAS_ENTER = ("dale enter", "manda enter", "presiona enter", "enter")
PALABRAS_BORRA_ESO = ("borra eso",)
PALABRAS_SELECCIONA_TODO = ("selecciona todo", "seleccionar todo")
PALABRAS_COPIA_TECLADO = ("copia", "copiar")
PALABRAS_PEGA_TECLADO = ("pega", "pegar")
PALABRAS_GUARDA_TECLADO = ("guarda", "guardar")
PALABRAS_DESHACER = ("deshacer", "deshace")
PALABRAS_DICTAR = ("dicta", "dictar")
PALABRAS_ESCRIBIR = ("escribe",)  # genérico, se revisa AL FINAL de este grupo

# Mouse — "click derecho" antes que "click" (más específico primero,
# mismo criterio que _quitar_palabra_clave ya usa en todo el archivo).
PALABRAS_CLICK_DERECHO = ("click derecho", "clic derecho", "click secundario")
PALABRAS_DOBLE_CLICK = ("doble click", "doble clic")
PALABRAS_CLICK = ("dale click", "haz click", "click", "clic", "clickea", "dale clic")
PALABRAS_SCROLL_ARRIBA = ("scroll arriba", "sube")  # "sube" bare: DESPUÉS de sube volumen/brillo
PALABRAS_SCROLL_ABAJO = ("scroll abajo", "baja")    # "baja" bare: DESPUÉS de baja volumen/brillo

# Sistema.
PALABRAS_ESTADO = (
    "cómo estás", "como estas", "estado del sistema", "tu estado",
    "qué tal vas", "que tal vas", "cómo va todo", "como va todo", "reporte del sistema",
)
PALABRAS_DESCANSA = ("descansa", "reposo", "ponte a dormir", "modo reposo", "vete a dormir", "suspéndete", "suspendete")
PALABRAS_APAGA_SISTEMA = ("apágate", "apagate", "shutdown", "apaga el equipo", "apaga la compu", "apaga la máquina", "apaga la maquina")
PALABRAS_BLOQUEATE = ("bloquéate", "bloqueate", "lock", "activa el bloqueo")

# Archivos y captura — "screenshot"/"captura" son CERO tokens (solo
# capturan); solo "ve mi pantalla" analiza con Gemini Vision (gasta
# tokens) — a propósito distinto de cómo funcionaba antes (ver
# PALABRAS_SCREENSHOT/_procesar_screenshot, que este grupo reemplaza).
# "foto" sola (sin "toma(me)") queda afuera a propósito: colisiona con
# cualquier mención de un archivo tipo "foto.png" (ej. "abre /home/
# mauri/foto.png" terminaba disparando esto en vez de "abrir").
PALABRAS_FOTO = ("tómame una foto", "tomame una foto", "toma una foto")
PALABRAS_CAPTURA = ("screenshot", "captura de pantalla", "captura pantalla", "captura", "hazme una captura", "toma una captura")
PALABRAS_VER_PANTALLA = ("ve mi pantalla", "qué hay en mi pantalla", "que hay en mi pantalla", "checa mi pantalla", "revisa mi pantalla")
PALABRAS_GRABA_PANTALLA = ("graba pantalla", "graba la pantalla", "empieza a grabar", "inicia grabación", "inicia grabacion", "comienza a grabar")
PALABRAS_PARA_GRABAR = ("para de grabar", "detén la grabación", "deten la grabacion", "para la grabación", "para la grabacion", "termina la grabación", "termina la grabacion")
PALABRAS_LEE_ARCHIVO = ("lee el archivo", "lee este archivo", "lee ese archivo", "léeme", "leeme", "muéstrame el contenido de", "muestrame el contenido de")
PALABRAS_DONDE_QUEDO = ("dónde quedó", "donde quedo", "dónde está mi archivo", "donde esta mi archivo", "en dónde está", "en donde esta", "dónde guardé", "donde guarde")

# Figuras/diagramas generados por código (figura_agent.py, matplotlib):
# deliberadamente frases EXPLÍCITAS y no un "quiero ver X" pelón, que
# chocaría con conversación normal. Gasta tokens (le pide a Gemini que
# escriba el código) — a diferencia del resto de este archivo.
PALABRAS_FIGURA = (
    "dibújame", "dibuja", "grafica", "gráfica de", "diagrama de flujo",
    "hazme un diagrama", "hazme una figura", "quiero ver la figura de",
    "quiero ver un diagrama de", "muéstrame la figura de", "muéstrame un diagrama de",
    "hazme una animación", "hazme una animacion", "anímame", "animame",
)

# Corrección de la ÚLTIMA figura (ver figura_agent.corregir_figura):
# a diferencia de PALABRAS_FIGURA (que siempre arranca una figura NUEVA
# desde cero), estas frases piden un ajuste puntual sobre lo que ya se
# dibujó — antes esto no existía y "corrígelo" caía a generar_figura()
# a ciegas (sin saber qué se había dibujado), lo que a veces cambiaba
# un problema por otro (ej. "salía al revés" -> se corregía, pero el
# resultado "no cabía"). Frases explícitas, mismo criterio que arriba.
PALABRAS_CORREGIR_FIGURA = (
    "corrígelo", "corrigelo", "corrígela", "corrigela",
    "corrige la figura", "corrige el dibujo", "corrige eso", "corrige la gráfica", "corrige la grafica",
    "está al revés", "esta al reves", "salió al revés", "salio al reves",
    "está volteado", "esta volteado", "está volteada", "esta volteada",
    "está invertido", "esta invertido", "está invertida", "esta invertida",
    "arréglalo", "arreglalo", "arréglala", "arreglala", "arregla la figura", "arregla el dibujo",
    "no quedó bien", "no quedo bien", "no cupo", "no cabe", "no cabía", "no cabia",
    "se corta", "está cortado", "esta cortado", "está cortada", "esta cortada",
)

# Programación bajo demanda (code_agent.py): Gemini ESCRIBE un programa
# nuevo desde cero (no solo dibuja con matplotlib, ver PALABRAS_FIGURA
# arriba) y lo prueba corriéndolo de verdad. Frases EXPLÍCITAS a
# propósito (igual que PALABRAS_FIGURA) para no chocar con
# conversación normal, y sobre todo para ganarle a PALABRAS_CONTROL:
# "créame/hazme/programa/crea un script/una app" sin acento en la "e"
# ("creame", "cream un programa") empieza igual que "crea"/"crear", así
# que este grupo se revisa ANTES que PALABRAS_CONTROL en
# _detectar_intencion (ver ahí). Gasta tokens (potencialmente varias
# veces si el código falla y hay que corregirlo, ver code_agent.py).
#
# Las últimas frases (modelo/escena/three.js) son para pedidos de
# objetos 3D interactivos que no dicen "programa"/"script"/"app" (ej.
# "créame un corazón 3D que gire con Three.js") — sin esto, ese tipo de
# pedido no matchea nada y se pierde antes de llegar a code_agent.py,
# que desde que soporta HTML/Three.js (ver code_agent._tipo_peticion)
# sabe generar y verificar visualmente ese caso.
PALABRAS_PROGRAMAR = (
    "créame un programa", "creame un programa", "hazme un programa",
    "hazme un sistema", "créame un sistema", "creame un sistema",
    "programa algo que", "prográmame algo", "programame algo",
    "crea un script", "hazme un script", "escríbeme un programa",
    "escribeme un programa", "necesito un programa que", "quiero un programa que",
    "hazme una app que", "créame una app", "creame una app",
    "crea una aplicación que", "crea una aplicacion que",
    "créame un modelo 3d", "creame un modelo 3d", "hazme un modelo 3d",
    "créame una escena 3d", "creame una escena 3d", "hazme una escena 3d",
    "con three.js", "con threejs",
)

# Proyectos MULTI-ARCHIVO (code_proyectos.py): a diferencia de
# PALABRAS_PROGRAMAR (que genera UN archivo suelto en experimentos/),
# esto genera varios archivos conectados en proyectos/{nombre}/ (ver
# code_proyectos.crear_proyecto_completo). Deliberadamente SIN
# "proyecto"/"proyectos" a secas — esas palabras ya disparan la
# intención "proyectos" (proyectos_agent.py, el tracker de Notion de
# proyectos escolares/personales, un dominio completamente distinto,
# sin relación con archivos de código) — usar frases explícitas evita
# esa colisión real. Se revisa ANTES que PALABRAS_PROGRAMAR en
# _detectar_intencion: "créame una app web" también matchea "créame
# una app" (que por sí sola cae a archivo suelto), y el multi-archivo
# debe ganar cuando la frase es más específica.
PALABRAS_PROYECTO_COMPLETO = (
    "créame un proyecto de código", "creame un proyecto de código", "creame un proyecto de codigo",
    "hazme un proyecto de código", "hazme un proyecto de codigo",
    "créame un proyecto de programación", "creame un proyecto de programacion",
    "hazme un proyecto de programación", "hazme un proyecto de programacion",
    "créame una app web", "creame una app web", "hazme una app web",
    "crea una aplicación web", "crea una aplicacion web",
    "créame un sitio web", "creame un sitio web", "hazme un sitio web", "crea un sitio web",
    "créame una página web", "creame una pagina web", "hazme una página web", "hazme una pagina web",
    "crea una página web", "crea una pagina web",
    "crea un juego de", "hazme un juego de", "créame un juego", "creame un juego",
)

# Obsidian (ver obsidian_agent.py): EXCLUSIVO para notas de ESTUDIO
# (resúmenes de temas académicos conectados entre sí) — NUNCA pendientes/
# tareas/finanzas/documentos generales, eso ya vive en Notion (ver
# PALABRAS_PENDIENTES/PALABRAS_PROYECTOS/PALABRAS_FINANZAS/PALABRAS_NOTION).
# Va ANTES que PALABRAS_CONTROL: "crea nota de estudio de X"/"haz una
# nota de X" empiezan con "crea"/"haz" y colisionarían con la intención
# genérica "control" (crear archivo vía Gemini) si se revisara después
# — mismo criterio que PALABRAS_PROGRAMAR/PALABRAS_PROYECTO_COMPLETO.
PALABRAS_OBSIDIAN_CREAR = (
    "guarda esto en obsidian", "guarda en obsidian", "guárdalo en obsidian", "guardalo en obsidian",
    "crea nota de estudio de", "crea una nota de estudio de",
    "crea nota de estudio sobre", "crea una nota de estudio sobre",
    "apunta en obsidian", "apunta esto en obsidian",
    "haz una nota de", "haz una nota sobre", "hazme una nota de", "hazme una nota sobre",
)
# Respaldo para cuando "obsidian" aparece en medio de la frase, en un
# punto que ninguna de las frases literales de arriba cubre (ej. "crea
# una nota de estudio EN OBSIDIAN sobre la fotosíntesis") — si el
# mensaje menciona "obsidian" en cualquier posición junto con un verbo
# de creación, también cuenta como "obsidian_crear" (ver
# _detectar_intencion/_extraer_tema_obsidian).
_VERBOS_OBSIDIAN_CREAR = ("crea", "creame", "créame", "haz", "hazme", "apunta", "guarda", "anota")
# "abre obsidian" va ANTES que PALABRAS_ABRIR genérico: control_agent.
# abrir_app busca .desktop en ~/.local/share/applications y /usr/share/
# applications, pero Obsidian (Flatpak) deja el suyo en
# /var/lib/flatpak/exports/share/applications, que esas carpetas NO
# cubren — sin esto, "abre obsidian" caía silenciosamente a "no
# encontré ni pude abrir 'obsidian'" (ver obsidian_agent.abrir_obsidian,
# que sí sabe usar "flatpak run" como respaldo).
PALABRAS_OBSIDIAN_ABRIR = ("abre obsidian", "abrir obsidian", "ábreme obsidian", "abreme obsidian")

# Exámenes de opción múltiple (ver examen_agent.py, active recall).
# Un solo intent "examen" — _procesar_examen distingue internamente
# entre PDF/apuntes de una materia/tema libre según pistas en el
# mensaje (ver _PALABRAS_EXAMEN_PDF/_PALABRAS_EXAMEN_APUNTES), mismo
# criterio que _procesar_investigacion/_procesar_correo/_procesar_
# classroom hacen sub-branching adentro de un solo handler.
PALABRAS_EXAMEN = (
    "hazme un examen", "hazme una prueba", "hazme un quiz",
    "examen de", "examen sobre", "prueba de", "prueba sobre", "quiz de", "quiz sobre",
)
_PALABRAS_EXAMEN_PDF_PISTA = ("pdf", "documento", "lectura", "archivo")
_PALABRAS_EXAMEN_APUNTES_PISTA = ("mis apuntes", "mis notas", "apuntes de", "notas de")

# Spotify (solo lectura, ver spotify_agent.py): frases explícitas, NO
# "spotify" a secas — así "abre/pon/cierra spotify" (ya funcionan, ver
# _SITIOS_PARA_PON/PALABRAS_CONTROL) no se ven afectados. CERO tokens
# (puro API de Spotify, sin pasar por Gemini).
PALABRAS_SPOTIFY = (
    "configura spotify", "conecta spotify", "qué estoy escuchando",
    "que estoy escuchando", "qué canción es esta", "que cancion es esta",
    "qué escucho", "que escucho", "últimas canciones en spotify",
    "ultimas canciones en spotify", "mi historial de spotify",
)

# "ábrela"/"ábrelo" SUELTAS (sin nombre): se refieren a la última carpeta
# que buscar_carpeta() encontró (ver _ultima_carpeta/_procesar_abrir_
# ultima_carpeta). Van ANTES que PALABRAS_ABRIR genérico en
# _detectar_intencion porque "abrela" (sin acento) ya empieza con "abre"
# y hoy caería a _procesar_abrir() intentando abrir una app llamada "la".
PALABRAS_ABRIR_ULTIMA_CARPETA = ("ábrela", "abrela", "ábrelo", "abrelo")

# Mismo criterio que arriba pero para "lo último que IRIS creó"
# (código de code_agent, o cualquier archivo/carpeta creado vía
# control_agent — ver context_engine.ultimo_archivo_creado): "ábrelo"
# sin nombre debe resolver esto ANTES que preguntar, y frases explícitas
# como "abre el archivo que creaste" también. _procesar_abrir_ultimo
# prioriza el archivo creado sobre _ultima_carpeta cuando hay ambos.
PALABRAS_ABRIR_ULTIMO = PALABRAS_ABRIR_ULTIMA_CARPETA + (
    "abre ese archivo", "abre el archivo", "abre el archivo que creaste",
    "abre el archivo que hiciste", "abre ese código", "abre ese codigo",
)

# Apps y web.
PALABRAS_ABRIR = ("abre", "abrí", "abrir", "ábreme")
# "pon X" solo cuenta como "abrir sitio" si X es un sitio conocido —
# de otro modo "pon" es demasiado genérico (ej. "pon un pendiente").
_SITIOS_PARA_PON = ("netflix", "spotify", "gmail", "github", "drive", "notion", "youtube", "instagram")

# "abre el repositorio" / "abre el repo": abre el repo del proyecto en
# GitHub (control_agent.abrir_repositorio, lee el remote real de git). Va
# ANTES que PALABRAS_ABRIR en _detectar_intencion porque contiene "abre" y
# si no caería a _procesar_abrir intentando abrir una app llamada
# "el repositorio". "repo"/"repositorio" a secas NO están para no pisar
# menciones casuales de la palabra.
PALABRAS_REPOSITORIO = (
    "abre el repositorio", "abre mi repositorio", "abrir repositorio", "abre repositorio",
    "abre el repo", "abre mi repo", "abrir repo", "abre repo", "ábreme el repositorio",
    "abre el repositorio en github", "abre el proyecto en github", "abre github del proyecto",
)

# "abre el proyecto X": abre la carpeta proyectos/X (control_agent.
# abrir_proyecto). Va ANTES que PALABRAS_PROYECTOS (tracker Notion) en
# _detectar_intencion porque "proyecto" también dispara ese dominio, y
# antes que PALABRAS_ABRIR genérico porque "proyecto" no es una app.
PALABRAS_ABRIR_PROYECTO = (
    "abre el proyecto", "abre mi proyecto", "abre proyecto", "abrir proyecto",
    "ábreme el proyecto", "abreme el proyecto", "abre la carpeta del proyecto",
)

# Preguntas de ESTADÍSTICAS sobre proyectos/cerebro_archivos ("cuántos
# archivos tengo en total/en Descargas"). Van DESPUÉS de PALABRAS_ABRIR
# en _detectar_intencion a propósito: "abrí el cerebro de archivos"
# también contiene "cerebro de archivos" pero debe abrir la app (ganar
# como intent "abrir"), no contestar una estadística — solo cae acá
# cuando NO hay un verbo de apertura en el mensaje.
PALABRAS_CEREBRO_ARCHIVOS = ("cerebro de archivos", "cerebro de mis archivos")

# Grupo combinado solo para _detectar_intencion/_es_compuesto.
PALABRAS_CONTROL_REMOTO = (
    PALABRAS_PESTANA_SIGUIENTE + PALABRAS_PESTANA_ANTERIOR + PALABRAS_PESTANA_CERRAR
    + PALABRAS_PESTANA_NUEVA + PALABRAS_PANTALLA_COMPLETA
    + PALABRAS_VENTANA_SIGUIENTE + PALABRAS_VENTANA_ANTERIOR + PALABRAS_VENTANA_MINIMIZAR
    + PALABRAS_VENTANA_MAXIMIZAR + PALABRAS_VENTANA_CERRAR + PALABRAS_CERRAR_TODO
    + PALABRAS_VENTANAS_LISTAR
    + PALABRAS_MEDIA_PLAY_PAUSE + PALABRAS_MEDIA_SIGUIENTE + PALABRAS_MEDIA_ANTERIOR + PALABRAS_YOUTUBE_PON
    + PALABRAS_SILENCIA + PALABRAS_VOLUMEN_SUBIR + PALABRAS_VOLUMEN_BAJAR
    + PALABRAS_BRILLO_SUBIR + PALABRAS_BRILLO_BAJAR + PALABRAS_APAGA_PANTALLA + PALABRAS_PRENDE_PANTALLA
    + PALABRAS_ENTER + PALABRAS_BORRA_ESO + PALABRAS_SELECCIONA_TODO + PALABRAS_COPIA_TECLADO
    + PALABRAS_PEGA_TECLADO + PALABRAS_GUARDA_TECLADO + PALABRAS_DESHACER + PALABRAS_DICTAR + PALABRAS_ESCRIBIR
    + PALABRAS_CLICK_DERECHO + PALABRAS_DOBLE_CLICK + PALABRAS_CLICK + PALABRAS_SCROLL_ARRIBA + PALABRAS_SCROLL_ABAJO
    + PALABRAS_ESTADO + PALABRAS_DESCANSA + PALABRAS_APAGA_SISTEMA + PALABRAS_BLOQUEATE
    + PALABRAS_FOTO + PALABRAS_CAPTURA + PALABRAS_VER_PANTALLA + PALABRAS_GRABA_PANTALLA + PALABRAS_PARA_GRABAR
    + PALABRAS_LEE_ARCHIVO + PALABRAS_DONDE_QUEDO
)

# "copia"/"pega"/"guarda"/"deshacer"/"borra eso" son atajos de teclado
# AMBIGUOS con operaciones de archivo reales ("copia el archivo X a Y",
# que sigue yendo al respaldo de Gemini vía PALABRAS_CONTROL) — se
# revisan por separado en _detectar_intencion, cediendo si el mensaje
# menciona archivo/carpeta (ver _PISTAS_ARCHIVO).
_ATAJOS_TECLADO_CON_RIESGO_ARCHIVO = (
    PALABRAS_COPIA_TECLADO + PALABRAS_PEGA_TECLADO + PALABRAS_GUARDA_TECLADO
    + PALABRAS_DESHACER + PALABRAS_BORRA_ESO
)
_CONTROL_REMOTO_SIN_ATAJOS = tuple(
    p for p in PALABRAS_CONTROL_REMOTO if p not in _ATAJOS_TECLADO_CON_RIESGO_ARCHIVO
)

# --- Fase I: autonomía para peticiones compuestas ("investiga X y
# guárdalo en Notion", "recuérdame llamar al doctor y agenda la cita
# el viernes"). PALABRAS_NOTION no es un intent real — solo existe
# para que "guárdalo en Notion" cuente como un segundo grupo distinto
# junto con "investiga", ver _es_compuesto.
PALABRAS_NOTION = (
    "notion", "guárdalo", "guardalo", "súbelo", "subelo",
    "mándalo", "mandalo", "mándamelo", "mandamelo", "apúntalo", "apuntalo",
)
# Grupos "independientemente accionables" para el conteo de
# _es_compuesto. Deliberadamente NO incluye conocimiento/web/chat
# (demasiado genéricos, dispararían falsos positivos en frases
# normales) ni PALABRAS_PDF/VIDEO/RESUMIR_PDF (esos ya tienen su
# propio flujo nativo de oferta a Notion, ver _procesar_investigacion).
_GRUPOS_COMPUESTO = (
    PALABRAS_CONTROL, PALABRAS_RECORDATORIO, PALABRAS_CALENDARIO, PALABRAS_CORREO,
    PALABRAS_CLASSROOM, PALABRAS_NEXUS, PALABRAS_FINANZAS, PALABRAS_PENDIENTES,
    PALABRAS_BRIEFING, PALABRAS_CLIPBOARD, PALABRAS_ARCHIVOS, PALABRAS_WHATSAPP,
    PALABRAS_CONTROL_REMOTO, PALABRAS_ABRIR,
)

# Intents "de acción concreta" que vale la pena registrar como migaja de
# patrón semanal (ver _rutear_por_intencion y proactividad_agent._revisar_patrones).
# Excluye chat/conocimiento/web/compuesto — demasiado genéricos/frecuentes
# como para significar un hábito real.
_INTENTS_PATRON = (
    "control", "recordatorio", "calendario", "correo", "classroom", "nexus",
    "finanzas", "pendientes", "briefing", "clipboard", "archivos", "whatsapp",
    "investigacion", "control_remoto", "abrir",
)

_PROMPT_GROQ_NOTION = """Genera un ensayo/resumen completo y detallado sobre: {tema}.
Incluye: introducción, datos importantes, contexto histórico si aplica,
y conclusión. En español, estilo académico pero entendible. Mínimo 500 palabras."""

_SYSTEM_PROMPT_GROQ_NOTION = (
    "Formatea tu respuesta en texto plano compatible con bloques de Notion: "
    "usa '## ' al inicio de cada encabezado de sección y '- ' al inicio de cada "
    "viñeta de lista. No uses negritas, cursivas, tablas ni ningún otro markdown."
)


def _detectar_intencion(texto):
    texto_bajo = texto.lower()
    # Fase F PRIMERO que todo lo demás (incluido classroom): "busca mi
    # tarea de historia" (archivos, busca un ARCHIVO) y "busca en lo
    # que copié algo de tarea" (clipboard) contienen la palabra "tarea"
    # y colisionarían con classroom si se revisaran después — el
    # prefijo "busca mi"/"busca archivo"/"busca en lo que copié" es
    # más específico y debe ganar. "qué es esto" (observador) también
    # colisiona con CONOCIMIENTO ("qué es") más abajo.
    if any(p in texto_bajo for p in PALABRAS_AYUDAME_ELEGIR):
        return "elegir"
    # AYUDA va antes que OBSERVADOR/CLIPBOARD/ARCHIVOS/WHATSAPP:
    # "manual de whatsapp" o "ayuda con archivos" contienen "whatsapp"/
    # "archivo" y esas ganarían si se revisaran primero, mandando al
    # jefe a abrir la app en vez de explicarle el comando.
    if any(p in texto_bajo for p in PALABRAS_AYUDA):
        return "ayuda"
    if any(p in texto_bajo for p in PALABRAS_OBSERVADOR):
        return "observador"
    if any(p in texto_bajo for p in PALABRAS_CLIPBOARD):
        return "clipboard"
    if any(p in texto_bajo for p in PALABRAS_ARCHIVOS):
        return "archivos"
    if any(p in texto_bajo for p in PALABRAS_BUSCAR_CARPETA):
        return "buscar_carpeta"
    if any(p in texto_bajo for p in PALABRAS_WHATSAPP):
        return "whatsapp"
    if any(p in texto_bajo for p in PALABRAS_VOZ_ACTIVAR + PALABRAS_VOZ_DESACTIVAR):
        return "voz"
    if any(p in texto_bajo for p in PALABRAS_MIC_ACTIVAR + PALABRAS_MIC_DESACTIVAR):
        return "mic"
    # Control remoto (Fase H2) va ANTES que PALABRAS_CONTROL: "cierra
    # pestaña"/"cierra app"/"cierra ventana" matchean "cierra" (control
    # genérico, que le pediría a Gemini el comando) y deben ganarle para
    # ir directo a xdotool/wmctrl/amixer/etc, CERO tokens. Se excluye a
    # propósito si también matchea PALABRAS_RESUMIR_PDF/RESUMIR_VIDEO:
    # "resume" (de PALABRAS_MEDIA_PLAY_PAUSE) es substring de "resume el
    # pdf/documento/video", y ese pedido debe ganar research_agent, no
    # play/pause. También se excluye cualquier mensaje con "resumen"
    # (con ene): "resume" ES substring de "resumen", así que "resumen
    # financiero"/"resumen del día" quedaban atrapados aquí en vez de
    # llegar a finanzas/briefing más abajo — bug real que ya existía
    # antes de agregar variantes.
    if (
        any(p in texto_bajo for p in _CONTROL_REMOTO_SIN_ATAJOS)
        and not any(p in texto_bajo for p in PALABRAS_RESUMIR_PDF + PALABRAS_RESUMIR_VIDEO)
        and "resumen" not in texto_bajo
    ):
        return "control_remoto"
    # Figuras/diagramas: va DESPUÉS de control_remoto a propósito, para
    # que "muéstrame las ventanas"/"ve mi pantalla" (más específicas,
    # cero tokens) sigan ganando sobre esto. La corrección ("corrígelo",
    # "está al revés") se revisa junto porque ambas ruteán al mismo
    # intent "figura" — _procesar_figura decide cuál de las dos es.
    if any(p in texto_bajo for p in PALABRAS_FIGURA + PALABRAS_CORREGIR_FIGURA):
        return "figura"
    # Proyecto completo (code_proyectos) va ANTES que PALABRAS_PROGRAMAR:
    # "créame una app web" también matchea "créame una app" (archivo
    # suelto) y la frase más específica de multi-archivo debe ganar —
    # ver comentario de PALABRAS_PROYECTO_COMPLETO más arriba.
    if any(p in texto_bajo for p in PALABRAS_PROYECTO_COMPLETO):
        return "proyecto_completo"
    # Programar (code_agent) va ANTES que PALABRAS_CONTROL: "creame un
    # programa que..."/"crea un script para..." empiezan con "crea",
    # que también matchea PALABRAS_CONTROL (crear archivo genérico vía
    # Gemini) y ese NO debe ganar aquí — ver comentario de
    # PALABRAS_PROGRAMAR más arriba.
    if any(p in texto_bajo for p in PALABRAS_PROGRAMAR):
        return "programar"
    # Obsidian: "abre obsidian" va antes que "crear nota" — comparten
    # este bloque solo para quedar juntos en el archivo, no hay colisión
    # real entre las dos frases.
    if any(p in texto_bajo for p in PALABRAS_OBSIDIAN_ABRIR):
        return "obsidian_abrir"
    if any(p in texto_bajo for p in PALABRAS_OBSIDIAN_CREAR) or (
        "obsidian" in texto_bajo and any(v in texto_bajo for v in _VERBOS_OBSIDIAN_CREAR)
    ):
        return "obsidian_crear"
    if any(p in texto_bajo for p in PALABRAS_SPOTIFY):
        return "spotify"
    if any(p in texto_bajo for p in PALABRAS_EXAMEN):
        return "examen"
    # Atajos de teclado (copia/pega/guarda/deshacer/borra eso) SOLO si
    # el mensaje no menciona un archivo/carpeta — si lo menciona, gana
    # la operación de archivo real (PALABRAS_CONTROL, respaldo de Gemini).
    if any(p in texto_bajo for p in _ATAJOS_TECLADO_CON_RIESGO_ARCHIVO) and not any(p in texto_bajo for p in _PISTAS_ARCHIVO):
        return "control_remoto"
    # Classroom/Nexus van ANTES que PALABRAS_CONTROL/PALABRAS_ABRIR:
    # "abre nexus" matchea "abre" y "tarea"/"tareas" podría en teoría
    # confundirse con algo de control, pero en la práctica ninguna
    # palabra de control usa esos términos — se prioriza que el
    # dominio específico (escuela) le gane a la genérica.
    if any(p in texto_bajo for p in PALABRAS_CLASSROOM):
        return "classroom"
    if any(p in texto_bajo for p in PALABRAS_NEXUS):
        return "nexus"
    # Igual que classroom/nexus: van antes que PALABRAS_CONTROL porque
    # "elimina pendiente" matchea "elimina" (control) y "agregar
    # pendiente" podría en teoría sonar a "crear" (control).
    if any(p in texto_bajo for p in PALABRAS_FINANZAS):
        return "finanzas"
    if any(p in texto_bajo for p in PALABRAS_PENDIENTES):
        return "pendientes"
    # "abre el repositorio" y "abre el proyecto X" van ANTES que
    # PALABRAS_PROYECTOS (tracker Notion, que tiene "proyecto") y que
    # PALABRAS_ABRIR genérico. Repositorio primero: su variante "abre el
    # proyecto en github" contiene "abre el proyecto" y no debe caer en
    # abrir_proyecto.
    if any(p in texto_bajo for p in PALABRAS_REPOSITORIO):
        return "repositorio"
    if any(p in texto_bajo for p in PALABRAS_ABRIR_PROYECTO):
        return "abrir_proyecto"
    if any(p in texto_bajo for p in PALABRAS_PROYECTOS):
        return "proyectos"
    # "ábrelo"/"abre ese archivo"/"abre el archivo que creaste" van ANTES
    # que PALABRAS_CONTROL: "creaste" contiene "crea" como substring y
    # colisionaría con la intención "control" (crear archivo genérico vía
    # Gemini) — la referencia a lo último creado/buscado debe ganar.
    # También va antes que PALABRAS_ABRIR genérico — "abrela" sin acento
    # ya empieza con "abre" y si no, caería a _procesar_abrir() tratando
    # de abrir una app llamada "la".
    if any(p in texto_bajo for p in PALABRAS_ABRIR_ULTIMO):
        return "abrir_ultimo"
    if any(p in texto_bajo for p in PALABRAS_CONTROL):
        return "control"
    # "abre X" (app/url/archivo, determinístico) y "pon X" solo si X es
    # un sitio conocido (ver _SITIOS_PARA_PON — "pon" solo es demasiado
    # genérico, ej. "pon un pendiente").
    if any(p in texto_bajo for p in PALABRAS_ABRIR):
        return "abrir"
    if "pon" in texto_bajo and any(s in texto_bajo for s in _SITIOS_PARA_PON):
        return "abrir"
    if any(p in texto_bajo for p in PALABRAS_CEREBRO_ARCHIVOS):
        return "cerebro_archivos"
    if any(p in texto_bajo for p in PALABRAS_RECORDATORIO):
        return "recordatorio"
    if any(p in texto_bajo for p in PALABRAS_CALENDARIO):
        return "calendario"
    if any(p in texto_bajo for p in PALABRAS_CORREO):
        return "correo"
    if any(p in texto_bajo for p in PALABRAS_BRIEFING):
        return "briefing"
    if any(p in texto_bajo for p in PALABRAS_CONOCIMIENTO):
        return "conocimiento"
    if "investiga" in texto_bajo or any(p in texto_bajo for p in PALABRAS_RESUMIR_PDF + PALABRAS_RESUMIR_VIDEO):
        return "investigacion"
    if any(p in texto_bajo for p in PALABRAS_WEB) and any(p in texto_bajo for p in PALABRAS_PDF + PALABRAS_VIDEO):
        return "investigacion"
    if any(p in texto_bajo for p in PALABRAS_WEB):
        if any(p in texto_bajo for p in _PISTAS_ARCHIVO):
            return "control"
        return "web"
    return "chat"


def _es_compuesto(texto):
    """True si el mensaje toca >=2 grupos DISTINTOS de _GRUPOS_COMPUESTO
    (o el caso especial "investiga"/Notion) — señal de que junta varias
    peticiones independientes en una sola frase. Heurística deliberadamente
    imprecisa: los falsos positivos degradan a un solo paso (ver
    _procesar_compuesto), nunca rompen nada."""
    texto_bajo = texto.lower()
    grupos = sum(1 for grupo in _GRUPOS_COMPUESTO if any(p in texto_bajo for p in grupo))
    if "investiga" in texto_bajo:
        grupos += 1
    if any(p in texto_bajo for p in PALABRAS_NOTION):
        grupos += 1
    return grupos >= 2


def _es_afirmacion(texto):
    """True si `texto` es una respuesta corta afirmativa (sí/dale/va/...).
    Compara por token exacto, no substring, para evitar falsos positivos
    (ej. "va" no debe matchear dentro de "nova")."""
    texto_bajo = texto.strip().lower()
    for signo in "¡!¿?.,;:":
        texto_bajo = texto_bajo.replace(signo, "")
    if "por favor" in texto_bajo:
        return True
    return any(token in _PALABRAS_AFIRMATIVAS for token in texto_bajo.split())


def _quitar_palabra_clave(texto, palabras):
    """Quita la primera palabra clave encontrada y devuelve el resto
    del mensaje (lo que el usuario quiso decir después de ella)."""
    texto_bajo = texto.lower()
    # Ordenadas de más larga a más corta para no cortar a medias
    # (ej. que "ejecuta el comando" no lo corte "ejecuta" dejando "el comando").
    for palabra in sorted(palabras, key=len, reverse=True):
        idx = texto_bajo.find(palabra)
        if idx != -1:
            return texto[idx + len(palabra):].strip(" :,.-")
    return texto.strip()


def _ejecutar_accion_pendiente():
    """_accion_pendiente puede venir de dos orígenes distintos (control
    del sistema o envío de correo) — cada uno con su propia forma de
    ejecutarse una vez confirmado. Ver _procesar_control/_procesar_correo,
    que son quienes la llenan con {"origen": ..., "datos": ...}."""
    global _accion_pendiente
    pendiente = _accion_pendiente
    _accion_pendiente = None

    if pendiente["origen"] == "system_control":
        datos = pendiente["datos"]
        mensaje = control_agent.ejecutar_accion_confirmada(datos)
        archivo_descargado = control_agent.extraer_archivo_descargado(datos)
        if archivo_descargado:
            context_engine.set_ultimo_archivo_descargado(archivo_descargado)
        else:
            archivo = control_agent.extraer_archivo_creado(datos)
            if archivo:
                context_engine.set_ultimo_archivo_creado(archivo)
        return mensaje

    if pendiente["origen"] == "correo":
        datos = pendiente["datos"]
        resultado = email_agent.enviar_correo(datos["destinatario"], datos["asunto"], datos["cuerpo"])
        if resultado.get("error"):
            return f"No se pudo enviar el correo: {resultado['error']}"
        return f"Correo enviado a {datos['destinatario']}."

    if pendiente["origen"] == "cerrar_ventana":
        return control_agent.cerrar_ventana()

    if pendiente["origen"] == "cerrar_todo":
        return control_agent.cerrar_todo_menos_servidor()

    if pendiente["origen"] == "eliminar_pendiente":
        datos = pendiente["datos"]
        resultado = pendientes_agent.eliminar_pendiente(datos["id"])
        if resultado.get("error"):
            return f"No se pudo eliminar el pendiente: {resultado['error']}"
        # El título real ya se conocía desde que se armó la confirmación
        # (ver _procesar_pendientes) — no usar resultado["titulo"], que
        # cuando se le pasa un id de Notion directo es solo un eco del
        # id (resolver_pendiente no puede saber el título real solo del id).
        return f"Listo, eliminé '{datos['titulo']}'."

    if pendiente["origen"] == "eliminar_proyecto":
        datos = pendiente["datos"]
        resultado = proyectos_agent.eliminar_proyecto(datos["id"])
        if resultado.get("error"):
            return f"No se pudo eliminar el proyecto: {resultado['error']}"
        return f"Listo, eliminé el proyecto '{datos['titulo']}'."

    if pendiente["origen"] == "instalar_dependencia":
        resultado = code_agent.confirmar_instalacion(pendiente["datos"])
        # Puede volver a traer OTRA dependencia faltante encima (ej. el
        # código necesitaba dos librerías nuevas) — arma otro wizard de
        # CONFIRMAR en vez de darlo por perdido.
        if resultado.get("pendiente_instalacion"):
            _accion_pendiente = {"origen": "instalar_dependencia", "datos": resultado["pendiente_instalacion"]}
        if resultado.get("exito") and resultado.get("ruta"):
            context_engine.set_ultimo_archivo_creado(resultado["ruta"])
        return resultado["mensaje"]

    # Modo arquitecto (ver _procesar_programar/_procesar_proyecto_completo):
    # el jefe ya vio el plan/la estructura y escribió CONFIRMAR — recién
    # AQUÍ se genera el código de verdad. "individual" es un archivo
    # suelto (mismo camino que _procesar_programar seguía directo antes
    # de que existiera el modo arquitecto); "proyecto" es multi-archivo.
    if pendiente["origen"] == "codigo_pendiente":
        datos = pendiente["datos"]
        if datos["modo"] == "individual":
            resultado = code_agent.crear_proyecto(datos["nombre"], datos["descripcion"])
            if resultado.get("pendiente_instalacion"):
                _accion_pendiente = {"origen": "instalar_dependencia", "datos": resultado["pendiente_instalacion"]}
            if resultado.get("exito") and resultado.get("ruta"):
                context_engine.set_ultimo_archivo_creado(resultado["ruta"])
            return resultado["mensaje"]

        resultado = code_proyectos.crear_proyecto_completo(datos["nombre"], datos["descripcion"], estructura=datos["estructura"])
        if resultado.get("pendiente_instalacion_proyecto"):
            _accion_pendiente = {"origen": "instalar_dependencias_proyecto", "datos": resultado["pendiente_instalacion_proyecto"]}
        if resultado.get("exito") and resultado.get("ruta"):
            context_engine.set_ultimo_archivo_creado(resultado["ruta"])
            # El mensaje de éxito ya le ofrece al jefe inicializar git —
            # este wizard queda listo para cuando conteste CONFIRMAR.
            _accion_pendiente = {"origen": "git_init_proyecto", "datos": {"ruta": resultado["ruta"]}}
        return resultado["mensaje"]

    if pendiente["origen"] == "instalar_dependencias_proyecto":
        resultado = code_proyectos.confirmar_instalacion_proyecto(pendiente["datos"])
        if resultado.get("pendiente_instalacion_proyecto"):
            _accion_pendiente = {"origen": "instalar_dependencias_proyecto", "datos": resultado["pendiente_instalacion_proyecto"]}
        if resultado.get("exito") and resultado.get("ruta"):
            context_engine.set_ultimo_archivo_creado(resultado["ruta"])
            _accion_pendiente = {"origen": "git_init_proyecto", "datos": {"ruta": resultado["ruta"]}}
        return resultado["mensaje"]

    if pendiente["origen"] == "git_init_proyecto":
        resultado = code_proyectos.inicializar_git(pendiente["datos"]["ruta"])
        return resultado["mensaje"]

    return "ERROR: acción pendiente de origen desconocido."


def _procesar_control(texto_usuario):
    """Le pasa el mensaje completo a control_agent.interpretar(),
    que le pide a Gemini/Ollama el comando de Linux exacto a ejecutar.
    Si requiere confirmación, guarda la acción pendiente para cuando
    el usuario escriba CONFIRMAR (ver _ejecutar_accion_pendiente)."""
    global _accion_pendiente

    resultado = control_agent.interpretar(texto_usuario)

    if resultado["requiere_confirmacion"]:
        _accion_pendiente = {"origen": "system_control", "datos": resultado["accion"]}
        log.info("director: acción '%s' esperando confirmación", resultado["accion"].get("tipo"))
    elif resultado.get("archivo_descargado"):
        # BUG1: si el comando generado fue una descarga (wget/curl -o),
        # cuenta como archivo_descargado Y archivo_creado (mismo
        # mecanismo, ver context_engine.set_ultimo_archivo_descargado).
        context_engine.set_ultimo_archivo_descargado(resultado["archivo_descargado"])
    elif resultado.get("archivo_creado"):
        context_engine.set_ultimo_archivo_creado(resultado["archivo_creado"])

    return resultado["mensaje"]


def _detectar_sitio_busqueda(texto_bajo):
    """Devuelve el sitio (clave de _SITIOS_BUSQUEDA_NAVEGADOR) al que va
    dirigida la búsqueda si el mensaje trae "en google"/"en amazon"/
    "googlea"/etc, o None si es una búsqueda genérica (resumen al chat)."""
    for sitio, disparadores in _SITIOS_BUSQUEDA_NAVEGADOR.items():
        if any(d in texto_bajo for d in disparadores):
            return sitio
    return None


def _extraer_busqueda_sitio(texto, sitio):
    """Quita el "en <sitio>"/"googlea" y el verbo de búsqueda para
    quedarse solo con lo que hay que buscar en el navegador."""
    limpio = texto
    for disparador in _SITIOS_BUSQUEDA_NAVEGADOR[sitio]:
        limpio = re.sub(r"(?i)\b" + re.escape(disparador) + r"\b", " ", limpio)
    return _quitar_palabra_clave(limpio, PALABRAS_WEB).strip(" :,.-")


def _procesar_web(texto_usuario):
    # ¿La búsqueda va dirigida a un sitio concreto ("en google"/"en amazon"/
    # "googlea X")? Entonces se ABRE el navegador ahí (control_agent), no se
    # trae un resumen de texto (web_agent.buscar_web).
    sitio = _detectar_sitio_busqueda(texto_usuario.lower())
    if sitio:
        query = _extraer_busqueda_sitio(texto_usuario, sitio)
        if not query:
            return "¿Qué quieres que busque, jefe?"
        return control_agent.buscar_en_navegador(query, sitio)

    query = _quitar_palabra_clave(texto_usuario, PALABRAS_WEB)
    if not query:
        return "¿Qué quieres que busque, jefe?"

    resultados = web_agent.buscar_web(query)

    if isinstance(resultados, dict) and "error" in resultados:
        return f"No pude buscar '{query}': {resultados['error']}"
    if not resultados:
        return f"No encontré resultados para '{query}'."

    texto_resultados = "\n".join(
        f"{i + 1}. {r['titulo']} — {r['url']}\n   {r['descripcion']}"
        for i, r in enumerate(resultados)
    )

    prompt_resumen = (
        f'El usuario preguntó: "{texto_usuario}"\n\n'
        f"Encontré estos resultados de búsqueda web:\n{texto_resultados}\n\n"
        "Resume esto en una respuesta breve y útil para el usuario, en tu estilo, "
        "mencionando de dónde sacaste la info si aplica."
    )
    return balancer.enviar_mensaje(
        prompt=prompt_resumen, historial=[], system_instruction=personality.obtener_system_prompt()
    )


def _extraer_json(texto):
    """Extrae el JSON de una respuesta del modelo, tolerando fences de
    markdown, igual que control_agent.py/reminder_agent.py."""
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.I)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        coincidencia = re.search(r"\{.*\}", texto, re.S)
        if coincidencia:
            try:
                return json.loads(coincidencia.group(0))
            except json.JSONDecodeError:
                pass
    return None


def _procesar_briefing(texto_usuario):
    """"Buenos días" / "resumen del día" / "briefing": arma el resumen
    matutino (Notion + calendario + sistema) bajo demanda, en vez de
    esperar al scheduler automático de las BRIEFING_HOUR. Si el
    briefing trae la sugerencia de examen rápido (ver
    daily_briefing_agent.MARCA_SUGERENCIA_EXAMEN), deja
    _examen_sugerido_pendiente para que el siguiente mensaje del
    usuario, si es afirmación, arranque el examen (ver _despachar)."""
    global _examen_sugerido_pendiente
    texto = daily_briefing_agent.generar_briefing(hablar_en_voz=False)
    if daily_briefing_agent.MARCA_SUGERENCIA_EXAMEN in texto:
        _examen_sugerido_pendiente = True
    return texto


def _procesar_recordatorio(texto_usuario):
    """"Recuérdame X", "qué recordatorios tengo": crea o lista
    recordatorios. Eliminar por voz no está soportado todavía (no hay
    forma confiable de saber a cuál se refiere sin que el usuario
    primero pida la lista y dé el id)."""
    texto_bajo = texto_usuario.lower()

    palabras_consulta = ("qué recordatorios", "que recordatorios", "mis recordatorios", "lista de recordatorios")
    if any(p in texto_bajo for p in palabras_consulta):
        pendientes = reminder_agent.listar_recordatorios()
        if not pendientes:
            return "No tienes recordatorios pendientes, jefe."
        lineas = [f"#{r['id']} — {r['texto']} ({r['fecha_hora']})" for r in pendientes]
        return "Tus recordatorios pendientes:\n" + "\n".join(lineas)

    return reminder_agent.crear_recordatorio_desde_texto(texto_usuario)


def _procesar_calendario(texto_usuario):
    """"Qué tengo hoy/esta semana": consulta el calendario. Cualquier
    otra frase con palabras de calendario ("agenda X a las Y") se
    interpreta como crear un evento nuevo."""
    texto_bajo = texto_usuario.lower()

    if "semana" in texto_bajo and any(p in texto_bajo for p in ("qué tengo", "que tengo", "mi agenda", "calendario")):
        eventos = calendar_agent.obtener_eventos_semana()
        if isinstance(eventos, dict) and eventos.get("error"):
            return f"No pude leer tu calendario: {eventos['error']}"
        if not eventos:
            return "No tienes nada agendado esta semana, jefe."
        return "Esta semana tienes:\n" + "\n".join(f"{e['inicio']} — {e['titulo']}" for e in eventos)

    if any(p in texto_bajo for p in ("qué tengo", "que tengo", "mi agenda")):
        return calendar_agent.resumen_eventos_hoy_texto()

    return calendar_agent.crear_evento_desde_texto(texto_usuario)


_PROMPT_PARSEAR_CORREO = """Eres un parser de correos. El usuario te pide mandar un correo, en lenguaje natural. Devuelve SOLO un JSON así, nada más:
{{
  "destinatario": "el email o nombre del destinatario, tal cual lo dijo el usuario",
  "asunto": "un asunto corto y razonable para el correo",
  "cuerpo": "el cuerpo del correo, redactado breve y profesional a partir de lo que pidió el usuario"
}}

SOLO responde el JSON, nada más.

Mensaje del usuario: {mensaje}"""


def _procesar_correo(texto_usuario):
    """"Manda correo a X diciendo Y": redacta con Gemini y pide
    CONFIRMAR antes de enviar (misma lógica que control_agent
    para acciones riesgosas). "Tengo correos nuevos?" / "resumen de
    bandeja": resume los no leídos directo, sin confirmación (leer no
    es riesgoso)."""
    global _accion_pendiente
    texto_bajo = texto_usuario.lower()

    palabras_enviar = ("manda", "envía", "envia", "redacta")
    if any(p in texto_bajo for p in palabras_enviar):
        crudo = balancer.enviar_mensaje(
            prompt=_PROMPT_PARSEAR_CORREO.format(mensaje=texto_usuario), historial=[], system_instruction=None,
        )
        if crudo.startswith("ERROR:"):
            return f"No pude preparar el correo: {crudo}"

        datos = _extraer_json(crudo)
        if not datos or not datos.get("destinatario"):
            return "No entendí bien a quién o qué mandar, ¿me lo repites más claro?"

        _accion_pendiente = {"origen": "correo", "datos": datos}
        return (
            "¿Seguro que quieres que mande este correo?\n"
            f"Para: {datos['destinatario']}\n"
            f"Asunto: {datos['asunto']}\n"
            f"Cuerpo: {datos['cuerpo']}\n"
            "Escribe CONFIRMAR para continuar o cualquier otra cosa para cancelar."
        )

    return email_agent.resumir_bandeja()


_PROMPT_PARSEAR_CLASSROOM = """Eres un parser de comandos para el tracker manual de tareas escolares
de IRIS (Classroom ya no tiene API disponible — el admin de la escuela la bloqueó — así que
Mauri dicta sus tareas a mano y IRIS las guarda).

Materias/cursos conocidos de Mauri: {materias_conocidas}
Fecha y hora actual: {ahora}

Devuelve SOLO un JSON así, nada más:
{{
  "accion": "listar" | "recordar" | "completar" | "abrir_classroom" | "abrir_curso",
  "materia": "la materia/curso que menciona. Si se parece a una de las MATERIAS CONOCIDAS de arriba (ej. 'mate' o 'matemática' cuando ya existe 'matematicas'), usa EXACTAMENTE el nombre conocido, no el que dijo Mauri. Si no se parece a ninguna, usa el nombre tal cual lo dijo. Vacío si no menciona ninguna.",
  "descripcion": "qué hay que hacer (para 'recordar'), o vacío",
  "fecha_entrega": "YYYY-MM-DD calculada a partir de la fecha actual de arriba (ej. 'el viernes' -> ese próximo viernes), o vacío si no menciona fecha",
  "identificador_tarea": "para 'completar': materia o palabras de la tarea que hay que marcar como hecha, o vacío",
  "alcance": "semana" | "todas" -- para 'listar': 'todas' SOLO si Mauri pide explícitamente ver todo/el semestre completo/sin filtro; si no dice nada, 'semana'"
}}

Reglas:
- "qué tareas tengo" (sin más) -> "listar", alcance "semana"
- "todas mis tareas" / "todo lo que tengo pendiente del semestre" -> "listar", alcance "todas"
- "qué tareas tengo de <materia>" -> "listar" + esa materia (el alcance no importa si ya filtra por materia)
- "tengo tarea de <materia>, <qué hay que hacer>, para el <fecha>" / "anota que..." -> "recordar"
- "ya hice/entregué la tarea de <algo>" / "marca como hecha/completada la tarea de <algo>" -> "completar"
- "abre classroom" (sin mencionar un curso puntual) -> "abrir_classroom"
- "abre el curso de <materia>" / "ábreme <materia> en classroom" -> "abrir_curso"
- SOLO responde el JSON, nada más.

Mensaje del usuario: {mensaje}"""


def _procesar_classroom(texto_usuario):
    """Rutea los comandos de Classroom (Plan B, sin API — ver
    classroom_agent.py): le pide a Gemini/Ollama que separe el mensaje
    en {accion, materia, descripcion, fecha_entrega, identificador_tarea,
    alcance} (mismo patrón que calendar_agent/email_agent para lenguaje
    natural), normalizando la materia contra CURSOS conocidos para que
    "mate"/"matemáticas"/"Matemáticas" no queden como grupos separados
    con cientos de tareas en la tabla, y despacha a classroom_agent
    según la acción."""
    materias_conocidas = ", ".join(classroom_agent.CURSOS.keys()) or "(ninguna todavía)"
    crudo = balancer.enviar_mensaje(
        prompt=_PROMPT_PARSEAR_CLASSROOM.format(
            materias_conocidas=materias_conocidas,
            ahora=datetime.now().isoformat(timespec="seconds"), mensaje=texto_usuario,
        ),
        historial=[], system_instruction=None,
    )
    datos = _extraer_json(crudo) if not crudo.startswith("ERROR:") else None
    accion = (datos or {}).get("accion", "listar")

    if accion == "abrir_classroom":
        return classroom_agent.abrir_classroom()

    if accion == "abrir_curso":
        curso = (datos or {}).get("materia") or texto_usuario
        return classroom_agent.abrir_curso(curso)

    if accion == "recordar":
        materia = (datos or {}).get("materia") or "General"
        descripcion = (datos or {}).get("descripcion") or texto_usuario
        fecha = (datos or {}).get("fecha_entrega") or None
        resultado = classroom_agent.recordar_tarea(materia, descripcion, fecha)
        if resultado.get("error"):
            return f"No pude guardar la tarea: {resultado['error']}"
        fecha_legible = f" para el {fecha}" if fecha else ""
        return f"Anotado, jefe: {materia} — {descripcion}{fecha_legible}."

    if accion == "completar":
        identificador = ((datos or {}).get("identificador_tarea") or texto_usuario).strip().lower()
        tareas = classroom_agent.listar_tareas(solo_pendientes=True)
        if isinstance(tareas, dict) and tareas.get("error"):
            return f"No pude leer tus tareas: {tareas['error']}"
        tarea = next(
            (t for t in tareas if identificador in t["materia"].lower() or identificador in t["descripcion"].lower()),
            None,
        )
        if not tarea:
            return f"No encontré una tarea pendiente que coincida con '{identificador}'."
        if classroom_agent.completar_tarea(tarea["id"]):
            return f"Listo, marqué '{tarea['materia']}: {tarea['descripcion']}' como completada."
        return "No pude marcar la tarea como completada."

    # "listar" (o fallback si el modelo no devolvió JSON válido).
    materia_filtro = (datos or {}).get("materia") or None
    alcance = (datos or {}).get("alcance") or "semana"

    # Plan principal: leer Classroom DE VERDAD por navegador (cuenta
    # real, tal como Classroom mismo la agrupa). Solo aplica a la
    # consulta genérica sin filtro de materia (filtrar/"todas" es
    # capacidad del tracker manual en Supabase, ver classroom_agent.py).
    if not materia_filtro and alcance == "semana":
        texto_auto = classroom_agent.resumen_pendientes_texto()
        if texto_auto is not None:
            return texto_auto
        log.warning("director: el lector automático de Classroom falló, cayendo al tracker manual")

    # Plan B: tracker manual (Supabase) — si no menciona materia ni pidió
    # "todas", vista recortada a la semana (con cientos de tareas por
    # semestre, mandarlas todas de un jalón por default sería inútil).
    dias = None if (materia_filtro or alcance == "todas") else 7
    return classroom_agent.listar_tareas_texto(materia=materia_filtro, dias=dias)


def _procesar_nexus(texto_usuario):
    """"Abre Nexus": abre el portal (con autologin si ya hay
    credenciales guardadas). "Configura Nexus": arranca el wizard de
    2 pasos (usuario, luego contraseña) que se completa en
    procesar_mensaje via _nexus_config_pendiente."""
    global _nexus_config_pendiente
    texto_bajo = texto_usuario.lower()

    if any(p in texto_bajo for p in ("configura", "configurar")):
        _nexus_config_pendiente = {"etapa": "usuario", "usuario": None}
        return "Claro, ¿cuál es tu usuario de Nexus?"

    return nexus_agent.abrir_nexus()


_PROMPT_PARSEAR_FINANZAS = """Eres un parser de finanzas personales. El usuario habla de dinero en lenguaje natural.

Categorías conocidas:
- Ingresos: negocio, trabajo, mesada, otro
- Gastos: comida, transporte, materiales, escuela, gym, ropa, entretenimiento, negocio_inversion, otro

Devuelve SOLO un JSON así, nada más:
{{
  "accion": "registrar_ingreso" | "registrar_gasto" | "balance" | "resumen_mes" | "resumen_semana" | "historial" | "ganancia_negocio",
  "cantidad": numero (0 si no aplica),
  "categoria": "la categoría más parecida de la lista de arriba, o una nueva si de plano no encaja, o vacío si no aplica",
  "descripcion": "descripción breve del movimiento (qué fue), o vacío",
  "negocio": "nombre del negocio si menciona uno en particular (ej. 'aguas', 'ropa'), o vacío"
}}

Reglas:
- "gasté/pagué/compré X en Y" -> "registrar_gasto"
- "vendí/me cayeron/gané/ingreso de X" -> "registrar_ingreso"
- "cuánto tengo"/"cuánto llevo"/"balance" (sin pedir desglose) -> "balance"
- "resumen financiero"/"cómo voy este mes"/"cuánto llevo este mes" -> "resumen_mes"
- "cómo voy esta semana" -> "resumen_semana"
- "historial"/"mis movimientos"/"qué he gastado" -> "historial"
- "cuánto he ganado con..."/"ganancia de..." -> "ganancia_negocio"
- SOLO responde el JSON, nada más.

Mensaje del usuario: {mensaje}"""


def _parsear_cantidad(texto):
    """Saca el primer número (con decimales opcionales) que aparezca en
    el texto, ej. "500", "fueron 200 pesos", "$150.50" -> 500, 200,
    150.5. None si no hay ninguno — para completar _finanzas_pendiente
    con la respuesta a "¿cuánto fue?"."""
    coincidencia = re.search(r"\d+(?:[.,]\d+)?", texto)
    if not coincidencia:
        return None
    return float(coincidencia.group(0).replace(",", "."))


def _registrar_movimiento_finanzas(accion, cantidad, categoria, descripcion):
    """Llama a finance_agent con un {accion,cantidad,categoria,descripcion}
    ya completos y arma el texto de respuesta — compartido entre
    _procesar_finanzas (cantidad venía en el primer mensaje) y
    _despachar (cantidad llegó en un mensaje de seguimiento, ver
    _finanzas_pendiente)."""
    if accion == "registrar_gasto":
        resultado = finance_agent.registrar_gasto(cantidad, descripcion, categoria)
        if resultado.get("error"):
            return f"No pude registrar el gasto: {resultado['error']}"
        respuesta = f"Anotado: gasto de ${float(cantidad):.2f} en {categoria} ({descripcion})."
        aviso = finance_agent.alerta_gastos()
        if aviso:
            respuesta += f"\n\n{aviso}"
        return respuesta

    resultado = finance_agent.registrar_ingreso(cantidad, descripcion, categoria)
    if resultado.get("error"):
        return f"No pude registrar el ingreso: {resultado['error']}"
    return f"Anotado: ingreso de ${float(cantidad):.2f} en {categoria} ({descripcion})."


def _procesar_finanzas(texto_usuario):
    """Rutea los comandos de finanzas: le pide a Gemini/Ollama que
    separe el mensaje en {accion, cantidad, categoria, descripcion,
    negocio} (mismo patrón que classroom/calendar/email para lenguaje
    natural), y despacha a finance_agent según la acción.

    Si la acción es registrar_gasto/registrar_ingreso pero no vino una
    cantidad reconocible, NO se pierde el pedido: se deja
    _finanzas_pendiente armado para que el próximo mensaje (ej. "500",
    "fueron 200 pesos") complete el registro, ver _despachar."""
    global _finanzas_pendiente
    crudo = balancer.enviar_mensaje(
        prompt=_PROMPT_PARSEAR_FINANZAS.format(mensaje=texto_usuario), historial=[], system_instruction=None,
    )
    datos = _extraer_json(crudo) if not crudo.startswith("ERROR:") else None
    accion = (datos or {}).get("accion", "balance")

    if accion in ("registrar_gasto", "registrar_ingreso"):
        cantidad = (datos or {}).get("cantidad") or 0
        categoria = (datos or {}).get("categoria") or "otro"
        descripcion = (datos or {}).get("descripcion") or texto_usuario
        if not cantidad:
            _finanzas_pendiente = {"accion": accion, "categoria": categoria, "descripcion": descripcion}
            pregunta = "gastaste" if accion == "registrar_gasto" else "te cayó"
            return f"¿Cuánto {pregunta}, jefe? No te entendí la cantidad."
        return _registrar_movimiento_finanzas(accion, cantidad, categoria, descripcion)

    if accion == "resumen_mes":
        return finance_agent.resumen_mes_texto()

    if accion == "resumen_semana":
        return finance_agent.resumen_semana_texto()

    if accion == "historial":
        return finance_agent.historial_texto()

    if accion == "ganancia_negocio":
        negocio = (datos or {}).get("negocio") or None
        return finance_agent.ganancia_negocio_texto(negocio)

    return finance_agent.balance_actual_texto()


_PROMPT_PARSEAR_PENDIENTE = """Eres un parser de pendientes personales del día a día (NO son tareas
escolares, esas se manejan aparte).

Devuelve SOLO un JSON así, nada más:
{{
  "accion": "agregar" | "listar" | "completar" | "eliminar",
  "texto": "qué hay que hacer (para 'agregar') o palabras para identificar cuál pendiente (para 'completar'/'eliminar'), o vacío",
  "prioridad": "alta" | "normal" | "baja" (para 'agregar', 'normal' si no la menciona; para 'listar', el filtro si lo pide, si no vacío)
}}

Reglas:
- "tengo que <algo>" / "agrega un pendiente de <algo>" -> "agregar"
- "qué pendientes tengo" -> "listar"
- "ya hice/compré/terminé <algo>" -> "completar"
- "elimina/borra el pendiente de <algo>" -> "eliminar"
- SOLO responde el JSON, nada más.

Mensaje del usuario: {mensaje}"""


def _procesar_pendientes(texto_usuario):
    """Rutea los comandos de pendientes: le pide a Gemini/Ollama que
    separe el mensaje en {accion, texto, prioridad}, y despacha a
    pendientes_agent según la acción. "eliminar" no elimina directo:
    arma _accion_pendiente (origen "eliminar_pendiente") para pedir
    CONFIRMAR antes de archivar de verdad en Notion."""
    global _accion_pendiente

    crudo = balancer.enviar_mensaje(
        prompt=_PROMPT_PARSEAR_PENDIENTE.format(mensaje=texto_usuario), historial=[], system_instruction=None,
    )
    datos = _extraer_json(crudo) if not crudo.startswith("ERROR:") else None
    accion = (datos or {}).get("accion", "listar")

    if accion == "agregar":
        texto = (datos or {}).get("texto") or texto_usuario
        prioridad = (datos or {}).get("prioridad") or "normal"
        resultado = pendientes_agent.agregar_pendiente(texto, prioridad)
        if resultado.get("error"):
            return f"No pude agregar el pendiente: {resultado['error']}"
        return f"Anotado, jefe: {texto} (prioridad {prioridad})."

    if accion == "completar":
        identificador = (datos or {}).get("texto") or texto_usuario
        resultado = pendientes_agent.completar_pendiente(identificador)
        if resultado.get("error"):
            return f"No pude marcarlo como hecho: {resultado['error']}"
        return f"Listo, marqué '{resultado['titulo']}' como completado."

    if accion == "eliminar":
        identificador = (datos or {}).get("texto") or texto_usuario
        pendiente = pendientes_agent.resolver_pendiente(identificador)
        if not pendiente:
            return f"No encontré un pendiente que coincida con '{identificador}'."
        _accion_pendiente = {"origen": "eliminar_pendiente", "datos": pendiente}
        return (
            f"¿Seguro que quieres eliminar el pendiente '{pendiente['titulo']}'?\n"
            "Escribe CONFIRMAR para continuar o cualquier otra cosa para cancelar."
        )

    filtro_prioridad = (datos or {}).get("prioridad") or None
    return pendientes_agent.listar_pendientes_texto(filtro_prioridad)


_PROMPT_PARSEAR_PROYECTO = """Eres un parser de proyectos personales/escolares de largo plazo (NO son
pendientes sueltos del día a día ni tareas de classroom, esos se manejan aparte).
Un proyecto se crea una vez y después se le van agregando AVANCES conforme pasa el tiempo.

Devuelve SOLO un JSON así, nada más:
{{
  "accion": "crear" | "listar" | "avance" | "avances" | "estado" | "eliminar",
  "texto": "nombre del proyecto (para 'crear') o palabras para identificar cuál proyecto (para el resto), o vacío",
  "tipo": "escolar" | "personal" (para 'crear', 'personal' si no lo menciona; para 'listar', el filtro si lo pide, si no vacío),
  "detalle": "el avance a anotar (para 'avance') o el nuevo estado 'no iniciado'/'en progreso'/'pausado'/'completado' (para 'estado'), o vacío"
}}

Reglas:
- "crea un proyecto de <algo>" / "nuevo proyecto <algo>" -> "crear"
- "qué proyectos tengo" -> "listar"
- "en el proyecto <X> ya <hice tal cosa>" / "avance en <X>: <cosa>" -> "avance" (detalle = la cosa)
- "cómo voy con <X>" / "qué avances lleva <X>" -> "avances"
- "pausa/termina/completa el proyecto <X>" -> "estado" (detalle = el nuevo estado)
- "elimina/borra el proyecto <X>" -> "eliminar"
- SOLO responde el JSON, nada más.

Mensaje del usuario: {mensaje}"""


def _procesar_proyectos(texto_usuario):
    """Rutea los comandos de proyectos: le pide a Gemini/Ollama que
    separe el mensaje en {accion, texto, tipo, detalle}, y despacha a
    proyectos_agent según la acción. "eliminar" no elimina directo:
    arma _accion_pendiente (origen "eliminar_proyecto") para pedir
    CONFIRMAR antes de archivar de verdad en Notion."""
    global _accion_pendiente

    crudo = balancer.enviar_mensaje(
        prompt=_PROMPT_PARSEAR_PROYECTO.format(mensaje=texto_usuario), historial=[], system_instruction=None,
    )
    datos = _extraer_json(crudo) if not crudo.startswith("ERROR:") else None
    accion = (datos or {}).get("accion", "listar")

    if accion == "crear":
        texto = (datos or {}).get("texto") or texto_usuario
        tipo = (datos or {}).get("tipo") or "personal"
        resultado = proyectos_agent.crear_proyecto(texto, tipo)
        if resultado.get("error"):
            return f"No pude crear el proyecto: {resultado['error']}"
        return f"Listo, jefe: creé el proyecto '{texto}' ({tipo})."

    if accion == "avance":
        identificador = (datos or {}).get("texto") or texto_usuario
        detalle = (datos or {}).get("detalle") or texto_usuario
        resultado = proyectos_agent.agregar_avance(identificador, detalle)
        if resultado.get("error"):
            return f"No pude anotar el avance: {resultado['error']}"
        return f"Anotado en '{resultado['titulo']}': {detalle}"

    if accion == "avances":
        identificador = (datos or {}).get("texto") or texto_usuario
        resultado = proyectos_agent.listar_avances(identificador)
        if resultado.get("error"):
            return f"No pude leer los avances: {resultado['error']}"
        return f"Avances de '{resultado['titulo']}':\n{resultado['avances']}"

    if accion == "estado":
        identificador = (datos or {}).get("texto") or texto_usuario
        nuevo_estado = (datos or {}).get("detalle") or ""
        resultado = proyectos_agent.cambiar_estado(identificador, nuevo_estado)
        if resultado.get("error"):
            return f"No pude actualizar el proyecto: {resultado['error']}"
        return f"Listo, '{resultado['titulo']}' ahora está en estado '{nuevo_estado}'."

    if accion == "eliminar":
        identificador = (datos or {}).get("texto") or texto_usuario
        proyecto = proyectos_agent.resolver_proyecto(identificador)
        if not proyecto:
            return f"No encontré un proyecto que coincida con '{identificador}'."
        _accion_pendiente = {"origen": "eliminar_proyecto", "datos": proyecto}
        return (
            f"¿Seguro que quieres eliminar el proyecto '{proyecto['titulo']}'?\n"
            "Escribe CONFIRMAR para continuar o cualquier otra cosa para cancelar."
        )

    filtro_tipo = (datos or {}).get("tipo") or None
    return proyectos_agent.listar_proyectos_texto(filtro_tipo=filtro_tipo)


def _procesar_elegir(texto_usuario):
    """"Ayúdame a elegir": screenshot + Gemini recomienda la mejor
    opción de lo que ve (gasta tokens). Es la única acción de
    screenshot_agent que NO tiene equivalente en control_agent — el
    resto ("screenshot"/"captura"/"ve mi pantalla") ahora vive en el
    grupo de control remoto, ver _procesar_control_remoto. Manda la
    imagen Y la recomendación juntas (ARREGLO 6)."""
    resultado = screenshot_agent.comparar_opciones()
    if resultado.startswith("No pude capturar tu pantalla"):
        return resultado
    return f"{resultado}\n\n{marcador_imagen('/captura')}"


def _procesar_observador(texto_usuario):
    """Requiere que VISTA esté activo (ver observador.set_vista_activa,
    actualizado por server.py POST /vista cuando el usuario togglea el
    botón) — si no, ni siquiera se intenta prender la cámara."""
    if not observador.vista_esta_activa():
        return "Activa mi vista primero, jefe."

    texto_bajo = texto_usuario.lower()
    if "qué es esto" in texto_bajo or "que es esto" in texto_bajo:
        return observador.ver_objeto()

    pregunta = _quitar_palabra_clave(texto_usuario, PALABRAS_OBSERVADOR)
    return observador.analizar_foto(pregunta or None)


def _procesar_clipboard(texto_usuario):
    """CERO tokens: todo es xclip + comparar/filtrar la lista en
    memoria de clipboard_agent, nunca pasa por Gemini."""
    texto_bajo = texto_usuario.lower()

    if "busca en lo que copié" in texto_bajo or "busca en lo que copie" in texto_bajo:
        termino = _quitar_palabra_clave(texto_usuario, ("busca en lo que copié", "busca en lo que copie"))
        if not termino:
            return "¿Qué buscas en lo que has copiado, jefe?"
        coincidencias = clipboard_agent.buscar(termino)
        if not coincidencias:
            return f"No encontré nada copiado con '{termino}', jefe."
        lineas = [f"[{h['hora']}] {h['texto'][:80]}" for h in coincidencias[:10]]
        return "Encontré esto en tu historial:\n" + "\n".join(lineas)

    if any(p in texto_bajo for p in ("portapapeles", "historial copiado")):
        entradas = clipboard_agent.historial(10)
        if not entradas:
            return "No tengo nada en el historial de portapapeles todavía, jefe."
        lineas = [f"[{h['hora']}] {h['texto'][:80]}" for h in entradas]
        return "Tu historial reciente:\n" + "\n".join(lineas)

    actual = clipboard_agent.obtener_actual()
    if isinstance(actual, dict):
        return f"No pude leer el portapapeles: {actual['error']}"
    if not actual.strip():
        return "No tienes nada copiado ahorita, jefe."
    return f"Tienes copiado: {actual[:200]}"


# BUG4: "busca en mis archivos/documentos de X (y ábrelo)" — frases que
# disparan la búsqueda TOLERANTE (ver PALABRAS_ARCHIVOS/_procesar_archivos),
# distintas de PALABRAS_BUSCAR_CARPETA (que es para carpetas, no archivos).
PALABRAS_BUSCAR_ARCHIVO_TEMA = ("busca en mis archivos", "busca en mis documentos", "busca entre mis archivos")

# Muletillas que suelen venir después de "busca en mis archivos ___":
# "uno de X", "algo sobre X", "un archivo de X" — se quitan para quedarnos
# solo con el tema real que hay que buscar.
_PATRON_MULETILLA_BUSQUEDA = re.compile(r"^(?:uno|una|algo|un archivo|un documento)\s+(?:de|sobre)\s+", re.I)


def _procesar_archivos(texto_usuario):
    """CERO tokens: os.walk/shutil.move de file_organizer_agent,
    nunca pasa por Gemini."""
    global _carpeta_pendiente, _ultima_carpeta
    texto_bajo = texto_usuario.lower()

    if any(p in texto_bajo for p in ("organiza descargas", "organiza mis descargas", "organiza las descargas")):
        return file_organizer_agent.organizar_descargas_texto()

    if any(p in texto_bajo for p in ("qué hay en mis descargas", "que hay en mis descargas")):
        return file_organizer_agent.info_descargas_texto()

    if any(p in texto_bajo for p in PALABRAS_BUSCAR_ARCHIVO_TEMA):
        abrir_tambien = any(texto_bajo.endswith(s) for s in _SUFIJOS_ABRIR_TAMBIEN)

        nombre = texto_usuario
        for sufijo in _SUFIJOS_ABRIR_TAMBIEN:
            if nombre.lower().endswith(sufijo):
                nombre = nombre[: -len(sufijo)]
                break
        nombre = _quitar_palabra_clave(nombre, PALABRAS_BUSCAR_ARCHIVO_TEMA).strip()
        nombre = _PATRON_MULETILLA_BUSQUEDA.sub("", nombre).strip()
        if not nombre:
            return "¿Qué archivo busco, jefe?"

        candidatos = file_organizer_agent.buscar_archivo_tolerante(nombre)
        if isinstance(candidatos, dict) and candidatos.get("error"):
            return f"No pude buscar: {candidatos['error']}"
        if not candidatos:
            return f"No encontré ningún archivo parecido a '{nombre}', jefe."

        if len(candidatos) == 1:
            _ultima_carpeta = candidatos[0]
            if abrir_tambien:
                return control_agent.abrir_archivo(candidatos[0])
            return f"Encontré: {candidatos[0]}. Dime \"ábrelo\" si quieres que lo abra."

        # Mismo wizard numerado que buscar_carpeta (_carpeta_pendiente/
        # _despachar caso 2.5) — reusado tal cual: la resolución ahí ya
        # es genérica (solo llama control_agent.abrir_archivo(ruta)),
        # no le importa si el candidato es un archivo o una carpeta.
        _carpeta_pendiente = {"candidatos": candidatos, "abrir": abrir_tambien}
        listado = "\n".join(f"{i + 1}. {ruta}" for i, ruta in enumerate(candidatos))
        return f"Encontré varios archivos parecidos a '{nombre}':\n{listado}\nDime el número de cuál quieres."

    if "busca mi" in texto_bajo or "busca archivo" in texto_bajo:
        nombre = _quitar_palabra_clave(texto_usuario, ("busca mi", "busca archivo"))
        if not nombre:
            return "¿Qué archivo busco, jefe?"
        return file_organizer_agent.buscar_archivo_texto(nombre)

    return file_organizer_agent.info_descargas_texto()


# "y ábrela"/"y ábrelo" al final de "busca la carpeta X y ábrela": se
# quitan ANTES de sacar el nombre (si no, "X y ábrela" quedaría como
# nombre de carpeta) — deliberadamente una lista aparte de _quitar_
# palabra_clave (que solo quita del INICIO del texto).
_SUFIJOS_ABRIR_TAMBIEN = (" y ábrela", " y abrela", " y ábrelo", " y abrelo")


def _procesar_buscar_carpeta(texto_usuario):
    """"Busca la carpeta X" (opcionalmente "... y ábrela" de un jalón):
    CERO tokens, os.walk de file_organizer_agent.buscar_carpeta(). Si
    hay una sola coincidencia, la recuerda en _ultima_carpeta para que
    un "ábrela" SUELTO en otro mensaje también funcione (ver
    _procesar_abrir_ultimo). Si hay varias, arma el mismo
    wizard numerado que investigación (ver _carpeta_pendiente/
    _despachar)."""
    global _carpeta_pendiente, _ultima_carpeta
    texto_bajo = texto_usuario.lower()
    abrir_tambien = any(p in texto_bajo for p in PALABRAS_ABRIR_ULTIMA_CARPETA + _SUFIJOS_ABRIR_TAMBIEN)

    nombre = texto_usuario
    for sufijo in _SUFIJOS_ABRIR_TAMBIEN:
        if nombre.lower().endswith(sufijo):
            nombre = nombre[: -len(sufijo)]
            break
    nombre = _quitar_palabra_clave(nombre, PALABRAS_BUSCAR_CARPETA).strip()
    if not nombre:
        return "¿Qué carpeta busco, jefe?"

    candidatos = file_organizer_agent.buscar_carpeta(nombre)
    if isinstance(candidatos, dict) and candidatos.get("error"):
        return f"No pude buscar: {candidatos['error']}"
    if not candidatos:
        return f"No encontré ninguna carpeta con '{nombre}' en el nombre, jefe."

    if len(candidatos) == 1:
        _ultima_carpeta = candidatos[0]
        if abrir_tambien:
            return control_agent.abrir_archivo(candidatos[0])
        return f"Encontré: {candidatos[0]}. Dime \"ábrela\" si quieres que la abra."

    _carpeta_pendiente = {"candidatos": candidatos, "abrir": abrir_tambien}
    listado = "\n".join(f"{i + 1}. {ruta}" for i, ruta in enumerate(candidatos))
    return f"Encontré varias carpetas con '{nombre}':\n{listado}\nDime el número de cuál quieres."


def _extraer_carpeta_cerebro(texto_usuario):
    """De "cuántos archivos tengo en Descargas (del cerebro de
    archivos)" saca "descargas". Best-effort: si no reconoce una
    carpeta puntual devuelve None y _procesar_cerebro_archivos cae al
    total general (mejor una respuesta general que una mal parseada)."""
    texto_bajo = texto_usuario.lower()
    for disparador in PALABRAS_CEREBRO_ARCHIVOS:
        idx = texto_bajo.find(disparador)
        if idx != -1:
            texto_bajo = texto_bajo[:idx]
            break

    # saca un "en (el/la/los/las)?" colgante al final: en "... en
    # Descargas EN EL cerebro de archivos" ese "en el" es parte de la
    # mención al cerebro, no del nombre de la carpeta — sin esto,
    # rfind(" en ") de abajo agarraba ESE "en" en vez del bueno.
    texto_bajo = re.sub(r"\s+en\s+(el|la|los|las)?\s*$", "", texto_bajo)

    idx_en = texto_bajo.rfind(" en ")
    if idx_en == -1:
        return None
    candidato = texto_bajo[idx_en + len(" en "):].strip(" ¿?.,")
    candidato = re.sub(r"^(la carpeta de|la carpeta|mi carpeta de|mi carpeta)\s+", "", candidato)
    candidato = re.sub(r"\s+(del|de|en|el|la|los|las)\s*$", "", candidato).strip()
    if candidato in _PALABRAS_VACIAS_CARPETA_CEREBRO:
        return None
    return candidato


_PALABRAS_VACIAS_CARPETA_CEREBRO = {"el", "la", "los", "las", "mi", "mis", "del", "de", "total", "general", ""}


def _procesar_cerebro_archivos(texto_usuario):
    """"Cuántos archivos/carpetas tengo (en <carpeta>) en el cerebro de
    archivos": estadísticas en vivo de proyectos/cerebro_archivos, CERO
    tokens (nada de Gemini). Arranca su servidor solo si hace falta
    (ver cerebro_archivos_agent._asegurar_servidor_corriendo), pero
    NUNCA abre el navegador acá — para "abrilo"/"mostramelo" ya está el
    intent "abrir" (control_agent.abrir_app vía el .desktop)."""
    nombre_carpeta = _extraer_carpeta_cerebro(texto_usuario)
    resultado = cerebro_archivos_agent.obtener_estadisticas(nombre_carpeta)

    if resultado.get("error"):
        return f"No pude consultar el cerebro de archivos, jefe: {resultado['error']}."

    if resultado["carpeta"]:
        return (
            f"En '{resultado['carpeta']}' tenés {resultado['archivos']} archivos "
            f"en {resultado['carpetas']} carpetas, jefe."
        )
    return f"Tenés {resultado['archivos']} archivos en {resultado['carpetas']} carpetas en total, jefe."


def _procesar_abrir_ultimo():
    """"Ábrelo"/"abre ese archivo"/"abre el archivo que creaste"/"abre
    el que descargaste": prioriza el último archivo/carpeta que IRIS
    CREÓ O DESCARGÓ (ver context_engine.obtener_ultimo_archivo_creado
    — lo llenan code_agent.crear_proyecto, control_agent.interpretar
    con touch/echo/mkdir/wget/curl, y research_agent.procesar_seleccion
    vía set_ultimo_archivo_descargado, que SIEMPRE también actualiza
    "creado" con el mismo timestamp — así esto ya resuelve solo cuál de
    los dos fue más reciente, sin comparar nada a mano, ver BUG3). Si
    no hay ninguno, cae a la última carpeta que buscar_carpeta()
    resolvió a una sola coincidencia (mismo comportamiento de siempre
    para "busca la carpeta X" + "ábrela")."""
    archivo_creado = context_engine.obtener_ultimo_archivo_creado()
    if archivo_creado:
        return control_agent.abrir_archivo(archivo_creado)
    if not _ultima_carpeta:
        return "No he creado ni buscado ningún archivo o carpeta últimamente, jefe. Dime \"busca la carpeta X\" primero."
    return control_agent.abrir_archivo(_ultima_carpeta)


# Marcador GENÉRICO que script.js/telegram_agent.py buscan en la
# respuesta para saber que trae una imagen que mostrar/mandar, y de qué
# endpoint del server pedirla — "[IMAGEN:/figura]", "[IMAGEN:/foto]",
# etc. Mismo criterio que ya usa el frontend para CONFIRMAR (un token
# reconocible dentro del texto en vez de inventar un canal aparte); se
# generalizó de un marcador fijo de figuras a esto para poder reusarlo
# también en "toma foto" sin duplicar la lógica de detección.
def marcador_imagen(ruta_endpoint):
    return f"[IMAGEN:{ruta_endpoint}]"


def _procesar_figura(texto_usuario):
    """"Dibújame X"/"hazme un diagrama de X": la ÚNICA función de todo
    el proyecto que ejecuta código escrito por Gemini (ver
    figura_agent.py para las 3 capas de mitigación). SÍ gasta tokens.

    "Corrígelo"/"está al revés"/"no cabe" (ver PALABRAS_CORREGIR_FIGURA)
    despacha a figura_agent.corregir_figura() en vez de generar_figura():
    corrige el código de la ÚLTIMA figura con lo que el jefe dice que
    está mal, en vez de dibujar algo nuevo a ciegas sin saber qué se
    había pedido antes — eso era lo que hacía que "corregir" a veces
    cambiara un problema por otro en vez de arreglarlo.

    Le manda a figura_agent el mensaje COMPLETO (no solo lo que queda
    tras _quitar_palabra_clave): la frase disparadora puede traer la
    señal de "en 3d"/"animación" (ej. "hazme una animación de X"), y
    figura_agent.generar_figura() la busca en todo el texto — si le
    mandáramos solo lo que sobra después de cortar la frase, esa señal
    se perdería antes de llegar allá."""
    texto_bajo = texto_usuario.lower()

    if any(p in texto_bajo for p in PALABRAS_CORREGIR_FIGURA):
        ruta, error = figura_agent.corregir_figura(texto_usuario)
    else:
        descripcion = _quitar_palabra_clave(texto_usuario, PALABRAS_FIGURA).strip()
        if not descripcion:
            return "¿Qué quieres que te dibuje, jefe?"
        ruta, error = figura_agent.generar_figura(texto_usuario)

    if error:
        return f"No pude generar la figura: {error}"
    endpoint = "/figura-animada" if ruta == figura_agent.RUTA_FIGURA_GIF else "/figura"
    return f"Aquí está, jefe.\n\n{marcador_imagen(endpoint)}"


def _procesar_programar(texto_usuario):
    """"Créame un programa que..."/"hazme un sistema de..."/"programa
    algo que...": a diferencia de _procesar_figura (que solo dibuja con
    matplotlib dentro de un `ax` ya dado), aquí Gemini escribe un
    PROGRAMA COMPLETO desde cero y code_agent.crear_proyecto() lo prueba
    corriéndolo de verdad, corrigiéndolo hasta 3 veces si truena. SÍ
    gasta tokens, potencialmente varias veces.

    Si la petición es COMPLEJA (visual/3D, o "hazlo bien"/"al límite",
    ver code_agent.es_peticion_compleja), primero pasa por el MODO
    ARQUITECTO: se genera un plan corto (ver code_agent.generar_plan) y
    se arma _accion_pendiente esperando CONFIRMAR antes de escribir
    código de verdad — mismo wizard genérico que ya usa control/correo
    (ver _ejecutar_accion_pendiente, origen "codigo_pendiente"). Si
    Gemini no pudo generar el plan, se degrada a generar directo (nunca
    bloquea al jefe por un fallo de infraestructura). Peticiones
    simples van directo, sin este paso extra.

    Si el código necesita una librería que no está instalada,
    crear_proyecto() no instala nada solo — arma _accion_pendiente de
    todas formas (origen "instalar_dependencia") para que el jefe
    confirme antes."""
    global _accion_pendiente

    descripcion = texto_usuario.strip()
    nombre = code_agent.generar_nombre_proyecto(descripcion)

    if code_agent.es_peticion_compleja(descripcion):
        plan = code_agent.generar_plan(descripcion)
        if plan:
            _accion_pendiente = {
                "origen": "codigo_pendiente",
                "datos": {"modo": "individual", "nombre": nombre, "descripcion": descripcion},
            }
            return f"{plan}\n\n¿Procedo con este plan? Escribe CONFIRMAR o dime qué cambiar."

    resultado = code_agent.crear_proyecto(nombre, descripcion)

    if resultado.get("pendiente_instalacion"):
        _accion_pendiente = {"origen": "instalar_dependencia", "datos": resultado["pendiente_instalacion"]}
    if resultado.get("exito") and resultado.get("ruta"):
        context_engine.set_ultimo_archivo_creado(resultado["ruta"])

    return resultado["mensaje"]


def _procesar_proyecto_completo(texto_usuario):
    """"Créame una app web de..."/"hazme un sitio web..."/"crea un
    juego de...": a diferencia de _procesar_programar (UN archivo
    suelto), esto genera un PROYECTO MULTI-ARCHIVO completo en
    proyectos/{nombre}/ (ver code_proyectos.crear_proyecto_completo).
    Un proyecto multi-archivo siempre cuenta como petición compleja —
    SIEMPRE pasa por el modo arquitecto: primero se planea la
    ESTRUCTURA (qué archivos, ver code_proyectos.generar_estructura) y
    se le muestra al jefe, esperando CONFIRMAR antes de generar nada
    (mismo wizard que _procesar_programar, origen "codigo_pendiente",
    modo "proyecto")."""
    global _accion_pendiente

    descripcion = texto_usuario.strip()
    nombre = code_proyectos.generar_nombre_proyecto(descripcion)

    estructura = code_proyectos.generar_estructura(descripcion)
    if estructura is None:
        return "No pude planear la estructura del proyecto, jefe: Gemini no respondió o no dio nada usable."

    _accion_pendiente = {
        "origen": "codigo_pendiente",
        "datos": {"modo": "proyecto", "nombre": nombre, "descripcion": descripcion, "estructura": estructura},
    }
    arbol = code_proyectos.formatear_estructura_para_mostrar(nombre, estructura)
    return f"Esta sería la estructura del proyecto:\n\n{arbol}\n\n¿Procedo con esta estructura? Escribe CONFIRMAR o dime qué cambiar."


def _procesar_foto_webcam():
    """"Toma foto"/"tómame una foto": igual que control_agent.
    tomar_foto_webcam() de siempre (CERO tokens, solo fswebcam), pero
    ahora le pega el marcador de imagen para que la foto de verdad se
    muestre en el HUD o se mande por Telegram — antes solo devolvía
    texto confirmando que se guardó, sin que el jefe la viera."""
    resultado = control_agent.tomar_foto_webcam()
    if resultado.startswith("No pude"):
        return resultado
    return f"{resultado}\n\n{marcador_imagen('/foto')}"


def _procesar_captura():
    """"screenshot"/"captura"/"captura de pantalla": igual que
    control_agent.tomar_screenshot() de siempre (CERO tokens, solo
    scrot/gnome-screenshot), pero ahora le pega el marcador de imagen
    (ARREGLO 6) para que la captura de verdad se muestre en el HUD o
    se mande por Telegram — antes solo devolvía texto confirmando que
    se guardó, sin que el jefe la viera."""
    resultado = control_agent.tomar_screenshot()
    if resultado.startswith("No pude"):
        return resultado
    return f"{resultado}\n\n{marcador_imagen('/captura')}"


def _procesar_ver_pantalla():
    """"Ve mi pantalla"/"qué hay en mi pantalla": screenshot + Gemini
    Vision (control_agent.screenshot_analizar, SÍ gasta tokens) — manda
    la imagen Y el análisis juntos (ARREGLO 6), no solo el texto."""
    resultado = control_agent.screenshot_analizar()
    if resultado.startswith("No pude capturar tu pantalla"):
        return resultado
    return f"{resultado}\n\n{marcador_imagen('/captura')}"


def _procesar_spotify(texto_usuario):
    """Spotify de solo lectura (ver spotify_agent.py): "configura/
    conecta spotify" dispara la autorización, "últimas canciones"/
    "historial" da el historial reciente, cualquier otra frase del
    grupo pregunta qué está sonando ahorita. CERO tokens."""
    texto_bajo = texto_usuario.lower()
    if any(p in texto_bajo for p in ("configura spotify", "conecta spotify")):
        return spotify_agent.iniciar_configuracion()
    if any(p in texto_bajo for p in ("últimas canciones", "ultimas canciones", "historial de spotify", "historial en spotify")):
        return spotify_agent.recientes_texto()
    return spotify_agent.cancion_actual_texto()


# CERO tokens (Fase F): el contacto/mensaje se extraen con regex en
# vez de pedirle a un LLM que los parsee (a diferencia de
# classroom/correo/finanzas/pendientes, que sí usan un parser de
# Gemini) — a propósito menos flexible con la redacción, para
# garantizar que WhatsApp nunca gaste ni un token.
_PATRONES_WHATSAPP = (
    re.compile(r"(?:manda|env[ií]a)(?:le)?(?:\s+(?:un\s+)?whatsapp)?\s+a\s+(.+?)\s+diciendo\s+(?:que\s+)?(.+)", re.I),
    re.compile(r"escr[ií]bele\s+a\s+(.+?)\s+que\s+(.+)", re.I),
    re.compile(r"escr[ií]bele\s+a\s+(.+?)[:,]\s*(.+)", re.I),
)
_PATRON_GUARDAR_CONTACTO = re.compile(r"guarda(?:r)?\s+el\s+n[uú]mero\s+de\s+(.+?)[:,]\s*(\+?[\d\s\-]{7,})", re.I)


def _procesar_whatsapp(texto_usuario):
    coincidencia_guardar = _PATRON_GUARDAR_CONTACTO.search(texto_usuario)
    if coincidencia_guardar:
        nombre, numero = coincidencia_guardar.group(1).strip(), coincidencia_guardar.group(2).strip()
        ok = whatsapp_agent.guardar_contacto(nombre, numero)
        return f"Listo, guardé el número de {nombre}." if ok else "No pude guardar el contacto."

    for patron in _PATRONES_WHATSAPP:
        coincidencia = patron.search(texto_usuario)
        if coincidencia:
            contacto, mensaje = coincidencia.group(1).strip(), coincidencia.group(2).strip()
            resultado = whatsapp_agent.enviar_mensaje_rapido(contacto, mensaje)
            if resultado.get("error"):
                return (
                    f"No tengo el número de {contacto}, jefe. Dime el número, o guárdalo con "
                    f"'guarda el número de {contacto}: <numero>'."
                )
            return f"Te abrí el chat de {contacto} con el mensaje listo — nomás dale enviar."

    return whatsapp_agent.abrir_whatsapp()


def _procesar_voz(texto_usuario):
    """Botón VOZ del HUD, pero por voz/texto/Telegram: estado real en
    control_agent (_voz_activa), no un evento efímero — así el HUD lo
    refleja via /control/estado-ui sin importar de dónde vino el
    cambio (ver server.py)."""
    texto_bajo = texto_usuario.lower()
    if any(p in texto_bajo for p in PALABRAS_VOZ_DESACTIVAR):
        return control_agent.desactivar_voz()
    return control_agent.activar_voz()


def _procesar_mic(texto_usuario):
    """Botón MIC del HUD, pero por voz/texto/Telegram. Solo deja una
    solicitud en control_agent (_mic_solicitud, "leer y limpia") — el
    MediaRecorder real vive en el navegador, así que esto solo hace
    algo si hay un HUD abierto haciendo polling de /control/estado-ui."""
    texto_bajo = texto_usuario.lower()
    if any(p in texto_bajo for p in PALABRAS_MIC_DESACTIVAR):
        return control_agent.solicitar_mic_desactivar()
    return control_agent.solicitar_mic_activar()


def _procesar_ayuda(texto_usuario):
    """"Ayuda"/"qué puedes hacer": si el jefe preguntó por un tema en
    concreto ("ayuda con finanzas", "comandos de whatsapp") regresa solo esa
    sección (ver manual.buscar_seccion); si no, el manual completo.
    CERO tokens — no pasa por Gemini."""
    return manual.buscar_seccion(texto_usuario) or manual.MANUAL_TEXTO


def _procesar_cerrar_todo():
    """"Cierra todo"/"apaga todo menos tú": arma _accion_pendiente
    (CONFIRMAR) mostrando ANTES la lista de ventanas que se van a
    cerrar (ver control_agent.previsualizar_cierre_todo) — mitiga que
    la heurística de "qué es mi propia ventana" no sea perfecta."""
    global _accion_pendiente
    titulos, error = control_agent.previsualizar_cierre_todo()
    if error:
        return f"No pude revisar las ventanas abiertas: {error}"
    if not titulos:
        return "No encontré ventanas para cerrar, jefe."

    _accion_pendiente = {"origen": "cerrar_todo", "datos": None}
    lista = "\n".join(f"- {t}" for t in titulos)
    return (
        f"¿Seguro que quieres que cierre estas {len(titulos)} ventanas?\n{lista}\n"
        "Escribe CONFIRMAR para continuar o cualquier otra cosa para cancelar."
    )


def _procesar_apagar():
    """"Apaga"/"shutdown": NO apaga directo — IRIS sugiere reposo
    primero. Arma _apagar_pendiente (wizard propio, distinto de
    _accion_pendiente porque tiene una tercera salida: "descansa" ->
    suspende en vez de apagar). Ver _despachar caso 0.5."""
    global _apagar_pendiente
    _apagar_pendiente = True
    return (
        "¿Seguro jefe? Si me apago ya no puedo escucharte. ¿No prefieres que me ponga en reposo?\n"
        "Escribe CONFIRMAR para apagar de verdad, o dime que descanse/se ponga en reposo."
    )


def _extraer_busqueda_youtube(texto):
    """Saca la búsqueda de "pon X en youtube"/"busca X en youtube":
    quita "en youtube" y el verbo inicial (pon/busca/reproduce)."""
    sin_youtube = re.sub(r"(?i)\ben\s+youtube\b", "", texto).strip()
    return _quitar_palabra_clave(sin_youtube, ("pon", "busca", "búscame", "buscame", "reproduce"))


_PATRON_DOMINIO = re.compile(r"^[\w.-]+\.[a-z]{2,}(/\S*)?$", re.I)


def _parece_sitio_o_url(texto):
    """True si `texto` es un sitio conocido (ver control_agent.
    SITIOS_CONOCIDOS), ya trae esquema (http/https/www), o tiene pinta
    de dominio (algo.tld) — para decidir abrir_url vs abrir_app sin
    pasar por Gemini."""
    clave = texto.strip().lower()
    if clave in control_agent.SITIOS_CONOCIDOS:
        return True
    if clave.startswith(("http://", "https://", "www.")):
        return True
    return bool(_PATRON_DOMINIO.match(texto.strip()))


# "abre notas.txt" (nombre de archivo suelto, con extensión, sin ruta
# completa): se distingue de "abre spotify"/"abre chrome" (nombre de
# app) por tener una extensión al final — solo en ese caso vale la pena
# probar la búsqueda aproximada de archivo ANTES de rendirse a abrir_app.
_PATRON_EXTENSION_ARCHIVO = re.compile(r"\.\w{1,5}$")


def _procesar_abrir_por_nombre_aproximado(nombre):
    """ARREGLO 2: "abre X.ext" donde X no es una ruta completa y no
    existe tal cual — busca coincidencias aproximadas (typos de voz/
    texto) con difflib en las carpetas relevantes del jefe (ver
    file_organizer_agent.buscar_similar). Devuelve None si no encontró
    nada (para que _procesar_abrir caiga a abrir_app como antes)."""
    candidatos = file_organizer_agent.buscar_similar(nombre)
    if not candidatos:
        return None

    if len(candidatos) == 1:
        ruta = candidatos[0]
        mensaje = control_agent.abrir_archivo(ruta)
        if mensaje.startswith("Abrí"):
            return f"No encontré '{nombre}' exacto, pero {mensaje[0].lower()}{mensaje[1:]} (asumo que te referías a eso)."
        return mensaje

    listado = "\n".join(f"{i + 1}. {os.path.basename(c)}" for i, c in enumerate(candidatos))
    return f"No encontré '{nombre}' exacto, pero encontré esto parecido:\n{listado}\n¿Cuál de estos abro, jefe?"


def _procesar_abrir(texto_usuario):
    """"Abre X" / "pon X" (X = sitio conocido): determinístico, CERO
    tokens — reemplaza el viejo camino de pedirle a Gemini que decida
    entre abrir_url/abrir_app/abrir_archivo. Prioridad: ruta de archivo
    explícita -> abrir_archivo; sitio conocido/URL -> abrir_url;
    nombre de archivo suelto con extensión que no existe tal cual ->
    búsqueda aproximada (ARREGLO 2); cualquier otra cosa -> abrir_app
    (busca el .desktop/ejecutable)."""
    texto_bajo = texto_usuario.lower()
    if any(p in texto_bajo for p in PALABRAS_ABRIR):
        objetivo = _quitar_palabra_clave(texto_usuario, PALABRAS_ABRIR)
    else:
        objetivo = _quitar_palabra_clave(texto_usuario, ("pon",))
    objetivo = objetivo.strip()
    if not objetivo:
        return "¿Qué quieres que abra, jefe?"

    ruta = _extraer_ruta_archivo(objetivo)
    if ruta:
        return control_agent.abrir_archivo(ruta)

    if _parece_sitio_o_url(objetivo):
        return f"Abriendo {objetivo}." if control_agent.abrir_url(objetivo) else f"No pude abrir '{objetivo}'."

    if _PATRON_EXTENSION_ARCHIVO.search(objetivo):
        resultado_aproximado = _procesar_abrir_por_nombre_aproximado(objetivo)
        if resultado_aproximado is not None:
            return resultado_aproximado

    return control_agent.abrir_app(objetivo)


def _procesar_abrir_proyecto(texto_usuario):
    """"Abre el proyecto X" -> control_agent.abrir_proyecto(X): abre la
    carpeta proyectos/X en el gestor de archivos. Quita la frase de
    apertura para quedarse solo con el nombre del proyecto."""
    nombre = _quitar_palabra_clave(texto_usuario, PALABRAS_ABRIR_PROYECTO)
    return control_agent.abrir_proyecto(nombre)


# Acciones "sin argumento" del grupo control remoto: se revisan en
# ESTE orden (la primera frase que matchee gana) — ver _procesar_control_remoto,
# que maneja aparte las que sí necesitan argumento (YouTube, escribir_especial,
# leer/buscar archivo) o un wizard (cerrar todo, cerrar ventana, apagar).
_ACCIONES_CONTROL_REMOTO_SIMPLES = (
    (PALABRAS_PESTANA_ANTERIOR, control_agent.anterior_pestana),
    (PALABRAS_PESTANA_SIGUIENTE, control_agent.siguiente_pestana),
    (PALABRAS_PESTANA_CERRAR, control_agent.cerrar_pestana),
    (PALABRAS_PESTANA_NUEVA, control_agent.nueva_pestana),
    (PALABRAS_PANTALLA_COMPLETA, control_agent.pantalla_completa),
    (PALABRAS_VENTANA_ANTERIOR, control_agent.anterior_ventana),
    (PALABRAS_VENTANA_SIGUIENTE, control_agent.siguiente_ventana),
    (PALABRAS_VENTANA_MAXIMIZAR, control_agent.maximizar_ventana),
    (PALABRAS_VENTANA_MINIMIZAR, control_agent.minimizar_ventana),
    (PALABRAS_VENTANAS_LISTAR, control_agent.listar_ventanas),
    (PALABRAS_MEDIA_SIGUIENTE, control_agent.siguiente_track),
    (PALABRAS_MEDIA_ANTERIOR, control_agent.anterior_track),
    (PALABRAS_SILENCIA, control_agent.silenciar),
    (PALABRAS_VOLUMEN_SUBIR, control_agent.subir_volumen),
    (PALABRAS_VOLUMEN_BAJAR, control_agent.bajar_volumen),
    (PALABRAS_BRILLO_SUBIR, control_agent.subir_brillo),
    (PALABRAS_BRILLO_BAJAR, control_agent.bajar_brillo),
    (PALABRAS_APAGA_PANTALLA, control_agent.apagar_pantalla),
    (PALABRAS_PRENDE_PANTALLA, control_agent.prender_pantalla),
    (PALABRAS_ENTER, control_agent.escribir_enter),
    (PALABRAS_DICTAR, control_agent.dictar),
    (PALABRAS_CLICK_DERECHO, control_agent.click_derecho_mouse),
    (PALABRAS_DOBLE_CLICK, control_agent.doble_click),
    (PALABRAS_CLICK, control_agent.click_mouse),
    (PALABRAS_SCROLL_ARRIBA, control_agent.scroll_arriba),
    (PALABRAS_SCROLL_ABAJO, control_agent.scroll_abajo),
    (PALABRAS_ESTADO, control_agent.estado_sistema),
    (PALABRAS_DESCANSA, control_agent.suspender),
    (PALABRAS_BLOQUEATE, control_agent.bloquear),
    (PALABRAS_FOTO, _procesar_foto_webcam),
    (PALABRAS_VER_PANTALLA, _procesar_ver_pantalla),
    (PALABRAS_CAPTURA, _procesar_captura),
    (PALABRAS_GRABA_PANTALLA, control_agent.grabar_pantalla),
    (PALABRAS_PARA_GRABAR, control_agent.parar_grabacion),
)


def _procesar_control_remoto(texto_usuario):
    """Control remoto de pestañas/ventanas/media/audio/pantalla/mouse/
    escritura/sistema/archivos por voz o texto (Fase H2): siempre
    control_agent.py, CERO tokens salvo "ve mi pantalla"
    (screenshot_analizar, la única que gasta tokens de Gemini Vision).
    "cierra app/ventana", "cierra todo" y "apaga" son las ÚNICAS
    acciones de este grupo que piden CONFIRMAR (o un wizard propio,
    ver _procesar_apagar); el resto se ejecuta directo."""
    global _accion_pendiente
    texto_bajo = texto_usuario.lower()

    if any(p in texto_bajo for p in PALABRAS_CERRAR_TODO):
        return _procesar_cerrar_todo()

    if any(p in texto_bajo for p in PALABRAS_VENTANA_CERRAR):
        _accion_pendiente = {"origen": "cerrar_ventana", "datos": None}
        return (
            "¿Seguro que quieres que cierre la ventana/app activa?\n"
            "Escribe CONFIRMAR para continuar o cualquier otra cosa para cancelar."
        )

    if any(p in texto_bajo for p in PALABRAS_APAGA_SISTEMA):
        return _procesar_apagar()

    if any(p in texto_bajo for p in PALABRAS_YOUTUBE_PON):
        return control_agent.abrir_en_youtube(_extraer_busqueda_youtube(texto_usuario))

    if any(p in texto_bajo for p in PALABRAS_BORRA_ESO):
        return control_agent.escribir_especial("backspace")
    if any(p in texto_bajo for p in PALABRAS_SELECCIONA_TODO):
        return control_agent.escribir_especial("selecciona todo")
    if any(p in texto_bajo for p in PALABRAS_COPIA_TECLADO):
        return control_agent.escribir_especial("copia")
    if any(p in texto_bajo for p in PALABRAS_PEGA_TECLADO):
        return control_agent.escribir_especial("pega")
    if any(p in texto_bajo for p in PALABRAS_GUARDA_TECLADO):
        return control_agent.escribir_especial("guarda")
    if any(p in texto_bajo for p in PALABRAS_DESHACER):
        return control_agent.escribir_especial("deshacer")

    if any(p in texto_bajo for p in PALABRAS_LEE_ARCHIVO):
        ruta = _extraer_ruta_archivo(texto_usuario)
        if not ruta:
            return "¿Cuál es la ruta completa del archivo que quieres que lea, jefe?"
        return control_agent.leer_archivo(ruta)

    if any(p in texto_bajo for p in PALABRAS_DONDE_QUEDO):
        nombre = _quitar_palabra_clave(texto_usuario, PALABRAS_DONDE_QUEDO)
        return control_agent.buscar_archivo(nombre)

    for palabras, accion in _ACCIONES_CONTROL_REMOTO_SIMPLES:
        if any(p in texto_bajo for p in palabras):
            return accion()

    if any(p in texto_bajo for p in PALABRAS_ESCRIBIR):
        texto = _quitar_palabra_clave(texto_usuario, PALABRAS_ESCRIBIR)
        return control_agent.escribir_texto(texto)

    # PALABRAS_MEDIA_PLAY_PAUSE ("pausa"/"play"/"resume") al final: son
    # las palabras más genéricas del grupo, para que las más
    # específicas de arriba (pestaña/ventana/track/etc) le ganen si el
    # mensaje trae varias.
    return control_agent.play_pause()


# BUG2: "baja el segundo"/"descarga el tercero" no traen ningún dígito
# — se reconocen por palabra ordinal (1-5 basta, las listas de
# investigar()/buscar_documentos() nunca traen más de 5, ver `limite`
# en research_agent.py). Se revisan como palabra completa (\b...\b)
# para no matchear "uno" dentro de otra palabra.
_PALABRAS_ORDINALES = {
    "primero": 1, "primera": 1, "primer": 1, "uno": 1,
    "segundo": 2, "segunda": 2, "dos": 2,
    "tercero": 3, "tercera": 3, "tercer": 3, "tres": 3,
    "cuarto": 4, "cuarta": 4, "cuatro": 4,
    "quinto": 5, "quinta": 5, "cinco": 5,
}


def _parsear_indice(texto):
    """Saca el primer número que aparezca en el texto (ej. "el 2",
    "2", "número 2 porfa"). Si no hay ningún dígito, prueba con una
    palabra ordinal hablada (ej. "baja el segundo", "descarga el
    tercero" — ver BUG2/_PALABRAS_ORDINALES). None si no reconoce
    nada de eso."""
    coincidencia = re.search(r"\d+", texto)
    if coincidencia:
        return int(coincidencia.group(0))

    texto_bajo = texto.lower()
    for palabra, valor in _PALABRAS_ORDINALES.items():
        if re.search(rf"\b{palabra}\b", texto_bajo):
            return valor
    return None


def _extraer_ruta_archivo(texto):
    """Saca una ruta de archivo del mensaje (ej. "resume este pdf
    ~/Descargas/algo.pdf"). Solo reconoce rutas explícitas
    (empiezan con / o ~), no nombres sueltos, para no confundir
    palabras del mensaje con una ruta."""
    coincidencia = re.search(r"[~/][^\s]+", texto)
    if not coincidencia:
        return None
    return os.path.expanduser(coincidencia.group(0))


def _extraer_url(texto):
    """Saca la primera URL http(s) del mensaje (ej. "resume este video
    https://youtube.com/watch?v=..."). A diferencia de
    _extraer_ruta_archivo (rutas locales), esto es para links reales."""
    coincidencia = re.search(r"https?://\S+", texto)
    if not coincidencia:
        return None
    return coincidencia.group(0).rstrip(").,;\"'")


def _procesar_investigacion(texto_usuario):
    """Rutea los distintos comandos de research_agent:
    - "resume el/este pdf <ruta>": resume directo, ofrece guardar en Notion.
    - "resume este video <url>": extrae la transcripción y la resume
      directo (ver research_agent.resumir_video_youtube), sin buscar
      primero — ofrece guardar en Notion igual que un PDF.
    - "busca videos de X" / "busca pdfs de X" / "investiga sobre X":
      presenta opciones y deja _investigacion_pendiente para que el
      siguiente mensaje del usuario elija por número o descargue
      ("descarga el número 2", "el 2", "baja el segundo" — ver BUG2/
      _parsear_indice), igual que el flujo completo de investigar().
      Para videos, "descargar" en realidad resume la transcripción
      (ver research_agent.procesar_seleccion, que distingue por URL)."""
    global _investigacion_pendiente, _resumen_pendiente_notion
    texto_bajo = texto_usuario.lower()

    if any(p in texto_bajo for p in PALABRAS_RESUMIR_PDF):
        ruta = _extraer_ruta_archivo(texto_usuario)
        if not ruta:
            return "¿Cuál es la ruta completa del PDF que quieres que resuma?"
        resumen = research_agent.resumir_documento(ruta)
        if resumen.startswith("ERROR:"):
            return resumen
        _resumen_pendiente_notion = {"titulo": os.path.basename(ruta), "contenido": resumen}
        return resumen + "\n\n¿Quieres que guarde este resumen en Notion, o como nota de estudio en Obsidian?"

    # Va ANTES que PALABRAS_VIDEO a propósito: "resume este video
    # https://..." también contiene "video" y caería a la rama de
    # búsqueda si se revisara después.
    if any(p in texto_bajo for p in PALABRAS_RESUMIR_VIDEO):
        url = _extraer_url(texto_usuario)
        if not url:
            return "¿Cuál es el link del video que quieres que resuma?"
        resumen = research_agent.resumir_video_youtube(url)
        if resumen.startswith("ERROR:"):
            return resumen
        _resumen_pendiente_notion = {"titulo": "Resumen de video de YouTube", "contenido": resumen}
        return resumen + "\n\n¿Quieres que guarde este resumen en Notion, o como nota de estudio en Obsidian?"

    if any(p in texto_bajo for p in PALABRAS_VIDEO):
        tema = _quitar_palabra_clave(texto_usuario, PALABRAS_WEB + PALABRAS_VIDEO)
        videos = research_agent.buscar_youtube(tema)
        if isinstance(videos, dict) and videos.get("error"):
            return f"No pude buscar videos de '{tema}': {videos['error']}"
        if not videos:
            return f"No encontré videos sobre '{tema}'."
        lineas = [f"{i + 1}. {v['titulo']} - {v['url']} ({v['canal'] or 'canal desconocido'})" for i, v in enumerate(videos)]
        # Se recuerda la lista igual que con PDFs (ver BUG2) — "resume
        # el número 2"/"el segundo" en el siguiente mensaje resume la
        # transcripción de ese video (ver research_agent.procesar_
        # seleccion, que distingue YouTube de un documento normal).
        _investigacion_pendiente = [{"titulo": v["titulo"], "url": v["url"]} for v in videos]
        return "Encontré estos videos:\n" + "\n".join(lineas) + "\n¿Quieres que resuma alguno? Dime el número."

    if any(p in texto_bajo for p in PALABRAS_PDF):
        tema = _quitar_palabra_clave(texto_usuario, PALABRAS_WEB + PALABRAS_PDF)
        documentos = research_agent.buscar_documentos(tema)
        if isinstance(documentos, dict) and documentos.get("error"):
            return f"No pude buscar PDFs de '{tema}': {documentos['error']}"
        if not documentos:
            return f"No encontré PDFs sobre '{tema}'."
        lineas = [f"{i + 1}. {d['titulo']} - {d['url']}" for i, d in enumerate(documentos)]
        # BUG2: se recuerda la lista para que "descarga el número 2"/"el
        # 2"/"baja el segundo" en el SIGUIENTE mensaje la resuelva (ver
        # _despachar, caso 2 — mismo wizard que ya usaba investigar()).
        _investigacion_pendiente = documentos
        return "Encontré estos PDFs:\n" + "\n".join(lineas) + "\n¿Quieres que descargue alguno? Dime el número."

    tema = _quitar_palabra_clave(texto_usuario, ("investiga",)) or texto_usuario
    resultado = research_agent.investigar(tema)
    if resultado.get("error"):
        return f"No pude investigar sobre '{tema}': {resultado['error']}"

    _investigacion_pendiente = resultado["documentos"]
    return resultado["mensaje"]


def _procesar_conocimiento(texto_usuario, historial, system_prompt):
    """Pregunta de conocimiento ("quién es X", "qué es Y", "explícame Z"):
    Gemini responde con lo que ya sabe (como chat normal) y se le
    agrega la oferta de armar un documento más completo en Notion.
    Guarda el tema en _tema_pendiente_notion para cuando el usuario
    responda que sí (ver procesar_mensaje)."""
    global _tema_pendiente_notion

    respuesta = _procesar_chat_normal(texto_usuario, historial, system_prompt)

    tema = _quitar_palabra_clave(texto_usuario, PALABRAS_CONOCIMIENTO)
    _tema_pendiente_notion = tema if tema else texto_usuario

    return respuesta + "\n\n¿Quieres que te arme un documento más completo en Notion?"


def _generar_documento_notion(tema, texto_usuario=""):
    """Genera un documento largo sobre `tema` con Groq y lo guarda como
    página nueva en Notion. Si el usuario registró varias bases en
    config/notion_bases.json (ver notion_memoria), elige la base según el
    mensaje/tema y devuelve el nombre de la base + la URL de la página; si
    no hay bases registradas, cae al flujo clásico de un solo
    NOTION_DATABASE_ID. Nunca lanza: todo error se refleja en el texto."""
    prompt_groq = _PROMPT_GROQ_NOTION.format(tema=tema)
    contenido = groq_agent.generar_contenido(prompt_groq, system_prompt=_SYSTEM_PROMPT_GROQ_NOTION)

    if contenido.startswith("ERROR:"):
        log.warning("director: Groq falló generando el documento (%s)", contenido)
        return f"No pude generar el documento: {contenido}"

    titulo = tema.strip()[:200] or "Documento"

    # Multi-base: elige por lo que pidió el jefe (o el tema); si no matchea
    # ninguna en concreto, usa la primera registrada.
    base = notion_memoria.elegir_base(f"{texto_usuario} {tema}") or notion_memoria.base_por_defecto()
    if base is not None:
        resultado = notion_memoria.guardar(base, titulo, contenido)
        if resultado.get("error"):
            log.warning("director: Notion falló guardando el documento (%s)", resultado["error"])
        return notion_memoria.mensaje_guardado(base, resultado, titulo)

    # Sin bases registradas: comportamiento de siempre (un solo database).
    resultado = notion_agent.crear_pagina(titulo=titulo, contenido=contenido)
    if resultado.get("error"):
        log.warning("director: Notion falló guardando el documento (%s)", resultado["error"])
        return f"Generé el contenido pero no lo pude guardar en Notion: {resultado['error']}"

    return "Listo jefe, ya te dejé el documento en Notion."


_PROMPT_GROQ_OBSIDIAN = """Genera contenido de ESTUDIO completo y detallado sobre: {tema}.
Es para una nota de repaso académico, no un documento genérico.
Incluye: definición, características/puntos clave, ejemplos si aplica, y conceptos relacionados.
En español, claro y bien organizado. Mínimo 300 palabras."""


def _extraer_tema_obsidian(texto_usuario):
    """Saca el tema de una frase de crear nota de Obsidian. Primero
    intenta el camino normal (_quitar_palabra_clave con las frases
    literales de PALABRAS_OBSIDIAN_CREAR); si ninguna matcheó fue
    porque "obsidian" apareció EN MEDIO de la frase rompiendo el orden
    esperado (ej. "crea una nota de estudio EN OBSIDIAN sobre la
    fotosíntesis" — ver _VERBOS_OBSIDIAN_CREAR en _detectar_intencion),
    así que en ese caso se quita la palabra "obsidian" y se toma lo que
    sigue al ÚLTIMO "sobre"/"de" del mensaje."""
    directo = _quitar_palabra_clave(texto_usuario, PALABRAS_OBSIDIAN_CREAR)
    if directo != texto_usuario.strip():
        return directo

    sin_obsidian = re.sub(r"\bobsidian\b", "", texto_usuario, flags=re.I).strip()
    coincidencias = list(re.finditer(r"\b(?:sobre|de)\s+", sin_obsidian, re.I))
    if coincidencias:
        return sin_obsidian[coincidencias[-1].end():].strip(" :,.-")
    return sin_obsidian


_PROMPT_PARSEAR_OBSIDIAN_PROYECTO = """El jefe pide crear una nota de ESTUDIO en Obsidian relacionada con uno
de sus proyectos escolares/personales. Los proyectos se rastrean aparte en Notion (avance/estado) — esto es
SOLO el material de estudio, independiente de eso.

Devuelve SOLO un JSON así, nada más:
{{
  "tema": "el tema puntual de la nota de estudio (de qué trata el contenido)",
  "proyecto": "el nombre/identificador del proyecto que menciona, tal cual lo dijo"
}}

Mensaje del usuario: {mensaje}"""


def _procesar_obsidian_crear_para_proyecto(texto_usuario):
    """"...para mi proyecto de X" / "...para el proyecto de X": además
    de generar la nota de estudio (mismo Groq que _procesar_obsidian_
    crear), la organiza en la subcarpeta de ESE proyecto (ver
    obsidian_agent.crear_nota_por_proyecto) — resuelve el nombre real
    del proyecto contra Notion (proyectos_agent.resolver_proyecto) para
    que la subcarpeta coincida con el título real y no con lo que el
    jefe haya abreviado al hablar. El seguimiento de avance/estado del
    proyecto sigue 100% en Notion — esto NUNCA le agrega un avance ni
    toca esa página, solo organiza las notas de estudio en el vault."""
    crudo = balancer.enviar_mensaje(
        prompt=_PROMPT_PARSEAR_OBSIDIAN_PROYECTO.format(mensaje=texto_usuario), historial=[], system_instruction=None,
    )
    datos = _extraer_json(crudo) if not crudo.startswith("ERROR:") else None
    tema = ((datos or {}).get("tema") or "").strip()
    identificador_proyecto = ((datos or {}).get("proyecto") or "").strip()

    if not tema or not identificador_proyecto:
        return "¿De qué proyecto y sobre qué tema quieres la nota, jefe?"

    proyecto = proyectos_agent.resolver_proyecto(identificador_proyecto)
    nombre_proyecto = proyecto["titulo"] if proyecto else identificador_proyecto

    contenido = groq_agent.generar_contenido(_PROMPT_GROQ_OBSIDIAN.format(tema=tema))
    if contenido.startswith("ERROR:"):
        return f"No pude generar el contenido: {contenido}"

    resultado = obsidian_agent.crear_nota_por_proyecto(nombre_proyecto, tema, contenido)
    if resultado.get("error"):
        return f"Generé el contenido pero no lo pude guardar en Obsidian: {resultado['error']}"
    return (
        f"Listo jefe, ya te dejé la nota de estudio '{resultado['titulo']}' en Obsidian, "
        f"dentro del proyecto '{nombre_proyecto}'."
    )


def _procesar_obsidian_crear(texto_usuario):
    """"Crea nota de estudio de X" / "haz una nota de X" / "apunta en
    Obsidian sobre X": genera contenido de estudio con Groq (mismo
    patrón que _generar_documento_notion, pero SIEMPRE hacia el vault
    de Obsidian, nunca Notion — ver obsidian_agent.py, exclusivo para
    apuntes académicos) y lo guarda con formato de estudio (headers +
    wikilinks a conceptos relacionados, ver
    obsidian_agent.crear_nota_estudio).

    "guarda esto en Obsidian" SIN tema (nada que generar de cero) cae
    aquí solo cuando NO hay un resumen de investigación pendiente — ese
    caso lo resuelve _despachar (caso 3) ANTES de llegar a este
    intent, guardando el resumen ya generado en vez de inventar uno
    nuevo.

    "...para mi proyecto de X" desvía a _procesar_obsidian_crear_para_
    proyecto (organiza la nota en la subcarpeta de ESE proyecto) —
    checa "proyecto" ANTES que nada más porque esa frase también trae
    palabras de PALABRAS_OBSIDIAN_CREAR y el caso general las
    consumiría sin enterarse del proyecto."""
    if "proyecto" in texto_usuario.lower():
        return _procesar_obsidian_crear_para_proyecto(texto_usuario)

    tema = _extraer_tema_obsidian(texto_usuario).strip()
    if not tema:
        return "¿Sobre qué tema quieres la nota de estudio, jefe?"

    contenido = groq_agent.generar_contenido(_PROMPT_GROQ_OBSIDIAN.format(tema=tema))
    if contenido.startswith("ERROR:"):
        return f"No pude generar el contenido: {contenido}"

    resultado = obsidian_agent.crear_nota_estudio(tema, contenido)
    if resultado.get("error"):
        return f"Generé el contenido pero no lo pude guardar en Obsidian: {resultado['error']}"
    return f"Listo jefe, ya te dejé la nota de estudio '{resultado['titulo']}' en tu vault de Obsidian."


def _extraer_num_preguntas(texto):
    """Saca el número de preguntas pedido (ej. "examen de 5 preguntas
    sobre la fotosíntesis" -> 5). None si el mensaje no especifica
    ninguno (ver _procesar_examen, que cae al default de examen_agent)."""
    coincidencia = re.search(r"(\d+)\s*preguntas?", texto.lower())
    return int(coincidencia.group(1)) if coincidencia else None


def _extraer_tema_examen(texto_usuario):
    """Saca el tema de una frase de examen. Primero quita "N preguntas"
    si lo trae (ej. "examen de 5 preguntas sobre X"), y LUEGO el prefijo
    de PALABRAS_EXAMEN — necesario en ese orden porque "hazme un examen"/
    "hazme una prueba"/"hazme un quiz" (a diferencia de "examen de"/
    "examen sobre", que ya incluyen el conector) no consumen el "de"/
    "sobre" que sigue, así que también se quita ese conector suelto que
    pueda quedar al principio."""
    sin_num_preguntas = re.sub(r"(?:de\s+)?\d+\s*preguntas?\s*", "", texto_usuario, flags=re.I)
    tema = _quitar_palabra_clave(sin_num_preguntas, PALABRAS_EXAMEN)
    tema = re.sub(r"^(de|sobre)\s+", "", tema, flags=re.I)
    return tema.strip(" :,.-")


def _procesar_examen(texto_usuario):
    """"Hazme un examen de X" / "examen de este pdf" / "examen de mis
    apuntes de X": genera un examen de opción múltiple con examen_agent
    (Groq) y lo arranca como el examen ACTIVO. A partir de aquí las
    respuestas van por /examen/responder (HUD) o directo por Telegram
    (ver telegram_agent.manejar_texto) — NO por procesar_mensaje, así
    que esta función solo genera y arranca el estado, nunca conduce el
    examen pregunta por pregunta.

    El marcador "[EXAMEN]" al final de la respuesta (mismo patrón que
    marcador_imagen/"[IMAGEN:...]") le dice al HUD que cambie a la
    vista de examen y empiece a pedir /examen/actual."""
    texto_bajo = texto_usuario.lower()
    num_preguntas = _extraer_num_preguntas(texto_usuario) or 10
    materia = None

    if any(p in texto_bajo for p in _PALABRAS_EXAMEN_PDF_PISTA):
        ruta = _extraer_ruta_archivo(texto_usuario)
        if not ruta and os.path.exists(examen_agent.RUTA_PDF_SUBIDO):
            ruta = examen_agent.RUTA_PDF_SUBIDO
        if not ruta:
            return "No tengo ningún PDF a la mano, jefe — súbelo con el botón del HUD o dame la ruta completa."
        resultado = examen_agent.generar_examen_de_pdf(ruta, num_preguntas)

    elif any(p in texto_bajo for p in _PALABRAS_EXAMEN_APUNTES_PISTA):
        materia = _quitar_palabra_clave(texto_usuario, ("de mis apuntes de", "de mis notas de", "apuntes de", "notas de"))
        if not materia:
            return "¿De qué materia quieres el repaso, jefe?"
        resultado = examen_agent.generar_examen_de_apuntes(materia, num_preguntas)

    else:
        tema = _extraer_tema_examen(texto_usuario)
        if not tema:
            return "¿Sobre qué tema quieres el examen, jefe?"
        resultado = examen_agent.generar_examen_de_tema(tema, num_preguntas)

    if resultado.get("error"):
        return f"No pude generar el examen: {resultado['error']}"

    examen_agent.iniciar_examen(resultado["preguntas"], tema=resultado["tema"], materia=materia)
    return (
        f"Listo jefe, examen de {len(resultado['preguntas'])} preguntas sobre "
        f"'{resultado['tema']}' listo. [EXAMEN]"
    )


def _procesar_examen_repaso_rapido():
    """Responde que sí a la sugerencia del briefing ("¿quieres un examen
    rápido de repaso de lo que estudiaste ayer?", ver
    daily_briefing_agent.MARCA_SUGERENCIA_EXAMEN): usa la nota de
    estudio MÁS RECIENTE de Obsidian como proxy de "lo que estudiaste
    ayer" — no hay forma de saber el tema exacto sin que el jefe lo diga."""
    notas = obsidian_agent.listar_notas(limite=1)
    if not notas:
        return "No tengo notas de estudio recientes en Obsidian para armarte un examen, jefe — dime sobre qué tema quieres uno."

    resultado = examen_agent.generar_examen_de_nota(notas[0]["titulo"], 5)
    if resultado.get("error"):
        return f"No pude generar el examen: {resultado['error']}"

    examen_agent.iniciar_examen(resultado["preguntas"], tema=resultado["tema"])
    return f"Va, examen rápido de {len(resultado['preguntas'])} preguntas sobre '{resultado['tema']}'. [EXAMEN]"


def _procesar_chat_normal(texto_usuario, historial, system_prompt):
    if offline_agent.modo_offline_forzado():
        log.info("director: modo offline forzado manualmente, usando Ollama directo")
        return offline_agent.obtener_respuesta_offline(
            prompt=texto_usuario, historial=historial, system_instruction=system_prompt,
        )

    # Chequeo real de internet ANTES de intentar Gemini (no después):
    # sin esto, cada mensaje sin internet perdía tiempo probando las
    # 5 keys gratuitas + la de pago (6 intentos que fallan igual) antes
    # de recién ahí caer a Ollama, sumando decenas de segundos extra
    # encima de los 20-30s que ya tarda Ollama en frío en este equipo.
    if not offline_agent.hay_internet():
        log.info("director: sin internet (chequeo real a 8.8.8.8), usando Ollama directo")
        return offline_agent.obtener_respuesta_offline(
            prompt=texto_usuario, historial=historial, system_instruction=system_prompt,
        )

    respuesta = balancer.enviar_mensaje(
        prompt=texto_usuario, historial=historial, system_instruction=system_prompt,
    )

    if respuesta.startswith("ERROR:"):
        # Había internet (el TCP a 8.8.8.8 conectó) pero Gemini falló
        # de todos modos (las 6 keys con rate limit, revocadas, etc);
        # Ollama como último recurso igual.
        log.warning("director: Gemini falló pese a haber internet, probando Ollama")
        respuesta = offline_agent.obtener_respuesta_offline(
            prompt=texto_usuario, historial=historial, system_instruction=system_prompt,
        )

    return respuesta


# Intents que necesitan la laptop físicamente prendida (cámara, mouse/
# teclado, navegador visible, ejecutar código arbitrario) — bloqueados
# en modo nube (ver config.MODO_NUBE/cloud_bot.py) con un mensaje claro
# en vez de tronar contra un agente que no se importó (ver el bloque de
# imports condicionales/_ModuloLocal al inicio del archivo).
INTENTS_SOLO_LOCAL = frozenset({
    "control", "control_remoto", "voz", "mic", "elegir",
    "observador", "clipboard", "archivos", "buscar_carpeta", "abrir_ultimo",
    "abrir", "figura", "programar", "proyecto_completo", "whatsapp",
    "classroom", "nexus", "obsidian_crear", "obsidian_abrir", "cerebro_archivos",
})

_MENSAJE_SOLO_LOCAL = (
    "Eso necesita que tu laptop esté prendida, jefe — ahorita estoy corriendo en la nube "
    "nada más para chat, pendientes, recordatorios, calendario, correo, finanzas, proyectos, "
    "Notion e investigación. En cuanto prendas la laptop, esto vuelve a funcionar solo."
)


def _rutear_por_intencion(texto_usuario, historial, system_prompt):
    intencion = _detectar_intencion(texto_usuario)

    if config.MODO_NUBE and intencion in INTENTS_SOLO_LOCAL:
        return _MENSAJE_SOLO_LOCAL

    if intencion in _INTENTS_PATRON:
        memory.guardar_memoria(texto=intencion, tipo="patron")

    if intencion == "control":
        return _procesar_control(texto_usuario)
    if intencion == "recordatorio":
        return _procesar_recordatorio(texto_usuario)
    if intencion == "calendario":
        return _procesar_calendario(texto_usuario)
    if intencion == "correo":
        return _procesar_correo(texto_usuario)
    if intencion == "classroom":
        return _procesar_classroom(texto_usuario)
    if intencion == "nexus":
        return _procesar_nexus(texto_usuario)
    if intencion == "finanzas":
        return _procesar_finanzas(texto_usuario)
    if intencion == "pendientes":
        return _procesar_pendientes(texto_usuario)
    if intencion == "proyectos":
        return _procesar_proyectos(texto_usuario)
    if intencion == "elegir":
        return _procesar_elegir(texto_usuario)
    if intencion == "observador":
        return _procesar_observador(texto_usuario)
    if intencion == "clipboard":
        return _procesar_clipboard(texto_usuario)
    if intencion == "archivos":
        return _procesar_archivos(texto_usuario)
    if intencion == "buscar_carpeta":
        return _procesar_buscar_carpeta(texto_usuario)
    if intencion == "cerebro_archivos":
        return _procesar_cerebro_archivos(texto_usuario)
    if intencion == "abrir_ultimo":
        return _procesar_abrir_ultimo()
    if intencion == "figura":
        return _procesar_figura(texto_usuario)
    if intencion == "programar":
        return _procesar_programar(texto_usuario)
    if intencion == "proyecto_completo":
        return _procesar_proyecto_completo(texto_usuario)
    if intencion == "spotify":
        return _procesar_spotify(texto_usuario)
    if intencion == "obsidian_crear":
        return _procesar_obsidian_crear(texto_usuario)
    if intencion == "obsidian_abrir":
        return obsidian_agent.abrir_obsidian()
    if intencion == "examen":
        return _procesar_examen(texto_usuario)
    if intencion == "whatsapp":
        return _procesar_whatsapp(texto_usuario)
    if intencion == "voz":
        return _procesar_voz(texto_usuario)
    if intencion == "mic":
        return _procesar_mic(texto_usuario)
    if intencion == "ayuda":
        return _procesar_ayuda(texto_usuario)
    if intencion == "control_remoto":
        return _procesar_control_remoto(texto_usuario)
    if intencion == "abrir":
        return _procesar_abrir(texto_usuario)
    if intencion == "repositorio":
        return control_agent.abrir_repositorio()
    if intencion == "abrir_proyecto":
        return _procesar_abrir_proyecto(texto_usuario)
    if intencion == "briefing":
        return _procesar_briefing(texto_usuario)
    if intencion == "conocimiento":
        return _procesar_conocimiento(texto_usuario, historial, system_prompt)
    if intencion == "investigacion":
        return _procesar_investigacion(texto_usuario)
    if intencion == "web":
        return _procesar_web(texto_usuario)
    return _procesar_chat_normal(texto_usuario, historial, system_prompt)


# Palabras demasiado comunes en español (y muletillas propias de cómo le
# habla el jefe a IRIS) como para servir de pista de búsqueda en
# memory.buscar_memoria_relevante() — de incluirlas, cualquier mensaje
# "matchearía" memorias al azar por esa palabra sola.
_STOPWORDS_MEMORIA = {
    "para", "esto", "esta", "estos", "estas", "pero", "como", "cuando",
    "donde", "porque", "sobre", "desde", "hasta", "entre", "todo", "toda",
    "todos", "todas", "algo", "alguna", "alguno", "algunos", "algunas",
    "tiene", "tengo", "quiero", "puedes", "podrias", "dime", "oye",
    "jefe", "iris", "ares", "creo", "hacer", "hecho", "estar",
    "estoy", "estas", "estamos", "estan", "hola", "gracias", "favor",
    "cosas", "cosa", "vamos", "vamos", "ahorita", "ahora", "luego",
}


def _construir_contexto(texto_usuario, buscar_memoria=True, sesion="hud"):
    """Arma (historial, system_prompt) para el turno actual: el
    historial de context_engine (solo esta sesión, se pierde al
    reiniciar) más, si hay algo relevante, memorias de largo plazo
    (Supabase, sobreviven reinicios) que mencionen alguna palabra clave
    del mensaje — así IRIS puede referirse a cosas que el jefe le
    contó en otra sesión, no solo lo de este chat.

    Búsqueda simple por ILIKE (ver memory.buscar_memoria_relevante), no
    semántica: se toman hasta 4 palabras "de contenido" del mensaje
    (4+ letras, fuera de _STOPWORDS_MEMORIA) y se busca cada una por
    separado, tope de 5 memorias en total para no inflar el prompt.

    buscar_memoria=False se usa para los sub-pasos de una cadena
    compuesta (ver _procesar_compuesto): la mayoría rutea a intents que
    ni siquiera usan system_prompt/historial, así que no vale la pena
    pagar hasta 4 búsquedas a Supabase por cada sub-paso."""
    historial = context_engine.obtener_historial(limite=10, sesion=sesion)
    system_prompt = personality.obtener_system_prompt()

    if not buscar_memoria:
        return historial, system_prompt

    palabras_clave = {
        p for p in re.findall(r"\w{4,}", texto_usuario.lower())
        if p not in _STOPWORDS_MEMORIA
    }

    memorias = {}
    for palabra in list(palabras_clave)[:4]:
        for m in memory.buscar_memoria_relevante(palabra, limite=3):
            memorias[m["id"]] = m

    if memorias:
        top = sorted(memorias.values(), key=lambda m: m["created_at"], reverse=True)[:5]
        texto_memorias = "\n".join(f"- {m['texto']}" for m in top)
        system_prompt += (
            "\n\nCosas que recuerdas de conversaciones pasadas con el jefe "
            "(úsalas solo si de verdad vienen al caso con lo que está "
            "preguntando ahora, no las repitas de golpe ni las fuerces "
            "si no aplican):\n" + texto_memorias
        )

    return historial, system_prompt


_PROMPT_PARSEAR_COMPUESTO = """Eres un planificador de instrucciones para IRIS, un asistente de
voz personal. El jefe te dio un mensaje que junta VARIAS peticiones en una sola frase. Sepáralo
en una lista ORDENADA de instrucciones independientes, cada una tal como el jefe se la diría a
IRIS por separado, en su propio turno.

Devuelve SOLO un JSON así, nada más:
{{
  "pasos": ["primera instrucción en lenguaje natural", "segunda instrucción...", "..."]
}}

Reglas:
- Cada paso debe ser una acción CONCRETA e INDEPENDIENTE (recordatorio, pendiente, correo,
  calendario, finanzas, tarea de escuela, WhatsApp, investigar algo, etc.) — algo que IRIS
  podría resolver sola sin necesitar el resultado de otro paso.
- Reusa las palabras/verbos originales del jefe en cada paso en vez de parafrasear, para que
  IRIS reconozca mejor de qué se trata cada uno.
- NO separes en un paso aparte un "guárdalo/súbelo/mándalo a Notion" ni ninguna confirmación
  que sea la continuación natural de investigar o preguntar algo — eso IRIS ya lo resuelve
  sola después.
- Si un paso depende del RESULTADO de otro paso anterior (ej. "revisa mi correo y crea un
  pendiente por cada cosa urgente que encuentres"), NO lo separes — devuélvelo completo, tal
  cual lo dijo el jefe, como un único paso.
- Máximo 5 pasos.
- SOLO responde el JSON, nada más.

Mensaje del usuario: {mensaje}"""


def _despachar(texto_usuario, permitir_compuesto=True, sesion="hud"):
    """Corazón de procesar_mensaje, sin los logs a context_engine/memory
    (esos solo deben pasar UNA vez por turno real, ver procesar_mensaje).
    Se separó para que _procesar_compuesto pueda llamarlo directo por
    cada sub-paso de una cadena, sin ensuciar el historial con
    respuestas sintéticas intermedias.

    permitir_compuesto=False fuerza que este mensaje NUNCA se detecte
    como otra petición compuesta (ver _despachar_normal) — evita que un
    sub-paso mal parafraseado dispare una recursión de planificación
    dentro de otra.

    `sesion` ("hud"/"telegram"/...) solo afecta qué ventana de
    context_engine se lee/escribe (ver _construir_contexto) — los
    wizards de confirmación de abajo (_accion_pendiente y demás) son
    A PROPÓSITO globales, no por sesión: es un solo jefe con un solo
    "cerebro" activo a la vez, sin importar desde qué canal habla."""
    global _accion_pendiente, _tema_pendiente_notion, _resumen_pendiente_notion
    global _investigacion_pendiente, _nexus_config_pendiente, _apagar_pendiente
    global _finanzas_pendiente, _carpeta_pendiente, _ultima_carpeta, _examen_sugerido_pendiente

    # Lo que se guarda en context_engine/memory al final. Normalmente
    # es el mensaje tal cual, PERO el paso de contraseña del wizard de
    # Nexus lo reemplaza por un placeholder (ver más abajo) — esa
    # contraseña nunca debe quedar en el historial ni en Supabase.
    texto_para_historial = texto_usuario

    # 0. Si hay una acción de control/correo esperando confirmación,
    # este mensaje SOLO decide si se ejecuta o se cancela.
    if _accion_pendiente is not None:
        if texto_usuario.strip() == "CONFIRMAR":
            respuesta = _ejecutar_accion_pendiente()
        else:
            _accion_pendiente = None
            respuesta = "Acción cancelada."

    # 0.5. Wizard propio de "apaga" (ver _procesar_apagar): a diferencia
    # del CONFIRMAR genérico de arriba, tiene una tercera salida —
    # "descansa"/"reposo"/"suspende" suspende en vez de apagar, sin
    # pedir nada más.
    elif _apagar_pendiente:
        _apagar_pendiente = False
        texto_bajo_apagar = texto_usuario.strip().lower()
        if texto_usuario.strip() == "CONFIRMAR":
            respuesta = control_agent.apagar()
        elif any(p in texto_bajo_apagar for p in ("descansa", "reposo", "suspende", "suspender")):
            respuesta = control_agent.suspender()
        else:
            respuesta = "Cancelado, jefe. Sigo despierta."

    # 1. Wizard de "configura Nexus": paso 1 pide usuario, paso 2 pide
    # contraseña y guarda encriptado. La contraseña jamás se persiste
    # en texto plano (ver texto_para_historial más abajo).
    elif _nexus_config_pendiente is not None:
        etapa = _nexus_config_pendiente["etapa"]
        if etapa == "usuario":
            _nexus_config_pendiente = {"etapa": "password", "usuario": texto_usuario.strip()}
            respuesta = "Perfecto, ahora dame tu contraseña de Nexus."
        else:
            usuario = _nexus_config_pendiente["usuario"]
            password = texto_usuario.strip()
            _nexus_config_pendiente = None
            ok = nexus_agent.configurar_nexus(usuario, password)
            respuesta = "Listo, guardé tus credenciales de Nexus encriptadas." if ok else "No pude guardar las credenciales de Nexus."
            texto_para_historial = "[contraseña de Nexus omitida por seguridad]"

    # 2. Lista de documentos de investigar() esperando que el usuario
    # elija por número cuál descargar y resumir.
    elif _investigacion_pendiente is not None:
        documentos = _investigacion_pendiente
        _investigacion_pendiente = None
        indice = _parsear_indice(texto_usuario)

        if not indice or not (1 <= indice <= len(documentos)):
            _investigacion_pendiente = documentos
            respuesta = f"No entendí cuál elegiste, dime el número de la lista (1 al {len(documentos)})."
        else:
            resultado = research_agent.procesar_seleccion(documentos[indice - 1], indice)
            # BUG1: la descarga puede haber salido bien aunque el resumen
            # falle después (ver research_agent.procesar_seleccion) — se
            # recuerda la ruta en cualquiera de los dos casos, así "ábrelo"
            # funciona incluso si el resumen no se pudo generar.
            if resultado.get("ruta"):
                context_engine.set_ultimo_archivo_descargado(resultado["ruta"])
            if resultado.get("error"):
                respuesta = resultado["error"]
            else:
                _resumen_pendiente_notion = {"titulo": resultado["titulo"], "contenido": resultado["resumen"]}
                respuesta = resultado["resumen"] + "\n\n¿Quieres que guarde este resumen en Notion, o como nota de estudio en Obsidian?"

    # 2.5. Lista de carpetas de buscar_carpeta() esperando que el
    # usuario elija por número — mismo patrón que investigación.
    elif _carpeta_pendiente is not None:
        pendiente_carpeta = _carpeta_pendiente
        _carpeta_pendiente = None
        candidatos = pendiente_carpeta["candidatos"]
        indice = _parsear_indice(texto_usuario)

        if not indice or not (1 <= indice <= len(candidatos)):
            _carpeta_pendiente = pendiente_carpeta
            respuesta = f"No entendí cuál elegiste, dime el número de la lista (1 al {len(candidatos)})."
        else:
            ruta = candidatos[indice - 1]
            _ultima_carpeta = ruta
            if pendiente_carpeta["abrir"]:
                respuesta = control_agent.abrir_archivo(ruta)
            else:
                respuesta = f"Esa es: {ruta}"

    # 3. Resumen de research_agent esperando confirmación para Notion
    # O Obsidian (baja fricción, igual que _tema_pendiente_notion más
    # abajo). "obsidian" explícito en la respuesta gana sobre el chequeo
    # genérico de afirmación — un "sí"/"dale" a secas sigue yendo a
    # Notion (comportamiento de siempre), Obsidian es EXCLUSIVO para
    # notas de estudio (ver obsidian_agent.py), así que solo se usa si
    # el jefe lo pide explícito.
    elif _resumen_pendiente_notion is not None:
        pendiente_resumen = _resumen_pendiente_notion
        _resumen_pendiente_notion = None

        if "obsidian" in texto_usuario.lower():
            resultado = obsidian_agent.crear_nota_estudio(pendiente_resumen["titulo"], pendiente_resumen["contenido"])
            respuesta = (
                f"No pude guardar la nota en Obsidian: {resultado['error']}" if resultado.get("error")
                else f"Listo, guardé '{resultado['titulo']}' como nota de estudio en Obsidian."
            )
        elif _es_afirmacion(texto_usuario):
            titulo_resumen = pendiente_resumen["titulo"][:200]
            # Multi-base: elige por el mensaje + el título del resumen; si el
            # usuario no registró bases, cae al database único de siempre.
            base = notion_memoria.elegir_base(f"{texto_usuario} {titulo_resumen}") or notion_memoria.base_por_defecto()
            if base is not None:
                resultado = notion_memoria.guardar(base, titulo_resumen, pendiente_resumen["contenido"])
                respuesta = notion_memoria.mensaje_guardado(base, resultado, titulo_resumen)
            else:
                resultado = notion_agent.crear_pagina(titulo=titulo_resumen, contenido=pendiente_resumen["contenido"])
                respuesta = "No pude guardar el resumen en Notion: " + resultado["error"] if resultado.get("error") else "Listo, guardé el resumen en Notion."
        else:
            respuesta = _despachar_normal(texto_usuario, permitir_compuesto, sesion)

    # 3.5. Registro de finanzas esperando la cantidad (ver
    # _procesar_finanzas/_finanzas_pendiente). Baja fricción: si el
    # mensaje no trae ningún número, no se cancela — se procesa normal,
    # igual que _tema_pendiente_notion/_resumen_pendiente_notion.
    elif _finanzas_pendiente is not None:
        pendiente_finanzas = _finanzas_pendiente
        _finanzas_pendiente = None
        cantidad = _parsear_cantidad(texto_usuario)

        if cantidad:
            respuesta = _registrar_movimiento_finanzas(
                pendiente_finanzas["accion"], cantidad,
                pendiente_finanzas["categoria"], pendiente_finanzas["descripcion"],
            )
        else:
            respuesta = _despachar_normal(texto_usuario, permitir_compuesto, sesion)

    # 4. Si hay un tema esperando confirmación para el documento de
    # Notion: si el usuario dice que sí, se genera; si no, el mensaje
    # se procesa normal (no se descarta como en el caso 0, porque esto
    # es de baja fricción, no una acción irreversible).
    elif _tema_pendiente_notion is not None:
        tema = _tema_pendiente_notion
        _tema_pendiente_notion = None

        if _es_afirmacion(texto_usuario):
            respuesta = _generar_documento_notion(tema, texto_usuario)
        else:
            respuesta = _despachar_normal(texto_usuario, permitir_compuesto, sesion)

    # 4.5. Sugerencia del briefing de un examen rápido de repaso (ver
    # daily_briefing_agent.MARCA_SUGERENCIA_EXAMEN/_procesar_briefing) —
    # misma baja fricción que los casos de arriba.
    elif _examen_sugerido_pendiente:
        _examen_sugerido_pendiente = False

        if _es_afirmacion(texto_usuario):
            respuesta = _procesar_examen_repaso_rapido()
        else:
            respuesta = _despachar_normal(texto_usuario, permitir_compuesto, sesion)

    else:
        respuesta = _despachar_normal(texto_usuario, permitir_compuesto, sesion)

    return respuesta, texto_para_historial


def _despachar_normal(texto_usuario, permitir_compuesto, sesion="hud"):
    """Camino de siempre: arma contexto y rutea por intención. Si el
    mensaje junta varias peticiones (_es_compuesto) y se permite
    (permitir_compuesto), se desvía a _procesar_compuesto en vez de
    tratarlo como un solo intent."""
    if permitir_compuesto and _es_compuesto(texto_usuario):
        return _procesar_compuesto(texto_usuario, sesion)
    historial, system_prompt = _construir_contexto(texto_usuario, buscar_memoria=permitir_compuesto, sesion=sesion)
    return _rutear_por_intencion(texto_usuario, historial, system_prompt)


def _auto_continuar(respuesta_inicial, max_saltos=3, sesion="hud"):
    """Después de despachar un paso de una cadena compuesta, revisa si
    dejó alguno de los estados de wizard pendiente y, si es de bajo
    riesgo (elegir documento de investigación / confirmar Notion), lo
    resuelve solo (auto-continúa con "1"/"sí") en vez de esperar a que
    el jefe conteste. Si es de alto riesgo (CONFIRMAR de control/correo,
    el wizard de password de Nexus, o "¿seguro que me apago?") NUNCA se
    auto-responde — ahí se detiene la cadena entera, es la regla que
    nunca se rompe.

    Devuelve (lista_de_respuestas, detener_cadena)."""
    respuestas = [respuesta_inicial]
    for _ in range(max_saltos):
        if _accion_pendiente is not None or _nexus_config_pendiente is not None or _apagar_pendiente:
            return respuestas, True
        if _investigacion_pendiente is not None:
            respuesta, _texto = _despachar("1", permitir_compuesto=False, sesion=sesion)
        elif _resumen_pendiente_notion is not None or _tema_pendiente_notion is not None:
            respuesta, _texto = _despachar("sí", permitir_compuesto=False, sesion=sesion)
        else:
            break
        respuestas.append(respuesta)
    return respuestas, False


def _procesar_compuesto(texto_usuario, sesion="hud"):
    """Planifica el mensaje compuesto con Gemini/Ollama (mismo patrón
    _extraer_json que el resto del archivo, ver _PROMPT_PARSEAR_COMPUESTO)
    y ejecuta cada paso en secuencia via _despachar, auto-resolviendo
    los wizards de bajo riesgo entre pasos (ver _auto_continuar) y
    deteniendo la cadena entera ante cualquier confirmación de alto
    riesgo. Nunca lanza excepción: un paso que revienta se reporta y se
    sigue con el siguiente, para no perder el trabajo ya hecho."""
    crudo = balancer.enviar_mensaje(
        prompt=_PROMPT_PARSEAR_COMPUESTO.format(mensaje=texto_usuario), historial=[], system_instruction=None,
    )
    datos = _extraer_json(crudo) if not crudo.startswith("ERROR:") else None
    pasos = (datos or {}).get("pasos") or []
    pasos = [p.strip() for p in pasos if isinstance(p, str) and p.strip()][:5]
    if not pasos:
        pasos = [texto_usuario]

    reportes = []
    for i, paso in enumerate(pasos, start=1):
        detener = False
        try:
            respuesta_paso, _texto = _despachar(paso, permitir_compuesto=False, sesion=sesion)
            respuestas_paso, detener = _auto_continuar(respuesta_paso, sesion=sesion)
            bloque = "\n".join(respuestas_paso)
        except Exception as e:
            log.error("director: falló el paso compuesto '%s' (%s)", paso, e)
            bloque = f"No pude completar esto: {e}"

        reportes.append(f"Paso {i} — {paso}:\n{bloque}" if len(pasos) > 1 else bloque)

        if detener:
            if len(pasos) > 1:
                reportes.append("(Me detuve ahí, jefe — resuelve esto antes de que siga con lo demás.)")
            break

    return "\n\n".join(reportes)


# Evita que dos mensajes casi simultáneos (voz + HUD web, o doble tap)
# pisen los globals de wizard pendiente a mitad de una cadena — antes
# ya era una carrera teórica de un solo dispatch, pero una cadena
# compuesta mantiene esos globals "calientes" varios segundos y varias
# llamadas a Gemini, así que vale la pena cerrarla ahora.
_lock_despacho = threading.Lock()


def _etiqueta_fuente():
    """Arma el sufijo (" .G1", " .GP", " .GR"...) según qué API sirvió
    la(s) llamada(s) de ESTE turno (ver balancer.ultima_fuente/
    groq_agent.ultima_fuente, reseteados a None antes de despachar en
    procesar_mensaje). "G1".."G5" = key gratuita de Gemini
    correspondiente, "GP" = key de pago de Gemini, "GR" = Groq. Si no
    se usó ninguna API en este turno (ej. un comando de control puro),
    regresa "" — sin sufijo. Si se usó más de una (una cadena compuesta
    que tocó, por ejemplo, investigación con Groq Y chat con Gemini),
    se muestran las dos separadas por "+"."""
    fuentes = [f for f in (balancer.ultima_fuente, groq_agent.ultima_fuente) if f]
    if not fuentes:
        return ""
    return " ." + "+".join(fuentes)


def procesar_mensaje(texto_usuario, sesion="hud"):
    """Recibe el mensaje del usuario y devuelve la respuesta de
    IRIS como texto, ruteando a control del sistema, pregunta de
    conocimiento (+ oferta de Notion), búsqueda web, cadena compuesta
    de varios pasos, o chat normal (Gemini/Ollama) según la intención
    detectada.

    `sesion` ("hud" por default, "telegram" para el bot — ver
    telegram_agent.py) separa el historial INMEDIATO de context_engine
    por canal, para que IRIS no mezcle turnos de la compu con turnos
    del celular a mitad de frase. La memoria de largo plazo (Supabase,
    ver memory.py) es una sola, compartida por todos los canales."""
    with _lock_despacho:
        balancer.ultima_fuente = None
        groq_agent.ultima_fuente = None
        respuesta, texto_para_historial = _despachar(texto_usuario, permitir_compuesto=True, sesion=sesion)
        etiqueta = _etiqueta_fuente()

    # ARREGLO 5: respaldo por regex además del system prompt (ver
    # personality.py) — para que ningún markdown que Gemini haya
    # colado se vea feo en el chat ni suene raro en voz (habla.py
    # aplica el mismo limpiar_markdown antes de sintetizar).
    respuesta = habla.limpiar_markdown(respuesta)

    # Historial y memoria se actualizan siempre, incluyendo confirmaciones/
    # cancelaciones — SIN la etiqueta de fuente (esa es solo para lo que
    # ve el jefe, no debe ensuciar lo que Gemini lee como su propio
    # historial de turnos pasados).
    context_engine.agregar("usuario", texto_para_historial, sesion=sesion)
    context_engine.agregar("iris", respuesta, sesion=sesion)
    memory.guardar_memoria(texto_para_historial, tipo="usuario")
    memory.guardar_memoria(respuesta, tipo="iris")

    return respuesta + etiqueta
