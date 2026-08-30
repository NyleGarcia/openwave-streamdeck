#!/bin/sh
# Build the release archive OpenDeck installs from.
#
# The zip contains the dev.openwave.sdPlugin directory at its root, which is
# what OpenDeck's installer expects: it extracts straight into the plugins
# directory, so a zip of the directory's *contents* silently installs a broken
# plugin with no manifest where one is expected.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(python3 -c "import json;print(json.load(open('$ROOT/dev.openwave.sdPlugin/manifest.json'))['Version'])")
OUT="$ROOT/dist/openwave-streamdeck-$VERSION.zip"

rm -rf "$ROOT/dist"
mkdir -p "$ROOT/dist"
cd "$ROOT"
# __pycache__ is excluded deliberately: bytecode compiled by one Python is
# loaded in preference to source by another, and the plugin runs against
# whatever python3 the host has.
zip -qr "$OUT" dev.openwave.sdPlugin \
    -x '*/__pycache__/*' '*.pyc' '*/plugin.log'
echo "$OUT"
