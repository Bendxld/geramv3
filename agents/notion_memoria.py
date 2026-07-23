# ============================================================
# GERAM OS v2 · notion_memoria.py
# "Memoria en Notion": el usuario crea en SU propio Notion las bases
# (databases) que quiera —Resúmenes, Finanzas, Ideas...— y las registra
# en config/notion_bases.json. IRIS elige la base según lo que le pidas,
# guarda ahí la página y te devuelve el NOMBRE de la base y la URL de la
# página creada (compartible con quien tenga acceso a esa base).
#
# Es OPCIONAL y aditivo: sin archivo o sin bases válidas, todo sigue
# cayendo al flujo clásico de un solo NOTION_DATABASE_ID (ver director.py
# / notion_agent.crear_pagina). Cada persona define las suyas; los IDs
# quedan en config/notion_bases.json (git-ignorado).
# ============================================================

import json
import logging
import os

from agents import notion_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("notion_memoria")

# config/notion_bases.json vive junto al repo (un nivel arriba de agents/).
_RUTA_BASES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "notion_bases.json",
)

# Se lee una vez y se cachea; recargar=True fuerza releer (ej. tras editar).
_cache = None


def cargar_bases(recargar=False):
    """Lee config/notion_bases.json y devuelve la lista de bases válidas
    (las que traen database_id). Tolerante: si el archivo no existe o está
    mal formado, devuelve [] y IRIS cae al flujo clásico de una sola base."""
    global _cache
    if _cache is not None and not recargar:
        return _cache

    bases = []
    try:
        with open(_RUTA_BASES, encoding="utf-8") as f:
            datos = json.load(f)
    except FileNotFoundError:
        _cache = bases
        return bases
    except (json.JSONDecodeError, OSError) as e:
        log.warning("notion_memoria: no pude leer %s (%s)", _RUTA_BASES, e)
        _cache = bases
        return bases

    crudas = datos.get("bases", []) if isinstance(datos, dict) else datos
    for b in crudas if isinstance(crudas, list) else []:
        if not isinstance(b, dict):
            continue
        database_id = (b.get("database_id") or "").strip()
        # Los placeholders del .example ("PON_AQUI_...") no son IDs reales.
        if not database_id or database_id.startswith("PON_AQUI"):
            continue
        nombre = (b.get("nombre") or b.get("clave") or "Sin nombre").strip()
        bases.append({
            "clave": (b.get("clave") or nombre).strip().lower(),
            "nombre": nombre,
            "database_id": database_id,
            "url": (b.get("url") or "").strip(),
            "descripcion": (b.get("descripcion") or "").strip(),
            "palabras_clave": [str(p).lower() for p in b.get("palabras_clave", [])],
        })

    _cache = bases
    return bases


def hay_bases():
    """True si el usuario registró al menos una base válida."""
    return bool(cargar_bases())


def base_por_defecto():
    """La primera base registrada, o None si no hay ninguna. Se usa cuando
    el pedido no menciona una base concreta."""
    bases = cargar_bases()
    return bases[0] if bases else None


def elegir_base(texto=""):
    """Elige la base que mejor matchee `texto` por su clave, nombre o
    palabras_clave. Devuelve None si nada matchea (el caller decide si usa
    base_por_defecto() o pregunta)."""
    bases = cargar_bases()
    if not bases:
        return None
    t = (texto or "").lower()
    for b in bases:
        if b["clave"] and b["clave"] in t:
            return b
        if b["nombre"].lower() in t:
            return b
        if any(p and p in t for p in b["palabras_clave"]):
            return b
    return None


def listar_bases():
    """Texto legible con las bases registradas, para 'qué bases tengo en
    Notion'. Sin bases, invita a crear config/notion_bases.json. Relee el
    archivo (recargar=True) para reflejar bases recién agregadas sin reiniciar."""
    bases = cargar_bases(recargar=True)
    if not bases:
        return ("No tienes bases de Notion registradas todavía. Crea "
                "config/notion_bases.json (copia config/notion_bases.example.json) "
                "y agrega las que quieras.")
    lineas = ["Tus bases de Notion:"]
    for b in bases:
        desc = f" — {b['descripcion']}" if b["descripcion"] else ""
        url = f"  {b['url']}" if b["url"] else ""
        lineas.append(f"• {b['nombre']}{desc}{url}")
    return "\n".join(lineas)


def guardar(base, titulo, contenido, fuente_url=""):
    """Crea una página en `base` (dict de cargar_bases) con `titulo` y
    `contenido`. Si viene `fuente_url`, la anexa al final del contenido
    para que quede la referencia. Devuelve {"id","url"} o {"error": ...}
    (lo que devuelva notion_agent.crear_pagina_con_propiedades)."""
    cuerpo = contenido or ""
    if fuente_url:
        cuerpo = f"{cuerpo}\n\n- Fuente: {fuente_url}"
    return notion_agent.crear_pagina_con_propiedades(
        base["database_id"], titulo[:200] or "Sin título", contenido=cuerpo,
    )


def mensaje_guardado(base, resultado, titulo):
    """Arma el mensaje para el usuario: nombre de la base, URL de la página
    creada y que es compartible. Nunca lanza: todo error va en el texto."""
    if resultado.get("error"):
        return (f"Generé el contenido pero no lo pude guardar en tu base "
                f"«{base['nombre']}» de Notion: {resultado['error']}")
    partes = [f"Listo, jefe. Guardé «{titulo}» en tu base «{base['nombre']}» de Notion."]
    url = resultado.get("url")
    if url:
        partes.append(f"Página: {url}")
    partes.append("Cualquiera con acceso a esa base puede verla.")
    return " ".join(partes)
