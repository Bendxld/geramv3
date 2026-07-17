# GERAM CORE OS v3 — Manual de I.R.I.S.

Creado por Gerónimo Ángel Mauricio Morales

## Qué es GERAM OS

GERAM CORE OS es tu asistente personal de inteligencia artificial y entorno de desarrollo local. Tiene dos roles coordinados:

- **I.R.I.S.** — Conversacional, sarcástica y cercana. Responde preguntas, coordina tareas y usa tus integraciones autorizadas.
- **A.R.E.S.** — Profesional y eficiente. Trabaja en el workspace, propone cambios de código y nunca los aplica sin revisión y aprobación explícitas.

Los dos roles viven dentro de la misma aplicación y pueden usar proveedores de IA diferentes. Configura al menos uno en **Settings → AI APIs**.

## Cómo Arrancar IRIS

IRIS arranca automáticamente al prender la laptop (autostart configurado). Si por alguna razón no arrancó:

1. Doble click en el ícono GERAM CORE OS del escritorio, o abre terminal y escribe:
   ```
   cd /home/mauri/geramv3/geram-core-os
   ./iniciar_app.sh
   ```
2. Abre el navegador en `localhost:8000`
3. Espera el boot sequence
4. Escribe la contraseña en la pantalla de standby

## Cómo Usar IRIS desde Telegram

Abre Telegram en tu celular, busca el bot Geram OS IRIS y escríbele como si fuera un chat normal. Todo lo que le digas se ejecuta en tu computadora.

## Comandos Completos

### Conversación Normal

Escríbele cualquier cosa y I.R.I.S. responde con su personalidad y en el idioma de tu pregunta. Usa el proveedor principal configurado para su rol y, si lo autorizaste, un proveedor de respaldo distinto.

| Lo que dices | Qué hace |
|---|---|
| Hola | Te saluda a su estilo |
| ¿Quién eres? | Se presenta |
| Explícame / define / qué significa [tema] | Te explica usando Gemini |
| Cualquier pregunta | Responde con Gemini |

### Ayuda y Manual

Pregúntale por el manual y te lo recita él mismo, gratis (sin pasar por Gemini). Si preguntas por un tema en concreto, te contesta solo esa sección; si preguntas en general, te da el manual completo.

| Lo que dices | Qué hace |
|---|---|
| Ayuda / manual / comandos / qué puedes hacer | Manual completo |
| Ayuda con [tema] / comandos de [tema] | Solo la sección de ese tema (finanzas, whatsapp, archivos, calendario, correo, sistema, offline, seguridad, arquitectura, etc.) |
| Qué sabes hacer / cómo funcionas | Manual completo |

### Briefing y Estado

| Lo que dices | Qué hace |
|---|---|
| Buenos días / resumen / briefing / dame el resumen / cómo va mi día / qué me perdí | Resumen del día: pendientes, calendario, finanzas, estado del sistema |
| Estado / cómo estás / qué tal vas / cómo va todo / reporte del sistema | CPU, RAM, temperatura, uptime |

### Abrir Apps y Sitios Web

| Lo que dices | Qué hace |
|---|---|
| Abre YouTube | Abre YouTube en el navegador |
| Abre Netflix | Abre Netflix |
| Abre WhatsApp | Abre WhatsApp Web |
| Abre Instagram | Abre Instagram |
| Abre Firefox / Brave / VSCode | Abre la app |
| Abre la terminal | Abre terminal |
| Abre [cualquier app] | Busca y abre la app |
| Abre Nexus | Abre portal UANL con login automático |
| Abre Classroom | Abre Google Classroom con tu cuenta escolar |

También puedes decir "ábreme X" en vez de "abre X", y "pon Netflix/Spotify/Gmail/GitHub/Drive/Notion/YouTube/Instagram" para abrir esos sitios directo.

### Control de Pestañas

| Lo que dices | Qué hace |
|---|---|
| Siguiente pestaña / otra pestaña / cambia de pestaña | Ctrl+Tab |
| Pestaña anterior | Ctrl+Shift+Tab |
| Cierra pestaña | Ctrl+W |
| Nueva pestaña | Ctrl+T |
| Pantalla completa / fullscreen | F11 |

### Control de Ventanas

| Lo que dices | Qué hace |
|---|---|
| Cambia de app / alt tab / otra ventana / cambia de ventana | Alt+Tab |
| Minimiza | Minimiza ventana actual |
| Maximiza / agranda la ventana / ponla en grande | Maximiza ventana |
| Cierra ventana (requiere CONFIRMAR) | Alt+F4 |
| Qué tengo abierto / qué apps tengo abiertas / muéstrame las ventanas | Lista ventanas abiertas |
| Cierra todo menos tú (CONFIRMAR) | Cierra todo excepto IRIS |

### Multimedia

| Lo que dices | Qué hace |
|---|---|
| Pausa / play / resume / pausar / dale play / reanuda | Play/Pause multimedia |
| Siguiente canción / otra canción | Next track |
| Canción anterior | Previous track |
| Pon [algo] en YouTube | Abre YouTube y busca |
| Sube volumen / súbele / sube el sonido | +10% volumen |
| Baja volumen / bájale / baja el sonido | -10% volumen |
| Silencia / mute / quítale el sonido / sin sonido | Toggle mute |

### Escritura Remota

Escríbele desde Telegram y IRIS lo escribe donde esté el cursor en la compu.

| Lo que dices | Qué hace |
|---|---|
| Escribe [texto] | Escribe el texto donde esté el cursor |
| Enter / dale enter | Presiona Enter |
| Borra eso | Backspace |
| Selecciona todo | Ctrl+A |
| Copia | Ctrl+C |
| Pega | Ctrl+V |
| Guarda | Ctrl+S |
| Deshacer | Ctrl+Z |
| Dicta | Activa mic, transcribe tu voz, escribe en pantalla |

### Mouse Remoto

| Lo que dices | Qué hace |
|---|---|
| Click / dale click / clickea / dale clic | Click izquierdo donde esté el mouse |
| Click derecho / click secundario | Click derecho |
| Doble click | Doble click |
| Scroll arriba / sube | Scroll up |
| Scroll abajo / baja | Scroll down |

### Pantalla y Brillo

| Lo que dices | Qué hace |
|---|---|
| Apaga pantalla | Pantalla negra (compu sigue corriendo) |
| Prende pantalla | Enciende la pantalla |
| Sube brillo | +10% brillo |
| Baja brillo | -10% brillo |

### Captura y Visión

| Lo que dices | Qué hace |
|---|---|
| Screenshot / captura / hazme una captura / toma una captura | Toma captura de pantalla |
| Foto / tómame una foto / toma una foto | Toma foto con webcam y te la muestra en el HUD o te la manda por Telegram |
| Ve mi pantalla / checa mi pantalla / revisa mi pantalla | Screenshot + Gemini analiza (usa tokens) |
| Ayúdame a elegir | Screenshot + Gemini recomienda (usa tokens) |
| Qué hay en mi pantalla | Screenshot + descripción (usa tokens) |
| Graba pantalla / inicia grabación / comienza a grabar | Empieza a grabar con ffmpeg |
| Para de grabar / termina la grabación | Detiene la grabación |

### Grabación

| Lo que dices | Qué hace |
|---|---|
| Graba pantalla / inicia grabación / comienza a grabar | Inicia grabación de pantalla |
| Para de grabar / termina la grabación | Detiene y guarda el video |

### Archivos

| Lo que dices | Qué hace |
|---|---|
| Organiza mis descargas | Mueve archivos a subcarpetas por tipo |
| Busca [archivo] | Busca en todo tu home (nombre exacto) |
| Busca en mis archivos uno de [tema] (y ábrelo) | Búsqueda TOLERANTE a errores de escritura/dictado (revisa Descargas y todo tu home); si encuentra uno solo y pediste abrirlo de una vez, lo abre directo |
| Dónde quedó [archivo] / en dónde está / dónde guardé [archivo] | Busca y te dice la ruta |
| Lee [archivo] / muéstrame el contenido de [archivo] | Lee contenido de txt/pdf y te lo muestra |
| Qué hay en mis descargas | Cuenta archivos sin organizar |
| Busca la carpeta [nombre] (y ábrela) | Busca carpetas (no archivos) por nombre; si hay una sola y le dijiste "y ábrela", la abre de una vez |
| Ábrela / ábrelo | Abre lo último que IRIS creó, descargó o encontró (carpeta o archivo), aunque haya sido en otro mensaje |

Si "busca la carpeta X" o "busca en mis archivos uno de X" encuentra varias coincidencias, te da una lista numerada — respondes con el número (o "el segundo", "el tercero"...) y lo abre si se lo pediste.

### Clipboard / Portapapeles

| Lo que dices | Qué hace |
|---|---|
| Qué copié | Muestra lo que hay en el portapapeles |
| Qué copié hace rato | Historial de lo copiado |
| Copia esto: [texto] | Pone texto en el portapapeles |

### Investigación

| Lo que dices | Qué hace |
|---|---|
| Investiga sobre [tema] | Busca PDFs y artículos, te los lista |
| Busca PDFs de [tema] | Busca documentos específicos |
| Busca videos de [tema] | Busca en YouTube, te los lista |
| Resume el/este/ese PDF o documento | Lee el PDF y lo resume con Groq |
| Resume el/este/ese video / resume este youtube [link] | Saca la transcripción (subtítulos) del video y la resume con Groq — sin descargar nada, funciona con o sin buscar antes |
| Descarga/resume el número 2 / el 2 / baja el segundo | De una lista de PDFs: descarga y resume. De una lista de videos: resume la transcripción. Reconoce dígitos y ordinales hablados |

Cuando investigas, buscas PDFs o buscas videos, IRIS te da una lista numerada. Respondes con el número (o "el segundo"/"el tercero") y descarga+resume (PDF) o resume la transcripción (video) automáticamente. Para PDFs recuerda dónde quedó el archivo para que "ábrelo" después funcione sin pedir el nombre — los videos no descargan ningún archivo, así que no hay nada que abrir después. Te ofrece guardar el resumen en Notion.

**Nota sobre videos:** si el video no tiene subtítulos/transcripción disponible (ni en español, inglés, ni autogenerados por YouTube), IRIS no puede resumirlo — te lo dice en vez de inventar contenido.

### Figuras y Diagramas

| Lo que dices | Qué hace |
|---|---|
| Dibújame [algo] / dibuja [algo] | Genera y ejecuta código de matplotlib, te muestra la imagen |
| Grafica [algo] / gráfica de [algo] | Igual, para gráficas matemáticas |
| Hazme un diagrama de [algo] / diagrama de flujo de [algo] | Igual, para diagramas de flujo/cajas y flechas |
| Dibújame [algo] en 3D / [algo] tridimensional | Igual, pero con proyección 3D (mplot3d: superficies, dispersión, etc.) |
| Hazme una animación de [algo] / [algo] animado / que se mueva | Igual, pero genera un GIF animado en vez de una imagen fija |
| Corrígelo / está al revés / no cabe / arréglalo | Corrige la ÚLTIMA figura con lo que le digas que está mal, en vez de dibujar una nueva desde cero |

IRIS le pide a Gemini el código Python (matplotlib) que dibuja lo que pediste y lo corre él mismo — es lo único en todo el sistema donde se ejecuta código escrito por la IA, así que tiene 3 candados: un filtro que rechaza código con imports peligrosos (red, sistema, archivos fuera de lo necesario), un tope de 15 segundos, y corre en una carpeta temporal aislada. Si el código generado falla o sale mal (al revés, cortado, etc.), pídele "corrígelo" — IRIS le manda a Gemini el código real que usó más lo que le digas que está mal, para un ajuste puntual en vez de dibujar algo nuevo a ciegas. La imagen (o GIF) aparece directo en el chat del HUD y, si se lo pides desde Telegram, te la manda como foto o animación. **Usa tokens** (le pide el código a Gemini).

### Programación Bajo Demanda

| Lo que dices | Qué hace |
|---|---|
| Créame un programa que... / hazme un sistema de... / crea un script que... | Gemini escribe un programa Python completo, lo guarda en `experimentos/` y lo corre de verdad |
| (implícito) si es visual/3D o dices "hazlo bien"/"al límite" | Primero muestra un PLAN corto y espera CONFIRMAR antes de escribir código |
| (implícito) en peticiones complejas | El primer intento se le pide EN PARALELO a Gemini y a Groq, y se queda con el mejor (o los combina) |

A diferencia de "dibújame X" (que solo dibuja con matplotlib), aquí Gemini escribe un **programa completo desde cero** y GERAM lo prueba corriéndolo — si truena, le manda el error exacto de vuelta y le pide que lo corrija, hasta 3 veces. Antes de correrlo, el código pasa por un linter (ruff) que detecta errores obvios sin gastar un ciclo de ejecución; si es un script de lógica pura (no interactivo/GUI/cámara), se le generan y corren 2-3 casos de prueba automáticos. Lo visual (Three.js/canvas) se verifica con una captura de pantalla real + Gemini Vision. Si necesita una librería que no está instalada, pide CONFIRMAR antes de instalarla con pip — nunca instala nada solo. **Usa tokens** (potencialmente varias veces si hay que corregir).

### Proyectos de Código Multi-Archivo

Distinto de "Proyectos (Notion)" más abajo: esto genera **archivos reales** en tu compu (una app, un sitio, un juego), no una tarjeta de seguimiento.

| Lo que dices | Qué hace |
|---|---|
| Créame una app web de... / hazme un sitio web de... | Planea la estructura de archivos y la muestra antes de generar nada |
| Crea un juego de... / créame un proyecto de código... | Igual — cualquier cosa que necesite varios archivos conectados |

Gemini primero planea qué archivos hacen falta (ej. `index.html` + `css/style.css` + `js/main.js`, o varios módulos Python con `main.py`) y te muestra el árbol completo — escribes CONFIRMAR para que genere de verdad. Cada archivo se escribe sabiendo qué exponen los archivos anteriores (funciones, IDs, clases CSS), para que todo se conecte bien. Al terminar genera README.md (y requirements.txt si es Python), verifica el resultado de verdad (captura de pantalla + Gemini Vision para web, ejecutándolo para Python — corrigiendo hasta 3 veces si algo falla), abre el proyecto (navegador si es web) y te ofrece inicializar un repo git. Todo queda en `proyectos/{nombre}/`. **Usa tokens** (varias llamadas: plan, cada archivo, verificación).

### Escuela (Google Classroom)

| Lo que dices | Qué hace |
|---|---|
| Qué tareas tengo / checa mis tareas / tengo tareas pendientes | Lista tareas pendientes |
| Tengo tarea/deberes de [materia] para el [fecha] | Registra la tarea |
| Ya hice la tarea de [materia] | Marca como completada |
| Abre Classroom | Abre con tu cuenta escolar |
| Abre Nexus | Login automático al portal UANL |

### Finanzas Personales

| Lo que dices | Qué hace |
|---|---|
| Gasté / pagué [cantidad] en [cosa] | Registra gasto con categoría automática |
| Vendí / cobré [cantidad] de [cosa] | Registra ingreso |
| Cuánto llevo este mes | Balance del mes |
| Cuánto tengo | Balance actual |
| Cuánto he ganado con las aguas | Ganancia neta del negocio |
| Resumen financiero | Desglose por categoría |

Categorías automáticas: comida, transporte, materiales, escuela, gym, ropa, entretenimiento, negocio, otro.

### Pendientes (Notion)

| Lo que dices | Qué hace |
|---|---|
| Tengo que [algo] / no se me olvide [algo] | Crea pendiente en Notion |
| Qué pendientes tengo | Lista pendientes no completados |
| Ya hice / ya terminé [pendiente] / márcalo como hecho | Marca como completado |
| Elimina pendiente [nombre] (CONFIRMAR) | Elimina de Notion |

### Proyectos (Notion)

Distinto de pendientes: un proyecto vive días/semanas y se le van agregando avances, para ver el progreso a lo largo del tiempo (escolares o personales).

| Lo que dices | Qué hace |
|---|---|
| Crea un proyecto de [algo] / nuevo proyecto [algo] | Crea proyecto en Notion (escolar o personal) |
| Qué proyectos tengo | Lista proyectos activos (no completados) |
| En el proyecto [X] ya [avance] / avance en [X]: [avance] | Anota el avance con fecha; si estaba "no iniciado" pasa a "en progreso" |
| Cómo voy con [X] / qué avances lleva [X] | Muestra el historial de avances anotados |
| Pausa / termina / completa el proyecto [X] | Cambia el estado del proyecto |
| Elimina el proyecto [nombre] (CONFIRMAR) | Elimina de Notion |

### Recordatorios

| Lo que dices | Qué hace |
|---|---|
| Recuérdame [algo] a las [hora] / ponme un recordatorio de [algo] | Crea recordatorio |
| Avísame cuando [algo] | Crea recordatorio |
| Qué recordatorios tengo | Lista recordatorios |
| Elimina recordatorio [id] | Elimina recordatorio |

IRIS te avisa automáticamente cuando llega la hora, por chat y por voz.

### Documentos en Notion

Cuando IRIS te explica algo, te pregunta: "¿Quieres que te arme un documento en Notion?" Si dices sí, Groq genera un documento completo y lo sube a Notion automáticamente.

### Calendario (Google Calendar)

| Lo que dices | Qué hace |
|---|---|
| Qué tengo hoy / qué tengo mañana | Lista eventos del día |
| Checa mi calendario / checa mi agenda | Lista eventos del día |
| Agenda [evento] a las [hora] / agrega un evento | Crea evento |
| Elimina evento [nombre] | Elimina evento |

### Correo (Gmail)

| Lo que dices | Qué hace |
|---|---|
| Tengo correos nuevos / checa mi correo / revisa mi correo | Resume bandeja de entrada |
| Lee el correo de [persona] | Lee correo específico |
| Manda correo a [persona] (CONFIRMAR) | Redacta y envía |

### WhatsApp

| Lo que dices | Qué hace |
|---|---|
| Abre WhatsApp | Abre WhatsApp Web |
| Manda / mándale whatsapp (wasap/guasap) a [contacto] | Abre chat con mensaje pre-escrito |

### Spotify

| Lo que dices | Qué hace |
|---|---|
| Abre / pon / cierra Spotify | Abre o cierra la app/sitio (esto ya no necesita configuración) |
| Configura spotify / conecta spotify | Conecta tu cuenta real de Spotify (una sola vez, ver abajo) |
| Qué estoy escuchando / qué canción es esta | Te dice la canción que suena ahorita (o la última, si está en pausa) |
| Mi historial de spotify / últimas canciones en spotify | Lista tus últimas canciones escuchadas |

La integración real (saber qué escuchas de verdad, no solo abrir la app) es de **solo lectura** — IRIS nunca controla tu reproducción, solo consulta. Antes de usarla necesitas:
1. Crear una app gratis en [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
2. En "Redirect URIs" agregar EXACTO: `http://127.0.0.1:8888/callback`.
3. Copiar el Client ID y Client Secret a tu `.env` (`SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET`) y reiniciar IRIS.
4. Decir "configura spotify" **estando frente a la laptop** (se abre el navegador para que autorices el acceso) — solo se hace una vez.

CERO tokens (habla directo con la API de Spotify, sin pasar por Gemini).

### Voz y Micrófono (botones VOZ / MIC del HUD)

Los botones VOZ y MIC de arriba del chat también se controlan por voz, texto o **desde Telegram** — no hace falta tener el HUD abierto para mandar la orden, pero MIC solo tiene efecto real si hay un HUD abierto en algún navegador (el micrófono vive ahí, no en el servidor).

| Lo que dices | Qué hace |
|---|---|
| Activa tu voz / ya puedes hablar / empieza a hablar | Prende el botón VOZ: IRIS habla sus respuestas |
| Desactiva tu voz / cállate / deja de hablar | Apaga el botón VOZ: IRIS solo responde por chat |
| Activa el micrófono / enciende el micrófono / activa mic | Prende el botón MIC en el HUD abierto (empieza a grabar) |
| Desactiva el micrófono / apaga el micrófono / apaga mic | Apaga el botón MIC en el HUD abierto (deja de grabar) |

### Sistema

| Lo que dices | Qué hace |
|---|---|
| Descansa / reposo / vete a dormir / suspéndete | Suspende la compu (se puede despertar) |
| Apaga / apaga la máquina (CONFIRMAR) | Apaga completamente |
| Bloquéate / lock / activa el bloqueo | Activa pantalla de contraseña |

## Workspace de Desarrollo

GERAM CORE OS incluye un editor basado en Monaco con una experiencia similar a VS Code:

- Explorer para archivos y carpetas dentro del workspace seguro.
- Autocompletado y diagnósticos para Python, JavaScript, TypeScript, HTML, CSS y JSON.
- Pyright local para Python y servicios de lenguaje locales para JavaScript/TypeScript.
- Cierre automático de etiquetas en HTML, XML, SVG, Vue, Svelte, JSX y TSX; Emmet se expande con `Tab`.
- Problems, Source Control, Preview y Terminal Watcher.
- Ejecución acotada de archivos Python, pruebas `unittest` y archivos Node.js `.js`.
- A.R.E.S. propone un diff revisable: primero revisas, después apruebas y solo entonces aplicas.

Los cambios sin guardar permanecen en memoria al cambiar de archivo. Guarda con `Ctrl+S`.

## Configuración de IA e Integraciones

En **Settings → AI APIs** eliges proveedor y modelo para I.R.I.S. y A.R.E.S. OpenAI, Gemini y Groq están disponibles. Las credenciales se almacenan localmente y se muestran siempre enmascaradas.

En **Settings → Integrations** conectas únicamente los recursos que quieras autorizar: Telegram, Notion, Google Calendar, Supabase, Spotify y Obsidian. Dejar una integración vacía la mantiene desconectada.

## Modos del HUD

### Modo Noche (default)

Fondo oscuro con acento rosa/magenta (Midnight Rose). Ideal para la noche o ambientes oscuros.

### Modo Día

Fondo claro con acento rosa oscuro. Ideal para ambientes con mucha luz. Actívalo con el botón sol/luna arriba a la derecha.

### Modo Expandido

Cuando IRIS responde, el núcleo y el chat se expanden y los paneles laterales se desvanecen. Para volver a la normalidad, click en cualquier botón de sentido o en el núcleo.

### Paneles Expandibles

Click en cualquier panel lateral (Sistema, Consola, Hora, Voz) para expandirlo al centro de la pantalla. Click fuera para cerrarlo.

## Seguridad

- Después de 5 minutos sin uso, IRIS entra en standby y pide contraseña
- Credenciales de Nexus UANL guardadas encriptadas localmente
- Acceso remoto protegido por Tailscale (solo tus dispositivos)
- Las acciones peligrosas (cerrar apps, apagar, eliminar) requieren escribir CONFIRMAR

### Cambiar Contraseña

```bash
python3 -c "import hashlib; print(hashlib.sha256('TU_NUEVA_CONTRASEÑA'.encode()).hexdigest())"
```

Copia el hash y reemplaza `LOCK_PASSWORD_HASH` en tu `.env`.

## Consumo de Tokens (tu presupuesto)

La mayoría de funciones son GRATIS (no gastan tokens):

**GRATIS (cero tokens):**
- Control de ventanas, pestañas, mouse, escritura
- Finanzas, pendientes, recordatorios
- Abrir apps/URLs
- Organizar archivos, clipboard, buscar/abrir carpetas
- Spotify (qué escuchas, historial)
- Voz (edge-tts/Piper), oído (faster-whisper)
- Acciones locales que no requieren un proveedor de IA

**USAN TOKENS (solo cuando tú lo pides):**
- Conversación normal → proveedor configurado para I.R.I.S.
- "Ve mi pantalla" / "Ayúdame a elegir" → Gemini Vision
- Documentos en Notion → Groq (gratis)
- Daily briefing → Gemini (1 vez al día)
- Investigación (resumir PDFs) → Groq (gratis)
- "Dibújame X" / diagramas → Gemini (5 keys gratis)
- "Créame un programa/script" → Gemini, + Groq en peticiones complejas (competencia entre los dos)
- "Créame una app web" / proyecto de código multi-archivo → Gemini + Groq (plan, cada archivo, verificación)

Los límites, precios y niveles gratuitos dependen del proveedor elegido. GERAM no aumenta límites ni evita términos o facturación del proveedor.

### Qué proveedor se usó

GERAM conserva metadatos operativos del proveedor y modelo usados por cada rol sin exponer la credencial. Las credenciales múltiples se administran como pools con etiqueta, prioridad, límite diario opcional y estado de salud; las respuestas nunca muestran la key completa.

## Modo Offline y Ollama

La integración local con Ollama está en preparación. GERAM ya reserva el proveedor, el modelo y el tiempo de espera para conectarse únicamente al servicio local de Ollama. No requiere API key.

Mientras no aparezca como disponible y no pase su comprobación local, no asumas que el chat cambiará automáticamente a Ollama. Incluso con Ollama activo, las funciones que dependen de internet —búsquedas web, Notion, Telegram y otras APIs— seguirán necesitando conexión.

## Acceso Remoto (Tailscale)

Desde tu celular, con Tailscale instalado:

1. Abre navegador en tu celular
2. Ve a `http://100.118.103.72:8000` (la IP de Tailscale de IRIS)
3. El HUD completo desde cualquier lugar

## Arquitectura Técnica

| Componente | Tecnología |
|---|---|
| Backend | Python + FastAPI |
| Frontend | HTML/CSS/JS |
| Cerebro de I.R.I.S. | Proveedor y modelo configurables |
| A.R.E.S. | Proveedor y modelo configurables + revisión de diffs |
| Modelo local en preparación | Ollama (`llama3.2:1b` por defecto) |
| Voz de salida | Edge-TTS (JorgeNeural) + Piper (offline) |
| Voz de entrada | Faster-Whisper |
| Memoria | Supabase (PostgreSQL) |
| Documentos | Notion API |
| Acceso remoto | Tailscale |
| Bot | Telegram Bot API |

---

GERAM CORE OS v3 — Construido por Mauricio

*"El Efecto GERAM: adaptación rápida, mejora deliberada"*
