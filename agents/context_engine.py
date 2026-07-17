# ============================================================
# GERAM OS v2 · context_engine.py
# Historial de la conversación ACTUAL, en memoria de proceso
# (no persiste entre reinicios; para eso está memory.py/Supabase).
#
# Separado POR SESIÓN ("hud", "telegram", ...): cada canal tiene su
# propia ventana de turnos recientes para no mezclar en el prompt de
# Gemini una conversación de la compu con una del celular a mitad de
# frase — pero ambos siguen leyendo/escribiendo la MISMA memoria de
# largo plazo en Supabase (ver memory.py), así que IRIS igual
# recuerda entre canales, solo que sin el "historial inmediato" cruzado.
# ============================================================

import config

# sesión -> lista de turnos: [{"rol": "usuario"|"iris", "texto": "..."}]
_historiales = {}

INSTANCIA_ACTIVA = config.INSTANCE_NAME

SESION_DEFAULT = "hud"


def _lista(sesion):
    return _historiales.setdefault(sesion or SESION_DEFAULT, [])


def agregar(rol, texto, sesion=SESION_DEFAULT):
    """Agrega un turno al historial de la conversación actual de `sesion`."""
    _lista(sesion).append({"rol": rol, "texto": texto})


def obtener_historial(limite=10, sesion=SESION_DEFAULT):
    """Devuelve los últimos `limite` turnos de `sesion`, en orden cronológico."""
    historial = _lista(sesion)
    if limite is None:
        return list(historial)
    return historial[-limite:]


def limpiar(sesion=None):
    """Borra el historial de `sesion` (o de TODAS las sesiones si no se
    especifica ninguna)."""
    if sesion is None:
        _historiales.clear()
    else:
        _historiales.pop(sesion, None)


# Último archivo que IRIS creó (código de code_agent.crear_proyecto,
# o cualquier archivo/carpeta creado vía control_agent.interpretar
# con touch/echo/mkdir) — GLOBAL a propósito, no por sesión, mismo
# criterio que director._ultima_carpeta: es un solo jefe con una sola
# "última cosa creada" sin importar desde qué canal la pidió. Así,
# "ábrelo"/"abre ese archivo" lo puede resolver sin pedir el nombre.
_ultimo_archivo_creado = None


def set_ultimo_archivo_creado(ruta):
    global _ultimo_archivo_creado
    _ultimo_archivo_creado = ruta


def obtener_ultimo_archivo_creado():
    return _ultimo_archivo_creado


# Último archivo que IRIS DESCARGÓ (research_agent.procesar_seleccion,
# o control_agent.interpretar cuando el comando generado es un wget/curl
# — ver control_agent.extraer_archivo_descargado). Aparte de
# _ultimo_archivo_creado porque semánticamente son cosas distintas
# (creado vs. bajado de internet), pero set_ultimo_archivo_descargado
# SIEMPRE también llama a set_ultimo_archivo_creado — mismo mecanismo,
# a propósito: así _ultimo_archivo_creado queda como la línea de tiempo
# UNIFICADA de "lo último que IRIS puso en el disco, sea como sea",
# y director._procesar_abrir_ultimo (que ya consulta
# obtener_ultimo_archivo_creado primero) resuelve "ábrelo" con el más
# reciente de los dos sin tener que comparar timestamps a mano.
_ultimo_archivo_descargado = None


def set_ultimo_archivo_descargado(ruta):
    global _ultimo_archivo_descargado
    _ultimo_archivo_descargado = ruta
    set_ultimo_archivo_creado(ruta)


def obtener_ultimo_archivo_descargado():
    return _ultimo_archivo_descargado
