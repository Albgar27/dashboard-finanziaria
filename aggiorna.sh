#!/bin/zsh
# Aggiorna la dashboard e, se il repository GitHub è configurato, la pubblica su GitHub Pages.
# Uso: ./aggiorna.sh            aggiornamento completo
#      ./aggiorna.sh --solo-notizie
# La pagina pubblicata sta nel ramo gh-pages, ridotto sempre a un solo commit (la cronologia non cresce).
set -u
ROOT="${0:A:h}"
cd "$ROOT" || exit 1

.venv/bin/python build_dashboard.py "$@" || exit $?

git remote get-url origin >/dev/null 2>&1 || exit 0   # nessun repository remoto: solo uso locale

PUB="$ROOT/.publish"
if [[ ! -d "$PUB/.git" ]]; then
  mkdir -p "$PUB"
  git -C "$PUB" init -q -b gh-pages
  git -C "$PUB" remote add origin "$(git remote get-url origin)"
  git -C "$PUB" config user.name "$(git config user.name)"
  git -C "$PUB" config user.email "$(git config user.email)"
fi
rsync -a --delete --exclude .git --exclude '*.pdf' --exclude '*.tmp' "$ROOT/docs/" "$PUB/"
git -C "$PUB" add -A
if git -C "$PUB" rev-parse -q --verify HEAD >/dev/null; then
  git -C "$PUB" diff --cached --quiet && exit 0
  git -C "$PUB" commit -q --amend -m "Pubblicazione $(date '+%Y-%m-%d %H:%M')"
else
  git -C "$PUB" commit -q -m "Pubblicazione $(date '+%Y-%m-%d %H:%M')"
fi
if git -C "$PUB" push -q -f origin gh-pages 2>>"$ROOT/build.log"; then
  echo "Pubblicato su GitHub Pages ($(date '+%H:%M'))."
else
  echo "ERRORE: pubblicazione su GitHub non riuscita (vedi build.log)." >&2
fi
