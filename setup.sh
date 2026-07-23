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

echo "==> [1/6] Backend de IRIS (:8010) — venv + dependencias"
"$PY" -m venv venv
./venv/bin/python -m pip install --upgrade pip >/dev/null
./venv/bin/python -m pip install -r requirements.txt

echo "==> [2/6] Backend de GERAM CORE OS (:8000) — venv + dependencias"
"$PY" -m venv geram-core-os/venv
./geram-core-os/venv/bin/python -m pip install --upgrade pip >/dev/null
./geram-core-os/venv/bin/python -m pip install -r geram-core-os/requirements.txt

echo "==> [3/6] Ventana Electron (Monaco se prepara solo en el postinstall)"
if command -v npm >/dev/null 2>&1; then
  ( cd geram-core-os/electron && npm install --no-audit --no-fund )
else
  echo "    npm no está instalado — salto Electron. Igual puedes usar CORE OS en el navegador."
fi

echo "==> [4/6] Configuración"
if [ -f .env ]; then
  echo "    .env ya existe — lo dejo como está."
else
  cp .env.example .env
  echo "    creado .env desde la plantilla (todas las claves son opcionales)."
fi

# ------------------------------------------------------------
# [5/6] Paquetes del sistema. No son de Python, así que pip no los puede
# instalar: hacen falta binarios del sistema operativo.
#   pdftotext (poppler-utils) -> leer PDFs adjuntos en el chat
#   bwrap     (bubblewrap)    -> sandbox del runner de código y la terminal
# Sin ellos la app arranca igual; sólo esas dos features quedan apagadas.
# Nunca ejecutamos sudo por tu cuenta sin preguntar.
# ------------------------------------------------------------
echo "==> [5/6] Paquetes del sistema (PDFs y sandbox)"
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

# ------------------------------------------------------------
# [6/6] Ollama: chat local sin API key. Con Ollama instalado, el asistente
# responde 100% local, gratis y sin internet (modelo chico llama3.2:1b por
# defecto; el código ya cae solo a Ollama —ver agents/offline_agent.py—).
# Es OPCIONAL: si pones tus API keys (Gemini/Groq) no hace falta. 'ollama pull'
# siempre trae la última versión del modelo, así que también sirve para
# actualizarlo. Nunca instalamos ni bajamos nada sin preguntarte.
# ------------------------------------------------------------
echo "==> [6/6] Ollama (chat local, sin API key — opcional)"

# El modelo lo tomamos del .env; si no está, usamos el chico por defecto.
MODELO_OLLAMA="$(grep -E '^OLLAMA_MODEL=' .env 2>/dev/null | head -1 | cut -d= -f2)"
[ -z "$MODELO_OLLAMA" ] && MODELO_OLLAMA="llama3.2:1b"
OLLAMA_INSTALL="curl -fsSL https://ollama.com/install.sh | sh"

if command -v ollama >/dev/null 2>&1; then
  echo "    ✓ Ollama ya está instalado ($(ollama --version 2>/dev/null | head -1))."
  if [ -t 0 ]; then
    printf "    ¿Actualizo Ollama a la última versión? [s/N] "
    read -r RESPUESTA || true
    case "$RESPUESTA" in
      [sSyY]*)
        if command -v brew >/dev/null 2>&1 && brew list ollama >/dev/null 2>&1; then
          brew upgrade ollama || echo "    No se pudo actualizar; hazlo a mano."
        else
          sh -c "$OLLAMA_INSTALL" || echo "    No se pudo actualizar; hazlo a mano: $OLLAMA_INSTALL"
        fi ;;
      *) echo "    Ok, lo dejo como está." ;;
    esac
  fi
else
  echo "    Ollama no está instalado. Sin él, para chatear necesitas una API key"
  echo "    (Gemini/Groq gratis). Con él, el asistente responde local y sin internet."
  if [ -t 0 ]; then
    printf "    ¿Instalo Ollama ahora? [s/N] "
    read -r RESPUESTA || true
    case "$RESPUESTA" in
      [sSyY]*)
        sh -c "$OLLAMA_INSTALL" \
          || echo "    No se pudo instalar. Hazlo a mano desde https://ollama.com/download" ;;
      *) echo "    Saltado. Para instalarlo luego: $OLLAMA_INSTALL  (o https://ollama.com/download)" ;;
    esac
  else
    echo "    Para instalarlo: $OLLAMA_INSTALL  (o https://ollama.com/download)"
  fi
fi

# Con Ollama disponible, bajamos/actualizamos el modelo (pull = última versión).
if command -v ollama >/dev/null 2>&1; then
  if [ -t 0 ]; then
    printf "    ¿Bajo/actualizo el modelo '%s' (~1.3 GB)? [s/N] " "$MODELO_OLLAMA"
    read -r RESPUESTA || true
    case "$RESPUESTA" in
      [sSyY]*)
        ollama pull "$MODELO_OLLAMA" \
          || echo "    No se pudo bajar el modelo. Luego: ollama pull $MODELO_OLLAMA" ;;
      *) echo "    Saltado. Para bajarlo luego: ollama pull $MODELO_OLLAMA" ;;
    esac
  else
    echo "    Para bajar el modelo: ollama pull $MODELO_OLLAMA"
  fi
fi

echo
echo "✓ Listo. Siguientes pasos:"
echo "  1) (opcional) edita .env con tus claves/integraciones."
echo "  2) ./geram.sh                    # arranca todo (IRIS + A.R.E.S. en Electron)"
echo "  3) ./scripts/install-desktop.sh  # (opcional) crea el ícono 'GERAM' en tu menú"
