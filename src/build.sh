#!/bin/bash
# Builds DM41L Explorer.app via PyInstaller. Run from src/ (or just
# ./build.sh from anywhere, it cd's there itself), with the project's venv
# active and its build requirements installed:
#
#   python3 -m venv dm41-venv
#   source dm41-venv/bin/activate
#   pip install -r requirements-dev.txt
#   (On Ubuntu) sudo apt install python3-tk
#   cd src
#   ./build.sh
#
# Output lands in src/dist/DM41L Explorer.app (macOS) or
# src/dist/dm41lexplorer/ (Linux/Windows).

set -e
cd "$(dirname "$0")"

rm -rf build dist

echo "_version = '$(git describe --tags --always)'" >dm41lversion.py
pyinstaller dm41l.spec

# macOS requires at least an ad-hoc signature for the app to launch at all
# on Apple Silicon -- this is separate from (and needed even without) a
# real Apple Developer ID; see docs/release_checklist.md. No-op elsewhere.
if [ "$(uname)" = "Darwin" ]; then
    codesign --force --deep --sign - "dist/DM41L Explorer.app"
fi
