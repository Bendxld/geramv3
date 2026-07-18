#!/bin/bash
# ============================================================
# GERAM · setup.sh  (Linux / macOS)
# Deja todo listo en un comando: crea los venvs, instala dependencias de
# ambas apps, instala Electron, y crea .env desde la plantilla.
#
#   ./setup.sh
#
# Idempotente: puedes correrlo de nuevo sin problema. Windows: usa setup.ps1.
# ============================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "ERROR: no encuentro python3. Instálalo (Python 3.11+) y reintenta." >&2
  exit 1
fi
echo "==> Python: $($PY --version 2>&1)"

echo "==> [1/4] Backend de IRIS (:8010) — venv + dependencias"
"$PY" -m venv venv
./venv/bin/python -m pip install --upgrade pip >/dev/null
./venv/bin/python -m pip install -r requirements.txt

echo "==> [2/4] Backend de GERAM CORE OS (:8000) — venv + dependencias"
"$PY" -m venv geram-core-os/venv
./geram-core-os/venv/bin/python -m pip install --upgrade pip >/dev/null
./geram-core-os/venv/bin/python -m pip install -r geram-core-os/requirements.txt

echo "==> [3/4] Ventana Electron (Monaco se prepara solo en el postinstall)"
if command -v npm >/dev/null 2>&1; then
  ( cd geram-core-os/electron && npm install --no-audit --no-fund )
else
  echo "    npm no está instalado — salto Electron. Igual puedes usar CORE OS en el navegador."
fi

echo "==> [4/4] Configuración"
if [ -f .env ]; then
  echo "    .env ya existe — lo dejo como está."
else
  cp .env.example .env
  echo "    creado .env desde la plantilla (todas las claves son opcionales)."
fi

echo
echo "✓ Listo. Siguientes pasos:"
echo "  1) (opcional) edita .env con tus claves/integraciones."
echo "  2) ./geram.sh                    # arranca todo (IRIS + A.R.E.S. en Electron)"
echo "  3) ./scripts/install-desktop.sh  # (opcional) crea el ícono 'GERAM' en tu menú"
