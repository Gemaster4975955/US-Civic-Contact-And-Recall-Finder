#!/usr/bin/env bash
# Create macOS .pkg locally (requires macOS and pkgbuild)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PAYLOAD_DIR="$ROOT/publish/macos-payload"
OUT_DIR="$ROOT/publish/macos"
rm -rf "$PAYLOAD_DIR" "$OUT_DIR" || true
mkdir -p "$PAYLOAD_DIR/Applications/USCivicContactFinder"

# Build launcher
pushd "$ROOT" > /dev/null
dotnet publish CivicContactFinderLauncher/CivicContactFinderLauncher.csproj -c Release -r osx-x64 --self-contained true /p:PublishSingleFile=true /p:PublishTrimmed=false -o out/launcher
cp out/launcher/CivicContactFinderLauncher "$PAYLOAD_DIR/Applications/USCivicContactFinder/"
cp -r civic_contact_finder "$PAYLOAD_DIR/Applications/USCivicContactFinder/"

# Bundle python
/usr/bin/python3 -m venv "$PAYLOAD_DIR/Applications/USCivicContactFinder/python"
source "$PAYLOAD_DIR/Applications/USCivicContactFinder/python/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "$PAYLOAD_DIR/Applications/USCivicContactFinder/civic_contact_finder/requirements.txt"
deactivate

mkdir -p "$OUT_DIR"
pkgbuild --root "$PAYLOAD_DIR/Applications/USCivicContactFinder" --identifier org.uscivicfinder --version 1.0 --install-location /Applications "$OUT_DIR/USCivicContactFinder.pkg" || true
popd > /dev/null

echo "Created $OUT_DIR/USCivicContactFinder.pkg"