"""
Estado de activación de agentes — IRIS.

Persistencia local (JSON, 0600) de qué agentes están SUSPENDIDOS. Los
loops/schedulers de fondo consultan `esta_suspendido()` antes de correr, y
el HUD (dashboard de agentes de GERAM CORE OS) lee/escribe el estado vía los
endpoints /agentes de server.py.

Semántica de "suspendido": el agente deja de actuar POR SU CUENTA (proactividad,
schedulers, monitores de fondo). Las peticiones explícitas del usuario a través
del chat siguen funcionando — suspender apaga lo automático, no la herramienta.

Fail-safe: si el archivo falta o está corrupto, ningún agente queda suspendido
(todos activos) y nunca se lanza una excepción hacia el caller — un estado
ilegible jamás debe tumbar a IRIS ni bloquear un scheduler.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_ARCHIVO = _RAIZ / "config" / "agentes_estado.json"
_LOCK = threading.Lock()

# Agentes de INFRAESTRUCTURA: IRIS deja de funcionar si se apagan, así que no
# son suspendibles desde el dashboard (se muestran como "núcleo", siempre on).
NUCLEO = frozenset({
    "director",
    "balancer",
    "memory",
    "context_engine",
    "personality",
    "escuchar",
    "habla",
    "offline_agent",
    "lock_agent",
    "control_agent",
})


def _leer() -> set[str]:
    """Conjunto de nombres suspendidos en disco. Nunca lanza."""
    try:
        datos = json.loads(_ARCHIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return set()
    suspendidos = datos.get("suspendidos", []) if isinstance(datos, dict) else []
    if not isinstance(suspendidos, list):
        return set()
    # Un agente de núcleo nunca cuenta como suspendido, aunque el archivo
    # (editado a mano) lo liste por error.
    return {str(n) for n in suspendidos if str(n) not in NUCLEO}


def _escribir(suspendidos: set[str]) -> None:
    """Escribe el estado atómicamente con permisos 0600 (solo dueño)."""
    _ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"suspendidos": sorted(suspendidos)},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(_ARCHIVO.parent), prefix=".agentes-", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(tmp, _ARCHIVO)
        os.chmod(_ARCHIVO, 0o600)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def esta_suspendido(nombre: str) -> bool:
    """True si `nombre` está suspendido. Los agentes de núcleo nunca lo están."""
    if nombre in NUCLEO:
        return False
    with _LOCK:
        return nombre in _leer()


def listar_suspendidos() -> set[str]:
    """Copia del conjunto de agentes suspendidos (para /agentes)."""
    with _LOCK:
        return _leer()


def fijar(nombre: str, suspendido: bool) -> bool:
    """Suspende (True) o reactiva (False) un agente y persiste el cambio.

    Devuelve el nuevo estado real (True = suspendido). Los agentes de núcleo
    son inmunes: siempre devuelven False sin escribir nada.
    """
    if nombre in NUCLEO:
        return False
    with _LOCK:
        actual = _leer()
        if suspendido:
            actual.add(nombre)
        else:
            actual.discard(nombre)
        _escribir(actual)
        return nombre in actual
