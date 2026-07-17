# ============================================================
# GERAM OS v2 · examen_agent.py
# Exámenes de opción múltiple para estudiar con active recall — a
# partir de un tema libre, un PDF, una nota de Obsidian (ver
# obsidian_agent.py, exclusivo para apuntes de estudio) o el repaso
# completo de una materia. Groq genera las preguntas en JSON (mismo
# patrón que code_proyectos.generar_estructura); el HUD y Telegram
# presentan el examen ACTIVO una pregunta a la vez (ver
# iniciar_examen/pregunta_actual/responder más abajo — un solo examen
# activo a la vez, mismo criterio de "un jefe, una sesión" que
# adjuntos_agent._pendiente/observador._vista_activa) y el resultado
# final se guarda en Supabase (tabla "examenes", ver el SQL en el
# reporte de esta fase) para que IRIS pueda notar en qué temas falla
# seguido Mauri.
# ============================================================

import json
import logging
import os
import re

from supabase import create_client

import config
from agents import groq_agent, obsidian_agent, research_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("examen_agent")

_cliente = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
TABLA = "examenes"

# Ruta fija donde server.py guarda el PDF subido desde el botón del HUD
# (ver /subir-pdf) — "examen de este pdf" lee de aquí si el mensaje no
# trae una ruta explícita (ver director._procesar_examen).
RUTA_PDF_SUBIDO = "/tmp/geram_examen_pdf_subido.pdf"

_NUM_PREGUNTAS_DEFAULT = 10
_NUM_PREGUNTAS_MAX = 20

# Groq tiene contexto de sobra, pero no hace falta mandar un PDF/nota
# completos para generar buenas preguntas (mismo criterio que
# research_agent._MAX_CARACTERES_PDF).
_MAX_CARACTERES_CONTENIDO = 20000

_PROMPT_EXAMEN = """Eres un generador de exámenes de opción múltiple para estudiar con active recall, en español.

Genera exactamente {num_preguntas} preguntas de opción múltiple sobre lo siguiente:

{fuente}

Devuelve SOLO un JSON así, nada más:
{{
  "preguntas": [
    {{
      "pregunta": "texto de la pregunta",
      "opciones": ["A) opción 1", "B) opción 2", "C) opción 3", "D) opción 4"],
      "respuesta_correcta": "A",
      "explicacion": "por qué esa es la respuesta correcta, breve"
    }}
  ]
}}

Reglas:
- Exactamente {num_preguntas} preguntas, ni una menos.
- Las 4 opciones deben ser plausibles (nada de "todas las anteriores" fácil de adivinar a ojo).
- "respuesta_correcta" es SIEMPRE una sola letra: "A", "B", "C" o "D".
- No repitas la misma pregunta dos veces.
- No inventes datos que no estén en el contenido si se te dio contenido específico.
- SOLO responde el JSON, nada más."""


def _extraer_json(texto):
    """Mismo patrón que director._extraer_json/code_proyectos._extraer_json
    — duplicado localmente, tolera fences de markdown alrededor del JSON."""
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


_LETRAS_VALIDAS = {"A", "B", "C", "D"}


def _validar_preguntas(preguntas):
    """Filtra cualquier pregunta mal formada que Groq haya devuelto
    (faltan campos, opciones != 4, respuesta_correcta fuera de A-D) —
    mejor una pregunta menos que una que truene la interfaz del HUD/
    Telegram a la mitad del examen."""
    validas = []
    for p in preguntas:
        if not isinstance(p, dict):
            continue
        pregunta = (p.get("pregunta") or "").strip()
        opciones = p.get("opciones")
        correcta = (p.get("respuesta_correcta") or "").strip().upper()[:1]
        explicacion = (p.get("explicacion") or "").strip()
        if not pregunta or not isinstance(opciones, list) or len(opciones) != 4:
            continue
        if correcta not in _LETRAS_VALIDAS:
            continue
        validas.append({
            "pregunta": pregunta,
            "opciones": [str(o) for o in opciones],
            "respuesta_correcta": correcta,
            "explicacion": explicacion,
        })
    return validas


def _generar_desde_fuente(fuente_texto, num_preguntas):
    """Núcleo compartido por las 4 funciones generar_examen_de_*: le
    pide a Groq el examen en JSON sobre `fuente_texto` (ya armado por
    el llamador) y devuelve {"preguntas": [...]} ya validadas, o
    {"error": "..."}."""
    num_preguntas = max(1, min(int(num_preguntas or _NUM_PREGUNTAS_DEFAULT), _NUM_PREGUNTAS_MAX))
    prompt = _PROMPT_EXAMEN.format(num_preguntas=num_preguntas, fuente=fuente_texto)

    crudo = groq_agent.generar_contenido(prompt)
    if crudo.startswith("ERROR:"):
        return {"error": crudo}

    datos = _extraer_json(crudo)
    preguntas = _validar_preguntas((datos or {}).get("preguntas") or [])
    if not preguntas:
        return {"error": "no pude generar preguntas válidas de eso, jefe."}

    return {"preguntas": preguntas}


def generar_examen_de_tema(tema, num_preguntas=10):
    """Examen sobre `tema` a partir de lo que Groq ya sabe (sin leer
    ningún archivo). Devuelve {"preguntas": [...], "tema": tema} o
    {"error": "..."}."""
    resultado = _generar_desde_fuente(f"Tema: {tema}", num_preguntas)
    if resultado.get("error"):
        return resultado
    resultado["tema"] = tema
    return resultado


def generar_examen_de_pdf(ruta_pdf, num_preguntas=10):
    """Lee el PDF en `ruta_pdf` (research_agent.extraer_texto_pdf,
    mismo lector que el resumen de investigación) y genera el examen a
    partir de su contenido real. Devuelve {"preguntas": [...], "tema": ...}
    o {"error": "..."}."""
    if not os.path.exists(ruta_pdf):
        return {"error": f"no encuentro el archivo '{ruta_pdf}'."}

    try:
        texto = research_agent.extraer_texto_pdf(ruta_pdf)
    except Exception as e:
        log.error("examen_agent: no se pudo leer el PDF '%s' (%s)", ruta_pdf, e)
        return {"error": f"no pude leer el PDF ({e})."}

    if not texto.strip():
        return {"error": "no encontré texto legible en ese PDF (¿es un escaneo de imágenes sin OCR?)."}

    resultado = _generar_desde_fuente(f"Contenido:\n{texto[:_MAX_CARACTERES_CONTENIDO]}", num_preguntas)
    if resultado.get("error"):
        return resultado
    resultado["tema"] = os.path.splitext(os.path.basename(ruta_pdf))[0]
    return resultado


def generar_examen_de_nota(titulo_nota, num_preguntas=10):
    """Toma una nota de estudio de Obsidian (por título, ver
    obsidian_agent.buscar_nota) y genera el examen a partir de su
    contenido. Devuelve {"preguntas": [...], "tema": ...} o
    {"error": "..."}."""
    notas = obsidian_agent.buscar_nota(titulo_nota)
    if not notas:
        return {"error": f"no encontré ninguna nota de estudio en Obsidian que coincida con '{titulo_nota}'."}

    nota = notas[0]
    try:
        with open(nota["ruta"], encoding="utf-8") as f:
            texto = f.read()
    except OSError as e:
        return {"error": f"no pude leer la nota '{nota['titulo']}' ({e})."}

    resultado = _generar_desde_fuente(f"Contenido:\n{texto[:_MAX_CARACTERES_CONTENIDO]}", num_preguntas)
    if resultado.get("error"):
        return resultado
    resultado["tema"] = nota["titulo"]
    return resultado


def generar_examen_de_apuntes(materia, num_preguntas=10):
    """Repaso de una MATERIA completa: junta el contenido de todas las
    notas de estudio de Obsidian cuyo título o contenido mencione
    `materia` (ver obsidian_agent.buscar_nota, incluye la subcarpeta de
    la materia si existe — ver obsidian_agent.crear_nota_por_materia) y
    genera el examen sobre ese conjunto. Devuelve
    {"preguntas": [...], "tema": materia} o {"error": "..."}."""
    notas = obsidian_agent.buscar_nota(materia)
    if not notas:
        return {"error": f"no encontré notas de estudio sobre '{materia}' en Obsidian."}

    partes = []
    for nota in notas:
        try:
            with open(nota["ruta"], encoding="utf-8") as f:
                partes.append(f"## {nota['titulo']}\n{f.read()}")
        except OSError:
            continue

    if not partes:
        return {"error": f"encontré notas de '{materia}' pero no pude leer ninguna."}

    texto = "\n\n".join(partes)
    resultado = _generar_desde_fuente(
        f"Contenido (varias notas de estudio de {materia}):\n{texto[:_MAX_CARACTERES_CONTENIDO]}", num_preguntas,
    )
    if resultado.get("error"):
        return resultado
    resultado["tema"] = materia
    return resultado


# ------------------------------------------------------------
# Examen ACTIVO: un solo examen en curso a la vez (mismo criterio de
# estado en memoria que adjuntos_agent._pendiente/observador._vista_
# activa) — el HUD (server.py /examen/actual y /examen/responder) y
# Telegram (telegram_agent.py) lo consumen pregunta por pregunta.
# ------------------------------------------------------------
_examen_activo = None


def iniciar_examen(preguntas, tema, materia=None):
    """Arranca un examen nuevo (pisa cualquiera que estuviera a medias
    — un solo examen activo a la vez). Devuelve el estado inicial."""
    global _examen_activo
    _examen_activo = {
        "preguntas": preguntas, "indice": 0, "aciertos": 0, "fallos": [],
        "tema": tema, "materia": materia,
    }
    return _examen_activo


def examen_activo():
    """True/el dict de estado si hay un examen en curso, None si no."""
    return _examen_activo


def pregunta_actual():
    """Pregunta ACTUAL sin "respuesta_correcta"/"explicacion" (para no
    hacer trampa en la interfaz) + metadata de progreso. None si no hay
    examen activo o ya terminó."""
    if not _examen_activo:
        return None
    idx = _examen_activo["indice"]
    preguntas = _examen_activo["preguntas"]
    if idx >= len(preguntas):
        return None
    p = preguntas[idx]
    return {
        "indice": idx, "total": len(preguntas),
        "pregunta": p["pregunta"], "opciones": p["opciones"],
        "tema": _examen_activo["tema"],
    }


def responder(letra):
    """Registra la respuesta a la pregunta ACTUAL y avanza el índice.
    Al terminar la última pregunta, guarda el resultado en Supabase
    automáticamente. Devuelve {"correcto", "respuesta_correcta",
    "explicacion", "terminado", y si terminado también "aciertos"/
    "total"} o {"error": "..."} si no hay examen activo."""
    global _examen_activo
    if not _examen_activo:
        return {"error": "no hay ningún examen activo, jefe."}

    idx = _examen_activo["indice"]
    preguntas = _examen_activo["preguntas"]
    if idx >= len(preguntas):
        return {"error": "ese examen ya terminó."}

    p = preguntas[idx]
    letra = (letra or "").strip().upper()[:1]
    correcto = letra == p["respuesta_correcta"]
    if correcto:
        _examen_activo["aciertos"] += 1
    else:
        _examen_activo["fallos"].append(p["pregunta"])

    _examen_activo["indice"] += 1
    terminado = _examen_activo["indice"] >= len(preguntas)

    resultado = {
        "correcto": correcto,
        "respuesta_correcta": p["respuesta_correcta"],
        "explicacion": p["explicacion"],
        "terminado": terminado,
    }

    if terminado:
        resultado["aciertos"] = _examen_activo["aciertos"]
        resultado["total"] = len(preguntas)
        # Para que la pantalla final del HUD/Telegram pueda ofrecer
        # "repasar las que fallaste" sin tener que volver a leer Supabase.
        resultado["fallos"] = list(_examen_activo["fallos"])
        guardar_resultado(
            tema=_examen_activo["tema"], materia=_examen_activo.get("materia"),
            num_preguntas=len(preguntas), aciertos=_examen_activo["aciertos"],
            temas_fallados=_examen_activo["fallos"],
        )

    return resultado


def cancelar_examen():
    global _examen_activo
    _examen_activo = None


# ------------------------------------------------------------
# Resultados (Supabase, tabla "examenes" — ver el SQL en el reporte).
# ------------------------------------------------------------
def guardar_resultado(tema, materia, num_preguntas, aciertos, temas_fallados):
    """Guarda el resultado de un examen ya terminado. `temas_fallados`
    es una lista de strings (texto de las preguntas falladas). Nunca
    lanza excepción: devuelve True/False."""
    fila = {
        "tema": tema,
        "materia": materia,
        "num_preguntas": num_preguntas,
        "aciertos": aciertos,
        "temas_fallados": temas_fallados,
        "instancia": config.INSTANCE_NAME,
    }
    try:
        _cliente.table(TABLA).insert(fila).execute()
        return True
    except Exception as e:
        log.error("examen_agent: no se pudo guardar el resultado (%s)", e)
        return False


def historial_texto(tema_filtro=None, limite=10):
    """Últimos resultados de exámenes (de cualquier instancia), como
    texto legible — para "cómo me ha ido en mis exámenes". Filtra por
    `tema_filtro` (ILIKE contra "tema") si se da."""
    try:
        consulta = _cliente.table(TABLA).select("*")
        if tema_filtro:
            consulta = consulta.ilike("tema", f"%{tema_filtro}%")
        resultado = consulta.order("created_at", desc=True).limit(limite).execute()
        filas = resultado.data
    except Exception as e:
        log.error("examen_agent: no se pudo leer el historial (%s)", e)
        return "No pude leer tu historial de exámenes, jefe."

    if not filas:
        return "Todavía no tienes exámenes registrados, jefe."

    lineas = [f"- {f['tema']}: {f['aciertos']}/{f['num_preguntas']} ({str(f['created_at'])[:10]})" for f in filas]
    return "Tu historial de exámenes:\n" + "\n".join(lineas)
