#!/bin/bash
# ============================================================
# GERAM CORE OS · salir_kiosk.sh
#
# Cierra el navegador en modo kiosk lanzado por iniciar_kiosk.sh.
# Pensado para poder correrse desde OTRA terminal (SSH/Tailscale)
# si te quedas atorado en el kiosk sin forma obvia de salir
# localmente. No toca el backend (uvicorn) — eso sigue corriendo.
# ============================================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$DIR/.kiosk.pid"
PROFILE_DIR="$DIR/.kiosk-profile"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  kill "$(cat "$PID_FILE")"
  echo "Kiosk closed (PID $(cat "$PID_FILE"))."
  rm -f "$PID_FILE"
else
  echo "Saved PID is invalid or the process no longer exists—searching by kiosk profile..."
  if pkill -f -- "--user-data-dir=$PROFILE_DIR"; then
    echo "Kiosk closed (found by --user-data-dir)."
  else
    echo "No running kiosk process was found."
  fi
  rm -f "$PID_FILE"
fi
