#!/bin/zsh
# Doppio clic dal Finder: avvia Analisi PMI e apre il browser.
# La finestra del Terminale deve restare aperta: chiudendola si ferma il server.
cd "$(dirname "$0")" || exit 1
if [ -x ../.venv/bin/python3 ]; then PY=../.venv/bin/python3; else PY=python3; fi
echo "Avvio Analisi PMI con $($PY --version 2>&1)…"
"$PY" server.py
echo
echo "Il server si è fermato (se c'è un errore qui sopra, copialo e mandalo)."
read -k1 "?Premi un tasto per chiudere."
