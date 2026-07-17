# ============================================================
# GERAM OS v2 · figura_agent.py
# "Dibújame X" / "hazme un diagrama de X": Gemini escribe el código
# de matplotlib que dibuja la figura, y ESTE archivo lo ejecuta.
#
# Es la ÚNICA parte de todo el proyecto donde se corre código escrito
# por la IA (en el resto, Gemini solo ELIGE entre acciones ya
# construidas — ver control_agent.interpretar()). El riesgo se acota
# con tres capas, ninguna es un sandbox perfecto pero juntas son
# proporcionales a que este mismo asistente ya tiene control total del
# equipo (mouse, teclado, apagar, borrar archivos):
#   1. Filtro de patrones peligrosos ANTES de ejecutar (ver
#      _PATRONES_PELIGROSOS) — best-effort, no reemplaza revisar qué
#      pide el jefe.
#   2. Timeout corto (ver _TIMEOUT_SEGUNDOS) para que un bucle infinito
#      no cuelgue el proceso.
#   3. Corre en una carpeta temporal aislada (tempfile.mkdtemp), y el
#      wrapper (no el código de Gemini) es el único que hace
#      plt.savefig/close — a Gemini solo se le pide que DIBUJE.
# ============================================================

import logging
import os
import shutil
import subprocess
import sys
import tempfile

from agents import balancer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("figura_agent")

RUTA_FIGURA = "/tmp/geram_figura.png"
RUTA_FIGURA_GIF = "/tmp/geram_figura_animada.gif"

_TIMEOUT_SEGUNDOS = 15

# Palabras que activan gráficas 3D (matplotlib mplot3d) o animaciones
# (GIF vía FuncAnimation) — ver _procesar_figura en director.py, que
# manda la descripción completa tal cual, así que basta con buscar
# estas pistas dentro de ella.
_PISTAS_3D = ("3d", "tridimensional")
_PISTAS_ANIMACION = ("animación", "animacion", "animado", "animada", "que se mueva", "gif", "anima")


def _es_3d(descripcion):
    descripcion_baja = descripcion.lower()
    return any(p in descripcion_baja for p in _PISTAS_3D)


def _es_animacion(descripcion):
    descripcion_baja = descripcion.lower()
    return any(p in descripcion_baja for p in _PISTAS_ANIMACION)

# Best-effort: si el código generado toca cualquiera de estos, se
# rechaza SIN ejecutar. No es exhaustivo (no hay forma de serlo con un
# blocklist de texto), pero cubre los casos obvios de red/sistema/
# archivos fuera de la carpeta de trabajo.
_PATRONES_PELIGROSOS = (
    "import os", "import sys", "import subprocess", "import shutil",
    "import socket", "import requests", "import urllib", "import ctypes",
    "import pathlib", "__import__", "eval(", "exec(", "compile(",
    "open(", "os.system", "os.remove", "os.popen", "input(",
    "globals(", "locals(", "getattr(", "setattr(", "delattr(",
)

_PROMPT_BASE_FIGURA = """Escribes SOLO código Python que dibuja una figura con matplotlib.

Reglas estrictas:
- Tu respuesta es ÚNICAMENTE código Python, sin explicaciones, sin comentarios de markdown, sin ```.
- Ya tienes disponibles, importados de antemano: `plt` (matplotlib.pyplot), `np` (numpy), `fig` y `ax` (una figura y unos ejes ya creados). Úsalos directo, no vuelvas a crear otra figura ni vuelvas a importar matplotlib/numpy.
- NUNCA llames a plt.savefig, plt.show, plt.close ni escribas archivos — el sistema se encarga de guardar el resultado después de que corra tu código.
- NUNCA importes os, sys, subprocess, shutil, socket, requests, urllib ni nada que toque red/sistema/archivos — solo lo necesario de matplotlib/numpy para dibujar.
- Formas simples ya están disponibles directo como plt.Circle/plt.Rectangle. OJO: "plt.patches" NO existe — para Polygon, FancyArrowPatch, Path, etc. impórtalos explícitamente al inicio de tu código, ej. `from matplotlib.patches import Polygon, FancyArrowPatch` o `from matplotlib.path import Path` (esos imports SÍ están permitidos, solo no reimportes matplotlib.pyplot ni numpy que ya están listos).
- Si lo que te piden es un diagrama de flujo o un dibujo con formas/texto, usa ax.add_patch(...), ax.annotate/ax.text y ax.set_xlim/ax.set_ylim/ax.axis('off') — no necesitas una librería de diagramas.
- OJO CON LA ORIENTACIÓN: en matplotlib el eje Y crece hacia ARRIBA (y más grande = más arriba en la imagen final) — es LO CONTRARIO de coordenadas de pantalla/imagen (donde y crece hacia ABAJO, como en HTML/canvas/PIL). Si dibujas algo con un orden vertical (un diagrama de flujo de arriba a abajo, una jerarquía, pasos numerados, una lista), el PRIMER elemento (el que debe quedar más arriba) necesita el valor de Y MÁS ALTO, y cada elemento siguiente hacia abajo necesita un Y MENOR. Si asignas los Y pensando en coordenadas de pantalla (primer elemento en y=0, bajando con y=1, y=2...), la figura entera sale volteada verticalmente — revisa esto SIEMPRE antes de responder.
- Deja MARGEN alrededor de lo que dibujes: calcula ax.set_xlim/ax.set_ylim con al menos 10-15% de espacio extra más allá de la posición más extrema de cualquier elemento (incluyendo el ancho/alto aproximado de cualquier texto o caja), para que nada quede cortado en el borde de la figura."""

_PROMPT_EXTRA_3D = """
- `ax` YA es de proyección 3D (creado con projection='3d'). Dibuja con métodos 3D: ax.plot_surface(X, Y, Z, ...), ax.plot3D(...), ax.scatter(x, y, z, ...), ax.set_zlabel(...), etc. — necesitas 3 coordenadas, no 2."""

_PROMPT_EXTRA_ANIMACION = """
- Esto es una ANIMACIÓN: en vez de dibujar una sola vez, define una función `def actualizar(frame):` que modifica el dibujo en cada cuadro (frame es un entero que va de 0 en adelante). NO llames a esa función tú mismo, ni crees FuncAnimation, ni guardes nada — el sistema la llama por su cuenta. Todo lo que dibujes debe pasar DENTRO de actualizar(frame) (usa las variables ax/fig ya existentes, no crees nuevas)."""


def _construir_prompt(es_3d, es_animacion):
    prompt = _PROMPT_BASE_FIGURA
    if es_3d:
        prompt += _PROMPT_EXTRA_3D
    if es_animacion:
        prompt += _PROMPT_EXTRA_ANIMACION
    return prompt


def _codigo_peligroso(codigo):
    codigo_bajo = codigo.lower()
    for patron in _PATRONES_PELIGROSOS:
        if patron in codigo_bajo:
            return patron
    return None


def _limpiar_markdown(texto):
    """Gemini a veces envuelve el código en ```python ... ``` pese a
    que se le pide que no lo haga — lo quitamos a mano en vez de
    confiar en que siempre obedezca."""
    texto = texto.strip()
    if texto.startswith("```"):
        lineas = texto.split("\n")
        lineas = lineas[1:]  # quita la línea ``` (o ```python) inicial
        if lineas and lineas[-1].strip() == "```":
            lineas = lineas[:-1]
        texto = "\n".join(lineas)
    return texto.strip()


def generar_codigo(descripcion, es_3d=False, es_animacion=False):
    """Le pide a Gemini el código de matplotlib para `descripcion`.
    Devuelve el código (string) o None si Gemini falló (ver
    balancer.enviar_mensaje, que nunca lanza excepción pero puede
    devolver un string "ERROR: ...")."""
    respuesta = balancer.enviar_mensaje(
        f"Dibuja: {descripcion}", system_instruction=_construir_prompt(es_3d, es_animacion),
    )
    if respuesta.startswith("ERROR:"):
        return None
    return _limpiar_markdown(respuesta)


def ejecutar_codigo(codigo, es_3d=False, es_animacion=False):
    """Corre `codigo` (ya generado) en un subproceso aislado. Guarda una
    imagen estática en RUTA_FIGURA, o un GIF en RUTA_FIGURA_GIF si
    `es_animacion`. Devuelve {"ruta": ...} o {"error": "..."}."""
    patron = _codigo_peligroso(codigo)
    if patron:
        return {"error": f"el código generado incluía algo que no permito ejecutar ('{patron}'), no lo corrí."}

    ruta_salida = RUTA_FIGURA_GIF if es_animacion else RUTA_FIGURA
    preambulo_ejes = (
        "fig = plt.figure()\nax = fig.add_subplot(projection='3d')\n" if es_3d
        else "fig, ax = plt.subplots()\n"
    )
    # El código de Gemini NUNCA guarda nada (ver prompt): para estáticas
    # el wrapper hace plt.savefig; para animadas arma el FuncAnimation
    # llamando a actualizar(frame), que Gemini debió definir.
    cierre = (
        "from matplotlib.animation import FuncAnimation, PillowWriter\n"
        f"_anim = FuncAnimation(fig, actualizar, frames=24, interval=100)\n"
        f"_anim.save({ruta_salida!r}, writer=PillowWriter(fps=10))\n"
        if es_animacion
        else f"plt.savefig({ruta_salida!r})\nplt.close('all')\n"
    )
    script = (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "import numpy as np\n"
        + preambulo_ejes
        + codigo
        + "\n" + cierre
    )

    if os.path.exists(ruta_salida):
        os.remove(ruta_salida)

    carpeta_temporal = tempfile.mkdtemp(prefix="geram_figura_")
    try:
        resultado = subprocess.run(
            [sys.executable, "-c", script],
            cwd=carpeta_temporal, capture_output=True, text=True, timeout=_TIMEOUT_SEGUNDOS,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"tardó más de {_TIMEOUT_SEGUNDOS}s en generar la figura, lo cancelé."}
    except Exception as e:
        log.error("figura_agent: no se pudo ejecutar el código generado (%s)", e)
        return {"error": str(e)}
    finally:
        shutil.rmtree(carpeta_temporal, ignore_errors=True)

    if resultado.returncode != 0:
        return {"error": f"el código generado falló: {resultado.stderr.strip()[:300]}"}
    if not os.path.exists(ruta_salida):
        return {"error": "el código corrió pero no generó ninguna imagen."}
    return {"ruta": ruta_salida}


# Última figura generada (código + parámetros), para que "corrígelo"/
# "está al revés"/"no cabe" en el SIGUIENTE mensaje le pida a Gemini una
# corrección PUNTUAL sobre el código real que se usó (ver
# corregir_figura), en vez de generar_figura() arrancando de cero sin
# saber qué se dibujó antes — eso es lo que hacía que "corregir" a veces
# saliera con un problema DISTINTO (ej. "no cabía"): no era una
# corrección, era una figura nueva a ciegas. GLOBAL a propósito (un solo
# jefe, una sola "última figura"), mismo criterio que
# context_engine._ultimo_archivo_creado.
_ultima_figura = None  # {"descripcion", "codigo", "es_3d", "es_animacion"}


def generar_figura(descripcion):
    """Junta generar_codigo() + ejecutar_codigo(), detectando solo/3D/
    animada a partir de `descripcion` (ver _es_3d/_es_animacion). Si
    sale bien, recuerda el código en _ultima_figura para que una
    corrección posterior (ver corregir_figura) no tenga que arrancar de
    cero. Devuelve (ruta, None) si salió bien, o (None, mensaje_de_error)
    si falló en cualquier paso. CERO tokens salvo la llamada a Gemini
    para escribir el código (no hay reintento automático ante un error
    de ejecución en esta versión: si el código generado falla, se
    reporta el error tal cual — la corrección es cosa del jefe, ver
    corregir_figura)."""
    global _ultima_figura
    es_3d = _es_3d(descripcion)
    es_animacion = _es_animacion(descripcion)

    codigo = generar_codigo(descripcion, es_3d=es_3d, es_animacion=es_animacion)
    if codigo is None:
        return None, "no pude generar el código de la figura (Gemini no respondió)."
    if not codigo.strip():
        return None, "Gemini regresó una respuesta vacía."

    resultado = ejecutar_codigo(codigo, es_3d=es_3d, es_animacion=es_animacion)
    if resultado.get("error"):
        return None, resultado["error"]

    _ultima_figura = {"descripcion": descripcion, "codigo": codigo, "es_3d": es_3d, "es_animacion": es_animacion}
    return resultado["ruta"], None


_PROMPT_CORRECCION_FIGURA = """Este es el código de matplotlib que escribiste para esta petición: "{descripcion}"

--- CÓDIGO ANTERIOR ---
{codigo}
--- FIN CÓDIGO ANTERIOR ---

El jefe revisó el resultado y dice que esto está mal: {retroalimentacion}

Corrige el código para arreglar ESE problema puntual (revisa especialmente la orientación de los ejes Y los márgenes si el problema es que algo salió volteado o cortado — ver las reglas de orientación/margen que ya conoces), manteniendo el resto del dibujo igual. Responde ÚNICAMENTE con el código Python COMPLETO ya corregido (el bloque de dibujo entero, no un parche/diff), sin explicaciones ni ``` de markdown."""


def corregir_figura(retroalimentacion):
    """"Corrígelo"/"está al revés"/"no cabe"/"arréglalo": le manda a
    Gemini el ÚLTIMO código generado (ver _ultima_figura) junto con lo
    que el jefe dice que está mal, pidiendo una corrección PUNTUAL —
    a diferencia de generar_figura(), que no tiene forma de saber qué
    se dibujó antes. Devuelve (ruta, None) si salió bien, o
    (None, mensaje_de_error) si no hay una figura previa que corregir
    o algo falló."""
    global _ultima_figura
    if _ultima_figura is None:
        return None, "no tengo ninguna figura reciente que corregir, jefe. Pídeme que dibuje algo primero."

    respuesta = balancer.enviar_mensaje(
        _PROMPT_CORRECCION_FIGURA.format(
            descripcion=_ultima_figura["descripcion"], codigo=_ultima_figura["codigo"],
            retroalimentacion=retroalimentacion,
        ),
        system_instruction=_construir_prompt(_ultima_figura["es_3d"], _ultima_figura["es_animacion"]),
    )
    if respuesta.startswith("ERROR:"):
        return None, "no pude corregir la figura (Gemini no respondió)."
    codigo = _limpiar_markdown(respuesta)
    if not codigo.strip():
        return None, "Gemini regresó una respuesta vacía al corregir."

    resultado = ejecutar_codigo(codigo, es_3d=_ultima_figura["es_3d"], es_animacion=_ultima_figura["es_animacion"])
    if resultado.get("error"):
        return None, resultado["error"]

    _ultima_figura = {**_ultima_figura, "codigo": codigo}
    return resultado["ruta"], None
