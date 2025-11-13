#!/usr/bin/env bash
set -euo pipefail
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -r requirements.txt
pip install -e .
echo "✅ venv ready. Activate with: source .venv/bin/activate"
