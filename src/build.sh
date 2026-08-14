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
else
    # The Linux/Windows build is a PyInstaller "onedir" bundle: the
    # executable needs its _internal/ support-files folder alongside it
    # to run. Drop a short README into that output directory so anyone
    # who unzips a release and sees an unfamiliar _internal folder next
    # to the exe knows it's required, not clutter. Not needed for macOS
    # -- the .app bundle is already a single self-contained unit.
    cp "../resources/dist_readme.txt" "dist/dm41lexplorer/README.txt"

    # Linux has no equivalent of a Windows .exe's baked-in icon (PyInstaller
    # doesn't support one there), so bundle MyIcon.png alongside the binary
    # -- ready to use as a .desktop file's Icon= entry. `uname` reports
    # "Linux" both natively and under WSL; on a Windows Git Bash shell it
    # reports something like "MINGW64_NT-...", so this correctly only fires
    # for actual Linux builds.
    if [ "$(uname)" = "Linux" ]; then
        cp "../resources/MyIcon.png" "dist/dm41lexplorer/MyIcon.png"
    fi
fi
