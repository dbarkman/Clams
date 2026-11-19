#!/usr/bin/env bash
# Zip the Chrome extension into the site's static folder (served at /static/clams-extension.zip).
set -euo pipefail
cd "$(dirname "$0")/.."
rm -f src/clams/static/clams-extension.zip
(cd extension && zip -qr -X ../src/clams/static/clams-extension.zip . -x '.*')
echo "built src/clams/static/clams-extension.zip"
