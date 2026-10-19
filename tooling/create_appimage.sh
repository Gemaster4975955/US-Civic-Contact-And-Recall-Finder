<<<<<<< HEAD
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT/publish/appimage"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64)
    APPIMAGE_ARCH="x86_64"
    ;;
  aarch64|arm64)
    APPIMAGE_ARCH="aarch64"
    ;;
  *)
    echo "Unsupported architecture: $ARCH" >&2
    exit 1
    ;;
esac
APPIMAGE_PATH="$OUT_DIR/CivicContactFinder-linux-$APPIMAGE_ARCH.AppImage"
APPIMAGETOOL_PATH="$ROOT/appimagetool-$APPIMAGE_ARCH.AppImage"
rm -rf AppDir "$OUT_DIR" || true
mkdir -p AppDir/usr/bin AppDir/usr/share/applications "$OUT_DIR"

pushd "$ROOT" > /dev/null
dotnet publish CivicContactFinderLauncher/CivicContactFinderLauncher.csproj -c Release -r linux-x64 --self-contained true /p:PublishSingleFile=true /p:PublishTrimmed=false -o out/launcher
cp out/launcher/CivicContactFinderLauncher AppDir/usr/bin/
cp -r civic_contact_finder AppDir/usr/bin/

python3 -m venv AppDir/usr/bin/python
source AppDir/usr/bin/python/bin/activate
python -m pip install --upgrade pip
python -m pip install -r AppDir/usr/bin/civic_contact_finder/requirements.txt
deactivate

cat > AppDir/AppRun <<'EOF'
#!/bin/bash
set -eu
APPDIR="$(dirname "$(readlink -f "$0")")"
exec "$APPDIR/usr/bin/CivicContactFinderLauncher" "$@"
EOF
chmod +x AppDir/AppRun

printf '%s\n' \
  '[Desktop Entry]' \
  'Name=U.S. Civic Contact Finder' \
  'Exec=AppRun' \
  'Icon=utilities-terminal' \
  'Terminal=false' \
  'Type=Application' \
  'Categories=Utility;Government;' \
  > AppDir/usr/share/applications/civic-contact-finder.desktop

if [ ! -f "$APPIMAGETOOL_PATH" ]; then
  curl -L -o "$APPIMAGETOOL_PATH" "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-$APPIMAGE_ARCH.AppImage"
  chmod +x "$APPIMAGETOOL_PATH"
fi

"$APPIMAGETOOL_PATH" AppDir "$APPIMAGE_PATH"
popd > /dev/null

echo "AppImage created at $APPIMAGE_PATH"
=======
#!/usr/bin/env bash
>>>>>>> 24d8f45f89a1b4d358a1735266de1824f16ed511
