#!/usr/bin/env bash
# Create a reveal session for the card saved by create-card.sh.
# Checkout entry point: create-fresh-session.sh stores the card immediately first.
# This lower-level command also supports explicit alias diagnostics.
#
# Usage: ./create-session.sh [--hosts h1,h2] [--adapter adyen|stripe|AD...] [--exp MM/YY] [--no-cvc]
#                            [--launch-browser] [--url URL]
#
#   --hosts      comma-separated allowed_hosts (the hosts that receive the REAL card).
#                Optional. Default: ALLOWED_HOSTS from .env if set, otherwise none (the vault's
#                destinations and the unlisted-host mode decide every host).
#   --no-cvc     only reveal the card number.
#   --pan-alias/--cvc-alias/--bin/--length   override what is in .state/card.json.
#   --adapter   use role-based cards; adyen also supplies timestamp and expiry context.
#   --exp       Adyen expiry override; otherwise use the saved card's expiry.
#   --egress-profile FILE  read proxy settings/credentials from a JSON file.
#                Allows Byteful, or EGRESS_ALLOWED_HOST:EGRESS_ALLOWED_PORT configured locally.
#
#   --launch-browser  open CloakBrowser with the newly created session.
#   --url URL         starting page with --launch-browser (default: https://ipinfo.io/json).
#                    CLOAK_PYTHON optionally overrides ../CloakBrowser/.venv/bin/python.
#
# Otherwise, required Byteful residential egress from EGRESS_PROXY in the environment:
#   EGRESS_PROXY='http://user:pass@host:port'   (http or https; hostname, not IP; raw password)
#
# Prints the session summary, proxy username/password and PAC URL. The full response is saved to
# .state/sessions/<id>.json; SESSION_FILE=<path> identifies it (last line unless launching).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
need curl jq

HOSTS=""; NO_CVC=0; PAN_ALIAS=""; CVC_ALIAS=""; BIN=""; LENGTH=""; ADAPTER=""; EXP=""; EGRESS_PROFILE=""
LAUNCH_BROWSER=0; BROWSER_URL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --hosts) HOSTS="$2"; shift 2 ;;
    --no-cvc) NO_CVC=1; shift ;;
    --pan-alias) PAN_ALIAS="$2"; shift 2 ;;
    --cvc-alias) CVC_ALIAS="$2"; shift 2 ;;
    --bin) BIN="$2"; shift 2 ;;
    --length) LENGTH="$2"; shift 2 ;;
    --adapter) ADAPTER="$2"; shift 2 ;;
    --exp) EXP="$2"; shift 2 ;;
    --egress-profile) EGRESS_PROFILE="$2"; shift 2 ;;
    --launch-browser) LAUNCH_BROWSER=1; shift ;;
    --url)
      [ $# -ge 2 ] && [ -n "$2" ] && [[ "$2" != --* ]] || die "--url requires a URL"
      BROWSER_URL="$2"; shift 2 ;;
    -h|--help) sed -n '2,/^set -/p' "$0" | sed '$d'; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

if [ "$LAUNCH_BROWSER" = 1 ]; then
  CLOAK_PYTHON="${CLOAK_PYTHON:-$KIT_DIR/../CloakBrowser/.venv/bin/python}"
  [ -x "$CLOAK_PYTHON" ] || die "CloakBrowser Python not found: $CLOAK_PYTHON (install its venv or set CLOAK_PYTHON)"
  [ -f "$KIT_DIR/cloak-launch.py" ] || die "missing CloakBrowser launcher: $KIT_DIR/cloak-launch.py"
elif [ -n "$BROWSER_URL" ]; then
  die "--url requires --launch-browser"
fi

load_env
DIR=$(state_dir)
HOSTS="${HOSTS:-${ALLOWED_HOSTS:-}}"

CARD="$DIR/card.json"
if [ -f "$CARD" ]; then
  PAN_ALIAS="${PAN_ALIAS:-$(jq -r .pan_alias "$CARD")}"
  CVC_ALIAS="${CVC_ALIAS:-$(jq -r '.cvc_alias // empty' "$CARD")}"
  BIN="${BIN:-$(jq -r .bin "$CARD")}"
  LENGTH="${LENGTH:-$(jq -r '.length // 16' "$CARD")}"
fi
[ -n "$PAN_ALIAS" ] || die "no card: run ./create-card.sh first (or pass --pan-alias and --bin)"
[ -n "$BIN" ] || die "missing --bin (first 6-8 digits of the card)"
LENGTH="${LENGTH:-16}"
[ "$NO_CVC" = 1 ] && CVC_ALIAS=""
if [ "$NO_CVC" != 1 ] && { [ -z "$CVC_ALIAS" ] || [ "$CVC_ALIAS" = null ]; }; then
  die "no CVC alias: use ./create-fresh-session.sh for checkout, or --no-cvc for an intentional PAN-only diagnostic"
fi

# Named adapters resolve from the same tenant's verified registration ledger.
REG="${ADAPTER_REGISTRY_DIR:-$KIT_DIR/registrations}"
ADYEN_ID=""
if [ -f "$REG/${KIT_ENV:-sandbox}-$VGS_TENANT-adyen.json" ]; then
  ADYEN_ID=$(jq -r .adapterId "$REG/${KIT_ENV:-sandbox}-$VGS_TENANT-adyen.json")
fi
case "$ADAPTER" in
  adyen|stripe)
    LEDGER="$REG/${KIT_ENV:-sandbox}-$VGS_TENANT-$ADAPTER.json"
    [ -f "$LEDGER" ] || die "no $ADAPTER registration for this environment/tenant"
    ADAPTER=$(jq -er .adapterId "$LEDGER") ;;
esac
CONTEXT_JSON=null
if [ -n "$ADAPTER" ] && [ "$ADAPTER" = "$ADYEN_ID" ]; then
  if [ -z "$EXP" ] && [ -f "$CARD" ]; then
    EXP=$(jq -r 'if .exp_month != null and .exp_year != null then "\(.exp_month)/\(.exp_year)" else empty end' "$CARD")
  fi
  [[ "$EXP" =~ ^([0-9]{1,2})/([0-9]{2}|[0-9]{4})$ ]] || die "Adyen needs the card expiry: create a new card or pass --exp MM/YY"
  EXP_MONTH=$((10#${BASH_REMATCH[1]})); EXP_YEAR=$((10#${BASH_REMATCH[2]}))
  [ "$EXP_MONTH" -ge 1 ] && [ "$EXP_MONTH" -le 12 ] || die "expiry month must be 01-12"
  [ "$EXP_YEAR" -ge 100 ] || EXP_YEAR=$((2000 + EXP_YEAR))
  CONTEXT_JSON=$(jq -n --arg m "$(printf '%02d' "$EXP_MONTH")" --arg y "$EXP_YEAR" \
    '{adyen_expiry_month:$m,adyen_expiry_year:$y}')
fi

# Egress proxy: split http(s)://user:pass@host:port (password may contain ':' or '@').
EGRESS_JSON=null
if [ -n "$EGRESS_PROFILE" ]; then
  [ -r "$EGRESS_PROFILE" ] || die "cannot read egress profile: $EGRESS_PROFILE"
  # An explicit profile takes precedence over EGRESS_PROXY. Keep the normal Byteful
  # restriction and permit an additional endpoint only when configured explicitly.
  EGRESS_JSON=$(jq -ce --arg allowed_host "${EGRESS_ALLOWED_HOST:-}" --arg allowed_port "${EGRESS_ALLOWED_PORT:-}" '
    if type == "object"
      and (.scheme == "http" or .scheme == "https")
      and (.port | type == "number" and . == floor and . >= 1 and . <= 65535)
      and (.hostname == "residential.byteful.com"
           or ($allowed_host != "" and .hostname == $allowed_host and (.port | tostring) == $allowed_port))
      and (.username | type == "string" and length > 0)
      and (.password | type == "string" and length > 0)
    then {type:"custom",scheme,hostname,port,username,password}
    else error("invalid egress profile") end' "$EGRESS_PROFILE" 2>/dev/null) \
    || die "egress profile must contain scheme, hostname, numeric port, username and password for Byteful or the locally configured EGRESS_ALLOWED_HOST:EGRESS_ALLOWED_PORT"
else
  [ -n "${EGRESS_PROXY:-}" ] || die "EGRESS_PROXY or --egress-profile is required; direct VGS egress is disabled for these tests"
  E_SCHEME=${EGRESS_PROXY%%://*}
  REST=${EGRESS_PROXY#*://}; REST=${REST%%/*}
  E_USER=""; E_PASS=""
  if [[ "$REST" == *@* ]]; then
    USERINFO=${REST%@*}; REST=${REST##*@}
    E_USER=${USERINFO%%:*}; E_PASS=${USERINFO#*:}
  fi
  E_HOST=${REST%:*}; E_PORT=${REST##*:}
  [[ "$E_SCHEME" =~ ^https?$ && "$E_PORT" =~ ^[0-9]+$ && -n "$E_HOST" ]] \
    || die "EGRESS_PROXY must look like http://user:pass@host:port"
  [ "$E_HOST" = residential.byteful.com ] || die "tests must egress through residential.byteful.com"
  EGRESS_JSON=$(jq -n --arg s "$E_SCHEME" --arg h "$E_HOST" --argjson p "$E_PORT" --arg u "$E_USER" --arg pw "$E_PASS" \
    '{type:"custom",scheme:$s,hostname:$h,port:$p} + (if $u != "" then {username:$u,password:$pw} else {} end)')
fi

body() {  # $1 = CVC storage
  jq -n --arg pa "$PAN_ALIAS" --arg b "$BIN" --argjson l "$LENGTH" --arg ca "$CVC_ALIAS" \
    --arg cs "$1" --arg h "$HOSTS" --argjson e "$EGRESS_JSON" --arg adapter "$ADAPTER" \
    --argjson context "$CONTEXT_JSON" --arg now "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)" '
    {data:{type:"reveal-sessions",attributes:(
      (if $adapter != "" then {adapter:$adapter,cards:[
        ({number:{alias:$pa,format:"card_number",bin:$b,length:$l,storage:"PERSISTENT"}}
         + (if $ca != "" then {cvc:{alias:$ca,format:"card_cvc",storage:$cs}} else {} end))]}
       else {aliases: ([{alias:$pa,format:"card_number",bin:$b,length:$l,storage:"PERSISTENT"}]
                 + (if $ca != "" then [{alias:$ca,format:"card_cvc",storage:$cs}] else [] end))} end)
      + (if $context then {context:($context + {adyen_generationtime:$now})} else {} end)
      + (($h|split(",")|map(select(. != ""))) as $hs | if ($hs|length) > 0 then {allowed_hosts:$hs} else {} end)
      + (if $e then {egress_proxy_settings:$e} else {} end))}}'
}

umask 077
RESP=$(mktemp "$DIR/sessions/new.XXXXXX")
TOKEN=$(access_token)
post() {  # $1 = CVC storage; prints HTTP status
  body "$1" > "$RESP.request.json"
  curl -sS -o "$RESP" -w '%{http_code}' -X POST "$VGS_API/reveal-sessions" \
    -H "Authorization: Bearer $TOKEN" \
    -H "VGS-Tenant: $VGS_TENANT" \
    -H "Content-Type: application/vnd.api+json" \
    -H "Accept: application/vnd.api+json" \
    --data-binary "@$RESP.request.json"
}

# POST /cards stores the PAN as PERSISTENT and the CVC as VOLATILE; the session must say so.
CODE=$(post "${CVC_STORAGE:-VOLATILE}")

if [ "$CODE" != 201 ]; then
  echo "HTTP $CODE" >&2
  jq '.errors // .' "$RESP" >&2 || cat "$RESP" >&2
  rm -f "$RESP" "$RESP.request.json"
  exit 1
fi

ID=$(jq -r .data.id "$RESP")
FILE="$DIR/sessions/$ID.json"
mv "$RESP" "$FILE"
mv "$RESP.request.json" "$DIR/sessions/$ID.request.json"
ln -sf "sessions/$ID.json" "$DIR/latest-session.json"

A='.data.attributes'
PROXY=$(jq -r "$A.proxy.url" "$FILE")
CREDS=${PROXY#https://}; CREDS=${CREDS%%@*}

jq "{id: .data.id, expires_at: $A.expires_at, unlisted_host_mode: $A.unlisted_host_mode,
     allowed_hosts: ($A.allowed_hosts // []),
     egress_proxy: ($A.egress_proxy_settings // null | if . then \"\(.scheme)://\(.hostname):\(.port)\" else \"none (VGS addresses)\" end),
     tokens_to_type: ($A.tokens | map({(.format): .value}) | add)}" "$FILE"
echo
echo "Proxy username: ${CREDS%%:*}"
echo "Proxy password: ${CREDS#*:}"
echo "PAC file:       $(jq -r "$A.proxy.pac_url" "$FILE")"
echo
echo "SESSION_FILE=$FILE"

if [ "$LAUNCH_BROWSER" = 1 ]; then
  echo "Opening CloakBrowser with session $ID..." >&2
  exec "$CLOAK_PYTHON" "$KIT_DIR/cloak-launch.py" "$FILE" "${BROWSER_URL:-https://ipinfo.io/json}"
fi
