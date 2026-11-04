#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077
# Nur für diesen Prozess; bestehende explizite Auswahl respektieren.
if [ -z "${DEVELOPER_DIR:-}" ] && [ -d /Applications/Xcode.app/Contents/Developer ]; then
    export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi
export APPIUM_HOME="$PWD"
exec ./node_modules/.bin/appium "$@"
