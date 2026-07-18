# ============================================================
# GERAM OS v2 · code_agent.py
# "Créame un programa que..."/"hazme un sistema de..."/"programa algo
# que...": a diferencia del resto de GERAM (donde Gemini solo ELIGE
# entre acciones ya construidas, ver control_agent.interpretar()),
# aquí Gemini ESCRIBE un programa Python nuevo desde cero para lo que
# pida el jefe, lo guarda en experimentos/ y lo prueba corriéndolo de
# verdad — si truena, le manda el error de vuelta a Gemini pidiendo
# que corrija ESE error puntual, hasta 3 intentos.
#
# Mismo espíritu que figura_agent.py (la otra excepción del proyecto
# que ejecuta código escrito por la IA) pero con mucho más blast
# radius: ahí el código SOLO puede dibujar con matplotlib dentro de un
# `ax` ya dado; aquí puede ser CUALQUIER programa. Las mitigaciones:
#   1. Filtro de patrones peligrosos ANTES de guardar/ejecutar (ver
#      _PATRONES_PELIGROSOS) — best-effort, no un sandbox real.
#   2. Timeout corto (ver _TIMEOUT_SEGUNDOS): si el proceso sigue vivo
#      al cumplirse, se asume que arrancó bien (típico de programas
#      con cámara/GUI/bucle de eventos) y se mata; si truena antes,
#      es un error real.
#   3. Todo vive en experimentos/, JAMÁS toca agents/ ni ningún otro
#      archivo de GERAM OS.
#   4. Instalar una dependencia nueva SIEMPRE pide CONFIRMAR primero
#      (ver instalar_dependencia/confirmar_instalacion) — nunca ocurre
#      solo porque Gemini "decidió" que hacía falta.
#
# Además de Python, este agente también genera páginas HTML/JS visuales
# (Three.js/canvas) cuando la petición lo pide (ver _tipo_peticion) —
# ahí "correr sin tronar" no basta para saber si el resultado sirve, así
# que en vez de un traceback se usa una CAPTURA DE PANTALLA (Playwright)
# + Gemini Vision para verificar que se vea como se pidió, corrigiendo
# con esa retroalimentación puntual (ver crear_proyecto_visual/
# _ciclo_visual). Peticiones con 3+ requisitos distintos (geometría +
# luces + animación + controles) se construyen paso a paso, verificando
# cada paso antes de agregar el siguiente (ver _detectar_pasos).
#
# Pipeline de calidad (ver code_pipeline.py/code_memoria.py):
#   - Peticiones COMPLEJAS (visual/3D, o "hazlo bien"/"al límite", ver
#     es_peticion_compleja) pasan primero por un PLAN en texto que
#     director.py le muestra al jefe antes de escribir código (modo
#     arquitecto, ver generar_plan), y el primer intento se genera por
#     COMPETENCIA entre Gemini y Groq en paralelo (ver
#     code_pipeline.generar_con_competencia) en vez de pedirlo solo a
#     Gemini — las correcciones posteriores siguen siendo Gemini-only.
#   - Python generado pasa por ruff (ver code_pipeline.lint_python)
#     ANTES de gastar un ciclo de _ejecutar, y si es un script de
#     lógica pura (ver code_pipeline.es_testeable) se le generan y
#     corren 2-3 casos de prueba (ver _ciclo_pruebas) antes de darlo
#     por bueno.
#   - Antes de generar, se busca un patrón ya exitoso parecido en
#     Supabase (ver code_memoria.buscar_patron_similar) para usarlo de
#     referencia; después de verificar éxito real, se guarda ahí
#     mismo (ver code_memoria.guardar_patron_exitoso).
# ============================================================

import logging
import os
import re
import subprocess
import sys

from playwright.sync_api import sync_playwright

from agents import balancer, code_memoria, code_pipeline, plantillas_codigo

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("code_agent")

# Relativa a la raíz del repo (agents/ -> raíz), para que funcione sin
# importar dónde se clone GERAM ni en qué usuario/OS.
CARPETA_EXPERIMENTOS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "experimentos"
)

_TIMEOUT_SEGUNDOS = 15
_TIMEOUT_PIP_SEGUNDOS = 120
_MAX_INTENTOS = 3

# --- Detección de tipo de petición (Python vs visual/web) ---
#
# Frases que indican que el jefe quiere una página HTML/JS con gráficos
# 3D (Three.js/WebGL) en vez de un programa Python. "3d" a secas es
# demasiado ambiguo (choca con figuras matplotlib en 3D, ver
# figura_agent.py), así que solo cuenta si además menciona una acción
# de navegador/mouse/animación — de otro modo cae a Python normal.
_PISTAS_VISUAL_3D = (
    "three.js", "threejs", "webgl", "modelo 3d", "objeto 3d", "escena 3d",
    "geometría 3d", "geometria 3d",
)
_PISTAS_ACCION_3D = (
    "gire", "girar", "gira", "rotar", "rota", "rotarlo", "rotarla",
    "mouse", "ratón", "raton", "interactivo", "interactiva", "navegador",
)
# Gráficos 2D interactivos en el navegador (canvas), distinto de una
# figura estática de matplotlib.
_PISTAS_VISUAL_2D = (
    "canvas", "html5 canvas", "gráfico interactivo en el navegador",
    "grafico interactivo en el navegador", "dibujo interactivo en el navegador",
)

_TIMEOUT_CAPTURA_MS = 10000
_MAX_INTENTOS_VISUAL = 3
_MAX_INTENTOS_PASO = 2
RUTA_CAPTURA_VISUAL = "/tmp/geram_code_agent_captura.png"


def _tipo_peticion(descripcion):
    """Decide si `descripcion` pide un programa Python (comportamiento
    de siempre) o una página HTML/JS visual (Three.js o canvas 2D, ver
    crear_proyecto_visual). Devuelve "python", "visual_3d" o "visual_2d"."""
    texto = descripcion.lower()
    if any(p in texto for p in _PISTAS_VISUAL_3D):
        return "visual_3d"
    if "3d" in texto and any(p in texto for p in _PISTAS_ACCION_3D):
        return "visual_3d"
    if any(p in texto for p in _PISTAS_VISUAL_2D):
        return "visual_2d"
    return "python"

# Best-effort: si el código generado toca cualquiera de estos, se
# rechaza SIN ejecutar ni guardar. No es exhaustivo (no hay forma de
# serlo con un blocklist de texto), pero cubre las 4 categorías que
# nunca deben pasar: borrado masivo, red sospechosa, credenciales, y
# eval/exec arbitrario.
_PATRONES_PELIGROSOS = (
    # Borrado masivo (equivalente a "rm -rf" venga de donde venga).
    "rm -rf", "rm -fr", "shutil.rmtree(",
    # Comandos de red sospechosos (descargar y correr, shells reversas).
    "curl ", "wget ", "| sh", "| bash", "nc -e", "ncat ", "/dev/tcp/",
    "bash -i", "base64 -d",
    # Acceso a credenciales/.env/config del propio GERAM OS.
    ".env", "credenciales/", "nexus.enc", "google_credentials",
    "token_personal", "import config", "from config",
    # eval/exec arbitrario.
    "eval(", "exec(",
)

_SYSTEM_PROMPT_EXPERTO = """Eres un programador Python experto. El usuario (tu jefe) te pide un programa completo y funcional, no un ejercicio ni un esqueleto.

Reglas estrictas:
- Responde ÚNICAMENTE con código Python, completo y listo para correr tal cual. Nada de explicaciones antes o después, nada de ``` de markdown.
- El código debe estar TERMINADO de verdad: nunca dejes funciones a medias, nunca escribas "# implementar después", "# TODO", "# aquí iría la lógica" ni ningún otro placeholder. Si algo requiere una implementación, ESCRÍBELA completa.
- Puedes usar cualquier librería estándar o de terceros que ya esté instalada en el sistema (numpy, matplotlib, opencv-python (cv2), Pillow, etc.) — si el jefe pidió algo que menciona una librería concreta, asume que se puede importar directo.
- Si el programa abre una ventana, cámara o cualquier bucle de eventos (GUI, video), debe poder cerrarse limpiamente (ej. con la tecla 'q' o cerrando la ventana) — nunca debe quedarse colgado para siempre sin forma de salir.
- Si el programa necesita saber cuándo terminar y no hay una condición natural, usa un límite razonable (ej. una animación de N cuadros) en vez de un bucle infinito sin salida.
- Nunca borres archivos del sistema, nunca ejecutes comandos de red sospechosos (descargar y correr scripts remotos, shells reversas), nunca leas archivos de credenciales/.env/configuración de otros programas, nunca uses eval()/exec()."""

_PROMPT_PLANTILLA_AUTOMATIZACION = f"""

Plantilla base de referencia para la estructura general de un script (adapta el contenido — si el programa necesita su propio loop de eventos, GUI o cámara, ese loop va dentro de main(), la estructura de afuera no cambia):
```
{plantillas_codigo.PLANTILLA_AUTOMATIZACION}
```"""


# Referencia de memoria de patrones exitosos (ver code_memoria.py):
# compartida entre el prompt de Python y el visual, la única diferencia
# es QUÉ código trae adentro.
_PROMPT_EXTRA_REFERENCIA = """

REFERENCIA: ya existe un programa parecido que se verificó exitoso antes. Úsalo como plantilla/inspiración de estructura y estilo, pero adáptalo por completo a la petición actual — no lo copies literal si no aplica:
```
{referencia}
```"""


def _construir_system_prompt(descripcion, referencia=None):
    """Igual que figura_agent._construir_prompt: el prompt base es fijo
    (con la plantilla de estructura general ya incluida, ver
    plantillas_codigo.PLANTILLA_AUTOMATIZACION) y, si
    code_memoria.buscar_patron_similar encontró algo parecido, esa
    referencia (ver _PROMPT_EXTRA_REFERENCIA)."""
    base = _SYSTEM_PROMPT_EXPERTO + _PROMPT_PLANTILLA_AUTOMATIZACION
    if referencia:
        base += _PROMPT_EXTRA_REFERENCIA.format(referencia=referencia)
    return base


_PROMPT_PLAN = """El jefe te pidió esto: "{descripcion}"

Antes de escribir el código, describe EN TEXTO PLANO (nada de código) un plan corto:
- Qué librerías/tecnologías vas a usar.
- Qué estructura tendrá (funciones principales, o archivos si aplica).
- Los pasos concretos que vas a seguir para construirlo.

Máximo 8 líneas, directo al grano, en español. NADA de código, NADA de ``` de markdown, NADA de explicaciones de más — solo el plan."""


def generar_plan(descripcion):
    """Modo arquitecto (pipeline de calidad, punto 1): antes de generar
    código de verdad para una petición COMPLEJA (ver
    es_peticion_compleja), le pide a Gemini un plan corto en texto
    plano para que el jefe lo apruebe antes de gastar tokens en código
    que no era lo que quería (ver director._procesar_programar /
    _procesar_proyecto_completo, que lo muestran y esperan CONFIRMAR).
    Devuelve el plan (string) o None si Gemini no respondió — en ese
    caso el llamador debe degradarse a generar directo, nunca bloquear
    al jefe por un fallo de infraestructura."""
    respuesta = balancer.enviar_mensaje(_PROMPT_PLAN.format(descripcion=descripcion))
    if respuesta.startswith("ERROR:"):
        log.warning("code_agent: Gemini no respondió al generar el plan (%s)", respuesta)
        return None
    plan = respuesta.strip()
    return plan or None


def es_peticion_compleja(descripcion):
    """Decide si `descripcion` amerita el pipeline completo (plan
    previo + competencia multi-modelo, ver code_pipeline.
    es_peticion_compleja) — resuelve aquí si la petición es visual
    (ver _tipo_peticion) para que director.py no tenga que conocer esa
    heurística por su cuenta."""
    es_visual = _tipo_peticion(descripcion) != "python"
    return code_pipeline.es_peticion_compleja(descripcion, es_visual=es_visual)


_PROMPT_CORRECCION = """El siguiente programa Python que escribiste falló al ejecutarlo. Aquí está el código:

--- CÓDIGO ---
{codigo}
--- FIN CÓDIGO ---

Este fue el error EXACTO al correrlo:

--- ERROR ---
{error}
--- FIN ERROR ---

Descripción original de lo que debía hacer el programa: {descripcion}

Corrige el código para que este error puntual ya no ocurra. Responde ÚNICAMENTE con el programa Python COMPLETO ya corregido (no un parche, no un diff, el archivo entero listo para correr), sin explicaciones ni ``` de markdown."""

# Nombres de módulo que no coinciden con el nombre del paquete de pip
# que hay que instalar (ej. "import cv2" -> "pip install opencv-python").
_MAPEO_PAQUETES = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "yaml": "pyyaml",
    "sklearn": "scikit-learn",
    "dotenv": "python-dotenv",
    "bs4": "beautifulsoup4",
    "mpl_toolkits": "matplotlib",
}

_TABLA_ACENTOS = str.maketrans("áéíóúñ", "aeioun")

# Palabras demasiado genéricas como para servir de nombre de archivo —
# se quitan al derivar un slug de la descripción (ver generar_nombre_proyecto).
_PALABRAS_VACIAS_NOMBRE = {
    "un", "una", "el", "la", "los", "las", "de", "del", "que", "para",
    "con", "y", "en", "por", "al", "me", "mi", "su", "sus", "creame",
    "cream", "crea", "hazme", "programa", "programame", "programa",
    "necesito", "quiero", "sistema", "script", "app", "aplicacion",
    "algo", "controlado", "controlada", "controladas", "controlados",
}


def _limpiar_markdown(texto):
    """Gemini a veces envuelve el código en ```python ... ``` pese a
    que se le pide que no lo haga — lo quitamos a mano en vez de
    confiar en que siempre obedezca (mismo criterio que figura_agent.py)."""
    texto = texto.strip()
    if texto.startswith("```"):
        lineas = texto.split("\n")
        lineas = lineas[1:]
        if lineas and lineas[-1].strip() == "```":
            lineas = lineas[:-1]
        texto = "\n".join(lineas)
    return texto.strip()


def generar_codigo(descripcion):
    """Genera el programa completo para `descripcion`. Antes de pedirlo,
    busca un patrón ya exitoso parecido en Supabase (ver code_memoria.
    buscar_patron_similar) para usarlo de referencia. Si la petición es
    compleja (ver code_pipeline.es_peticion_compleja — aquí solo por
    frase tipo "hazlo bien", ya se sabe que es Python, no visual), el
    primer intento se genera por competencia Gemini+Groq (ver
    code_pipeline.generar_con_competencia); si no, o si la competencia
    no dio nada usable, se le pide solo a Gemini como siempre. Devuelve
    el código (string) o None si nadie respondió o regresó vacío."""
    referencia = code_memoria.buscar_patron_similar("automatizacion", descripcion)
    system_prompt = _construir_system_prompt(descripcion, referencia=referencia)
    prompt = f"Escribe un programa Python completo y funcional para esto: {descripcion}"

    if code_pipeline.es_peticion_compleja(descripcion):
        codigo = code_pipeline.generar_con_competencia(descripcion, prompt, system_prompt)
        if codigo:
            return codigo
        log.warning("code_agent: competencia multi-modelo sin resultado usable, reintento solo con Gemini")

    respuesta = balancer.enviar_mensaje(prompt, system_instruction=system_prompt)
    if respuesta.startswith("ERROR:"):
        log.warning("code_agent: Gemini no respondió al generar código (%s)", respuesta)
        return None
    codigo = _limpiar_markdown(respuesta)
    return codigo or None


def _corregir_codigo(descripcion, codigo_anterior, error):
    """Le manda a Gemini el código que falló + el traceback exacto,
    pidiendo el programa COMPLETO ya corregido para ese error puntual."""
    respuesta = balancer.enviar_mensaje(
        _PROMPT_CORRECCION.format(codigo=codigo_anterior, error=error[:2000], descripcion=descripcion),
        system_instruction=_construir_system_prompt(descripcion),
    )
    if respuesta.startswith("ERROR:"):
        log.warning("code_agent: Gemini no respondió al corregir código (%s)", respuesta)
        return None
    codigo = _limpiar_markdown(respuesta)
    return codigo or None


def _codigo_peligroso(codigo):
    codigo_bajo = codigo.lower()
    for patron in _PATRONES_PELIGROSOS:
        if patron in codigo_bajo:
            return patron
    return None


# ============================================================
# Generación visual (HTML/JS: Three.js o canvas 2D) — ver _tipo_peticion.
# A diferencia del flujo Python (que reintenta cuando el programa
# TRUENA), aquí el programa casi siempre "corre" sin error aunque se
# vea mal (un blob en vez de un corazón sigue siendo HTML válido), así
# que la señal de corrección es una CAPTURA DE PANTALLA evaluada por
# Gemini Vision en vez de un traceback. Reusa _codigo_peligroso,
# _limpiar_markdown y _normalizar_nombre tal cual (funcionan sobre
# cualquier texto, no son específicas de Python).
# ============================================================

_SYSTEM_PROMPT_VISUAL_BASE = """Eres un experto en gráficos web (Three.js, WebGL, Canvas 2D). El jefe te pide una página HTML completa, autocontenida y funcional — no un ejercicio ni un esqueleto.

Reglas estrictas:
- Responde ÚNICAMENTE con el HTML completo (un solo archivo, con el JavaScript inline en <script>), listo para abrir tal cual en un navegador. Nada de explicaciones antes o después, nada de ``` de markdown.
- El código debe estar TERMINADO de verdad: nunca dejes funciones a medias, nunca escribas "// implementar después" ni ningún otro placeholder (salvo los TODO que ya trae la plantilla base, que SÍ debes resolver).
- Se te da una PLANTILLA BASE ya funcional (escena/cámara/luces/renderer, o el setup de canvas, según aplique) — ADAPTA la geometría/dibujo específico que pidió el jefe en el lugar marcado con TODO, y agrega ahí lo que haga falta (animación, interactividad, colores). NO reescribas desde cero la escena/cámara/renderer/loop que ya trae la plantilla salvo que el jefe pida explícitamente cambiar eso.
- Si el jefe pide una forma reconocible (ej. un corazón, una estrella, una letra), constrúyela con geometría real (ej. THREE.Shape + ExtrudeGeometry) — nunca la aproximes con una primitiva genérica (esfera/cubo/cono) que no se parezca a la forma pedida.
- Nunca cargues recursos externos que no sean las librerías ya indicadas en la plantilla, nunca uses eval(), nunca hagas fetch()/XMLHttpRequest a servidores externos, nunca leas cookies ni almacenamiento local de otros sitios."""


def _construir_system_prompt_visual(tipo, referencia=None):
    plantilla = plantillas_codigo.PLANTILLA_THREEJS if tipo == "visual_3d" else plantillas_codigo.PLANTILLA_CANVAS_2D
    base = f"{_SYSTEM_PROMPT_VISUAL_BASE}\n\n--- PLANTILLA BASE (adáptala, no la reescribas desde cero) ---\n{plantilla}\n--- FIN PLANTILLA BASE ---"
    if referencia:
        base += _PROMPT_EXTRA_REFERENCIA.format(referencia=referencia)
    return base


def generar_codigo_visual(descripcion, tipo, codigo_previo=None, retroalimentacion=None):
    """Le pide el HTML/JS completo para `descripcion` (tipo "visual_3d"
    o "visual_2d"). Si `codigo_previo` viene dado (paso de construcción
    incremental, o corrección tras retroalimentación de Playwright/
    Gemini Vision), le pide a GEMINI que EXTIENDA/CORRIJA ese código en
    vez de partir de la plantilla otra vez — mismo criterio que
    _corregir_codigo para Python, sin competencia (eso solo aplica al
    PRIMER intento). Si `codigo_previo` es None (primer intento), es
    siempre una petición "compleja" (todo lo visual lo es, ver
    es_peticion_compleja) — busca un patrón exitoso parecido (ver
    code_memoria.buscar_patron_similar) y genera por competencia
    Gemini+Groq (ver code_pipeline.generar_con_competencia). Devuelve
    el HTML (string) o None si nadie respondió o regresó vacío."""
    if codigo_previo:
        prompt = f"Este es el código HTML actual:\n\n--- CÓDIGO ACTUAL ---\n{codigo_previo}\n--- FIN CÓDIGO ACTUAL ---\n\n"
        if retroalimentacion:
            prompt += f"Esto está mal / falta corregir:\n{retroalimentacion[:2000]}\n\n"
        prompt += f"Petición original completa: {descripcion}\n\nDevuelve el HTML COMPLETO ya corregido/extendido (el archivo entero, no un parche ni un diff)."

        respuesta = balancer.enviar_mensaje(prompt, system_instruction=_construir_system_prompt_visual(tipo))
        if respuesta.startswith("ERROR:"):
            log.warning("code_agent: Gemini no respondió al generar código visual (%s)", respuesta)
            return None
        codigo = _limpiar_markdown(respuesta)
        return codigo or None

    categoria = "3d" if tipo == "visual_3d" else "2d"
    referencia = code_memoria.buscar_patron_similar(categoria, descripcion)
    system_prompt = _construir_system_prompt_visual(tipo, referencia=referencia)
    prompt = f"Escribe una página HTML completa y funcional para esto: {descripcion}"

    codigo = code_pipeline.generar_con_competencia(descripcion, prompt, system_prompt)
    if codigo:
        return codigo
    log.warning("code_agent: competencia multi-modelo sin resultado usable, reintento solo con Gemini")

    respuesta = balancer.enviar_mensaje(prompt, system_instruction=system_prompt)
    if respuesta.startswith("ERROR:"):
        log.warning("code_agent: Gemini no respondió al generar código visual (%s)", respuesta)
        return None
    codigo = _limpiar_markdown(respuesta)
    return codigo or None


def _capturar_screenshot(ruta_html, ruta_png=RUTA_CAPTURA_VISUAL):
    """Abre `ruta_html` en Chromium headless (Playwright), junta
    cualquier error de JS (excepciones no atrapadas + console.error) y
    toma un screenshot en `ruta_png`. No usa subprocess (a diferencia
    de _ejecutar, que corre programas Python): Playwright ya maneja sus
    propios timeouts internos, así que no hay riesgo de bloquear
    GERAM aunque la página tenga un bucle de animación infinito.
    Devuelve {"ok": bool, "ruta_png": str, "errores_js": [str, ...]} —
    `ok=False` si Playwright truena o si hubo errores de JS."""
    errores_js = []
    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            try:
                pagina = navegador.new_page(viewport={"width": 1280, "height": 800})
                pagina.on("pageerror", lambda exc: errores_js.append(str(exc)))
                pagina.on("console", lambda msg: errores_js.append(msg.text) if msg.type == "error" else None)
                pagina.goto(f"file://{ruta_html}", timeout=_TIMEOUT_CAPTURA_MS)
                try:
                    pagina.wait_for_load_state("networkidle", timeout=_TIMEOUT_CAPTURA_MS)
                except Exception:
                    pass  # animación infinita (RAF) nunca queda "idle" de verdad, seguimos igual
                pagina.wait_for_timeout(500)  # deja correr al menos medio segundo de animación antes de la foto
                pagina.screenshot(path=ruta_png)
            finally:
                navegador.close()
    except Exception as e:
        log.error("code_agent: no se pudo capturar screenshot de '%s' (%s)", ruta_html, e)
        return {"ok": False, "ruta_png": ruta_png, "errores_js": errores_js + [str(e)]}

    return {"ok": not errores_js, "ruta_png": ruta_png, "errores_js": errores_js}


_PROMPT_VISION = """Esta es una captura de pantalla ESTÁTICA de una página web que debía cumplir esta descripción: "{descripcion}"

Importante: es una sola imagen fija — NO puedes ver si algo se mueve/gira/anima ni si el mouse/los controles funcionan, así que NUNCA marques eso como un problema. Evalúa ÚNICAMENTE lo que sí es visible en una foto: la forma/geometría, los colores, la iluminación/sombras y la composición general.
{nota_paso}
Responde ÚNICAMENTE en este formato exacto, sin nada más:
OK: si
o
OK: no
PROBLEMA: <qué está mal específicamente, en una o dos frases>"""


def _evaluar_con_vision(ruta_png, descripcion, nota_paso=None):
    """Le manda `ruta_png` a Gemini Vision preguntando si coincide con
    `descripcion` (balancer.enviar_mensaje_con_imagen, ya existente).
    Devuelve {"aprobado": bool, "problema": str|None}. Si Gemini no
    responde o el formato no se puede parsear, se falla "abierto" (se
    da por aprobado) — mejor entregar algo no verificado que gastar los
    3 intentos peleando con un problema de parseo en vez de uno real."""
    nota = f"\n{nota_paso}\n" if nota_paso else ""
    prompt = _PROMPT_VISION.format(descripcion=descripcion, nota_paso=nota)
    respuesta = balancer.enviar_mensaje_con_imagen(prompt, ruta_png)
    if respuesta.startswith("ERROR:"):
        log.warning("code_agent: Gemini Vision no respondió (%s), se da por aprobado", respuesta)
        return {"aprobado": True, "problema": None}

    coincidencia = re.search(r"OK:\s*(s[ií]|no)", respuesta, re.IGNORECASE)
    if not coincidencia:
        log.warning("code_agent: no se pudo parsear la respuesta de Gemini Vision, se da por aprobado: %r", respuesta[:200])
        return {"aprobado": True, "problema": None}

    if coincidencia.group(1).lower().startswith("s"):
        return {"aprobado": True, "problema": None}

    problema_match = re.search(r"PROBLEMA:\s*(.+)", respuesta, re.IGNORECASE | re.DOTALL)
    problema = problema_match.group(1).strip() if problema_match else "Gemini Vision no dio detalles."
    return {"aprobado": False, "problema": problema}


def _ciclo_visual(descripcion, tipo, ruta_html, codigo_previo=None, descripcion_paso=None, max_intentos=_MAX_INTENTOS_VISUAL):
    """Ciclo genérico de generar -> guardar -> capturar -> evaluar ->
    corregir con la retroalimentación puntual, hasta `max_intentos`.
    Prioriza corregir errores de JS sobre pedirle a Gemini Vision (si
    la página ni renderizó bien, preguntar "¿se ve bien?" no tiene
    caso). Lo reusan tanto crear_proyecto_visual() en una sola pasada
    como cada paso de la construcción incremental (`descripcion_paso`
    ajusta qué se le pide evaluar a Gemini Vision en ESE paso, ver
    _DESCRIPCIONES_PASO).

    `descripcion` es la petición COMPLETA (para que Gemini nunca pierda
    contexto general al generar/corregir), incluso cuando se está
    evaluando solo un paso.

    Devuelve {"ok": bool, "codigo": str|None, "problema": str|None}:
    `codigo` es None solo si Gemini nunca respondió nada usable o si el
    código se rechazó por peligroso (ver _codigo_peligroso) — en
    cualquier otro caso, aunque `ok` sea False, `codigo` trae el último
    HTML generado (se corrió sin errores de JS, pero Gemini Vision no
    quedó conforme tras agotar los intentos)."""
    codigo = codigo_previo
    retroalimentacion = None
    descripcion_evaluar = descripcion_paso["evaluar"] if descripcion_paso else descripcion
    nota_paso = descripcion_paso["nota"] if descripcion_paso else None
    ultimo_problema = None

    intentos_restantes = max_intentos
    while intentos_restantes > 0:
        nuevo_codigo = generar_codigo_visual(descripcion, tipo, codigo_previo=codigo, retroalimentacion=retroalimentacion)
        if nuevo_codigo is None:
            return {"ok": False, "codigo": codigo, "problema": "Gemini no respondió al generar el código."}
        codigo = nuevo_codigo

        patron = _codigo_peligroso(codigo)
        if patron:
            log.warning("code_agent: código visual rechazado por patrón peligroso '%s'", patron)
            return {"ok": False, "codigo": None, "problema": f"código rechazado por seguridad ('{patron}')"}

        with open(ruta_html, "w") as f:
            f.write(codigo)

        captura = _capturar_screenshot(ruta_html)
        intentos_restantes -= 1

        if captura["errores_js"]:
            errores_unicos = list(dict.fromkeys(captura["errores_js"]))
            ultimo_problema = "Errores de JavaScript en consola:\n" + "\n".join(errores_unicos)
            retroalimentacion = ultimo_problema
            continue

        evaluacion = _evaluar_con_vision(captura["ruta_png"], descripcion_evaluar, nota_paso=nota_paso)
        if evaluacion["aprobado"]:
            return {"ok": True, "codigo": codigo, "problema": None}

        ultimo_problema = evaluacion["problema"]
        retroalimentacion = f"Gemini Vision revisó el screenshot y dijo que esto está mal: {ultimo_problema}"

    return {"ok": False, "codigo": codigo, "problema": ultimo_problema}


# Construcción incremental: si la petición tiene 3+ requisitos
# distintos (geometría + luces + animación + controles), se arma en
# pasos — cada uno agrega SOLO su feature sobre el código del paso
# anterior y se verifica antes de seguir, en vez de pedirle a Gemini
# todo junto de una (que es cuando más se le "olvida" alguna parte o
# mezcla mal las features). El orden es fijo porque cada feature
# depende conceptualmente de la anterior (no hay luces que lucir sin
# geometría, no hay controles de cámara sin algo que ver).
_CATEGORIAS_REQUISITOS = {
    "geometria": ("geometría", "geometria", "forma", "figura", "modelo", "objeto", "extruid"),
    "iluminacion": ("luz", "luces", "iluminación", "iluminacion", "sombra"),
    "animacion": ("gire", "girar", "gira", "rota", "anima", "rotarlo", "rotarla"),
    "controles": ("mouse", "ratón", "raton", "arrastrar", "orbit", "interactiv"),
}
_ORDEN_PASOS = ("geometria", "iluminacion", "animacion", "controles")

_DESCRIPCIONES_PASO = {
    "geometria": {
        "evaluar": "Este es el PRIMER paso de una construcción incremental: solo debe verse la forma/geometría base, reconocible, con un color simple.",
        "nota": "Ignora que todavía no tenga iluminación realista, animación ni controles de mouse — eso se agrega en los siguientes pasos. Juzga ÚNICAMENTE si la forma es reconocible.",
    },
    "iluminacion": {
        "evaluar": "Este paso agrega ILUMINACIÓN a una geometría que ya existía de un paso anterior.",
        "nota": "Evalúa si la escena se ve con volumen/sombras razonables. Ignora que todavía no gire ni tenga controles de mouse.",
    },
    "animacion": {
        "evaluar": "Este paso agrega ANIMACIÓN/ROTACIÓN automática a una escena que ya existía.",
        "nota": "No puedes ver movimiento en una imagen fija — evalúa solo que la geometría e iluminación se sigan viendo bien, no juzgues el movimiento en sí.",
    },
    "controles": {
        "evaluar": "Este paso agrega CONTROLES DE MOUSE (orbit) a una escena que ya existía.",
        "nota": "No puedes ver la interactividad en una imagen fija — evalúa solo que la escena se siga viendo bien.",
    },
}


def _detectar_pasos(descripcion):
    """Devuelve la lista de categorías de _ORDEN_PASOS mencionadas en
    `descripcion` (en ese orden fijo) — cada una se vuelve un paso de
    construcción incremental si hay 3 o más (ver crear_proyecto_visual)."""
    texto = descripcion.lower()
    return [cat for cat in _ORDEN_PASOS if any(p in texto for p in _CATEGORIAS_REQUISITOS[cat])]


def crear_proyecto_visual(nombre, descripcion, tipo):
    """Genera una página HTML/JS (Three.js o canvas 2D) para
    `descripcion`, verificando visualmente el resultado (Playwright +
    Gemini Vision, ver _ciclo_visual) en vez de solo confirmar que
    "no truena" como hace crear_proyecto() para Python. Si la petición
    tiene 3+ requisitos distintos, construye en pasos incrementales
    (ver _detectar_pasos), verificando cada paso antes de agregar el
    siguiente. Mismo contrato de retorno que crear_proyecto():
      {"exito": True, "ruta": str, "mensaje": str}
      {"exito": False, "mensaje": str}"""
    nombre_archivo = _normalizar_nombre(nombre)
    ruta = os.path.join(CARPETA_EXPERIMENTOS, f"{nombre_archivo}.html")
    os.makedirs(CARPETA_EXPERIMENTOS, exist_ok=True)

    pasos = _detectar_pasos(descripcion)
    problemas_pendientes = []

    if len(pasos) >= 3:
        log.info("code_agent: construcción incremental para '%s', pasos=%s", nombre_archivo, pasos)
        codigo = None
        for paso in pasos:
            resultado_paso = _ciclo_visual(
                descripcion, tipo, ruta, codigo_previo=codigo,
                descripcion_paso=_DESCRIPCIONES_PASO[paso], max_intentos=_MAX_INTENTOS_PASO,
            )
            if resultado_paso["codigo"] is None:
                return {"exito": False, "mensaje": f"No pude generar el código, jefe: {resultado_paso['problema']}"}
            codigo = resultado_paso["codigo"]
            if not resultado_paso["ok"]:
                problemas_pendientes.append(f"{paso}: {resultado_paso['problema']}")
    else:
        resultado = _ciclo_visual(descripcion, tipo, ruta, max_intentos=_MAX_INTENTOS_VISUAL)
        if resultado["codigo"] is None:
            return {"exito": False, "mensaje": f"No pude generar el código, jefe: {resultado['problema']}"}
        codigo = resultado["codigo"]
        if not resultado["ok"]:
            problemas_pendientes.append(resultado["problema"])

    mensaje = (
        f"Listo, jefe. Creé '{nombre_archivo}.html' en experimentos/ y lo verifiqué con capturas de pantalla.\n\n"
        f"Qué hace: {descripcion}\n\n"
        f"Ábrelo diciendo \"ábrelo\" o abre {ruta} directo en tu navegador."
    )
    if problemas_pendientes:
        mensaje += "\n\nOjo: tras varios intentos, esto no quedó perfecto según la verificación visual:\n" + "\n".join(f"- {p}" for p in problemas_pendientes)
    else:
        # Solo se guarda como patrón exitoso si TODOS los pasos (o el
        # único intento) quedaron aprobados de verdad por Gemini Vision.
        categoria = "3d" if tipo == "visual_3d" else "2d"
        code_memoria.guardar_patron_exitoso(categoria, descripcion, codigo)

    return {"exito": True, "ruta": ruta, "mensaje": mensaje}


def _normalizar_nombre(nombre):
    """Sanitiza `nombre` para usarlo como nombre de archivo dentro de
    experimentos/ — quita cualquier cosa que pudiera escapar de esa
    carpeta (barras, puntos dobles, rutas absolutas)."""
    limpio = nombre.strip().lower().translate(_TABLA_ACENTOS)
    limpio = re.sub(r"[^a-z0-9_-]+", "_", limpio).strip("_")
    return limpio[:60] or "proyecto"


def generar_nombre_proyecto(descripcion):
    """Deriva un nombre de archivo corto a partir de la descripción del
    jefe, SIN gastar tokens (solo decide cómo se llama el .py, no
    afecta la calidad del código que escribe Gemini)."""
    texto = descripcion.lower().translate(_TABLA_ACENTOS)
    palabras = [p for p in re.findall(r"[a-z0-9]+", texto) if p not in _PALABRAS_VACIAS_NOMBRE]
    return _normalizar_nombre("_".join(palabras[:5]) or "proyecto")


def _detectar_modulo_faltante(stderr):
    """Si `stderr` es un ModuleNotFoundError, devuelve el nombre del
    paquete de pip a instalar (traduciendo casos conocidos como
    cv2 -> opencv-python). None si no es ese tipo de error."""
    coincidencia = re.search(r"ModuleNotFoundError: No module named '([\w.]+)'", stderr or "")
    if not coincidencia:
        return None
    modulo = coincidencia.group(1).split(".")[0]
    return _MAPEO_PAQUETES.get(modulo, modulo)


def _ejecutar(ruta):
    """Corre `ruta` con el mismo intérprete que ya está corriendo GERAM
    (venv activo, con matplotlib/mediapipe/opencv ya instalados) y
    detecta si truena en los primeros _TIMEOUT_SEGUNDOS. Si el proceso
    sigue vivo al cumplirse el timeout, se asume que arrancó bien
    (programas con cámara/GUI/bucle de eventos nunca "terminan" solos)
    y subprocess.run ya lo mata al lanzar TimeoutExpired.
    Devuelve {"ok": bool, "stderr": str}."""
    try:
        resultado = subprocess.run(
            [sys.executable, ruta],
            cwd=CARPETA_EXPERIMENTOS, capture_output=True, text=True, timeout=_TIMEOUT_SEGUNDOS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": True, "stderr": ""}
    except Exception as e:
        log.error("code_agent: no se pudo ejecutar '%s' (%s)", ruta, e)
        return {"ok": False, "stderr": str(e)}

    if resultado.returncode != 0:
        return {"ok": False, "stderr": resultado.stderr.strip()}
    return {"ok": True, "stderr": ""}


def instalar_dependencia(paquete):
    """Instala `paquete` con pip. SOLO se debe llamar después de que el
    jefe ya escribió CONFIRMAR (ver confirmar_instalacion y el wizard
    de _accion_pendiente en director.py) — esta función en sí no
    vuelve a preguntar nada, confía en que ya se confirmó antes."""
    log.info("code_agent: instalando dependencia '%s'", paquete)
    try:
        resultado = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--break-system-packages", paquete],
            capture_output=True, text=True, timeout=_TIMEOUT_PIP_SEGUNDOS,
        )
    except subprocess.TimeoutExpired:
        return {"exito": False, "mensaje": f"tardó más de {_TIMEOUT_PIP_SEGUNDOS}s instalando '{paquete}', lo cancelé."}
    except Exception as e:
        return {"exito": False, "mensaje": str(e)}

    if resultado.returncode != 0:
        return {"exito": False, "mensaje": resultado.stderr.strip()[:300]}
    return {"exito": True, "mensaje": f"'{paquete}' instalado."}


def _mensaje_exito(nombre_archivo, ruta, descripcion):
    return (
        f"Listo, jefe. Creé '{nombre_archivo}.py' en experimentos/ y ya lo probé — corre sin tronar.\n\n"
        f"Qué hace: {descripcion}\n\n"
        f"Cómo correrlo: python3 {ruta}"
    )


_MAX_INTENTOS_PRUEBAS = 2


def _ciclo_pruebas(descripcion, codigo, ruta, max_intentos=_MAX_INTENTOS_PRUEBAS):
    """Auto-testing (pipeline de calidad, punto 4): genera casos de
    prueba (ver code_pipeline.generar_casos_prueba) para un script que
    YA se confirmó que corre sin tronar, y si fallan, le pide a Gemini
    que corrija el script con el traceback de la aserción — EXACTAMENTE
    igual que un error de ejecución real (ver _corregir_codigo) — hasta
    `max_intentos` veces. Presupuesto PROPIO, aparte de _MAX_INTENTOS,
    igual que _MAX_INTENTOS_PASO en el flujo visual.

    Devuelve (codigo_final, ok): `ok` es True si las pruebas pasaron o
    si Gemini no propuso ninguna (nada que probar), False si se
    agotaron los intentos con pruebas fallando. El archivo en `ruta`
    siempre queda con el `codigo_final` devuelto."""
    casos = code_pipeline.generar_casos_prueba(descripcion, codigo)
    if casos is None:
        return codigo, True

    intentos = max_intentos
    while intentos > 0:
        with open(ruta, "w") as f:
            f.write(codigo)
        resultado = code_pipeline.ejecutar_pruebas(ruta, casos)
        intentos -= 1

        if resultado["ok"]:
            return codigo, True
        if intentos == 0:
            return codigo, False

        log.info("code_agent: pruebas automáticas fallaron para '%s', pidiendo corrección", ruta)
        nuevo_codigo = _corregir_codigo(descripcion, codigo, "Las pruebas automáticas fallaron:\n" + resultado["traceback"])
        if nuevo_codigo is None:
            return codigo, False
        patron = _codigo_peligroso(nuevo_codigo)
        if patron:
            log.warning("code_agent: corrección por pruebas rechazada por patrón peligroso '%s'", patron)
            return codigo, False
        codigo = nuevo_codigo
        # El código cambió: regenera los casos por si las firmas de las funciones cambiaron.
        nuevos_casos = code_pipeline.generar_casos_prueba(descripcion, codigo)
        if nuevos_casos:
            casos = nuevos_casos

    return codigo, False


def crear_proyecto(nombre, descripcion, _reanudacion=None):
    """Genera el código con generar_codigo(), lo guarda en
    experimentos/{nombre}.py, lo ejecuta para detectar si truena, y si
    truena le manda el error de vuelta a Gemini para que lo corrija —
    hasta _MAX_INTENTOS intentos en total.

    Si el error es una dependencia faltante, NO instala nada solo: para
    la ejecución y devuelve {"pendiente_instalacion": {...}} para que
    director.py pida CONFIRMAR primero (ver confirmar_instalacion, que
    retoma este mismo flujo una vez instalada la dependencia).

    `_reanudacion` es uso interno de confirmar_instalacion(): trae
    {"codigo", "intentos_restantes"} para no volver a generar el código
    desde cero (ni gastar tokens de más) después de instalar.

    Devuelve un dict:
      {"exito": True, "ruta": str, "mensaje": str}
      {"exito": False, "mensaje": str}
      {"exito": False, "mensaje": str, "pendiente_instalacion": {...}}

    Si `descripcion` pide algo visual (Three.js/canvas, ver
    _tipo_peticion) en vez de un programa Python, despacha a
    crear_proyecto_visual() — ese flujo no tiene pendiente_instalacion
    (no depende de pip), por eso este chequeo se salta cuando viene una
    `_reanudacion` en curso (siempre es Python, ver confirmar_instalacion)."""
    if not _reanudacion:
        tipo = _tipo_peticion(descripcion)
        if tipo != "python":
            return crear_proyecto_visual(nombre, descripcion, tipo)

    nombre_archivo = _normalizar_nombre(nombre)
    ruta = os.path.join(CARPETA_EXPERIMENTOS, f"{nombre_archivo}.py")

    if _reanudacion:
        codigo = _reanudacion["codigo"]
        intentos_restantes = _reanudacion["intentos_restantes"]
        error_anterior = None
    else:
        codigo = generar_codigo(descripcion)
        if codigo is None:
            return {"exito": False, "mensaje": "No pude generar el código, jefe: Gemini no respondió."}
        intentos_restantes = _MAX_INTENTOS
        error_anterior = None

    while intentos_restantes > 0:
        if error_anterior:
            nuevo_codigo = _corregir_codigo(descripcion, codigo, error_anterior)
            if nuevo_codigo is None:
                return {
                    "exito": False,
                    "mensaje": f"El código falló y no pude pedirle una corrección a Gemini. Último error:\n{error_anterior[:400]}",
                }
            codigo = nuevo_codigo

        patron = _codigo_peligroso(codigo)
        if patron:
            log.warning("code_agent: código rechazado por patrón peligroso '%s'", patron)
            return {
                "exito": False,
                "mensaje": f"El código que generó Gemini intentó algo que no permito ejecutar ('{patron}'), cancelé todo por seguridad. No se guardó ni se corrió nada.",
            }

        os.makedirs(CARPETA_EXPERIMENTOS, exist_ok=True)
        with open(ruta, "w") as f:
            f.write(codigo)

        # Linter (pipeline de calidad, punto 5): ruff corre GRATIS y
        # detecta sintaxis/imports rotos sin gastar el timeout de
        # _ejecutar — si encuentra algo, se corrige aquí mismo antes de
        # intentar correr el programa (mismo "intento" del presupuesto
        # general, solo se salta el paso de ejecución en esta vuelta).
        errores_lint = code_pipeline.lint_python(ruta)
        if errores_lint:
            log.info("code_agent: ruff encontró %d problema(s) en '%s', corrigiendo antes de ejecutar", len(errores_lint), nombre_archivo)
            intentos_restantes -= 1
            error_anterior = "Errores del linter (ruff), corrígelos:\n" + "\n".join(errores_lint)
            continue

        resultado = _ejecutar(ruta)
        intentos_restantes -= 1

        if resultado["ok"]:
            pruebas_ok = True
            if code_pipeline.es_testeable(descripcion):
                codigo, pruebas_ok = _ciclo_pruebas(descripcion, codigo, ruta)

            mensaje = _mensaje_exito(nombre_archivo, ruta, descripcion)
            if pruebas_ok:
                code_memoria.guardar_patron_exitoso("automatizacion", descripcion, codigo)
            else:
                mensaje += (
                    "\n\nOjo: generé pruebas automáticas para verificarlo y no lograron pasar del todo "
                    "tras varios intentos — revísalo con calma antes de confiar en él a ciegas."
                )
            return {"exito": True, "ruta": ruta, "mensaje": mensaje}

        paquete = _detectar_modulo_faltante(resultado["stderr"])
        if paquete:
            return {
                "exito": False,
                "mensaje": (
                    f"El programa necesita la librería '{paquete}', que no está instalada.\n"
                    f"¿Quieres que la instale con pip? Escribe CONFIRMAR para continuar o cualquier otra cosa para cancelar."
                ),
                "pendiente_instalacion": {
                    "paquete": paquete,
                    "nombre": nombre,
                    "descripcion": descripcion,
                    "codigo": codigo,
                    "intentos_restantes": max(intentos_restantes, 1),
                },
            }

        error_anterior = resultado["stderr"]

    return {
        "exito": False,
        "mensaje": f"Después de {_MAX_INTENTOS} intentos, el código sigue fallando, jefe. Último error:\n{(error_anterior or '')[:400]}",
    }


def confirmar_instalacion(datos):
    """Instala datos["paquete"] (ya confirmado por el jefe) y retoma
    crear_proyecto() con el mismo código que ya se había generado, sin
    volver a gastar tokens en regenerarlo desde cero. Devuelve el mismo
    contrato que crear_proyecto()."""
    paquete = datos["paquete"]
    resultado_pip = instalar_dependencia(paquete)
    if not resultado_pip["exito"]:
        return {"exito": False, "mensaje": f"No pude instalar '{paquete}': {resultado_pip['mensaje']}"}

    return crear_proyecto(
        datos["nombre"], datos["descripcion"],
        _reanudacion={"codigo": datos["codigo"], "intentos_restantes": datos["intentos_restantes"]},
    )
