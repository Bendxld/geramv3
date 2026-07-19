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

echo "==> [1/5] Backend de IRIS (:8010) — venv + dependencias"
"$PY" -m venv venv
./venv/bin/python -m pip install --upgrade pip >/dev/null
./venv/bin/python -m pip install -r requirements.txt

echo "==> [2/5] Backend de GERAM CORE OS (:8000) — venv + dependencias"
"$PY" -m venv geram-core-os/venv
./geram-core-os/venv/bin/python -m pip install --upgrade pip >/dev/null
./geram-core-os/venv/bin/python -m pip install -r geram-core-os/requirements.txt

echo "==> [3/5] Ventana Electron (Monaco se prepara solo en el postinstall)"
if command -v npm >/dev/null 2>&1; then
  ( cd geram-core-os/electron && npm install --no-audit --no-fund )
else
  echo "    npm no está instalado — salto Electron. Igual puedes usar CORE OS en el navegador."
fi

echo "==> [4/5] Configuración"
if [ -f .env ]; then
  echo "    .env ya existe — lo dejo como está."
else
  cp .env.example .env
  echo "    creado .env desde la plantilla (todas las claves son opcionales)."
fi

# ------------------------------------------------------------
# [5/5] Paquetes del sistema. No son de Python, así que pip no los puede
# instalar: hacen falta binarios del sistema operativo.
#   pdftotext (poppler-utils) -> leer PDFs adjuntos en el chat
#   bwrap     (bubblewrap)    -> sandbox del runner de código y la terminal
# Sin ellos la app arranca igual; sólo esas dos features quedan apagadas.
# Nunca ejecutamos sudo por tu cuenta sin preguntar.
# ------------------------------------------------------------
echo "==> [5/5] Paquetes del sistema (PDFs y sandbox)"
FALTAN=""
command -v pdftotext >/dev/null 2>&1 || FALTAN="$FALTAN poppler-utils"
if [ "$(uname -s)" = "Linux" ]; then
  command -v bwrap >/dev/null 2>&1 || FALTAN="$FALTAN bubblewrap"
fi

if [ -z "$FALTAN" ]; then
  echo "    ✓ pdftotext y bwrap ya están instalados."
else
  # Cada gestor nombra los paquetes distinto; traducimos según el que haya.
  INSTALAR=""
  if command -v apt-get >/dev/null 2>&1; then
    INSTALAR="sudo apt-get install -y$FALTAN"
  elif command -v dnf >/dev/null 2>&1; then
    INSTALAR="sudo dnf install -y$(echo "$FALTAN" | sed 's/poppler-utils/poppler-utils/; s/bubblewrap/bubblewrap/')"
  elif command -v pacman >/dev/null 2>&1; then
    INSTALAR="sudo pacman -S --needed$(echo "$FALTAN" | sed 's/poppler-utils/poppler/')"
  elif command -v zypper >/dev/null 2>&1; then
    INSTALAR="sudo zypper install -y$(echo "$FALTAN" | sed 's/poppler-utils/poppler-tools/')"
  elif command -v brew >/dev/null 2>&1; then
    # bubblewrap no existe en macOS; sólo poppler aplica.
    INSTALAR="brew install poppler"
  fi

  echo "    Faltan:$FALTAN"
  if [ -z "$INSTALAR" ]; then
    echo "    No reconozco tu gestor de paquetes. Instala a mano:$FALTAN"
  elif [ -t 0 ]; then
    printf "    ¿Los instalo ahora con '%s'? [s/N] " "$INSTALAR"
    # '|| true' porque con set -e un EOF en read abortaría todo el setup.
    read -r RESPUESTA || true
    case "$RESPUESTA" in
      [sSyY]*)
        # Si falla (sin sudo, sin red), lo decimos y seguimos: no es fatal.
        $INSTALAR || echo "    No se pudieron instalar. Hazlo a mano: $INSTALAR"
        ;;
      *) echo "    Saltado. Para hacerlo luego: $INSTALAR" ;;
    esac
  else
    echo "    Para instalarlos: $INSTALAR"
  fi
fi

echo
echo "✓ Listo. Siguientes pasos:"
echo "  1) (opcional) edita .env con tus claves/integraciones."
echo "  2) ./geram.sh                    # arranca todo (IRIS + A.R.E.S. en Electron)"
echo "  3) ./scripts/install-desktop.sh  # (opcional) crea el ícono 'GERAM' en tu menú"
