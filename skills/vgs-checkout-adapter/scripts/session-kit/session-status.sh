#!/usr/bin/env bash
# Show a session's live status from GET /reveal-sessions/{id}: state, reveal_count, refusal_count.
# reveal_count is supporting evidence; correlate request IDs, function logs and payload checks.
# Echo masking varies by path and does not prove merchant acceptance.
# Usage: ./session-status.sh [session-id]     (default: the latest session)
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
RESP=$(curl -sS -w '\n%{http_code}' "$VGS_API/reveal-sessions/$ID" \
  -H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $VGS_TENANT" -H "Accept: application/vnd.api+json")
CODE=${RESP##*$'\n'}; BODY=${RESP%$'\n'*}
[ "$CODE" = 200 ] || { echo "HTTP $CODE" >&2; echo "$BODY" | jq '.errors // .' >&2; exit 1; }
echo "$BODY" | jq '.data | {id, state: .attributes.state, expires_at: .attributes.expires_at,
  allowed_hosts: .attributes.allowed_hosts, reveal_count: .attributes.reveal_count,
  refusal_count: .attributes.refusal_count, pending_approvals: .attributes.pending_approvals}'
