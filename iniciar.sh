#!/bin/bash
# ============================================================
# GERAM OS v2 · iniciar.sh
# Arranca todo lo necesario para que IRIS quede en línea:
# activa el venv, asegura que Ollama esté corriendo (por si el
# servicio systemd no está activo) y levanta server.py.
#
# Pensado para correr solo (autostart de sesión, ver
# ~/.config/autostart/geram-os.desktop) o a mano desde terminal.
# ============================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

source venv/bin/activate

# Ollama: se verifica pegándole a su API (no por nombre de proceso)
# para no lanzar una segunda instancia si ya está corriendo, sea por
# el servicio systemd o por una anterior de esta misma terminal.
if curl -s -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "Ollama is already running."
else
  echo "Ollama is not responding; starting it..."
  nohup ollama serve > /tmp/geram-ollama.log 2>&1 &
  disown

  for i in $(seq 1 15); do
    curl -s -m 1 http://localhost:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi

echo "Starting GERAM OS (server.py)..."
exec python3 server.py
