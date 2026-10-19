#!/usr/bin/env bash
# Create a portable venv for distribution inside a target directory
set -euo pipefail
if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <target-dir> <python-executable>"
  exit 2
fi
TARGET_DIR="$1"
PYTHON="$2"

mkdir -p "$TARGET_DIR"
"$PYTHON" -m venv "$TARGET_DIR/python"
source "$TARGET_DIR/python/bin/activate"
python -m pip install --upgrade pip
if [ -f "civic_contact_finder/requirements.txt" ]; then
  python -m pip install -r civic_contact_finder/requirements.txt
fi
python -m pip cache purge || true
 deactivate

echo "Portable Python created at $TARGET_DIR/python"