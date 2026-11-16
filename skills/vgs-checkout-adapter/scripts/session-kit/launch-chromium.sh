#!/usr/bin/env bash
# Open Chromium (Chrome for Testing, installed by setup.sh) through a reveal session.
#
# Usage: ./launch-chromium.sh [session.json] [url] [--insecure]
#   session.json  default: .state/latest-session.json
#   url           default: https://<first allowed host>/
#   --insecure    ignore ALL certificate errors (fallback if the VGS CA check fails)
#
# - The browser uses the session's PAC file, so every request goes through VGS.
# - A throwaway extension answers the proxy login (a PAC file can't carry credentials).
# - A throwaway profile is used; your normal Chrome is untouched.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
need jq openssl

ARGS=(); INSECURE=0
for a in "$@"; do [ "$a" = "--insecure" ] && INSECURE=1 || ARGS+=("$a"); done
SESSION="${ARGS[0]:-$STATE_DIR/latest-session.json}"
[ -f "$SESSION" ] || die "no session file at $SESSION; run ./create-session.sh first"

BIN=$(find -L "$KIT_DIR/browsers" -type f \( -path '*Contents/MacOS/Google Chrome for Testing' -o -name chrome \) -perm -u+x 2>/dev/null | head -1 || true)
[ -n "$BIN" ] || die "Chromium not found; run ./setup.sh"

A='.data.attributes'
EXPIRES=$(jq -r "$A.expires_at" "$SESSION")
[ "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \< "$EXPIRES" ] || die "session expired at $EXPIRES; create a new one"

FIRST_HOST=$(jq -r "$A.allowed_hosts[0] // empty" "$SESSION")
URL="${ARGS[1]:-${FIRST_HOST:+https://$FIRST_HOST/}}"
URL="${URL:-about:blank}"   # session without allowed_hosts and no URL given
PAC=$(jq -r "$A.proxy.pac_url" "$SESSION")
PROXY=$(jq -r "$A.proxy.url" "$SESSION")
CREDS=${PROXY#https://}; CREDS=${CREDS%%@*}
PROXY_USER=${CREDS%%:*}; PROXY_PASS=${CREDS#*:}

umask 077
WORK=$(mktemp -d "$(state_dir)/browser.XXXXXX")
jq -r "$A.proxy.ca_bundle" "$SESSION" > "$WORK/vgs-ca.pem"
# Trust only the VGS proxy CA (by public-key hash) instead of disabling all certificate checks.
SPKI=$(openssl x509 -in "$WORK/vgs-ca.pem" -pubkey -noout \
  | openssl pkey -pubin -outform der | openssl dgst -sha256 -binary | base64)
CERT_FLAG="--ignore-certificate-errors-spki-list=$SPKI"
[ "$INSECURE" = 1 ] && CERT_FLAG="--ignore-certificate-errors"

EXT="$WORK/proxy-auth-ext"
mkdir -p "$EXT"
cat > "$EXT/manifest.json" <<'JSON'
{
  "manifest_version": 3,
  "name": "VGS session proxy auth",
  "version": "1.0",
  "permissions": ["webRequest", "webRequestAuthProvider"],
  "host_permissions": ["<all_urls>"],
  "background": { "service_worker": "background.js" }
}
JSON
echo "const CREDS = $(jq -cn --arg u "$PROXY_USER" --arg p "$PROXY_PASS" '{username:$u,password:$p}');" > "$EXT/background.js"
cat >> "$EXT/background.js" <<'JS'
// Answer each request's proxy challenge once. If the proxy rejects the credentials again, fall
// back to Chrome's login prompt instead of looping (which ends in ERR_TOO_MANY_RETRIES).
const tried = new Set();
chrome.webRequest.onAuthRequired.addListener(
  (details) => {
    if (!details.isProxy || tried.has(details.requestId)) return {};
    tried.add(details.requestId);
    return { authCredentials: CREDS };
  },
  { urls: ["<all_urls>"] },
  ["blocking"]
);
chrome.webRequest.onCompleted.addListener((d) => tried.delete(d.requestId), { urls: ["<all_urls>"] });
chrome.webRequest.onErrorOccurred.addListener((d) => tried.delete(d.requestId), { urls: ["<all_urls>"] });
JS

echo "Session:   $(jq -r .data.id "$SESSION")  (expires $EXPIRES)"
echo "Opening:   $URL"
jq -r "$A.tokens[] | \"Type this: \(.format) = \(.value)\"" "$SESSION"
echo "Proxy login is automatic. If a login prompt appears anyway, reload once or enter:"
echo "  username: $PROXY_USER"
echo "  password: $PROXY_PASS"
echo "Browser data: $WORK (delete when done)"

# CDP_PORT=9222 lets a tool (e.g. Claude via Playwright connectOverCDP) drive this window.
# Only on 127.0.0.1; this is a throwaway profile.
DEBUG_FLAGS=()
[ -n "${CDP_PORT:-}" ] && DEBUG_FLAGS=(--remote-debugging-address=127.0.0.1 --remote-debugging-port="$CDP_PORT") \
  && echo "Remote debugging: http://127.0.0.1:$CDP_PORT"

"$BIN" \
  "${DEBUG_FLAGS[@]+"${DEBUG_FLAGS[@]}"}" \
  --user-data-dir="$WORK/profile" \
  --proxy-pac-url="$PAC" \
  "$CERT_FLAG" \
  --disable-extensions-except="$EXT" \
  --load-extension="$EXT" \
  --no-first-run --no-default-browser-check \
  "$URL" >/dev/null 2>&1 &
