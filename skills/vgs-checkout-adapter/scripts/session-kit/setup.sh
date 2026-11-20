#!/usr/bin/env bash
# One-time setup: check tools, create .env, download Chrome for Testing into ./browsers.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
need curl jq openssl unzip
chmod +x "$KIT_DIR"/*.sh

if [ ! -f "$KIT_DIR/.env" ]; then
  ( umask 077; cp "$KIT_DIR/.env.example" "$KIT_DIR/.env" )
  echo "Created .env from .env.example. Fill in VGS_CLIENT_ID, VGS_CLIENT_SECRET and VGS_TENANT."
else
  chmod 600 "$KIT_DIR/.env"
fi

if [ -d "$KIT_DIR/browsers" ] && find -L "$KIT_DIR/browsers" -type f \( -path '*Contents/MacOS/Google Chrome for Testing' -o -name chrome \) -perm -u+x 2>/dev/null | grep -q .; then
  echo "Chromium already installed in $KIT_DIR/browsers"
  exit 0
fi

case "$(uname -s)/$(uname -m)" in
  Darwin/arm64)  PLATFORM=mac-arm64 ;;
  Darwin/x86_64) PLATFORM=mac-x64 ;;
  Linux/x86_64)  PLATFORM=linux64 ;;
  *) die "unsupported platform $(uname -s)/$(uname -m)" ;;
esac

echo "Looking up the current stable Chrome for Testing build for $PLATFORM..."
URL=$(curl -sS https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json \
  | jq -r --arg p "$PLATFORM" '.channels.Stable.downloads.chrome[] | select(.platform == $p) | .url')
[ -n "$URL" ] || die "could not find a download URL"

mkdir -p "$KIT_DIR/browsers"
ZIP="$KIT_DIR/browsers/chrome.zip"
echo "Downloading $URL"
# Resume on dropped connections (large file).
for i in 1 2 3 4 5; do curl -fSL -C - -o "$ZIP" "$URL" && break; echo "retrying ($i)..."; sleep 2; done
unzip -tq "$ZIP" >/dev/null || die "download is corrupt; delete $ZIP and run again"

if command -v ditto >/dev/null; then ditto -x -k "$ZIP" "$KIT_DIR/browsers/"; else unzip -q "$ZIP" -d "$KIT_DIR/browsers/"; fi
rm -f "$ZIP"
xattr -dr com.apple.quarantine "$KIT_DIR/browsers" 2>/dev/null || true
echo "Installed Chromium into $KIT_DIR/browsers"
