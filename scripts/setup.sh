#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077
PYTHON_BIN="${PYTHON_BIN:-python3.13}"
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --requirement requirements.lock
npm ci --cache "$PWD/.npm-cache"
printf '%s\n' 'Installation fertig. Diagnose: .venv/bin/python -m receiptbot doctor'
