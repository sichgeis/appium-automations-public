#!/bin/sh
set -eu
cd "$(dirname "$0")/../modules/household-consumption"
exec npm run dev
