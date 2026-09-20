#!/usr/bin/env bash
# One command to a running dashboard, from a clean clone.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "→ creating virtualenv"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

MODE="${PRAHARI_SOURCE_MODE:-auto}"
PORT="${PRAHARI_PORT:-8000}"
echo "→ Prahari starting on http://localhost:${PORT}  (source mode: ${MODE})"
PRAHARI_SOURCE_MODE="$MODE" .venv/bin/python -m uvicorn backend.main:app \
  --host 0.0.0.0 --port "$PORT"
