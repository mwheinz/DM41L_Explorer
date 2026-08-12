#!/bin/bash
# Builds DM41 Explorer.app via PyInstaller. Run from src/ (or just
# ./build.sh from anywhere, it cd's there itself), with the project's venv
# active and its build requirements installed:
#
#   python3 -m venv dm41-venv
#   source dm41-venv/bin/activate
#   pip install -r requirements.txt
#   (On Ubuntu) sudo apt install python3-tk
#   cd src
#   ./build.sh
#
# Output lands in src/dist/DM41 Explorer.app.

set -e
cd "$(dirname "$0")"

rm -rf build dist

echo "_version = '$(git describe --tags --always)'" >dm41lversion.py
pyinstaller dm41l.spec
