#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "ERROR: Missing venv at $HERE/.venv"
  echo "Run: python -m venv .venv && source .venv/bin/activate && python -m pip install -e ."
  exit 1
fi
exec "$PY" -m monarch_tools "$@"
