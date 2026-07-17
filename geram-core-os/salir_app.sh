#!/bin/sh
# Close only the Electron process whose exact executable, cwd, argv and start
# time are validated by desktop_launcher.py. The waiting launcher then performs
# owned-backend cleanup through launcher.py.
set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN="$DIR/venv/bin/python"

if [ ! -x "$PYTHON_BIN" ] || [ ! -f "$DIR/desktop_launcher.py" ]; then
  echo "ERROR: the desktop launcher or GERAM CORE OS virtual environment is missing." >&2
  exit 1
fi

exec "$PYTHON_BIN" "$DIR/desktop_launcher.py" --stop "$@"
