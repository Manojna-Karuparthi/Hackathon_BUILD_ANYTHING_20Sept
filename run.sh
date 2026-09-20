#!/usr/bin/env bash
# One command to a running dashboard, from a clean clone.
#
# Works on Linux, macOS, and Windows Git Bash / WSL. Windows Git Bash usually
# only has `python`, not `python3`, and a venv created by a native Windows
# Python puts its executables in `.venv/Scripts/` instead of `.venv/bin/` -
# both are handled below rather than assumed away.
set -euo pipefail
cd "$(dirname "$0")"

# --- find a usable Python interpreter --------------------------------------
PYTHON=""
for candidate in python3 python "py -3" py; do
  if command -v "${candidate%% *}" >/dev/null 2>&1; then
    if $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo "✗ No Python 3.10+ found on PATH."
  echo "  Install it from https://python.org/downloads (check 'Add to PATH' on Windows)"
  echo "  then re-run ./run.sh."
  exit 1
fi

# --- create the venv if it doesn't exist yet -------------------------------
if [ ! -d .venv ]; then
  echo "→ creating virtualenv with '$PYTHON'"
  $PYTHON -m venv .venv
fi

# --- locate the venv's own python/pip, whichever layout this OS used -------
# POSIX venvs (Linux/macOS/WSL) use .venv/bin/; a venv made by native Windows
# Python (even from Git Bash) uses .venv/Scripts/.
if [ -x ".venv/bin/python" ]; then
  VPY=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
  VPY=".venv/Scripts/python.exe"
elif [ -x ".venv/Scripts/python" ]; then
  VPY=".venv/Scripts/python"
else
  echo "✗ Could not find a python executable inside .venv/ (looked in bin/ and Scripts/)."
  echo "  Delete the .venv folder and re-run ./run.sh."
  exit 1
fi

# --- install dependencies once ----------------------------------------------
if [ ! -f .venv/.deps-installed ]; then
  echo "→ installing dependencies"
  "$VPY" -m pip install -q --upgrade pip
  "$VPY" -m pip install -q -r requirements.txt
  touch .venv/.deps-installed
fi

MODE="${PRAHARI_SOURCE_MODE:-auto}"
PORT="${PRAHARI_PORT:-8000}"
echo "→ Prahari starting on http://localhost:${PORT}  (source mode: ${MODE})"
echo "  Press Ctrl+C to stop."
PRAHARI_SOURCE_MODE="$MODE" "$VPY" -m uvicorn backend.main:app \
  --host 0.0.0.0 --port "$PORT"
