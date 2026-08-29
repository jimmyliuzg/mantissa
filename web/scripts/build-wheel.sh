#!/usr/bin/env bash
# Build the mantissa wheel for the Pyodide engine and copy it into
# web/public/vendor/. CI calls this before `vite build`.
set -euo pipefail
cd "$(dirname "$0")/../.."

VERSION=$(python -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project'].get('version','0.2.0'))")
PKG_NAME=$(python -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['name'])")

echo "==> building $PKG_NAME-$VERSION wheel"
mkdir -p /tmp/mantissa-wheel
python -m build --wheel --outdir /tmp/mantissa-wheel 2>&1 | tail -n 5

mkdir -p web/public/vendor
WHEEL_FILE=$(ls /tmp/mantissa-wheel/${PKG_NAME}-${VERSION}-*.whl | head -n 1)
if [ -z "$WHEEL_FILE" ]; then
  echo "wheel not found" >&2
  exit 1
fi
cp "$WHEEL_FILE" "web/public/vendor/${PKG_NAME}-${VERSION}-py3-none-any.whl"
ls -la web/public/vendor/
