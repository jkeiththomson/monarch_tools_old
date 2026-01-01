#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   apply_monarch_patch.sh <zip-name-or-fragment>
#
# Examples:
#   apply_monarch_patch.sh monarch-tools-taxonomy-ui-fixes-v1.zip
#   apply_monarch_patch.sh taxonomy-ui-fixes
#
# Behavior:
#   - Looks in ~/Downloads for matching .zip files
#   - Picks the most recently modified match
#   - Unzips into a unique folder in Downloads
#   - Copies src/ and/or data/ into your local monarch-tools repo
#   - Overwrites existing files
#   - Performs safety checks before copying

QUERY="${1:-}"

DOWNLOADS="$HOME/Downloads"
PROJECT_ROOT="$HOME/dev/mon/monarch-tools"

if [[ -z "$QUERY" ]]; then
  echo "Usage: $0 <zip-name-or-fragment>"
  exit 1
fi

# ---- Safety checks: destination repo ----

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "ERROR: Project root not found:"
  echo "  $PROJECT_ROOT"
  exit 2
fi

if [[ ! -f "$PROJECT_ROOT/pyproject.toml" ]]; then
  echo "ERROR: Safety check failed:"
  echo "  pyproject.toml not found in $PROJECT_ROOT"
  exit 3
fi

if [[ ! -d "$PROJECT_ROOT/src/monarch_tools" ]]; then
  echo "ERROR: Safety check failed:"
  echo "  src/monarch_tools not found in $PROJECT_ROOT"
  exit 4
fi

if ! grep -Eq 'name\s*=\s*"(monarch-tools|monarch_tools)"' \
     "$PROJECT_ROOT/pyproject.toml"; then
  echo "ERROR: Safety check failed:"
  echo "  pyproject.toml does not look like monarch-tools"
  exit 5
fi

# ---- Find matching ZIP in Downloads ----

cd "$DOWNLOADS"

ZIP_MATCHES=()

# Exact match if .zip provided
if [[ "$QUERY" == *.zip && -f "$QUERY" ]]; then
  ZIP_MATCHES+=("$QUERY")
fi

# Partial match (newest first)
while IFS= read -r z; do
  ZIP_MATCHES+=("$z")
done < <(ls -t *.zip 2>/dev/null | grep -F "$QUERY" || true)

if [[ "${#ZIP_MATCHES[@]}" -eq 0 ]]; then
  echo "ERROR: No matching .zip found in $DOWNLOADS for:"
  echo "  $QUERY"
  echo
  echo "Recent downloads:"
  ls -t *.zip 2>/dev/null | head
  exit 6
fi

ZIP_NAME="${ZIP_MATCHES[0]}"
ZIP_PATH="$DOWNLOADS/$ZIP_NAME"

echo "==> Using patch ZIP:"
echo "    $ZIP_NAME"

# ---- Unzip into unique patch directory ----

STAMP="$(date +%Y%m%d_%H%M%S)"
PATCH_DIR="$DOWNLOADS/_patch_${ZIP_NAME%.zip}_$STAMP"

mkdir -p "$PATCH_DIR"

echo "==> Unzipping into:"
echo "    $PATCH_DIR"

unzip -o "$ZIP_PATH" -d "$PATCH_DIR" >/dev/null

# ---- Copy patched files ----

echo "==> Applying patch to:"
echo "    $PROJECT_ROOT"

COPIED=0

for dir in src data; do
  if [[ -d "$PATCH_DIR/$dir" ]]; then
    echo "  - copying $dir/"
    mkdir -p "$PROJECT_ROOT/$dir"
    cp -Rfv "$PATCH_DIR/$dir/" "$PROJECT_ROOT/$dir/"
    COPIED=1
  fi
done

if [[ "$COPIED" -eq 0 ]]; then
  echo "ERROR: Patch ZIP did not contain src/ or data/"
  echo "Patch contents:"
  ls -la "$PATCH_DIR"
  exit 7
fi

echo "==> Patch applied successfully"
echo
echo "Patch unpacked at:"
echo "  $PATCH_DIR"
echo
echo "You may delete it when satisfied:"
echo "  rm -rf \"$PATCH_DIR\""