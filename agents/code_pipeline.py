# ============================================================
# GERAM OS v2 · code_pipeline.py
# Pipeline de calidad que usa code_agent.py (y code_proyectos.py) para
# subir el nivel de lo que genera: decidir qué peticiones ameritan el
# esfuerzo extra (ver es_peticion_compleja), pedirle el primer intento
# a DOS modelos en paralelo y quedarse con el mejor (ver
# generar_con_competencia), correr un linter antes de gastar un ciclo
# de ejecución (ver lint_python), y generar/correr un par de casos de
# prueba básicos para scripts de lógica pura (ver es_testeable/
# generar_casos_prueba/ejecutar_pruebas).
#
# Deliberadamente NO importa nada de code_agent.py (sería circular,
# code_agent.py es quien importa esto) — todo lo que necesita del
# contexto de la petición (si es visual, qué código ya se generó) se
# lo pasa el llamador como parámetro.
# ============================================================

import logging
import os
import subprocess
import sys
import threading

from agents import balancer, groq_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("code_pipeline")

_TIMEOUT_LINT_SEGUNDOS = 10
_TIMEOUT_PRUEBAS_SEGUNDOS = 10

# --- Petición "compleja": amerita plan previo (modo arquitecto) y
# competencia multi-modelo. `es_visual` lo decide el llamador (ver
# code_agent._tipo_peticion) para no duplicar esa heurística aquí —
# cualquier cosa visual/3D siempre cuenta. Además, cualquier frase que
# pida explícitamente el máximo esfuerzo.
_PISTAS_EXIGENCIA = (
    "hazlo bien", "hazlo lo mejor posible", "al límite", "al limite",
    "lo mejor posible", "hazlo perfecto", "sin límites", "sin limites",
    "que quede increíble", "que quede increible", "que quede perfecto",
)


def es_peticion_compleja(descripcion, es_visual=False):
    """True si `descripcion` amerita el pipeline completo (plan previo
    + competencia multi-modelo): cualquier cosa visual/3D, o si el
    jefe pide explícitamente el máximo esfuerzo con alguna de
    _PISTAS_EXIGENCIA. Peticiones simples ("hazme un script que sume
    dos números") siguen yendo directo, sin este paso extra."""
    if es_visual:
        return True
    texto = descripcion.lower()
    return any(p in texto for p in _PISTAS_EXIGENCIA)


def _limpiar_markdown(texto):
    """Mismo criterio que code_agent._limpiar_markdown/figura_agent.
    _limpiar_markdown — duplicado a propósito (convención ya usada en
    el proyecto en vez de un import cruzado para una función trivial)."""
    texto = texto.strip()
    if texto.startswith("```"):
        lineas = texto.split("\n")
        lineas = lineas[1:]
        if lineas and lineas[-1].strip() == "```":
            lineas = lineas[:-1]
        texto = "\n".join(lineas)
    return texto.strip()


# ============================================================
# Competencia multi-modelo (Gemini + Groq en paralelo + juez)
# ============================================================

_PROMPT_JUEZ = """El jefe pidió esto: "{descripcion}"

Aquí hay DOS soluciones completas para esa petición, escritas por dos modelos distintos.

--- SOLUCIÓN A ---
{solucion_a}
--- FIN SOLUCIÓN A ---

--- SOLUCIÓN B ---
{solucion_b}
--- FIN SOLUCIÓN B ---

Decide cuál de las dos cumple mejor la petición, o combina lo mejor de ambas si eso da un resultado superior a cualquiera de las dos por separado. Responde ÚNICAMENTE con el código final ganador (o combinado), completo y listo para usar tal cual — nada de explicaciones, nada de decir cuál elegiste ni por qué, nada de ``` de markdown."""


def generar_con_competencia(descripcion, prompt, system_prompt):
    """Le pide el PRIMER intento del código a Gemini (balancer) y a
    Groq (groq_agent, primer uso para generar código en vez de texto
    largo) EN PARALELO, con el mismo prompt/system_prompt, y si ambos
    responden algo usable, le pide a Gemini un tercer juicio: cuál es
    mejor o una combinación de ambas (ver _PROMPT_JUEZ). Si solo uno
    de los dos respondió, se usa ese directo sin gastar el tercer
    prompt. Devuelve el código ya limpio de markdown, o None si
    NINGUNO de los dos modelos respondió nada usable.

    Solo se usa para el primer intento de peticiones complejas (ver
    es_peticion_compleja) — las correcciones posteriores siguen siendo
    Gemini-only (_corregir_codigo en code_agent.py/code_proyectos.py):
    repetir la competencia en cada retry sería carísimo en tokens para
    poco beneficio."""
    resultados = {}

    def _pedir_gemini():
        resultados["gemini"] = balancer.enviar_mensaje(prompt, system_instruction=system_prompt)

    def _pedir_groq():
        resultados["groq"] = groq_agent.generar_contenido(prompt, system_prompt=system_prompt or "")

    hilo_gemini = threading.Thread(target=_pedir_gemini)
    hilo_groq = threading.Thread(target=_pedir_groq)
    hilo_gemini.start()
    hilo_groq.start()
    hilo_gemini.join()
    hilo_groq.join()

    texto_gemini = resultados.get("gemini")
    texto_groq = resultados.get("groq")
    gemini_ok = bool(texto_gemini) and not texto_gemini.startswith("ERROR:")
    groq_ok = bool(texto_groq) and not texto_groq.startswith("ERROR:")

    if gemini_ok and not groq_ok:
        log.info("code_pipeline: competencia — solo Gemini respondió")
        return _limpiar_markdown(texto_gemini)
    if groq_ok and not gemini_ok:
        log.info("code_pipeline: competencia — solo Groq respondió")
        return _limpiar_markdown(texto_groq)
    if not gemini_ok and not groq_ok:
        log.warning("code_pipeline: competencia — ni Gemini ni Groq respondieron")
        return None

    log.info("code_pipeline: competencia — ambos respondieron, pidiendo juicio a Gemini")
    veredicto = balancer.enviar_mensaje(
        _PROMPT_JUEZ.format(descripcion=descripcion, solucion_a=texto_gemini, solucion_b=texto_groq),
        system_instruction=system_prompt,
    )
    if veredicto.startswith("ERROR:"):
        log.warning("code_pipeline: el juicio falló, me quedo con la versión de Gemini")
        return _limpiar_markdown(texto_gemini)
    return _limpiar_markdown(veredicto)


# ============================================================
# Linter (ruff) — solo errores reales (sintaxis + pyflakes), nada de
# estilo, para no pelear con Gemini por nimiedades.
# ============================================================

def lint_python(ruta):
    """Corre ruff sobre `ruta` (mismo intérprete que ya corre GERAM,
    vía `-m ruff` en vez de depender de que el binario esté en PATH).
    Devuelve la lista de líneas de error (E9 = errores de sintaxis, F =
    pyflakes: imports rotos, nombres no definidos, etc.), vacía si está
    limpio o si ruff no se pudo correr — best-effort, nunca bloquea el
    pipeline por su cuenta."""
    try:
        resultado = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--quiet", "--output-format=concise", "--select=E9,F", ruta],
            capture_output=True, text=True, timeout=_TIMEOUT_LINT_SEGUNDOS,
        )
    except Exception as e:
        log.warning("code_pipeline: no se pudo correr ruff sobre '%s' (%s)", ruta, e)
        return []

    if resultado.returncode == 0:
        return []
    return [linea for linea in resultado.stdout.strip().split("\n") if linea.strip()]


# ============================================================
# Auto-testing para scripts de lógica pura (no aplica a programas
# interactivos/GUI/cámara, ver es_testeable).
# ============================================================

_PISTAS_NO_TESTEABLE = (
    "cámara", "camara", "webcam", "gui", "ventana", "interfaz gráfica", "interfaz grafica",
    "mouse", "ratón", "raton", "teclado", "servidor", "server", "socket",
    "voz", "micrófono", "microfono", "reconocimiento de voz",
    "tiempo real", "bucle infinito", "notificación", "notificacion",
    "reproduce", "reproducir audio", "reproducir video", "captura de pantalla",
)


def es_testeable(descripcion):
    """True si `descripcion` tiene pinta de lógica pura/automatización
    (una función que calcula/procesa/transforma algo, verificable con
    asserts) en vez de un programa interactivo/GUI/cámara/servidor sin
    un comportamiento fijo que probar con casos sueltos."""
    texto = descripcion.lower()
    return not any(p in texto for p in _PISTAS_NO_TESTEABLE)


_PROMPT_CASOS_PRUEBA = """Este es un programa Python ya escrito que debía cumplir esta petición: "{descripcion}"

--- CÓDIGO ---
{codigo}
--- FIN CÓDIGO ---

Escribe 2 o 3 casos de prueba simples en Python que verifiquen que el programa hace lo que se le pidió. Reglas:
- Usa `assert` plano (nada de pytest/unittest ni ningún framework).
- Llama DIRECTO a las funciones que ya están definidas en el código de arriba — no las vuelvas a definir, ya van a estar disponibles al correr tus pruebas.
- Casos realistas y simples basados en la petición original, nada exhaustivo — solo el comportamiento básico esperado.
- Si el programa NO define ninguna función reutilizable con un resultado verificable (ej. todo el trabajo pasa dentro de main() sin retornar nada, o es puramente interactivo), responde ÚNICAMENTE la palabra: NINGUNA

Responde ÚNICAMENTE con el código Python de las pruebas (o la palabra NINGUNA), sin explicaciones, sin ``` de markdown."""


def generar_casos_prueba(descripcion, codigo):
    """Le pide a Gemini 2-3 casos de prueba (asserts) para `codigo`, ya
    generado y confirmado que corre sin tronar. Devuelve el snippet de
    Python, o None si Gemini no propuso pruebas útiles (dijo NINGUNA,
    no respondió, o regresó vacío) — en ese caso no hay auto-testing
    para este script en particular."""
    respuesta = balancer.enviar_mensaje(_PROMPT_CASOS_PRUEBA.format(descripcion=descripcion, codigo=codigo))
    if respuesta.startswith("ERROR:"):
        return None
    texto = _limpiar_markdown(respuesta)
    if not texto or texto.strip().upper() == "NINGUNA":
        return None
    return texto


def ejecutar_pruebas(ruta_script, codigo_pruebas):
    """Corre `codigo_pruebas` (snippet con asserts, ver
    generar_casos_prueba) en un subproceso que primero importa
    `ruta_script` como módulo — mismo intérprete/entorno que
    code_agent._ejecutar, mismo criterio de timeout corto. El archivo
    de prueba temporal vive junto al script (mismo directorio, para
    que el import por nombre de módulo funcione) y se borra al
    terminar, sin importar el resultado. Devuelve
    {"ok": bool, "traceback": str}."""
    carpeta = os.path.dirname(ruta_script) or "."
    modulo = os.path.splitext(os.path.basename(ruta_script))[0]
    script_prueba = f"import sys\nsys.path.insert(0, {carpeta!r})\nfrom {modulo} import *\n\n{codigo_pruebas}\n"
    ruta_temporal = os.path.join(carpeta, f"_prueba_{modulo}.py")

    try:
        with open(ruta_temporal, "w") as f:
            f.write(script_prueba)
        resultado = subprocess.run(
            [sys.executable, ruta_temporal],
            cwd=carpeta, capture_output=True, text=True, timeout=_TIMEOUT_PRUEBAS_SEGUNDOS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "traceback": "Las pruebas automáticas tardaron demasiado (posible bucle infinito)."}
    except Exception as e:
        log.error("code_pipeline: no se pudieron correr las pruebas de '%s' (%s)", ruta_script, e)
        return {"ok": False, "traceback": str(e)}
    finally:
        if os.path.exists(ruta_temporal):
            os.remove(ruta_temporal)

    if resultado.returncode != 0:
        return {"ok": False, "traceback": resultado.stderr.strip()}
    return {"ok": True, "traceback": ""}
