#!/usr/bin/env bash
# One step: store the card, create a fresh reveal session, and open Chromium with it.
# Supply CARD_PAN/CARD_CVC/CARD_EXP, or enter the details at the terminal prompts.
#
# Usage: ./start.sh [allowed-hosts] [url]
#   allowed-hosts  comma-separated; optional (default ALLOWED_HOSTS from .env, else none).
#                  Pass "" to skip it and still give a url.
#   url            page to open; default https://<first allowed host>/, or about:blank
#
# Examples:
#   ./start.sh www.example-shop.com
#   ./start.sh www.example-shop.com,payments.example.com https://www.example-shop.com/
set -euo pipefail
cd "$(dirname "$0")"

HOSTS_ARGS=()
[ -n "${1:-}" ] && HOSTS_ARGS=(--hosts "$1")

OUT=$(bash ./create-fresh-session.sh "${HOSTS_ARGS[@]+"${HOSTS_ARGS[@]}"}")
echo "$OUT"
FILE=$(printf '%s\n' "$OUT" | sed -n 's/^SESSION_FILE=//p')
echo
bash ./launch-chromium.sh "$FILE" ${2:+"$2"}
