# ============================================================
# GERAM CORE OS v3 · manual.py
# Texto plano del manual de usuario (ver MANUAL.md para la versión
# con tablas). Lo usa director.py para responder "ayuda"/"qué puedes
# hacer" directo, sin gastar tokens de Gemini: manual completo si la
# pregunta es genérica, o solo la sección que corresponda si el jefe
# pregunta por un tema en concreto (ver buscar_seccion/TEMA_KEYWORDS).
# ============================================================

_INTRO = 'GERAM CORE OS v3 — Manual de I.R.I.S. Creado por Gerónimo Ángel Mauricio Morales.'

_QUE_ES = """QUÉ ES GERAM CORE OS
Tu asistente personal de IA y entorno de desarrollo local. I.R.I.S. es el rol conversacional, sarcástico y cercano; A.R.E.S. es el rol profesional que propone cambios de código revisables. Ambos viven en la misma aplicación y pueden usar proveedores de IA diferentes."""

_CONVERSACION = """COMANDOS DE CONVERSACIÓN Y ESTADO
- Hola / quién eres / explícame, define, qué significa [tema] / cualquier pregunta → responde con el proveedor configurado y en el idioma de la pregunta.
- Buenos días, resumen, briefing, dame el resumen, cómo va mi día, qué me perdí → resumen del día (pendientes, calendario, finanzas, estado del sistema).
- Estado, cómo estás, qué tal vas, cómo va todo, reporte del sistema → CPU, RAM, temperatura, uptime."""

_AYUDA_MANUAL = """AYUDA Y MANUAL
- Ayuda, manual, comandos, qué puedes hacer, qué sabes hacer, cómo funcionas → manual completo, gratis (sin gastar tokens).
- Ayuda con [tema], comandos de [tema] → solo la sección de ese tema (finanzas, whatsapp, archivos, calendario, correo, sistema, offline, seguridad, arquitectura, etc.)."""

_APPS = """ABRIR APPS Y SITIOS
- Abre / ábreme YouTube / Netflix / WhatsApp / Instagram / Firefox / Brave / VSCode / terminal / cualquier app → la abre.
- Pon Netflix/Spotify/Gmail/GitHub/Drive/Notion/YouTube/Instagram → abre ese sitio directo.
- Abre Nexus → portal UANL con login automático. Abre Classroom → Google Classroom con tu cuenta escolar."""

_PESTANAS_VENTANAS = """PESTAÑAS Y VENTANAS
- Siguiente pestaña / otra pestaña / cambia de pestaña, pestaña anterior, cierra pestaña, nueva pestaña, pantalla completa.
- Cambia de app / alt tab / otra ventana / cambia de ventana, minimiza, maximiza / agranda la ventana / ponla en grande, cierra ventana (CONFIRMAR), qué tengo abierto / qué apps tengo abiertas / muéstrame las ventanas, cierra todo menos tú (CONFIRMAR)."""

_MULTIMEDIA = """MULTIMEDIA
- Pausa/play/resume/pausar/dale play/reanuda, siguiente canción / otra canción, canción anterior, pon [algo] en YouTube.
- Sube volumen / súbele / sube el sonido, baja volumen / bájale / baja el sonido, silencia / mute / quítale el sonido / sin sonido."""

_ESCRITURA_MOUSE = """ESCRITURA Y MOUSE REMOTOS (desde Telegram escribe donde esté el cursor de la compu)
- Escribe [texto], enter, borra eso, selecciona todo, copia, pega, guarda, deshacer, dicta (activa mic y transcribe).
- Click / clickea / dale clic, click derecho / click secundario, doble click, scroll arriba/abajo."""

_PANTALLA_BRILLO = """PANTALLA Y BRILLO
- Apaga/prende pantalla, sube/baja brillo."""

_CAPTURA = """CAPTURA Y VISIÓN
- Screenshot/captura/hazme una captura/toma una captura, foto/tómame una foto (webcam, se muestra en el HUD o se manda por Telegram — útil para chequear tu casa si no estás ahí).
- Ve mi pantalla / checa mi pantalla / revisa mi pantalla (usa tokens), ayúdame a elegir (usa tokens), qué hay en mi pantalla (usa tokens).
- Graba pantalla / inicia grabación / comienza a grabar, para de grabar / termina la grabación."""

_ARCHIVOS_CLIPBOARD = """ARCHIVOS Y CLIPBOARD
- Organiza mis descargas, busca [archivo], dónde quedó / en dónde está / dónde guardé [archivo], lee [archivo] / muéstrame el contenido de [archivo], qué hay en mis descargas.
- Busca en mis archivos uno de [tema] (y ábrelo): búsqueda TOLERANTE a errores de escritura/dictado (revisa Descargas y todo tu home) — si encuentra un solo archivo y le pediste abrirlo de una vez, lo abre directo; si hay varios, da una lista numerada.
- Busca la carpeta [nombre] (y ábrela): busca carpetas por nombre, no archivos; si hay una sola y pediste abrirla de una vez, la abre. Si hay varias, da una lista numerada (igual que investigación).
- "Ábrela"/"ábrelo" sueltas abren lo último que I.R.I.S creó, descargó (de investigación o de un comando) o encontró (carpeta o archivo), aunque haya sido en otro mensaje.
- Qué copié, qué copié hace rato, copia esto: [texto]."""

_FIGURAS = """FIGURAS Y DIAGRAMAS (usa tokens)
- Dibújame/dibuja [algo], grafica/gráfica de [algo], hazme un diagrama/diagrama de flujo de [algo] → Gemini escribe código de matplotlib y lo ejecuta para mostrarte la imagen.
- [algo] en 3D/tridimensional → lo mismo pero con proyección 3D (mplot3d).
- Hazme una animación de [algo] / [algo] animado / que se mueva → lo mismo pero genera un GIF animado en vez de una imagen fija.
- Corrígelo / está al revés / no cabe / arréglalo → corrige la ÚLTIMA figura con lo que le digas que está mal, en vez de dibujar una nueva desde cero sin saber qué se había pedido.
Es lo único del sistema que corre código escrito por la IA: se mitiga con un filtro de patrones peligrosos (nada de red/sistema/archivos fuera de lo necesario), un tope de 15 segundos, y una carpeta temporal aislada. Si el código generado falla al dibujar, se reporta el error tal cual — pídele "corrígelo" para que lo intente de nuevo sobre lo mismo. La imagen (o GIF) se muestra en el chat del HUD, o como foto/animación si lo pediste desde Telegram."""

_PROGRAMACION = """PROGRAMACIÓN BAJO DEMANDA (usa tokens)
- Créame un programa que... / hazme un sistema de... / crea un script que... / prográmame algo que... → Gemini escribe un programa Python completo, lo guarda en experimentos/ y lo corre de verdad para comprobar que no truena, corrigiendo el error exacto hasta 3 veces si falla.
- Antes de escribir código: si es visual/3D o dices "hazlo bien"/"al límite", primero te muestra un PLAN corto (librerías, estructura, pasos) y espera que escribas CONFIRMAR — así no se gastan tokens en algo que no era lo que querías. Peticiones simples van directo, sin este paso.
- En peticiones complejas, el primer intento se le pide EN PARALELO a Gemini y a Groq y se queda con el mejor de los dos (o los combina).
- El Python generado pasa por un linter (ruff) antes de correrlo, y si es un script de lógica pura se le generan y corren 2-3 casos de prueba automáticos antes de darlo por bueno.
- Lo visual (Three.js/canvas, ej. "créame un corazón 3D que gire") se verifica con una captura de pantalla real + Gemini Vision, corrigiendo hasta 3 veces si no se ve como pediste.
- Si necesita una librería no instalada, pide CONFIRMAR antes de instalarla con pip — nunca instala nada solo."""

_PROYECTOS_CODIGO = """PROYECTOS DE CÓDIGO MULTI-ARCHIVO (usa tokens)
Distinto del proyecto de Notion (ver PROYECTOS): esto genera ARCHIVOS reales en tu compu, no una tarjeta de seguimiento.
- Créame una app web de... / hazme un sitio web de... / crea un juego de... / créame un proyecto de código... → Gemini planea la estructura (qué archivos, qué hace cada uno), te la muestra como árbol y espera CONFIRMAR antes de generar nada.
- Al confirmar, genera cada archivo conectado con los demás (HTML/CSS/JS separados, o varios módulos Python con main.py), más README.md y requirements.txt si aplica.
- Verifica el resultado de verdad: web con captura de pantalla + Gemini Vision, Python ejecutándolo — corrigiendo hasta 3 veces si algo falla.
- Al terminar abre el proyecto (el navegador si es web) y te ofrece inicializar un repo git (CONFIRMAR).
- Todo queda en proyectos/{nombre}/, separado de experimentos/ (que es solo para archivos sueltos)."""

_INVESTIGACION = """INVESTIGACIÓN
- Investiga sobre [tema], busca PDFs de [tema], resume el/este/ese PDF o documento. Te da lista numerada.
- Busca videos de [tema] → lista videos de YouTube; resume el/este/ese video / resume este youtube [link] → saca la transcripción (subtítulos, con o sin buscar antes) y la resume, sin descargar nada.
- Descarga/resume el número 2 / el 2 / baja el segundo → descarga y resume ese de la lista (PDF) o resume su transcripción (video) — reconoce dígitos y también "primero/segundo/tercero...". Para PDFs recuerda dónde quedó, para que "ábrelo" después lo abra sin pedir el nombre. Se puede guardar el resumen en Notion."""

_ESCUELA = """ESCUELA (Classroom/Nexus)
- Qué tareas tengo / checa mis tareas / tengo tareas pendientes, tengo tarea/deberes de [materia] para el [fecha], ya hice la tarea de [materia], abre Classroom, abre Nexus."""

_FINANZAS = """FINANZAS PERSONALES
- Gasté / pagué [cantidad] en [cosa], vendí / cobré [cantidad] de [cosa], cuánto llevo este mes, cuánto tengo, cuánto he ganado con las aguas, resumen financiero. Categorías automáticas: comida, transporte, materiales, escuela, gym, ropa, entretenimiento, negocio, otro."""

_PENDIENTES_RECORDATORIOS = """PENDIENTES Y RECORDATORIOS (Notion)
- Tengo que [algo] / no se me olvide [algo], qué pendientes tengo, ya hice / ya terminé [pendiente] / márcalo como hecho, elimina pendiente [nombre] (CONFIRMAR).
- Recuérdame [algo] a las [hora] / ponme un recordatorio de [algo], avísame cuando [algo], qué recordatorios tengo, elimina recordatorio [id]. I.R.I.S avisa por chat y voz cuando llega la hora."""

_PROYECTOS = """PROYECTOS (Notion)
Distinto de pendientes: un proyecto vive días/semanas y se le van agregando avances, para ver el progreso a lo largo del tiempo (escolares o personales).
- Crea un proyecto de [algo] / nuevo proyecto [algo], qué proyectos tengo.
- En el proyecto [X] ya [avance] / avance en [X]: [avance] → anota el avance con fecha (si estaba "no iniciado" pasa a "en progreso" solo).
- Cómo voy con [X] / qué avances lleva [X] → historial de avances.
- Pausa / termina / completa el proyecto [X], elimina el proyecto [nombre] (CONFIRMAR)."""

_CALENDARIO_CORREO = """CALENDARIO Y CORREO
- Qué tengo hoy / qué tengo mañana / checa mi calendario / checa mi agenda, agenda [evento] a las [hora] / agrega un evento, elimina evento [nombre].
- Tengo correos nuevos / checa mi correo / revisa mi correo, lee el correo de [persona], manda correo a [persona] (CONFIRMAR)."""

_WHATSAPP = """WHATSAPP
- Abre WhatsApp, manda / mándale whatsapp (wasap/guasap) a [contacto]."""

_SPOTIFY = """SPOTIFY (solo lectura, no controla reproducción)
- Abre/pon/cierra Spotify (ya funciona sin configurar nada, es solo abrir la app/sitio).
- Configura spotify / conecta spotify → conecta tu cuenta real (una sola vez, requiere Client ID/Secret en .env de developer.spotify.com y aprobar en el navegador estando frente a la laptop).
- Qué estoy escuchando / qué canción es esta → la canción que suena ahorita.
- Mi historial de spotify / últimas canciones en spotify → tus últimas canciones escuchadas.
CERO tokens (API directa de Spotify, sin pasar por Gemini)."""

_VOZ_MIC = """VOZ Y MICRÓFONO (botones VOZ/MIC del HUD, también por voz/texto o desde Telegram)
- Activa tu voz / ya puedes hablar / empieza a hablar → prende VOZ (I.R.I.S habla sus respuestas).
- Desactiva tu voz / cállate / deja de hablar → apaga VOZ (I.R.I.S solo responde por chat).
- Activa el micrófono / enciende el micrófono / activa mic → prende MIC en el HUD abierto.
- Desactiva el micrófono / apaga el micrófono / apaga mic → apaga MIC en el HUD abierto.
MIC solo tiene efecto real si hay un HUD abierto en algún navegador (el micrófono vive ahí, no en el servidor)."""

_SISTEMA = """SISTEMA
- Descansa/reposo/vete a dormir/suspéndete, apaga/apaga la máquina (CONFIRMAR), bloquéate/lock/activa el bloqueo."""

_MODOS_HUD = """MODOS DEL HUD
- Modo Noche (default): fondo oscuro, acento rosa/magenta.
- Modo Día: fondo claro, acento rosa oscuro. Se activa con el botón sol/luna.
- Modo Expandido: al responder, el núcleo y el chat se expanden. Click en cualquier botón de sentido o en el núcleo para volver a la normalidad.
- Paneles expandibles: click en Sistema, Consola, Hora o Voz para expandir al centro; click afuera para cerrar."""

_DESARROLLO = """WORKSPACE DE DESARROLLO
- Explorer + Monaco para editar archivos dentro del workspace seguro; Ctrl+S guarda y los cambios sin guardar sobreviven al cambiar de pestaña.
- Autocompletado y diagnósticos: Pyright para Python; servicios locales para JavaScript/TypeScript, HTML, CSS y JSON.
- Cierre automático de etiquetas en HTML, XML, SVG, Vue, Svelte, JSX y TSX; Emmet se expande con Tab.
- A.R.E.S. genera un diff: primero se revisa, después se aprueba y solo entonces se aplica.
- Terminal Watcher ejecuta perfiles cerrados: Python, unittest y Node.js .js.
- Settings → AI APIs configura proveedor/modelo; Settings → Integrations limita Telegram, Notion, Calendar, Supabase, Spotify y Obsidian a los recursos indicados."""

_SEGURIDAD = """SEGURIDAD
- Standby y contraseña tras 5 minutos sin uso.
- Credenciales de Nexus UANL encriptadas localmente.
- Acceso remoto protegido por Tailscale.
- Acciones peligrosas (cerrar apps, apagar, eliminar) requieren escribir CONFIRMAR."""

_TOKENS = """CONSUMO DE PROVEEDORES
Las acciones locales de control, archivos y editor no requieren una llamada de IA. Conversación, visión, investigación y generación sí pueden usar el proveedor configurado. Los límites, precios y niveles gratuitos pertenecen a OpenAI, Gemini, Groq u otro proveedor elegido; GERAM no aumenta límites ni evita facturación o términos."""

_OFFLINE = """MODO OFFLINE Y OLLAMA
Ollama ya está habilitado como proveedor local (sin API key, solo loopback 127.0.0.1:11434): puedes elegirlo en el panel Configuración para el asistente (I.R.I.S.) o el editor de IA (A.R.E.S.), y sin internet el sistema cae solo a Ollama. En esta laptop (i3, 7.7 GB RAM, sin GPU) usa modelos de 1B–3B: llama3.2:1b o phi3 para chat, qwen2.5-coder:1.5b para código; evita modelos de 7B+ porque saturan la RAM. Las integraciones web (Notion, Telegram, búsquedas) siguen necesitando internet aunque el chat use Ollama."""

_REMOTO = """ACCESO REMOTO
Con Tailscale instalado en tu celular, entra a http://100.118.103.72:8000 para el HUD completo desde cualquier lugar."""

_ARQUITECTURA = """ARQUITECTURA TÉCNICA
Backend Python + FastAPI, frontend HTML/CSS/JS, editor Monaco, Pyright local, proveedores configurables OpenAI/Gemini/Groq/Ollama local (llama3.2:1b por defecto, funciona sin internet), credenciales locales enmascaradas, integraciones Notion/Telegram/Calendar/Supabase/Spotify/Obsidian y ejecución con perfiles cerrados."""

_OUTRO = 'GERAM CORE OS v3 — Construido por Mauricio. "El Efecto GERAM: adaptación rápida, mejora deliberada".'

# Orden en el que aparecen en el manual completo.
SECCIONES = {
    "que_es": _QUE_ES,
    "conversacion": _CONVERSACION,
    "ayuda_manual": _AYUDA_MANUAL,
    "apps": _APPS,
    "pestanas_ventanas": _PESTANAS_VENTANAS,
    "multimedia": _MULTIMEDIA,
    "escritura_mouse": _ESCRITURA_MOUSE,
    "pantalla_brillo": _PANTALLA_BRILLO,
    "captura": _CAPTURA,
    "archivos_clipboard": _ARCHIVOS_CLIPBOARD,
    "investigacion": _INVESTIGACION,
    "figuras": _FIGURAS,
    "programacion": _PROGRAMACION,
    "proyectos_codigo": _PROYECTOS_CODIGO,
    "escuela": _ESCUELA,
    "finanzas": _FINANZAS,
    "pendientes_recordatorios": _PENDIENTES_RECORDATORIOS,
    "proyectos": _PROYECTOS,
    "calendario_correo": _CALENDARIO_CORREO,
    "whatsapp": _WHATSAPP,
    "spotify": _SPOTIFY,
    "voz_mic": _VOZ_MIC,
    "sistema": _SISTEMA,
    "modos_hud": _MODOS_HUD,
    "desarrollo": _DESARROLLO,
    "seguridad": _SEGURIDAD,
    "tokens": _TOKENS,
    "offline": _OFFLINE,
    "remoto": _REMOTO,
    "arquitectura": _ARQUITECTURA,
}

MANUAL_TEXTO = "\n\n".join([_INTRO] + list(SECCIONES.values()) + [_OUTRO])

# Tema preguntado -> sección de SECCIONES. Se revisa en ESTE orden (el
# primer match gana) porque algunas palabras se pisan entre secciones
# ("pantalla" aparece tanto en captura como en pantalla/brillo: captura
# va primero porque "captura"/"screenshot"/"webcam" son más específicas).
TEMA_KEYWORDS = (
    (("finanza", "aguas"), "finanzas"),
    (("pendiente",), "pendientes_recordatorios"),
    (("recordatorio", "recuérdame", "recuerdame"), "pendientes_recordatorios"),
    # "app web"/"sitio web"/"juego"/"proyecto de código" ANTES que
    # "proyecto" a secas (más abajo) — si no, "ayuda con proyecto de
    # código" caería al tracker de Notion en vez de esta sección.
    (("app web", "sitio web", "página web", "pagina web", "proyecto de código", "proyecto de codigo"), "proyectos_codigo"),
    (("juego",), "proyectos_codigo"),
    (("proyecto",), "proyectos"),
    (("programa", "script"), "programacion"),
    (("calendario", "agenda", "evento"), "calendario_correo"),
    (("correo", "gmail", "email"), "calendario_correo"),
    (("whatsapp",), "whatsapp"),
    (("spotify",), "spotify"),
    (("micrófono", "microfono", "mic"), "voz_mic"),
    (("voz",), "voz_mic"),
    (("clipboard", "portapapeles"), "archivos_clipboard"),
    (("carpeta", "archivo", "descargas"), "archivos_clipboard"),
    (("dibuj", "grafica", "gráfica", "diagrama", "figura"), "figuras"),
    (("investiga", "pdf", "video", "youtube", "transcripción", "transcripcion"), "investigacion"),
    (("classroom", "escuela", "tarea", "nexus"), "escuela"),
    (("multimedia", "música", "musica", "canción", "cancion", "volumen"), "multimedia"),
    (("captura", "screenshot", "webcam", "foto", "graba", "visión", "vision"), "captura"),
    (("pantalla", "brillo"), "pantalla_brillo"),
    (("ventana",), "pestanas_ventanas"),
    (("pestaña", "pestana"), "pestanas_ventanas"),
    (("escribe", "teclado", "dicta", "mouse", "click", "scroll"), "escritura_mouse"),
    (("sistema", "apaga", "suspende", "bloqu"), "sistema"),
    (("modo día", "modo dia", "modo noche", "modo expandido", "hud"), "modos_hud"),
    (("editor", "workspace", "monaco", "autocompletado", "ares", "programación", "programacion"), "desarrollo"),
    (("seguridad", "contraseña", "contrasena"), "seguridad"),
    (("token",), "tokens"),
    (("offline",), "offline"),
    (("tailscale", "remoto"), "remoto"),
    (("arquitectura", "tecnología", "tecnologia"), "arquitectura"),
    (("qué es geram", "que es geram", "quién eres", "quien eres"), "que_es"),
)


def buscar_seccion(texto):
    """Si el jefe preguntó por un tema en concreto (ej. "ayuda con
    finanzas", "comandos de whatsapp"), regresa solo esa sección del manual.
    Si no matchea ningún tema conocido, regresa None y el llamador
    debe caer al manual completo (MANUAL_TEXTO)."""
    texto_bajo = texto.lower()
    for palabras, clave in TEMA_KEYWORDS:
        if any(p in texto_bajo for p in palabras):
            return SECCIONES[clave]
    return None
