#!/usr/bin/env bash
# Read back an adapter's effective bindings from VGS as a route list for har-index.py. Read-only.
# Usage: ./read-bindings.sh <adapter name or AD… id> [--session RS…] [--output FILE]
#
# Prints the adapter's published version, and for each binding its stage, exact route and whether it
# is enabled. With --session it adds the session's state, counts and whether it selected this adapter.
# Function inputs, session values and credentials are never printed.
#
#   --output FILE  also write the route list to a new private FILE, for
#                  har-index.py --cybersource-bindings FILE <capture.har>
#
# The stage is taken from each function's name (capture, bridge, encrypt); a function with another
# name is classed by its phase: request as encrypt, response as capture.
# Not readable with a kit service account, so not checked: the vault route's content-type policy.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
need curl jq

ADAPTER=""; SESSION=""; OUTPUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --session) [ $# -ge 2 ] || die "--session requires a session id"; SESSION="$2"; shift 2 ;;
    --output) [ $# -ge 2 ] || die "--output requires a file"; OUTPUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,/^set -/p' "$0" | sed '$d'; exit 0 ;;
    --*) die "unknown option: $1 (see --help)" ;;
    *) [ -z "$ADAPTER" ] || die "give one adapter"; ADAPTER="$1"; shift ;;
  esac
done
[ -n "$ADAPTER" ] || die "give an adapter name or id (see --help)"
[[ -z "$SESSION" || "$SESSION" =~ ^RS[A-Za-z0-9]+$ ]] || die "the session id looks wrong"
[ -z "$OUTPUT" ] || [ ! -e "$OUTPUT" ] || die "the output file already exists"
load_env
TOKEN=$(access_token)

fetch() {  # fetch <path>; prints the body, or stops with the HTTP status
  local resp code
  resp=$(curl -sS -w '\n%{http_code}' "$VGS_API/$1" \
    -H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $VGS_TENANT" -H "Accept: application/vnd.api+json")
  code=${resp##*$'\n'}
  [ "$code" = 200 ] || die "GET /${1%%\?*} answered HTTP $code"
  printf '%s' "${resp%$'\n'*}"
}

ADAPTERS=$(fetch agent-gateway-adapters)
BINDINGS=$(fetch agent-gateway-adapter-destinations)
FUNCTIONS=$(fetch functions)
SESSION_JSON=null
[ -z "$SESSION" ] || SESSION_JSON=$(fetch "reveal-sessions/$SESSION")

# The responses go to jq on stdin, not the command line: function sources are large.
REPORT=$(printf '%s\n%s\n%s\n%s\n' "$ADAPTERS" "$BINDINGS" "$FUNCTIONS" "$SESSION_JSON" | jq -s --arg wanted "$ADAPTER" '
  .[0] as $adapters | .[1] as $bindings | .[2] as $functions | .[3] as $session
  | ([$adapters.data[] | select(.id == $wanted or (.attributes.name | ascii_downcase) == ($wanted | ascii_downcase))]) as $found
  | if ($found | length) != 1 then {error: "adapter-not-found-or-ambiguous", matches: ($found | length)} else
    $found[0] as $adapter
    | ($functions.data | map({key: .id, value: (.attributes.name // "")}) | from_entries) as $names
    | [$bindings.data[] | select(.attributes.adapter == $adapter.id) | .attributes as $b | $b.functions[]?
       | (($names[.id] // "") | ascii_downcase) as $name
       | {key: (if ($name | test("bridge")) then "bridge-sdk" elif ($name | test("capture")) then "capture"
                elif ($name | test("encrypt")) then "encrypt"
                elif .extension_point == "route.request" then "encrypt" else "capture" end),
          when: {host: $b.when.host, method: $b.when.method, path: $b.when.path},
          enabled: ($b.enabled == true), adapterVersion: $b.adapter_version}] as $rows
    | ($rows | map(select((.when.host | type) == "string" and (.when.method | type) == "string"
        and (.when.path | type) == "string" and (.when.path | test("[*?#]") | not)))) as $exact
    | {adapter: {id: $adapter.id, name: $adapter.attributes.name, status: $adapter.attributes.status,
                 latestVersion: $adapter.attributes.latest_version, publishedVersion: $adapter.attributes.published_version},
       bindings: $exact,
       bindingsNotExactRoutes: (($rows | length) - ($exact | length)),
       disabledBindings: ($exact | map(select(.enabled | not)) | length),
       notChecked: ["vault route content-type policy"]}
      + (if $session == null then {} else {session: ($session.data.attributes | {state, expiresAt: .expires_at,
           revealCount: .reveal_count, refusalCount: .refusal_count,
           adapterSelection: (if .adapter == null then "automatic" elif .adapter == $adapter.id then "this-adapter" else "another-adapter" end)})} end)
  end')

if [ -n "$(printf '%s' "$REPORT" | jq -r '.error // empty')" ]; then
  die "no single adapter matches that name or id"
fi
if [ -n "$OUTPUT" ]; then
  ( umask 077; set -o noclobber; printf '%s\n' "$REPORT" | jq '{bindings}' > "$OUTPUT" )
fi
printf '%s\n' "$REPORT"
