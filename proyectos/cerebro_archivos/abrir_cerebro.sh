#!/bin/bash
# ============================================================
# Cerebro de Archivos · abrir_cerebro.sh
# Usado por el acceso directo del escritorio (~/Desktop/Cerebro-de-Archivos.desktop):
# si el servidor no está corriendo lo arranca primero, y luego abre
# el visualizador en el navegador.
# ============================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL="http://127.0.0.1:8420"

if ! curl -s -m 2 "$URL" >/dev/null 2>&1; then
  nohup "$DIR/venv/bin/python" "$DIR/server.py" >> "$DIR/servidor.log" 2>&1 &
  disown

  # Espera a que el servidor conteste antes de abrir el navegador (máx 20s)
  for i in $(seq 1 20); do
    curl -s -m 1 "$URL" >/dev/null 2>&1 && break
    sleep 1
  done
fi

if command -v firefox >/dev/null 2>&1; then
  firefox "$URL" &
elif command -v brave-browser >/dev/null 2>&1; then
  brave-browser "$URL" &
else
  xdg-open "$URL" &
fi
