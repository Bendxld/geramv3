# ============================================================
# GERAM OS v2 · groq_agent.py
# Genera contenido largo (ensayos, resúmenes detallados, reportes,
# análisis) con la API de Groq — formato compatible con OpenAI,
# mucho más rápida y gratis que pedirle lo mismo a Gemini.
#
# Round-robin entre hasta 5 keys gratuitas (GROQ_FREE_1..5, mismo
# patrón que balancer.py usa para Gemini). A diferencia de Gemini,
# acá no todas tienen que estar configuradas: las vacías se ignoran,
# así que agregar/quitar una key en .env + reiniciar el server basta,
# sin tocar este archivo.
# ============================================================

import logging

import httpx

import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("groq_agent")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# llama-3.1-70b-versatile (el modelo pedido originalmente) fue
# descontinuado por Groq; este es su sucesor directo, mismo tamaño
# (70B) y mismo perfil "versatile" para texto largo.
MODELO = "llama-3.3-70b-versatile"

# Qué proveedor sirvió la ÚLTIMA llamada exitosa — director.
# procesar_mensaje() lo lee (junto con balancer.ultima_fuente) para
# taggear la respuesta (".GR") y que el jefe sepa qué API se usó. Un
# solo valor de módulo basta porque _lock_despacho en director.py ya
# serializa el despacho de mensajes (nunca hay dos en vuelo a la vez).
# Se queda en "GR" sin importar cuál de las 5 keys respondió — el
# número de key es detalle interno, solo va al log (nunca al jefe).
ultima_fuente = None

# Índice para el round-robin, se conserva entre llamadas (igual que
# balancer._indice_actual).
_indice_actual = 0


def _keys_disponibles():
    """Las keys de GROQ_FREE_KEYS que sí están configuradas, con su
    número de slot original (1-based, ej. si solo están la 1, 2 y 4,
    devuelve [(1, ...), (2, ...), (4, ...)] — el número que se loggea
    siempre corresponde a su GROQ_FREE_N en .env, no a su posición en
    esta lista filtrada)."""
    return [(i + 1, key) for i, key in enumerate(config.GROQ_FREE_KEYS) if key]


def _intentar_con_key(key, numero_key, mensajes):
    """Un solo intento con una key específica. Devuelve el texto o
    lanza una excepción si falla (la captura el llamador). NUNCA
    loggea la key completa, solo su número de slot."""
    log.info("groq_agent: intentando con GROQ key %s", numero_key)
    respuesta = httpx.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": MODELO, "messages": mensajes, "temperature": 0.7},
        # Contenido largo (500+ palabras) tarda más que una respuesta corta.
        timeout=60,
    )
    respuesta.raise_for_status()
    return respuesta.json()["choices"][0]["message"]["content"]


def generar_contenido(prompt, system_prompt=""):
    """Genera texto largo con Groq a partir de `prompt` (+ `system_prompt`
    opcional). Prueba las keys gratuitas disponibles en round-robin
    (empezando desde donde se quedó la última llamada, para repartir
    la carga); si una falla (rate limit, auth, lo que sea) pasa
    automáticamente a la siguiente. Devuelve el contenido como string,
    o un mensaje que empieza con "ERROR:" si todas fallan (nunca lanza
    excepción, para que quien lo llame siempre reciba un string)."""
    global ultima_fuente, _indice_actual

    disponibles = _keys_disponibles()
    if not disponibles:
        return "ERROR: no hay ninguna GROQ_FREE_N configurada en .env."

    mensajes = []
    if system_prompt:
        mensajes.append({"role": "system", "content": system_prompt})
    mensajes.append({"role": "user", "content": prompt})

    total = len(disponibles)
    orden = [disponibles[(_indice_actual + offset) % total] for offset in range(total)]

    for posicion, (numero_key, key) in enumerate(orden):
        try:
            texto = _intentar_con_key(key, numero_key, mensajes)
            # Avanza el puntero para que la próxima llamada empiece en
            # la siguiente key disponible (round-robin real entre
            # llamadas).
            _indice_actual = (_indice_actual + posicion + 1) % total
            ultima_fuente = "GR"
            return texto
        except httpx.HTTPStatusError as e:
            log.warning("groq_agent: GROQ key %s falló (%s), probando la siguiente", numero_key, e.response.status_code)
        except Exception as e:
            log.warning("groq_agent: GROQ key %s falló (%s), probando la siguiente", numero_key, type(e).__name__)

    log.error("groq_agent: las %s keys de Groq disponibles fallaron", total)
    return "ERROR: no se pudo contactar a Groq (todas las keys disponibles fallaron)."
