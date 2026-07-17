#!/bin/sh
# Desktop lifecycle delegates to desktop_launcher.py, which in turn reuses the
# identity-safe BackendLauncher from launcher.py. No shell matching is used.
set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN="$DIR/venv/bin/python"

if [ ! -x "$PYTHON_BIN" ] || [ ! -f "$DIR/desktop_launcher.py" ]; then
  echo "ERROR: the desktop launcher or GERAM CORE OS virtual environment is missing." >&2
  exit 1
fi

exec "$PYTHON_BIN" "$DIR/desktop_launcher.py" "$@"
