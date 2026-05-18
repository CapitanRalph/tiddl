#!/bin/sh
set -eu

VERSION="$(python - <<'PY'
import tomllib
with open("pyproject.toml", "rb") as file:
    print(tomllib.load(file)["project"]["version"])
PY
)"

APP_NAME="Tiddl DDJ"
APP_PATH="dist/${APP_NAME}.app"
DMG_PATH="dist/Tiddl-DDJ-v${VERSION}-macOS-arm64.dmg"
VOLUME_NAME="Tiddl DDJ ${VERSION}"
ICON_PATH="build/installer-icons/tiddl-ddj.icns"

if [ ! -f "$ICON_PATH" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv run python packaging/icons/build-icons.py
  else
    python packaging/icons/build-icons.py
  fi
fi

if [ ! -d "$APP_PATH" ]; then
  echo "No existe ${APP_PATH}. Ejecuta primero:"
  echo "uv run pyinstaller packaging/pyinstaller/tiddl-desktop.spec --clean --noconfirm"
  exit 1
fi

rm -f "$DMG_PATH"
hdiutil create \
  -volname "$VOLUME_NAME" \
  -srcfolder "$APP_PATH" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo "DMG creado: $DMG_PATH"
