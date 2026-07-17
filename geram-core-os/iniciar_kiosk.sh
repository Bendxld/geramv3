#!/bin/bash
# ============================================================
# GERAM CORE OS · iniciar_kiosk.sh
#
# Levanta el backend (si no está corriendo) y lanza el HUD en
# modo kiosk real con Brave: pantalla completa, sin barra de
# navegador, perfil de navegador aislado (no toca bookmarks ni
# extensiones normales). Pensado para dejar la laptop fija en
# el HUD o para autostart.
#
# Para salir del kiosk ver salir_kiosk.sh (o Alt+F4 local).
# ============================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

BASE_URL="http://localhost:8000"
LOG_DIR="$DIR/logs"
KIOSK_LOG="$LOG_DIR/kiosk.log"
KIOSK_PROFILE_DIR="$DIR/.kiosk-profile"
KIOSK_PID_FILE="$DIR/.kiosk.pid"
PYTHON_BIN="$DIR/venv/bin/python"
LAUNCHER="$DIR/launcher.py"

mkdir -p "$LOG_DIR" "$KIOSK_PROFILE_DIR"

# --- 1. Backend: validate exact Core identity before reuse or startup ---
# The legacy ../server.py is intentionally not a valid backend identity.
if [ ! -x "$PYTHON_BIN" ] || [ ! -f "$LAUNCHER" ]; then
  echo "ERROR: the local launcher or GERAM CORE OS virtual environment is missing." >&2
  exit 1
fi
"$PYTHON_BIN" "$LAUNCHER" start --wait 15

# --- 2. Lanzar Brave en modo kiosk ---
# Flags:
#   --kiosk                        pantalla completa real, sin barra/tabs/UI
#   --user-data-dir=...            perfil aislado — no carga bookmarks/
#                                   extensiones/historial del perfil normal
#   --no-first-run                 salta el asistente de primera vez
#   --noerrdialogs                 sin diálogos de error nativos
#   --disable-session-crashed-bubble / --disable-infobars
#                                   sin el aviso de "restaurar pestañas"
#   --overscroll-history-navigation=0 / --disable-pinch
#                                   desactiva swipe-back y pinch-zoom
#                                   (evita gestos que naveguen o hagan
#                                   zoom fuera del HUD)
#   --disable-pull-to-refresh-effect
#                                   sin gesto de "jalar para refrescar"
#   --disable-features=TranslateUI  sin el globo de "traducir esta página"
echo "Lanzando HUD en modo kiosk..."
nohup brave-browser \
  --kiosk "$BASE_URL/" \
  --user-data-dir="$KIOSK_PROFILE_DIR" \
  --no-first-run \
  --noerrdialogs \
  --disable-session-crashed-bubble \
  --disable-infobars \
  --disable-features=TranslateUI \
  --overscroll-history-navigation=0 \
  --disable-pinch \
  --disable-pull-to-refresh-effect \
  > "$KIOSK_LOG" 2>&1 &

echo $! > "$KIOSK_PID_FILE"
disown

echo "Kiosk lanzado (PID $(cat "$KIOSK_PID_FILE")). Log: $KIOSK_LOG"
echo "Para salir: Alt+F4 en la laptop, o ./salir_kiosk.sh (local o por SSH/Tailscale)."
