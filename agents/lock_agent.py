# ============================================================
# GERAM OS v2 · lock_agent.py
# Standby por inactividad + desbloqueo por contraseña. La
# contraseña se guarda como hash SHA-256 en .env (LOCK_PASSWORD_HASH),
# nunca en texto plano.
# ============================================================

import hashlib
import hmac
import logging
import time

import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("lock_agent")

STANDBY_MINUTOS = getattr(config, "STANDBY_MINUTES", 5)
LOCK_PASSWORD_HASH = getattr(config, "LOCK_PASSWORD_HASH", None)

# Momento de la última interacción real del usuario. Arranca ya vencido
# (mismo truco que forzar_bloqueo) para que el sistema SIEMPRE nazca
# bloqueado al arrancar el server — IRIS debe pedir la contraseña
# antes de usarse, no solo tras STANDBY_MINUTOS de inactividad.
_ultima_actividad = time.time() - (STANDBY_MINUTOS * 60) - 1


def registrar_actividad():
    """Marca actividad del usuario y reinicia el contador de standby.
    Debe llamarse en cada interacción real (chat, voz, etc.)."""
    global _ultima_actividad
    _ultima_actividad = time.time()


def forzar_bloqueo():
    """Bloquea de inmediato sin esperar a que pasen STANDBY_MINUTOS —
    usado por cualquier "bloquéate ya" explícito. No hay una bandera
    aparte: simplemente
    se echa _ultima_actividad lo bastante atrás para que esta_bloqueado()
    ya dé True en el siguiente chequeo (el mismo mecanismo de siempre,
    solo que empujado a mano en vez de esperar la inactividad real)."""
    global _ultima_actividad
    _ultima_actividad = time.time() - (STANDBY_MINUTOS * 60) - 1
    log.info("lock_agent: bloqueo forzado")


def esta_bloqueado():
    """True si pasaron más de STANDBY_MINUTOS sin actividad."""
    inactivo_segundos = time.time() - _ultima_actividad
    bloqueado = inactivo_segundos > (STANDBY_MINUTOS * 60)
    return bloqueado


def minutos_inactivo():
    """Útil para mostrar en el HUD cuánto lleva inactivo."""
    return round((time.time() - _ultima_actividad) / 60, 1)


def _hash(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def verificar_password(intento):
    """Compara `intento` contra el hash guardado en .env. Si es
    correcto, además reinicia el standby (desbloquea)."""
    if not LOCK_PASSWORD_HASH:
        raise RuntimeError("lock_agent.py: falta LOCK_PASSWORD_HASH en el .env")

    intento_hash = _hash(intento)
    # hmac.compare_digest evita timing attacks al comparar hashes.
    correcto = hmac.compare_digest(intento_hash, LOCK_PASSWORD_HASH)

    if correcto:
        log.info("lock_agent: desbloqueo correcto")
        registrar_actividad()
    else:
        log.warning("lock_agent: intento de desbloqueo fallido")

    return correcto
