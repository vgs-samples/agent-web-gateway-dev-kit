#!/usr/bin/env bash
# Store the supplied card, then immediately create a session from its returned aliases.
# Usage: bash ./create-fresh-session.sh [create-session.sh options]
# Supply CARD_PAN, CARD_CVC, CARD_EXP (MM/YY), or use the hidden terminal prompts.
# Requires a new card ID and both aliases; never substitutes cards or cached aliases.
# Select a kit with KIT_ENV: dev or revolut_sandbox (unset = default sandbox).
# Example: KIT_ENV=revolut_sandbox bash ./create-fresh-session.sh [session options]
# Each kit uses its own .env.<name> credentials and .state-<name>/ aliases/sessions.
set -euo pipefail
cd "$(dirname "$0")"

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      sed -n '2,/^set -/p' "$0" | sed '$d'
      bash ./create-session.sh --help
      exit 0 ;;
    --pan-alias|--cvc-alias|--bin|--length)
      echo "error: fresh sessions must use the aliases returned by this card-storage request; use create-session.sh for explicit alias diagnostics" >&2
      exit 1 ;;
  esac
done

bash ./create-card.sh --require-new >&2
unset CARD_PAN CARD_CVC
bash ./create-session.sh "$@"
