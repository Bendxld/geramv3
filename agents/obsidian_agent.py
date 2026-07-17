# ============================================================
# GERAM OS v2 · obsidian_agent.py
# Obsidian es EXCLUSIVAMENTE para apuntes/notas de ESTUDIO de Mauri
# (resúmenes de temas académicos, conceptos conectados entre sí para
# repasar) — NUNCA para pendientes, tareas, finanzas ni documentos
# generales, eso ya vive en Notion (ver pendientes_agent.py/
# proyectos_agent.py/finance_agent.py/notion_agent.py). Por eso este
# módulo NO expone una crear_nota() genérica: solo funciones pensadas
# para contenido de estudio.
#
# Sin API: las notas son archivos .md directo en la carpeta del vault
# (config.OBSIDIAN_VAULT_PATH) — Obsidian solo lee esa carpeta del
# disco, así que escribir el archivo ahí basta. crear_nota_estudio() es
# la pieza pensada para conectarse con research_agent.py: toma
# contenido YA generado (un resumen, un ensayo) y lo reformatea con
# encabezados + [[wikilinks]] a los conceptos que menciona, para que
# quede enlazada con el resto del vault en vez de ser una nota huérfana.
#
# Obsidian está instalado como Flatpak en este equipo (ver
# abrir_obsidian) — su sandbox YA incluye el permiso de filesystem
# "home" (ver `flatpak info --show-permissions md.obsidian.Obsidian`),
# así que el vault bajo ~/Documentos/Obsidian es visible para la app
# sin necesitar "flatpak override" de entrada. Si algún día se acota
# ese permiso y Obsidian deja de ver el vault, el arreglo es:
#   flatpak override md.obsidian.Obsidian --filesystem=<OBSIDIAN_VAULT_PATH>
# ============================================================

import glob
import logging
import os
import re

import config
from agents import control_agent, groq_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("obsidian_agent")

VAULT_PATH = config.OBSIDIAN_VAULT_PATH

# Caracteres inválidos en nombres de archivo/carpeta (Windows/Linux
# combinados, por si el vault algún día se sincroniza a otro SO).
_PATRON_INVALIDO = re.compile(r'[\\/:*?"<>|]')

_PROMPT_NOTA_ESTUDIO = """Convierte el siguiente contenido en una nota de ESTUDIO para Obsidian, en español —
es para que Mauri repase un tema académico, no un documento genérico.

Formato exigido (texto plano, SIN bloques de código ni markdown de más):
- Usa "## " al inicio de cada encabezado de sección (ej. "## Definición", "## Características", "## Ejemplos").
- Usa "- " al inicio de cada viñeta donde tenga sentido.
- Resalta los CONCEPTOS CLAVE del tema directo en el texto, con claridad, como para repasar rápido.
- Cuando menciones un CONCEPTO relacionado que merecería su propia nota algún día (otro tema, término técnico, persona, evento, proceso), enciérralo en dobles corchetes estilo wikilink de Obsidian, ej. "[[Fotosíntesis]]", "[[ATP]]", "[[Clorofila]]". Usa el wikilink SOLO la primera vez que aparece cada concepto, no lo repitas en cada mención.
- No inventes información que no esté en el contenido de abajo.
- No agregues comentarios sobre el formato ni una introducción tipo "aquí está tu nota" — solo el contenido de la nota.

Tema: {tema}

Contenido:
{contenido}"""


def _asegurar_vault():
    os.makedirs(VAULT_PATH, exist_ok=True)


def _nombre_valido(texto):
    """Sanea un título de nota O un nombre de subcarpeta de materia —
    misma regla en ambos casos (sin caracteres inválidos de filesystem)."""
    limpio = _PATRON_INVALIDO.sub("", texto).strip()
    limpio = re.sub(r"\s+", " ", limpio)
    return limpio[:200]


def _ruta_disponible(directorio, nombre_base):
    """Nunca pisa una nota existente: si "Fotosíntesis.md" ya existe,
    prueba "Fotosíntesis (2).md", etc. — igual que hace Obsidian mismo
    al crear una nota con un nombre repetido."""
    ruta = os.path.join(directorio, f"{nombre_base}.md")
    contador = 2
    while os.path.exists(ruta):
        ruta = os.path.join(directorio, f"{nombre_base} ({contador}).md")
        contador += 1
    return ruta


def _crear_archivo_nota(titulo, contenido, carpeta=None):
    """Primitiva interna de escritura — TODAS las notas de estudio
    (con o sin materia) pasan por aquí. No se expone directo: el
    contenido debe llegar ya formateado como nota de estudio (ver
    crear_nota_estudio), nunca texto arbitrario sin ese contexto."""
    _asegurar_vault()
    directorio = os.path.join(VAULT_PATH, carpeta) if carpeta else VAULT_PATH

    try:
        os.makedirs(directorio, exist_ok=True)
    except OSError as e:
        log.error("obsidian_agent: no se pudo crear la carpeta '%s' (%s)", carpeta, e)
        return {"error": f"no pude crear la carpeta '{carpeta}': {e}"}

    ruta = _ruta_disponible(directorio, _nombre_valido(titulo) or "Nota de estudio")

    try:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(contenido.strip() + "\n")
    except OSError as e:
        log.error("obsidian_agent: no se pudo crear la nota '%s' (%s)", titulo, e)
        return {"error": str(e)}

    log.info("obsidian_agent: nota de estudio creada en '%s'", ruta)
    return {"ok": True, "ruta": ruta, "titulo": os.path.splitext(os.path.basename(ruta))[0]}


def crear_nota_estudio(tema, contenido, carpeta=None):
    """Reformatea `contenido` (ya generado — un resumen de investigación,
    un ensayo de Groq, lo que sea) con Groq: encabezados "## " y
    [[wikilinks]] a los conceptos relacionados que menciona, y lo
    guarda como nota de estudio nueva. Así la nota queda conectada con
    el resto del vault en vez de ser texto plano suelto. `carpeta`
    opcional (ver crear_nota_por_materia, que la usa para organizar por
    materia). Devuelve {"ok": True, "ruta": ..., "titulo": ...} o
    {"error": "..."}."""
    formateado = groq_agent.generar_contenido(_PROMPT_NOTA_ESTUDIO.format(tema=tema, contenido=contenido))
    if formateado.startswith("ERROR:"):
        log.warning("obsidian_agent: Groq falló formateando la nota de estudio (%s)", formateado)
        # Degrada a guardar el contenido tal cual en vez de perder el
        # trabajo ya hecho (ej. el resumen de research_agent) solo
        # porque Groq no pudo darle formato de estudio.
        formateado = contenido

    return _crear_archivo_nota(tema, formateado, carpeta=carpeta)


def crear_nota_por_materia(materia, tema, contenido):
    """Como crear_nota_estudio, pero organizada en una subcarpeta por
    MATERIA dentro del vault (ej. "Matemáticas/", "Historia/") — para
    que las notas de una misma materia queden juntas y sea más fácil
    repasar por curso. Devuelve {"ok": True, "ruta": ..., "titulo": ...}
    o {"error": "..."}."""
    carpeta = _nombre_valido(materia) or "Sin materia"
    return crear_nota_estudio(tema, contenido, carpeta=carpeta)


def crear_nota_por_proyecto(proyecto, tema, contenido):
    """Como crear_nota_estudio, pero organizada bajo "Proyectos/<nombre
    del proyecto>/" — para cuando un proyecto escolar/personal (ver
    proyectos_agent.py, que sigue siendo el ÚNICO lugar donde vive el
    Estado/avance de ese proyecto, en Notion) requiere investigación y
    Mauri quiere sus apuntes de estudio agrupados ahí, conectados entre
    sí con wikilinks. Esto NUNCA escribe nada en Notion — es solo
    organización dentro del vault. Devuelve
    {"ok": True, "ruta": ..., "titulo": ...} o {"error": "..."}."""
    carpeta = os.path.join("Proyectos", _nombre_valido(proyecto) or "Sin proyecto")
    return crear_nota_estudio(tema, contenido, carpeta=carpeta)


def _todas_las_notas():
    return glob.glob(os.path.join(VAULT_PATH, "**", "*.md"), recursive=True)


def _buscar_ruta_por_titulo(titulo):
    """Encuentra una nota existente por título (match exacto del nombre
    de archivo primero, luego substring en cualquier dirección) — mismo
    criterio de dos pasadas que proyectos_agent.resolver_proyecto.
    Devuelve la ruta o None."""
    titulo_bajo = titulo.strip().lower()
    candidatos = _todas_las_notas()

    for ruta in candidatos:
        if os.path.splitext(os.path.basename(ruta))[0].lower() == titulo_bajo:
            return ruta

    for ruta in candidatos:
        nombre_bajo = os.path.splitext(os.path.basename(ruta))[0].lower()
        if titulo_bajo in nombre_bajo or nombre_bajo in titulo_bajo:
            return ruta

    return None


def agregar_a_nota(titulo, contenido):
    """Añade `contenido` al final de una nota de estudio YA existente
    (buscada por título en TODO el vault, ver _buscar_ruta_por_titulo —
    no importa en qué subcarpeta de materia esté). Devuelve
    {"ok": True, "ruta": ..., "titulo": ...} o {"error": "..."} si no
    encontró ninguna nota que coincida."""
    _asegurar_vault()
    ruta = _buscar_ruta_por_titulo(titulo)
    if not ruta:
        return {"error": f"no encontré ninguna nota de estudio que coincida con '{titulo}'."}

    try:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write("\n\n" + contenido.strip() + "\n")
    except OSError as e:
        log.error("obsidian_agent: no se pudo agregar contenido a '%s' (%s)", ruta, e)
        return {"error": str(e)}

    return {"ok": True, "ruta": ruta, "titulo": os.path.splitext(os.path.basename(ruta))[0]}


def listar_notas(limite=20):
    """Últimas `limite` notas de estudio del vault (por fecha de
    modificación, más reciente primero, cualquier subcarpeta de
    materia) como lista de {"titulo", "ruta"}."""
    _asegurar_vault()
    rutas = sorted(_todas_las_notas(), key=os.path.getmtime, reverse=True)
    return [
        {"titulo": os.path.splitext(os.path.basename(r))[0], "ruta": r}
        for r in rutas[:limite]
    ]


def listar_notas_texto(limite=15):
    notas = listar_notas(limite)
    if not notas:
        return "Todavía no tienes ninguna nota de estudio en Obsidian, jefe."
    return "Tus notas de estudio más recientes en Obsidian:\n" + "\n".join(f"- {n['titulo']}" for n in notas)


def buscar_nota(query):
    """Notas de estudio cuyo TÍTULO o CONTENIDO contenga `query`
    (insensible a mayúsculas, cualquier subcarpeta de materia).
    Devuelve lista de {"titulo", "ruta"} (vacía si no hay coincidencias
    o `query` viene vacío) — usada también por examen_agent.py para
    generar exámenes de repaso a partir de una nota o materia."""
    _asegurar_vault()
    query_bajo = query.strip().lower()
    if not query_bajo:
        return []

    resultados = []
    for ruta in _todas_las_notas():
        nombre = os.path.splitext(os.path.basename(ruta))[0]
        if query_bajo in nombre.lower():
            resultados.append({"titulo": nombre, "ruta": ruta})
            continue
        try:
            with open(ruta, encoding="utf-8", errors="ignore") as f:
                contenido = f.read()
        except OSError:
            continue
        if query_bajo in contenido.lower():
            resultados.append({"titulo": nombre, "ruta": ruta})

    return resultados


def buscar_nota_texto(query):
    notas = buscar_nota(query)
    if not notas:
        return f"No encontré ninguna nota de estudio que mencione '{query}', jefe."
    return f"Notas de estudio que coinciden con '{query}':\n" + "\n".join(f"- {n['titulo']}" for n in notas)


# Flatpak: su .desktop vive en /var/lib/flatpak/exports/share/applications,
# que NO está entre las carpetas que control_agent.abrir_app ya recorre
# (~/.local/share/applications, /usr/share/applications) — se prueba esa
# búsqueda genérica primero por si algún día SÍ queda indexada ahí, y
# este comando directo queda como respaldo firme, sin depender de dónde
# haya quedado el .desktop.
_COMANDO_FLATPAK = ["flatpak", "run", "md.obsidian.Obsidian"]


def abrir_obsidian():
    """Abre la app de Obsidian (Flatpak). Devuelve el mensaje para el usuario."""
    mensaje = control_agent.abrir_app("obsidian")
    if mensaje.startswith("Abriendo") or mensaje.startswith("Intentando"):
        return mensaje

    if control_agent._lanzar(_COMANDO_FLATPAK):
        return "Abriendo Obsidian."
    return "No pude abrir Obsidian, jefe — revisa que esté instalado."
