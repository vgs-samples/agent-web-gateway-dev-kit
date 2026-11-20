#!/usr/bin/env bash
# Store a card (PAN + CVC) in the sandbox vault with POST /cards and save its aliases.
#
# Three ways to give the card details (first one found wins):
#   1. Flags:        ./create-card.sh --pan 4111111111111111 --cvc 123 --exp 12/30
#   2. Environment:  CARD_PAN=... CARD_CVC=... CARD_EXP=12/30 ./create-card.sh
#   3. Prompt:       ./create-card.sh          (asks; PAN and CVC are hidden while typing)
#
# The prompt needs a real terminal. Inside Claude Code (`!` commands) use flags or env.
# The aliases are saved to .state/card.json and used by create-session.sh / start.sh.
# The PAN and CVC themselves are never written to disk by this script.
# --require-new rejects deduplicated responses or an unchanged saved card ID.
#
# This is a SANDBOX vault: use test cards (e.g. 4111111111111111). See README.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
need curl jq

PAN="${CARD_PAN:-}"; CVC="${CARD_CVC:-}"; EXP="${CARD_EXP:-}"; REQUIRE_NEW=0
while [ $# -gt 0 ]; do
  case "$1" in
    --require-new) REQUIRE_NEW=1; shift ;;
    --pan) PAN="$2"; shift 2 ;;
    --cvc) CVC="$2"; shift 2 ;;
    --exp) EXP="$2"; shift 2 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

if [ -z "$PAN" ] || [ -z "$CVC" ] || [ -z "$EXP" ]; then
  [ -t 0 ] || die "missing card details. Pass --pan/--cvc/--exp or CARD_PAN/CARD_CVC/CARD_EXP (no terminal to prompt in)"
  [ -n "$PAN" ] || { read -r -s -p "Card number (hidden): " PAN; echo; }
  [ -n "$CVC" ] || { read -r -s -p "CVC (hidden): " CVC; echo; }
  [ -n "$EXP" ] || read -r -p "Expiry (MM/YY): " EXP
fi

PAN=${PAN//[ -]/}
[[ "$PAN" =~ ^[0-9]{13,19}$ ]] || die "card number must be 13-19 digits"
[[ "$CVC" =~ ^[0-9]{3,4}$ ]] || die "CVC must be 3 or 4 digits"
[[ "$EXP" =~ ^([0-9]{1,2})/([0-9]{2}|[0-9]{4})$ ]] || die "expiry must be MM/YY"
EXP_MONTH=$((10#${BASH_REMATCH[1]})); EXP_YEAR=$((10#${BASH_REMATCH[2]: -2}))
[ "$EXP_MONTH" -ge 1 ] && [ "$EXP_MONTH" -le 12 ] || die "expiry month must be 01-12"

# Luhn check catches typos before they reach the API.
sum=0; alt=0
for ((i=${#PAN}-1; i>=0; i--)); do
  d=${PAN:i:1}
  if [ $alt = 1 ]; then d=$((d*2)); [ $d -gt 9 ] && d=$((d-9)); fi
  sum=$((sum+d)); alt=$((1-alt))
done
[ $((sum % 10)) = 0 ] || die "card number fails the Luhn check (typo?)"

load_env
DIR=$(state_dir)
umask 077
RESP=$(mktemp "$DIR/card-resp.XXXXXX")
trap 'rm -f "$RESP"' EXIT

TOKEN=$(access_token)
CODE=$(curl -sS -o "$RESP" -w '%{http_code}' -X POST "$VGS_API/cards" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/vnd.api+json" \
  -H "Accept: application/vnd.api+json" \
  --data-binary @- <<EOF
$(jq -n --arg p "$PAN" --arg c "$CVC" --argjson m "$EXP_MONTH" --argjson y "$EXP_YEAR" \
   '{data:{attributes:{pan:$p,cvc:$c,exp_month:$m,exp_year:$y}}}')
EOF
)
unset PAN CVC

case "$CODE" in
  201|303)
    [ "$CODE" = 303 ] && echo "(card already stored; existing aliases returned)"
    jq -e '.data.attributes | (.pan_alias | type == "string" and length > 0)
      and (.cvc_alias | type == "string" and length > 0)' "$RESP" >/dev/null \
      || die "card API returned no PAN or CVC alias (HTTP $CODE); no session created. Re-store the supplied card and obtain a CVC alias before continuing; saved aliases will not be used as a fallback"
    if [ "$REQUIRE_NEW" = 1 ]; then
      [ "$CODE" = 201 ] || die "card API reused an existing card (HTTP $CODE); a new card ID is required, so no session was created"
      NEW_CARD_ID=$(jq -er '.data.id | select(type == "string" and length > 0)' "$RESP") \
        || die "card API returned no card ID; no session created"
      if [ -f "$DIR/card.json" ]; then
        PREVIOUS_CARD_ID=$(jq -r '.card_id // empty' "$DIR/card.json")
        [ "$NEW_CARD_ID" != "$PREVIOUS_CARD_ID" ] || die "card API did not return a new card ID; no session created"
      fi
    fi
    [ -f "$DIR/card.json" ] && echo "(replacing the previously saved card in $DIR/card.json)"
    jq --argjson m "$EXP_MONTH" --argjson y "$EXP_YEAR" '.data | {card_id: .id, brand: .attributes.card_brand, last4: .attributes.last4,
                 bin: .attributes.bin, length: (.attributes.enriched_attributes.card_properties.card_number_length // 16),
                 pan_alias: .attributes.pan_alias, cvc_alias: .attributes.cvc_alias,
                 exp_month: (.attributes.exp_month // $m), exp_year: (.attributes.exp_year // $y)}' "$RESP" \
      | tee "$DIR/card.json"
    echo
    echo "Saved to $DIR/card.json. Immediately run: ${KIT_ENV:+KIT_ENV=$KIT_ENV }./create-session.sh --hosts <allowed-host>"
    ;;
  *)
    echo "HTTP $CODE" >&2
    jq '.errors // .' "$RESP" >&2 || cat "$RESP" >&2
    exit 1
    ;;
esac
