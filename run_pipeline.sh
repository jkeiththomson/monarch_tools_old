#!/usr/bin/env bash
set -euo pipefail

# --- Paths (edit if your statement lives elsewhere) ---
PDF="statements/chase/9391/2018/20180112-statements-9391.pdf"
OUT_DIR="out"

CATEGORIES="data/categories.txt"
GROUPS="data/groups.txt"
RULES="data/rules.json"

# --- Ensure we're running from the repo root ---
if [[ ! -f "pyproject.toml" ]]; then
  echo "ERROR: run this from the monarch-tools repo root (where pyproject.toml lives)."
  exit 2
fi

# --- Sanity checks ---
if [[ ! -f "$PDF" ]]; then
  echo "ERROR: PDF not found: $PDF"
  exit 3
fi

mkdir -p "$OUT_DIR"

echo "==> 1) Clean baseline data/*"
python -m monarch_tools clean

echo "==> 2) Extract transactions from PDF -> out/"
python -m monarch_tools extract --pdf "$PDF" --out "$OUT_DIR"

# The extractor writes: out/<pdf_stem>.monarch.csv
PDF_STEM="$(basename "$PDF")"
PDF_STEM="${PDF_STEM%.*}"
MONARCH_CSV="$OUT_DIR/$PDF_STEM.monarch.csv"

if [[ ! -f "$MONARCH_CSV" ]]; then
  echo "ERROR: expected output CSV not found: $MONARCH_CSV"
  echo "Check extract output above."
  exit 4
fi

echo "==> 3) Categorize (TUI) -> writes back to the same CSV by default"
python -m monarch_tools categorize \
  --in "$MONARCH_CSV" \
  --rules "$RULES" \
  --categories "$CATEGORIES" \
  --groups "$GROUPS"

echo "==> DONE"
echo "Categorized CSV: $MONARCH_CSV"
echo "Rules file:      $RULES"