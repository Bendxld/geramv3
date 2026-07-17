# ============================================================
# GERAM OS v2 · balancer.py
# Round-robin entre las 5 keys gratuitas de Gemini. Si una falla
# (rate limit, auth, timeout, lo que sea) prueba la siguiente. Si
# las 5 fallan, usa la key de pago como último recurso.
#
# NOTA: usa el SDK nuevo `google-genai` (google-generativeai fue
# descontinuado por Google en 2025).
# ============================================================

import base64
import datetime
import logging

from google import genai
from google.genai import errors

import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("balancer")

MODELO_DEFAULT = "gemini-2.5-flash"

# Índice para el round-robin, se conserva entre llamadas.
_indice_actual = 0

# Qué key sirvió la ÚLTIMA llamada exitosa ("G1".."G5" gratuita, "GP"
# la de pago) — director.procesar_mensaje() lo lee (junto con
# groq_agent.ultima_fuente) para taggear la respuesta y que el jefe
# sepa qué API se usó. Un solo valor de módulo basta porque
# _lock_despacho en director.py ya serializa el despacho de mensajes.
ultima_fuente = None

# --- Uso diario ESTIMADO por key (para avisar cuando se acerca al
# límite, ver proactividad_agent._revisar_uso_gemini) — conteo LOCAL de
# llamadas hechas por ESTE proceso, se reinicia solo al cambiar de día.
# No consulta la cuota real de Google (no hay endpoint para eso). ---
_uso_hoy = {i: 0 for i in range(1, 6)}
_pago_usos_hoy = 0
_fecha_uso = None


def _resetear_uso_si_cambio_dia():
    global _uso_hoy, _pago_usos_hoy, _fecha_uso
    hoy = datetime.date.today()
    if _fecha_uso != hoy:
        _uso_hoy = {i: 0 for i in range(1, 6)}
        _pago_usos_hoy = 0
        _fecha_uso = hoy


def _registrar_uso_key(numero_key):
    global _uso_hoy
    _resetear_uso_si_cambio_dia()
    _uso_hoy[numero_key] = _uso_hoy.get(numero_key, 0) + 1


def _registrar_uso_pago():
    global _pago_usos_hoy
    _resetear_uso_si_cambio_dia()
    _pago_usos_hoy += 1


def obtener_uso_hoy():
    """Devuelve {"por_key": {1: n, ..., 5: n}, "pago_usos": n,
    "porcentajes": {1: %, ..., 5: %}} — uso ESTIMADO de hoy contra
    config.GEMINI_LIMITE_DIARIO_POR_KEY. Lo usa proactividad_agent
    para avisar cuando alguna key gratis se acerca al límite o cuando
    ya se usó la de pago (ver _revisar_uso_gemini)."""
    _resetear_uso_si_cambio_dia()
    limite = max(config.GEMINI_LIMITE_DIARIO_POR_KEY, 1)
    porcentajes = {numero: (n / limite) * 100 for numero, n in _uso_hoy.items()}
    return {"por_key": dict(_uso_hoy), "pago_usos": _pago_usos_hoy, "porcentajes": porcentajes}


def _mapear_historial(historial):
    """Convierte el historial de context_engine (rol: usuario/iris)
    al formato de contenidos que espera el SDK (role: user/model)."""
    contenidos = []
    for turno in historial:
        rol = "user" if turno.get("rol") == "usuario" else "model"
        contenidos.append({"role": rol, "parts": [{"text": turno.get("texto", "")}]})
    return contenidos


def _armar_config(system_instruction):
    if not system_instruction:
        return None
    from google.genai import types
    return types.GenerateContentConfig(system_instruction=system_instruction)


def _intentar_con_key(key, numero_key, contenidos, cfg):
    """Un solo intento con una key específica. Devuelve el texto o
    lanza una excepción si falla (la captura el llamador)."""
    log.info("balancer: intentando con key #%s", numero_key)
    client = genai.Client(api_key=key)
    respuesta = client.models.generate_content(
        model=MODELO_DEFAULT,
        contents=contenidos,
        config=cfg,
    )
    return respuesta.text


def _intentar_todas_las_keys(contenidos, cfg):
    """Ciclo común de round-robin + fallback a la key de pago,
    compartido por enviar_mensaje() y enviar_mensaje_con_imagen() (solo
    cambia qué `contenidos` se mandan). Nunca lanza excepción: siempre
    devuelve un string, empieza con "ERROR:" si todo falló."""
    global _indice_actual, ultima_fuente

    # Prueba las 5 keys gratuitas empezando desde el índice actual,
    # para repartir la carga entre llamadas sucesivas.
    orden = [(i, config.GEMINI_FREE_KEYS[i]) for i in
             [(_indice_actual + offset) % 5 for offset in range(5)]]

    for indice_key, key in orden:
        try:
            texto = _intentar_con_key(key, indice_key + 1, contenidos, cfg)
            # Avanza el puntero para que la próxima llamada empiece
            # en la siguiente key (round-robin real entre llamadas).
            _indice_actual = (indice_key + 1) % 5
            ultima_fuente = f"G{indice_key + 1}"
            _registrar_uso_key(indice_key + 1)
            return texto
        except Exception as e:
            log.warning("balancer: key #%s falló (%s), probando la siguiente", indice_key + 1, type(e).__name__)

    # Las 5 gratuitas fallaron: último recurso, la key de pago.
    try:
        log.info("balancer: las 5 keys gratuitas fallaron, usando key de pago")
        texto = _intentar_con_key(config.GEMINI_PAY_KEY, "PAGO", contenidos, cfg)
        ultima_fuente = "GP"
        _registrar_uso_pago()
        return texto
    except Exception as e:
        log.error("balancer: la key de pago también falló (%s)", type(e).__name__)
        return "ERROR: no se pudo contactar a Gemini (todas las keys fallaron)."


def enviar_mensaje(prompt, historial=None, system_instruction=None):
    """Envía `prompt` (+ `historial` opcional) a Gemini.

    Prueba las 5 keys gratuitas en round-robin; si todas fallan,
    intenta con la key de pago. Si esa también falla, devuelve un
    mensaje de error en texto (no lanza excepción) para que el
    resto del sistema (director.py) siempre reciba un string.
    """
    historial = historial or []
    contenidos = _mapear_historial(historial)
    contenidos.append({"role": "user", "parts": [{"text": prompt}]})
    cfg = _armar_config(system_instruction)
    return _intentar_todas_las_keys(contenidos, cfg)


def enviar_mensaje_con_imagen(prompt, ruta_imagen, mime_type="image/png", historial=None, system_instruction=None):
    """Como enviar_mensaje(), pero adjunta la imagen en `ruta_imagen`
    (Gemini Vision) — usada por screenshot_agent.py/observador.py.
    Mismo round-robin de keys, mismo contrato: nunca lanza excepción,
    siempre string ("ERROR:..." si falla, incluida la lectura del
    archivo). Estas dos SÍ gastan tokens (a diferencia de la mera
    captura, ver capturar_pantalla/capturar_foto en esos agentes) —
    por eso viven separadas de enviar_mensaje() en vez de meter la
    imagen ahí con un parámetro opcional: que quede explícito en el
    nombre de la función cuál gasta tokens de visión y cuál no."""
    try:
        with open(ruta_imagen, "rb") as f:
            imagen_b64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        return f"ERROR: no pude leer la imagen '{ruta_imagen}' ({e})."

    historial = historial or []
    contenidos = _mapear_historial(historial)
    contenidos.append({
        "role": "user",
        "parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime_type, "data": imagen_b64}},
        ],
    })
    cfg = _armar_config(system_instruction)
    return _intentar_todas_las_keys(contenidos, cfg)
