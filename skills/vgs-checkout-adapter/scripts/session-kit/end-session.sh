#!/usr/bin/env bash
# End (revoke) a reveal session before it expires.
# Usage: ./end-session.sh [session-id]     (default: the latest session)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
need curl jq
load_env

ID="${1:-}"
if [ -z "$ID" ]; then
  [ -f "$STATE_DIR/latest-session.json" ] || die "no latest session; pass a session id"
  ID=$(jq -r .data.id "$STATE_DIR/latest-session.json")
fi

TOKEN=$(access_token)
CODE=$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE "$VGS_API/reveal-sessions/$ID" \
  -H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $VGS_TENANT")
case "$CODE" in
  204) echo "Ended $ID" ;;
  404) echo "$ID not found (already ended or expired)" ;;
  *)   die "HTTP $CODE ending $ID" ;;
esac
