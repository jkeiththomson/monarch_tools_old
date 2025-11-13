#!/usr/bin/env bash
set -euo pipefail
echo "Python:" "$(python -V)"
echo "VENV:" "${VIRTUAL_ENV:-<none>}"
echo "which python:" "$(which python)"
echo "which monarch-tools:" "$(command -v monarch-tools || true)"
echo "hash -r to clear zsh cache if the path above does not point into your .venv/bin"
python - <<'PY'
import sys, importlib.util, shutil
print("sys.executable:", sys.executable)
print("sys.path[0]:", sys.path[0])
spec = importlib.util.find_spec("monarch_tools")
print("monarch_tools found at:", None if spec is None else spec.origin)
print("venv monarch-tools script:", shutil.which("monarch-tools"))
PY
