#!/usr/bin/env bash
# Download/verify the official binary outside the skill, then prepare its pinned image.
set -euo pipefail
[ "$#" = 1 ] || { echo "Usage: $0 /absolute/private/runtime-directory" >&2; exit 2; }
case "$1" in /*) ;; *) echo 'Use an absolute runtime directory' >&2; exit 2 ;; esac
umask 077
mkdir -p "$1"
LARKY_BIN="$1/larky-1.0.0-linux"
EXPECTED=9a2d9f179984f2e019132e04e9fdc5d17e21d1f1e9cd12581018519acf7f34b3
if [ ! -f "$LARKY_BIN" ]; then
  PART=$(mktemp "$1/download.XXXXXX")
  trap 'rm -f "$PART"' EXIT
  curl --fail --location --retry 2 'https://github.com/verygoodsecurity/starlarky/releases/download/v1.0.0/larky-1.0.0-linux' -o "$PART"
  python3 - "$PART" "$EXPECTED" <<'PY'
import hashlib, pathlib, sys
if hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest() != sys.argv[2]:
    raise SystemExit('Larky checksum mismatch')
PY
  mv "$PART" "$LARKY_BIN"
fi
python3 - "$LARKY_BIN" "$EXPECTED" <<'PY'
import hashlib, pathlib, sys
if hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest() != sys.argv[2]:
    raise SystemExit('Larky checksum mismatch; stop without changing the pin')
PY
chmod 700 "$LARKY_BIN"
docker pull --platform linux/amd64 debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc
echo 'Native Larky verified and Docker image prepared.'
