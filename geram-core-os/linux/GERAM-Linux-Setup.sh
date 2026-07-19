#!/bin/sh
set -eu

if ! command -v python3 >/dev/null 2>&1 || ! command -v bwrap >/dev/null 2>&1; then
  echo "Install Python 3, python3-venv, Bubblewrap, poppler-utils, Git, and Node.js with your distribution package manager." >&2
  exit 1
fi

python3 -c 'import venv' >/dev/null
bwrap --version >/dev/null
git --version >/dev/null
node --version >/dev/null
echo "GERAM CORE OS Linux prerequisites are ready."
