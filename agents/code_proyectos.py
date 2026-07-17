# ============================================================
# GERAM OS v2 · code_proyectos.py
# "Créame un proyecto de código..."/"hazme una app web..."/"crea un
# juego de..."/"hazme un sitio web...": a diferencia de code_agent.py
# (que genera UN archivo suelto en experimentos/), este módulo genera
# un PROYECTO MULTI-ARCHIVO completo en proyectos/{nombre}/ — primero
# planea la estructura (qué archivos, qué contiene cada uno) y se la
# muestra al jefe para que confirme (mismo "modo arquitecto" que
# code_agent.generar_plan, ver director._procesar_proyecto_completo),
# y solo al CONFIRMAR genera cada archivo, manteniendo un mapa del
# proyecto (qué expone cada archivo ya generado — funciones, IDs,
# clases CSS) para que los archivos siguientes referencien cosas
# reales en vez de inventarlas.
#
# Reusa deliberadamente varias piezas "privadas" de code_agent.py
# (_codigo_peligroso, _normalizar_nombre, _capturar_screenshot,
# _evaluar_con_vision, _MAPEO_PAQUETES, instalar_dependencia) en vez
# de duplicarlas — mismo filtro de seguridad, misma verificación
# visual Playwright+Gemini Vision, mismo instalador de pip que ya usa
# el flujo de archivo suelto.
# ============================================================

import importlib
import json
import logging
import os
import re
import subprocess
import sys

from agents import balancer, code_agent, code_memoria, control_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("code_proyectos")

CARPETA_PROYECTOS = "/home/mauri/geramv3/proyectos"

_TIMEOUT_EJECUCION_SEGUNDOS = 15
_MAX_INTENTOS_PROYECTO = 3
RUTA_CAPTURA_PROYECTO = "/tmp/geram_code_proyectos_captura.png"


def _limpiar_markdown(texto):
    """Mismo criterio que code_agent._limpiar_markdown — duplicado a
    propósito (convención ya usada en el proyecto)."""
    texto = texto.strip()
    if texto.startswith("```"):
        lineas = texto.split("\n")
        lineas = lineas[1:]
        if lineas and lineas[-1].strip() == "```":
            lineas = lineas[:-1]
        texto = "\n".join(lineas)
    return texto.strip()


def _extraer_json(texto):
    """Mismo patrón que director._extraer_json — duplicado localmente,
    tolera fences de markdown alrededor del JSON."""
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


# ============================================================
# 1. Plan de estructura (modo arquitecto para proyectos)
# ============================================================

_PROMPT_ESTRUCTURA = """El jefe te pidió crear un proyecto completo (varios archivos, no uno solo): "{descripcion}"

Diseña la estructura de archivos necesaria. Devuelve SOLO un JSON así, nada más:
{{
  "tipo": "web" | "python",
  "archivos": [
    {{"ruta": "index.html", "descripcion": "qué debe contener y hacer este archivo"}},
    {{"ruta": "css/style.css", "descripcion": "..."}},
    {{"ruta": "js/main.js", "descripcion": "..."}}
  ]
}}

Reglas:
- "tipo": "web" si el resultado es una página/app que corre en el navegador (HTML/CSS/JS); "python" si es un programa/sistema en Python con varios módulos.
- Para "web": SIEMPRE incluye un "index.html" como punto de entrada. Si el jefe pidió CSS/JS separados, ponlos en archivos aparte (ej. "css/style.css", "js/main.js") en vez de todo inline.
- Para "python": SIEMPRE incluye un "main.py" como punto de entrada que use los demás módulos.
- Entre 3 y 8 archivos — ni uno solo (eso no es un proyecto multi-archivo) ni una fragmentación excesiva.
- NO incluyas README.md ni requirements.txt en la lista — esos se generan aparte, automáticamente.
- SOLO responde el JSON, nada más."""


def generar_estructura(descripcion):
    """Le pide a Gemini el plan de estructura (qué archivos, qué
    contiene cada uno) como JSON — esto ES el "modo arquitecto" para
    proyectos multi-archivo (siempre se muestra y se confirma antes de
    generar nada, ver director._procesar_proyecto_completo). Devuelve
    {"tipo": ..., "archivos": [...]} o None si Gemini no respondió o
    el JSON no se pudo parsear / vino vacío."""
    respuesta = balancer.enviar_mensaje(_PROMPT_ESTRUCTURA.format(descripcion=descripcion))
    if respuesta.startswith("ERROR:"):
        log.warning("code_proyectos: Gemini no respondió al generar la estructura (%s)", respuesta)
        return None
    datos = _extraer_json(respuesta)
    if not datos or not datos.get("archivos"):
        return None
    datos.setdefault("tipo", "web")
    return datos


def generar_nombre_proyecto(descripcion):
    """Reusa code_agent.generar_nombre_proyecto tal cual — deriva un
    slug corto de la descripción, no es específico de Python/archivo
    suelto (solo limpia palabras vacías y normaliza)."""
    return code_agent.generar_nombre_proyecto(descripcion)


def formatear_estructura_para_mostrar(nombre, estructura):
    """Árbol de texto simple para que el jefe vea qué se va a crear
    ANTES de confirmar (Parte B punto 1b: "muestra la estructura al
    usuario y confirma")."""
    nombre_carpeta = code_agent._normalizar_nombre(nombre)
    lineas = [f"proyectos/{nombre_carpeta}/"]
    for archivo in estructura["archivos"]:
        lineas.append(f"  ├── {archivo['ruta']} — {archivo.get('descripcion', '')}")
    lineas.append("  ├── README.md")
    if estructura.get("tipo") == "python":
        lineas.append("  └── requirements.txt (si el proyecto usa librerías externas)")
    return "\n".join(lineas)


# ============================================================
# 2. Mapa del proyecto (qué expone cada archivo ya generado) — CERO
# tokens, todo regex, para que cada archivo nuevo sepa a qué IDs/
# funciones/clases referirse sin tener que pasarle el contenido
# COMPLETO de todos los archivos anteriores (más barato en tokens).
# ============================================================

def _resumir_archivo(ruta, contenido):
    """Resumen corto (regex) de lo que define/expone `contenido` según
    la extensión de `ruta`, para alimentar el mapa del proyecto."""
    ext = os.path.splitext(ruta)[1].lower()

    if ext == ".py":
        nombres = re.findall(r"^\s*(?:def|class)\s+(\w+)", contenido, re.MULTILINE)
        return "funciones/clases: " + ", ".join(nombres[:15]) if nombres else "(sin funciones/clases top-level detectadas)"

    if ext in (".html", ".htm"):
        ids = sorted(set(re.findall(r'id=["\']([\w-]+)["\']', contenido)))
        grupos_clase = re.findall(r'class=["\']([\w -]+)["\']', contenido)
        clases = sorted({c for grupo in grupos_clase for c in grupo.split()})
        partes = []
        if ids:
            partes.append("ids: " + ", ".join(ids[:20]))
        if clases:
            partes.append("clases css: " + ", ".join(clases[:20]))
        return "; ".join(partes) if partes else "(sin ids/clases detectados)"

    if ext == ".js":
        nombres = set(re.findall(r"function\s+(\w+)\s*\(", contenido))
        nombres |= set(re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:\(|function|async)", contenido))
        return "funciones/variables: " + ", ".join(sorted(nombres)[:15]) if nombres else "(sin funciones top-level detectadas)"

    if ext == ".css":
        selectores = sorted(set(re.findall(r"([.#][\w-]+)\s*\{", contenido)))
        return "selectores: " + ", ".join(selectores[:20]) if selectores else "(sin selectores detectados)"

    return "(archivo de texto, sin resumen estructurado)"


# ============================================================
# 3. Generación de un archivo individual (fresco, o corregido con
# retroalimentación — mismo criterio que code_agent.
# generar_codigo_visual con codigo_previo).
# ============================================================

_PROMPT_ARCHIVO_PROYECTO = """Estás construyendo un proyecto multi-archivo. Petición completa del jefe: "{descripcion_proyecto}"

Archivo a escribir: {ruta}
Qué debe contener este archivo: {descripcion_archivo}
{contexto_otros_archivos}{referencia_bloque}
Responde ÚNICAMENTE con el contenido COMPLETO y funcional de este archivo, listo para guardar tal cual — nada de explicaciones, nada de ``` de markdown. Debe referenciar correctamente los IDs/clases/funciones de los otros archivos del proyecto listados arriba (si aplica) — no inventes nombres que no coincidan con lo que ya existe."""

_PROMPT_CORREGIR_ARCHIVO = """Este archivo de un proyecto multi-archivo tiene un problema. Petición completa del proyecto: "{descripcion_proyecto}"

Archivo: {ruta}

--- CONTENIDO ACTUAL ---
{contenido_actual}
--- FIN CONTENIDO ACTUAL ---

Esto está mal / hay que corregir:
{retroalimentacion}
{contexto_otros_archivos}
Responde ÚNICAMENTE con el contenido COMPLETO ya corregido de este archivo (el archivo entero, no un parche ni un diff), sin explicaciones ni ``` de markdown."""


def generar_archivo(ruta, descripcion_archivo, descripcion_proyecto, mapa_proyecto, referencia=None, contenido_actual=None, retroalimentacion=None):
    """Genera (o corrige, si vienen `contenido_actual`/
    `retroalimentacion`) el contenido completo de UN archivo del
    proyecto. Le pasa a Gemini el RESUMEN (ver _resumir_archivo, no el
    contenido completo) de los demás archivos ya generados en
    `mapa_proyecto`, para que referencie IDs/funciones reales. Devuelve
    el contenido (string) o None si Gemini no respondió."""
    resumenes = "\n".join(f"- {r}: {resumen}" for r, resumen in mapa_proyecto.items() if r != ruta)
    contexto = f"\nOtros archivos YA generados en este proyecto (lo que exponen/definen):\n{resumenes}\n" if resumenes else ""

    if contenido_actual is not None:
        prompt = _PROMPT_CORREGIR_ARCHIVO.format(
            descripcion_proyecto=descripcion_proyecto, ruta=ruta, contenido_actual=contenido_actual,
            retroalimentacion=(retroalimentacion or "")[:2000], contexto_otros_archivos=contexto,
        )
    else:
        referencia_bloque = (
            f"\nREFERENCIA: un proyecto parecido que ya funcionó (úsalo de inspiración de estructura/estilo, no lo copies literal si no aplica):\n```\n{referencia[:4000]}\n```\n"
            if referencia else ""
        )
        prompt = _PROMPT_ARCHIVO_PROYECTO.format(
            descripcion_proyecto=descripcion_proyecto, ruta=ruta, descripcion_archivo=descripcion_archivo,
            contexto_otros_archivos=contexto, referencia_bloque=referencia_bloque,
        )

    respuesta = balancer.enviar_mensaje(prompt)
    if respuesta.startswith("ERROR:"):
        log.warning("code_proyectos: Gemini no respondió al generar '%s' (%s)", ruta, respuesta)
        return None
    return _limpiar_markdown(respuesta) or None


# ============================================================
# 4. README y requirements.txt
# ============================================================

_PROMPT_README = """Escribe un README.md para este proyecto: "{descripcion}"

Archivos que tiene: {lista_archivos}

Incluye: qué es, qué hace, y cómo correrlo (comando exacto — ej. "abre index.html en tu navegador" o "python3 main.py"). Formato Markdown simple y directo, en español, máximo 25 líneas. Responde ÚNICAMENTE el contenido del README, sin ``` de markdown envolviendo todo."""


def generar_readme(nombre, descripcion, archivos):
    """Genera README.md con Gemini; si falla, se degrada a un README
    mínimo generado localmente (nunca bloquea la entrega del proyecto
    por un documento no esencial)."""
    respuesta = balancer.enviar_mensaje(_PROMPT_README.format(descripcion=descripcion, lista_archivos=", ".join(archivos)))
    if respuesta.startswith("ERROR:"):
        log.warning("code_proyectos: Gemini no respondió al generar el README (%s)", respuesta)
        return f"# {nombre}\n\n{descripcion}\n\nArchivos: {', '.join(archivos)}\n"
    return _limpiar_markdown(respuesta)


_PATRON_IMPORT = re.compile(r"^\s*(?:import|from)\s+([\w]+)", re.MULTILINE)


def _detectar_dependencias(contenidos_py):
    """CERO tokens: escanea `import`/`from ... import` en todos los
    .py del proyecto, filtra librería estándar (sys.stdlib_module_names,
    Python 3.12) y traduce con code_agent._MAPEO_PAQUETES (cv2 ->
    opencv-python, etc.). Devuelve {modulo_import: paquete_pip}."""
    modulos = set()
    for contenido in contenidos_py:
        modulos |= set(_PATRON_IMPORT.findall(contenido))

    stdlib = set(sys.stdlib_module_names)
    externos = {m for m in modulos if m and m not in stdlib and m != "__future__"}
    return {m: code_agent._MAPEO_PAQUETES.get(m, m) for m in externos}


def generar_requirements(mapa_dependencias):
    """CERO tokens: arma el contenido de requirements.txt a partir de
    {modulo_import: paquete_pip} ya detectado (ver _detectar_dependencias)."""
    paquetes = sorted(set(mapa_dependencias.values()))
    return "\n".join(paquetes) + "\n" if paquetes else ""


def _paquetes_faltantes(mapa_dependencias):
    """Cuáles de `mapa_dependencias` NO se pueden importar ya mismo en
    este intérprete — para decidir si hace falta pedir CONFIRMAR antes
    de intentar correr el proyecto."""
    faltantes = []
    for modulo, paquete in mapa_dependencias.items():
        try:
            importlib.import_module(modulo)
        except Exception:
            faltantes.append(paquete)
    return sorted(set(faltantes))


# ============================================================
# 5. Verificación end-to-end
# ============================================================

def _referencias_rotas(html, archivos_existentes):
    """Regex CERO tokens: src=/href= relativos del HTML que NO están
    entre `archivos_existentes` (rutas relativas del proyecto ya
    generadas). Ignora URLs externas/absolutas y anclas."""
    rutas = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', html)
    rotos = []
    for ruta in rutas:
        ruta = ruta.strip()
        if not ruta or ruta.startswith(("http://", "https://", "//", "data:", "#", "mailto:")):
            continue
        ruta_limpia = ruta.split("#")[0].split("?")[0].lstrip("./")
        if ruta_limpia and ruta_limpia not in archivos_existentes:
            rotos.append(ruta)
    return rotos


def _archivo_js_principal(contenidos):
    if "js/main.js" in contenidos:
        return "js/main.js"
    if "main.js" in contenidos:
        return "main.js"
    candidatos = [r for r in contenidos if r.endswith(".js")]
    return candidatos[0] if len(candidatos) == 1 else None


def _verificar_web(ruta_proyecto, contenidos, mapa_proyecto, descripcion):
    """Web (tiene index.html): chequeo determinístico de referencias
    rotas (ver _referencias_rotas), luego captura + Gemini Vision
    (reusa code_agent._capturar_screenshot/_evaluar_con_vision tal
    cual). Corrige el archivo responsable con esa retroalimentación
    puntual, hasta _MAX_INTENTOS_PROYECTO veces. Muta `contenidos` y
    `mapa_proyecto` en sitio conforme corrige. Devuelve (ok, problema)."""
    if "index.html" not in contenidos:
        return True, None

    ruta_index = os.path.join(ruta_proyecto, "index.html")
    intentos = _MAX_INTENTOS_PROYECTO

    while intentos > 0:
        rotos = _referencias_rotas(contenidos["index.html"], set(contenidos.keys()))
        if rotos:
            nuevo = generar_archivo(
                "index.html", "", descripcion, mapa_proyecto,
                contenido_actual=contenidos["index.html"],
                retroalimentacion="Estas referencias apuntan a archivos que no existen: " + ", ".join(rotos),
            )
            intentos -= 1
            if nuevo is None:
                return False, "no pude corregir las referencias rotas del HTML."
            contenidos["index.html"] = nuevo
            mapa_proyecto["index.html"] = _resumir_archivo("index.html", nuevo)
            with open(ruta_index, "w") as f:
                f.write(nuevo)
            continue

        captura = code_agent._capturar_screenshot(ruta_index, ruta_png=RUTA_CAPTURA_PROYECTO)
        if captura["errores_js"]:
            objetivo = _archivo_js_principal(contenidos) or "index.html"
            errores_unicos = list(dict.fromkeys(captura["errores_js"]))
            problema = "Errores de JavaScript en consola:\n" + "\n".join(errores_unicos)
            nuevo = generar_archivo(
                objetivo, "", descripcion, mapa_proyecto,
                contenido_actual=contenidos.get(objetivo, ""), retroalimentacion=problema,
            )
            intentos -= 1
            if nuevo is None:
                return False, problema
            contenidos[objetivo] = nuevo
            mapa_proyecto[objetivo] = _resumir_archivo(objetivo, nuevo)
            with open(os.path.join(ruta_proyecto, objetivo), "w") as f:
                f.write(nuevo)
            continue

        evaluacion = code_agent._evaluar_con_vision(captura["ruta_png"], descripcion)
        if evaluacion["aprobado"]:
            return True, None

        intentos -= 1
        if intentos == 0:
            return False, evaluacion["problema"]

        nuevo = generar_archivo(
            "index.html", "", descripcion, mapa_proyecto,
            contenido_actual=contenidos["index.html"],
            retroalimentacion=f"Gemini Vision revisó el screenshot y dijo que esto está mal: {evaluacion['problema']}",
        )
        if nuevo is None:
            return False, evaluacion["problema"]
        contenidos["index.html"] = nuevo
        mapa_proyecto["index.html"] = _resumir_archivo("index.html", nuevo)
        with open(ruta_index, "w") as f:
            f.write(nuevo)

    return False, "no se pudo verificar visualmente tras varios intentos."


def _archivo_principal_python(contenidos):
    """main.py si existe, o el único .py en la raíz si solo hay uno —
    None si no se puede identificar un punto de entrada con certeza."""
    if "main.py" in contenidos:
        return "main.py"
    raiz_py = [r for r in contenidos if r.endswith(".py") and "/" not in r]
    return raiz_py[0] if len(raiz_py) == 1 else None


def _archivo_del_traceback(traceback_texto, ruta_proyecto, contenidos):
    """Frame más profundo del traceback que caiga dentro de
    `ruta_proyecto` — ese es el archivo que de verdad causó el error.
    None si no se pudo determinar (el llamador cae a regenerar el
    archivo principal como fallback)."""
    rutas = re.findall(r'File "([^"]+)"', traceback_texto or "")
    for ruta_abs in reversed(rutas):
        if ruta_abs.startswith(ruta_proyecto):
            relativa = os.path.relpath(ruta_abs, ruta_proyecto)
            if relativa in contenidos:
                return relativa
    return None


def _ejecutar_principal(ruta_principal, ruta_proyecto):
    """Mismo criterio que code_agent._ejecutar: timeout corto, si el
    proceso sigue vivo al cumplirse se asume que arrancó bien (GUI/
    cámara/servidor) y se mata solo."""
    try:
        resultado = subprocess.run(
            [sys.executable, ruta_principal],
            cwd=ruta_proyecto, capture_output=True, text=True, timeout=_TIMEOUT_EJECUCION_SEGUNDOS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": True, "stderr": ""}
    except Exception as e:
        return {"ok": False, "stderr": str(e)}

    if resultado.returncode != 0:
        return {"ok": False, "stderr": resultado.stderr.strip()}
    return {"ok": True, "stderr": ""}


def _verificar_python(ruta_proyecto, contenidos, mapa_proyecto, descripcion):
    """Python (tiene main.py o un único .py en la raíz): lo corre y, si
    truena, identifica qué archivo del proyecto causó el error (ver
    _archivo_del_traceback) y SOLO regenera ese, hasta
    _MAX_INTENTOS_PROYECTO veces. Muta `contenidos`/`mapa_proyecto` en
    sitio. Devuelve (ok, problema)."""
    principal = _archivo_principal_python(contenidos)
    if not principal:
        return True, None

    ruta_principal = os.path.join(ruta_proyecto, principal)
    intentos = _MAX_INTENTOS_PROYECTO

    while intentos > 0:
        resultado = _ejecutar_principal(ruta_principal, ruta_proyecto)
        intentos -= 1
        if resultado["ok"]:
            return True, None
        if intentos == 0:
            return False, resultado["stderr"][:400]

        objetivo = _archivo_del_traceback(resultado["stderr"], ruta_proyecto, contenidos) or principal
        nuevo = generar_archivo(
            objetivo, "", descripcion, mapa_proyecto,
            contenido_actual=contenidos.get(objetivo, ""), retroalimentacion=resultado["stderr"],
        )
        if nuevo is None:
            return False, resultado["stderr"][:400]
        patron = code_agent._codigo_peligroso(nuevo)
        if patron:
            return False, f"la corrección automática intentó algo que no permito ('{patron}')."
        contenidos[objetivo] = nuevo
        mapa_proyecto[objetivo] = _resumir_archivo(objetivo, nuevo)
        with open(os.path.join(ruta_proyecto, objetivo), "w") as f:
            f.write(nuevo)

    return False, "no se pudo verificar tras varios intentos."


# ============================================================
# 6. Orquestador principal
# ============================================================

def crear_proyecto_completo(nombre, descripcion, estructura=None, _reanudacion=None):
    """Genera el proyecto multi-archivo completo (se llama al
    CONFIRMAR la estructura que mostró director._procesar_proyecto_
    completo). Si detecta librerías Python faltantes, NO instala nada
    solo: pausa y devuelve {"pendiente_instalacion_proyecto": {...}}
    para que director.py pida CONFIRMAR primero (ver
    confirmar_instalacion_proyecto, que retoma este mismo flujo sin
    regenerar los archivos ya escritos, vía `_reanudacion`).

    Devuelve:
      {"exito": True, "ruta": str, "mensaje": str}
      {"exito": False, "mensaje": str}
      {"exito": False, "mensaje": str, "ruta": str, "pendiente_instalacion_proyecto": {...}}
    """
    if _reanudacion:
        ruta_proyecto = _reanudacion["ruta_proyecto"]
        contenidos = _reanudacion["contenidos"]
        mapa_proyecto = _reanudacion["mapa_proyecto"]
        mapa_dependencias = _reanudacion["mapa_dependencias"]
        tipo = _reanudacion["tipo"]
        descripcion = _reanudacion["descripcion"]
    else:
        if not estructura or not estructura.get("archivos"):
            return {"exito": False, "mensaje": "La estructura del proyecto quedó vacía, jefe, no pude generar nada."}

        nombre_carpeta = code_agent._normalizar_nombre(nombre)
        ruta_proyecto = os.path.join(CARPETA_PROYECTOS, nombre_carpeta)
        os.makedirs(ruta_proyecto, exist_ok=True)

        tipo = estructura.get("tipo", "web")
        referencia = code_memoria.buscar_patron_similar("proyecto", descripcion)

        mapa_proyecto = {}
        contenidos = {}

        for meta in estructura["archivos"]:
            ruta_relativa = meta["ruta"].strip().lstrip("/")
            contenido = generar_archivo(
                ruta_relativa, meta.get("descripcion", ""), descripcion, mapa_proyecto, referencia=referencia,
            )
            if contenido is None:
                return {"exito": False, "mensaje": f"No pude generar '{ruta_relativa}', jefe: Gemini no respondió."}

            patron = code_agent._codigo_peligroso(contenido)
            if patron:
                return {
                    "exito": False,
                    "mensaje": f"El archivo '{ruta_relativa}' intentó algo que no permito ('{patron}'), cancelé el proyecto completo por seguridad.",
                }

            ruta_absoluta = os.path.join(ruta_proyecto, ruta_relativa)
            os.makedirs(os.path.dirname(ruta_absoluta), exist_ok=True)
            with open(ruta_absoluta, "w") as f:
                f.write(contenido)
            contenidos[ruta_relativa] = contenido
            mapa_proyecto[ruta_relativa] = _resumir_archivo(ruta_relativa, contenido)

        readme = generar_readme(nombre_carpeta, descripcion, list(contenidos.keys()))
        with open(os.path.join(ruta_proyecto, "README.md"), "w") as f:
            f.write(readme)

        mapa_dependencias = {}
        if tipo == "python":
            archivos_py = [c for r, c in contenidos.items() if r.endswith(".py")]
            mapa_dependencias = _detectar_dependencias(archivos_py)
            if mapa_dependencias:
                with open(os.path.join(ruta_proyecto, "requirements.txt"), "w") as f:
                    f.write(generar_requirements(mapa_dependencias))

                faltantes = _paquetes_faltantes(mapa_dependencias)
                if faltantes:
                    return {
                        "exito": False,
                        "ruta": ruta_proyecto,
                        "mensaje": (
                            f"Ya generé los archivos del proyecto en proyectos/{nombre_carpeta}/, pero necesita estas "
                            f"librerías que no están instaladas: {', '.join(faltantes)}.\n"
                            "¿Quieres que las instale con pip? Escribe CONFIRMAR para continuar o cualquier otra cosa "
                            "para cancelar (los archivos ya quedaron guardados de cualquier forma)."
                        ),
                        "pendiente_instalacion_proyecto": {
                            "paquetes": faltantes,
                            "reanudacion": {
                                "ruta_proyecto": ruta_proyecto, "contenidos": contenidos,
                                "mapa_proyecto": mapa_proyecto, "mapa_dependencias": mapa_dependencias,
                                "tipo": tipo, "descripcion": descripcion,
                            },
                        },
                    }

    problemas = []
    if tipo == "web":
        ok, problema = _verificar_web(ruta_proyecto, contenidos, mapa_proyecto, descripcion)
        if not ok:
            problemas.append(problema)
    elif tipo == "python":
        ok, problema = _verificar_python(ruta_proyecto, contenidos, mapa_proyecto, descripcion)
        if not ok:
            problemas.append(problema)

    if not problemas:
        resumen_codigo = "\n\n".join(f"# {r}\n{c}" for r, c in contenidos.items())[:20000]
        code_memoria.guardar_patron_exitoso("proyecto", descripcion, resumen_codigo)

    mensaje_apertura = ""
    if tipo == "web" and "index.html" in contenidos:
        mensaje_apertura = "\n\n" + control_agent.abrir_archivo(os.path.join(ruta_proyecto, "index.html"))
    try:
        subprocess.Popen(["code", ruta_proyecto], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass  # VSCode no instalado o "code" no está en PATH — no es un error, solo no se ofrece.

    nombre_carpeta = os.path.basename(ruta_proyecto)
    extra_archivos = " + requirements.txt" if tipo == "python" and mapa_dependencias else ""
    mensaje = (
        f"Listo, jefe. Creé el proyecto completo en proyectos/{nombre_carpeta}/ "
        f"({len(contenidos)} archivo(s) + README.md{extra_archivos}).\n\n"
        f"Qué hace: {descripcion}"
        f"{mensaje_apertura}\n\n"
        "¿Quieres que inicialice un repo git aquí? Escribe CONFIRMAR."
    )
    if problemas:
        mensaje += "\n\nOjo: tras varios intentos, esto no quedó perfecto según la verificación:\n" + "\n".join(f"- {p}" for p in problemas)

    return {"exito": True, "ruta": ruta_proyecto, "mensaje": mensaje}


def confirmar_instalacion_proyecto(datos):
    """Instala datos["paquetes"] (ya confirmados por el jefe, uno por
    uno vía code_agent.instalar_dependencia) y retoma
    crear_proyecto_completo() sin regenerar los archivos ya escritos
    (ver datos["reanudacion"]). Mismo contrato de retorno que
    crear_proyecto_completo()."""
    for paquete in datos["paquetes"]:
        resultado = code_agent.instalar_dependencia(paquete)
        if not resultado["exito"]:
            return {"exito": False, "mensaje": f"No pude instalar '{paquete}': {resultado['mensaje']}"}

    reanudacion = datos["reanudacion"]
    return crear_proyecto_completo(None, None, _reanudacion=reanudacion)


def inicializar_git(ruta_proyecto):
    """git init + git add -A + primer commit en `ruta_proyecto` (ya
    confirmado por el jefe, ver director._ejecutar_accion_pendiente
    origen "git_init_proyecto"). Best-effort: si git no está instalado,
    o la identidad de git no está configurada (git commit la exige), se
    reporta el error sin tronar."""
    try:
        for comando in (["git", "init"], ["git", "add", "-A"], ["git", "commit", "-m", "Proyecto generado por IRIS"]):
            resultado = subprocess.run(comando, cwd=ruta_proyecto, capture_output=True, text=True, timeout=10)
            if resultado.returncode != 0:
                return {"exito": False, "mensaje": resultado.stderr.strip()[:300] or "git devolvió un error."}
    except Exception as e:
        return {"exito": False, "mensaje": str(e)}
    return {"exito": True, "mensaje": f"Listo, inicialicé un repo git en {ruta_proyecto} con el primer commit."}
