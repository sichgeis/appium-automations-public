#!/bin/sh
# Einmaliger kleiner Gerätetest. Keine Hintergrundinstallation, kein Dauerwatcher.
set -eu
cd "$(dirname "$0")/.."
umask 077
trap 'printf "%s\n" "Automatische Sperre am iPhone nach dem Lauf wieder auf den bisherigen Wert setzen."' 0
trap 'exit 130' INT
trap 'exit 143' TERM
if [ ! -x .venv/bin/python ]; then
    printf '%s\n' 'Projekt-venv fehlt; zuerst sh scripts/setup.sh ausführen.'
    exit 2
fi
printf '%s\n' 'iPhone per USB verbinden und entsperren. Automatische Sperre für diesen Lauf auf Nie.'
.venv/bin/python -m receiptbot ready --wait 900
# Caffeinate hält nur den Mac für den Kindprozess wach; iPhone-Auto-Lock bleibt separat.
/usr/bin/caffeinate -i .venv/bin/python -m receiptbot export --app kaufland --transport icloud --limit 1
.venv/bin/python -m receiptbot report
printf '%s\n' 'Einzeltest beendet.'
