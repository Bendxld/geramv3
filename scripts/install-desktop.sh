#!/bin/bash
# ============================================================
# GERAM · install-desktop.sh  (Linux)
# Genera e instala el ícono de escritorio apuntando a la ruta REAL donde
# clonaste GERAM (no a una ruta fija). Corre esto una vez tras instalar.
#
#   ./scripts/install-desktop.sh
#
# Windows no usa .desktop — ahí se abre en el navegador (ver README).
# ============================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPS="$HOME/.local/share/applications"
DEST="$APPS/geram.desktop"
mkdir -p "$APPS"

cat > "$DEST" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=GERAM
Comment=GERAM — entorno de desarrollo (A.R.E.S.) con IRIS como complemento
Exec=$DIR/geram.sh
TryExec=$DIR/geram.sh
Icon=$DIR/geram-core-os/static/favicon.svg
Path=$DIR
Terminal=false
Categories=Development;
StartupNotify=true
StartupWMClass=geram-core-os
EOF

chmod +x "$DEST"
chmod +x "$DIR/geram.sh" "$DIR/iniciar.sh" "$DIR/geram-core-os/iniciar_app.sh" 2>/dev/null || true

# XFCE/GNOME confían en el .desktop si tiene el bit ejecutable y (XFCE) el
# atributo de confianza; lo marcamos para que abra sin advertencia.
gio set "$DEST" metadata::trusted true 2>/dev/null || true

echo "✓ Ícono instalado en: $DEST"
echo "  Apunta a: $DIR/geram.sh"
echo "  Búscalo como 'GERAM' en tu menú de aplicaciones."
