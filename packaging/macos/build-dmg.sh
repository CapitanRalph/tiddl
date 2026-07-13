#!/bin/sh
set -eu

run_python() {
  if command -v uv >/dev/null 2>&1; then
    uv run python "$@"
  elif command -v python3 >/dev/null 2>&1; then
    python3 "$@"
  else
    python "$@"
  fi
}

VERSION="$(run_python - <<'PY'
import tomllib
with open("pyproject.toml", "rb") as file:
    print(tomllib.load(file)["project"]["version"])
PY
)"

APP_NAME="Tiddl DDJ"
APP_PATH="dist/${APP_NAME}.app"
BUILD_ARCH="${TIDDL_BUILD_ARCH:-$(uname -m)}"

case "$BUILD_ARCH" in
  arm64|aarch64)
    DMG_ARCH="arm64"
    ;;
  x86_64|amd64|x64)
    DMG_ARCH="x64"
    ;;
  *)
    echo "Arquitectura macOS no soportada: ${BUILD_ARCH}" >&2
    exit 1
    ;;
esac

DMG_PATH="dist/Tiddl-DDJ-v${VERSION}-macOS-${DMG_ARCH}.dmg"
VOLUME_NAME="Tiddl DDJ ${VERSION}"
ICON_PATH="build/installer-icons/tiddl-ddj.icns"

if [ ! -f "$ICON_PATH" ]; then
  run_python packaging/icons/build-icons.py
fi

if [ ! -d "$APP_PATH" ]; then
  echo "No existe ${APP_PATH}. Ejecuta primero:"
  echo "uv run pyinstaller packaging/pyinstaller/tiddl-desktop.spec --clean --noconfirm"
  exit 1
fi

rm -f "$DMG_PATH"
DMG_ROOT="$(mktemp -d)"
trap 'rm -rf "$DMG_ROOT"' EXIT

cp -R "$APP_PATH" "$DMG_ROOT/"
ln -s /Applications "$DMG_ROOT/Applications"

hdiutil create \
  -volname "$VOLUME_NAME" \
  -srcfolder "$DMG_ROOT" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo "DMG creado: $DMG_PATH"
