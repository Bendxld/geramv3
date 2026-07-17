"""
Compartir en vivo — GERAM CORE OS (v3)

Expone UNA página web del workspace a la red para compartirla con amigos, SIN
abrir el server de desarrollo (que sigue siendo localhost-only). Arranca un
mini-server ESTÁTICO (`python -m http.server`) en un proceso APARTE, acotado a la
CARPETA de la página elegida, escuchando en 0.0.0.0 para la red local (LAN). Si
`cloudflared` está disponible, además abre un túnel público
(https://*.trycloudflare.com) para amigos fuera de la WiFi.

Solo una sesión de compartir a la vez. Los endpoints que lo controlan son
localhost-only (ver app/api/share.py): nadie de la red puede iniciar/parar; solo
consumir la página compartida.
"""

from __future__ import annotations

import base64
import io
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import segno

from app.api.workspace import workspace_service
from app.core.workspace import normalize_relative_path

# La URL efímera que imprime cloudflared al abrir un "quick tunnel".
_TRYCLOUDFLARE_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
# Solo se comparte una página web servible directamente por el navegador.
_WEB_SUFFIXES = {".html", ".htm"}
# Cuánto esperamos a que cloudflared publique la URL antes de rendirnos.
_TUNNEL_TIMEOUT_SECONDS = 25


def _lan_ip() -> str:
    """IP LAN principal (la de la ruta por defecto). No envía tráfico real."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _free_port() -> int:
    """Pide al SO un puerto libre para el mini-server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        return sock.getsockname()[1]


def _qr_data_uri(url: str) -> str:
    """QR del link como SVG en un data URI, listo para un <img src>. Sin red."""
    buffer = io.BytesIO()
    segno.make(url, error="m").save(
        buffer, kind="svg", scale=4, border=2,
        dark="#101014", light="#ffffff", xmldecl=False,
    )
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _find_cloudflared() -> Optional[str]:
    """cloudflared en el PATH o en el binario local del proyecto (bin/)."""
    found = shutil.which("cloudflared")
    if found:
        return found
    local = Path(__file__).resolve().parents[2] / "bin" / "cloudflared"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return None


def _drain(pipe) -> None:
    """Vacía la salida de cloudflared para que no se bloquee al llenar el buffer."""
    try:
        for _ in iter(pipe.readline, ""):
            pass
    except (ValueError, OSError):
        pass


class ShareManager:
    """Gestiona la única sesión de "compartir en vivo" a la vez."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._server: Optional[subprocess.Popen] = None
        self._tunnel: Optional[subprocess.Popen] = None
        self._state: dict = {"active": False}

    # ------------------------------------------------------------------ API
    def status(self) -> dict:
        with self._lock:
            # Si el mini-server murió por fuera, reflejamos que ya no está activo.
            if self._state.get("active") and self._server and self._server.poll() is not None:
                self._teardown_locked()
            return dict(self._state)

    def start(self, path: str, tunnel: bool) -> dict:
        folder, filename = self._resolve_web_folder(path)

        with self._lock:
            self._teardown_locked()  # una sola sesión a la vez
            port = _free_port()
            self._server = subprocess.Popen(
                [
                    sys.executable, "-m", "http.server", str(port),
                    "--bind", "0.0.0.0", "--directory", str(folder),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            lan_url = f"http://{_lan_ip()}:{port}/{filename}"
            self._state = {
                "active": True,
                "file": filename,
                "folder": str(folder),
                "port": port,
                "lan_url": lan_url,
                "lan_qr": _qr_data_uri(lan_url),
                "public_url": None,
                "public_qr": None,
                "tunnel_requested": bool(tunnel),
                "tunnel_available": _find_cloudflared() is not None,
            }

        # El túnel puede tardar; se abre fuera del lock. Si mientras tanto se
        # detuvo o reemplazó la sesión (otro start), descartamos el resultado.
        if tunnel:
            public = self._start_tunnel(port, filename)
            with self._lock:
                if self._state.get("active") and self._state.get("port") == port:
                    self._state["public_url"] = public
                    self._state["public_qr"] = _qr_data_uri(public) if public else None
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._teardown_locked()
            return dict(self._state)

    # -------------------------------------------------------------- helpers
    def _resolve_web_folder(self, path: str) -> tuple[Path, str]:
        """Valida la ruta (misma seguridad del workspace) y devuelve (carpeta, archivo)."""
        _canonical, parts = normalize_relative_path(path)
        filename = parts[-1]
        if Path(filename).suffix.casefold() not in _WEB_SUFFIXES:
            raise ValueError("Only a web page (.html) can be shared.")

        root = workspace_service.root.resolve()
        folder = root.joinpath(*parts[:-1]).resolve()
        # Defensa contra symlinks que se salgan de la raíz del workspace.
        if folder != root and root not in folder.parents:
            raise ValueError("The page is outside the workspace.")
        if not folder.is_dir() or not (folder / filename).is_file():
            raise ValueError("The page to share was not found.")
        return folder, filename

    def _start_tunnel(self, port: int, filename: str) -> Optional[str]:
        binary = _find_cloudflared()
        if not binary:
            return None
        proc = subprocess.Popen(
            [binary, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._tunnel = proc

        url = None
        deadline = time.monotonic() + _TUNNEL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None:
                    break
                continue
            match = _TRYCLOUDFLARE_RE.search(line)
            if match:
                url = match.group(0)
                break

        # Seguimos vaciando la salida para que cloudflared no se cuelgue.
        if proc.stdout:
            threading.Thread(target=_drain, args=(proc.stdout,), daemon=True).start()
        return f"{url}/{filename}" if url else None

    def _teardown_locked(self) -> None:
        for attr in ("_tunnel", "_server"):
            proc = getattr(self, attr)
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            setattr(self, attr, None)
        self._state = {"active": False}


share_manager = ShareManager()
