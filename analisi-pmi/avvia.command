#!/bin/zsh
# Doppio clic dal Finder: avvia Analisi PMI e apre il browser.
cd "$(dirname "$0")"
if [ -x ../.venv/bin/python3 ]; then PY=../.venv/bin/python3; else PY=python3; fi
exec "$PY" server.py
