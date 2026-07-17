#!/bin/bash
# ============================================================
# GERAM CORE OS · instalar_cloudflared.sh
# Descarga el binario cloudflared correcto para este equipo en bin/, sin sudo.
# Lo usa el "Modo en línea → link público" de Compartir. Es OPCIONAL: sin
# cloudflared, compartir sigue funcionando por LAN (misma WiFi).
#
# Linux y macOS. En Windows: descarga cloudflared.exe desde
#   https://github.com/cloudflare/cloudflared/releases/latest
# y colócalo en geram-core-os/bin/cloudflared.exe
# ============================================================
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$DIR/bin"
mkdir -p "$BIN_DIR"

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Linux)  OS_TAG=linux ;;
  Darwin) OS_TAG=darwin ;;
  *) echo "SO no soportado por este script: $OS. Baja el binario a mano (ver cabecera)."; exit 1 ;;
esac

case "$ARCH" in
  x86_64|amd64)  CF_ARCH=amd64 ;;
  aarch64|arm64) CF_ARCH=arm64 ;;
  *) echo "Arquitectura no soportada: $ARCH"; exit 1 ;;
esac

URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-${OS_TAG}-${CF_ARCH}"
echo "Descargando cloudflared ($OS_TAG/$CF_ARCH)…"
if curl -fL --connect-timeout 20 -o "$BIN_DIR/cloudflared" "$URL"; then
  chmod +x "$BIN_DIR/cloudflared"
  "$BIN_DIR/cloudflared" --version
  echo "Done: cloudflared installed at $BIN_DIR/cloudflared"
else
  echo "Download failed. Check your connection or download the binary manually (see header)."
  rm -f "$BIN_DIR/cloudflared"
  exit 1
fi
