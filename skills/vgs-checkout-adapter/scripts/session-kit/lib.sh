# shellcheck shell=bash
# Shared helpers, sourced by the other scripts. Not meant to be run directly.

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${KIT_ENV:-}" && ! "$KIT_ENV" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "error: KIT_ENV must contain only letters, digits, underscore or hyphen" >&2
  exit 1
fi

# Environment selection: KIT_ENV=dev uses .env.dev and .state-dev/ (VGS dev, .io domains).
# Unset = .env and .state/ (the default sandbox environment, .com domains).
if [ -n "${KIT_ENV:-}" ]; then
  ENV_FILE="$KIT_DIR/.env.$KIT_ENV"
  STATE_DIR="$KIT_DIR/.state-$KIT_ENV"
else
  ENV_FILE="$KIT_DIR/.env"
  STATE_DIR="$KIT_DIR/.state"          # card aliases + session files (contain secrets)
fi

die() { echo "error: $*" >&2; exit 1; }

need() {
  for c in "$@"; do command -v "$c" >/dev/null 2>&1 || die "'$c' is required (macOS: brew install $c)"; done
}

# Load .env (VGS_CLIENT_ID, VGS_CLIENT_SECRET, VGS_TENANT, optional EGRESS_PROXY, ALLOWED_HOSTS).
# Values already set in the environment win over .env.
load_env() {
  [ -f "$ENV_FILE" ] || die "missing $ENV_FILE (copy .env.example)"
  local line key
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    key=${line%%=*}
    [ -z "${!key:-}" ] && export "$line"
  done < "$ENV_FILE"
  : "${VGS_CLIENT_ID:?set VGS_CLIENT_ID in $ENV_FILE}"
  : "${VGS_CLIENT_SECRET:?set VGS_CLIENT_SECRET in $ENV_FILE}"
  : "${VGS_TENANT:?set VGS_TENANT in $ENV_FILE (vault id, tnt...)}"
  # VGS endpoints: .com sandbox by default; an env file can set VGS_API / VGS_AUTH_URL (dev uses .io).
  VGS_API="${VGS_API:-https://sandbox.vgsapi.com}"
  VGS_AUTH_URL="${VGS_AUTH_URL:-https://auth.verygoodsecurity.com/auth/realms/vgs/protocol/openid-connect/token}"
}

state_dir() {
  ( umask 077; mkdir -p "$STATE_DIR/sessions" )
  echo "$STATE_DIR"
}

# Prints an access token for the service account (client-credentials grant).
access_token() {
  local tok
  tok=$(curl -sS -X POST "$VGS_AUTH_URL" \
    -d grant_type=client_credentials \
    -d client_id="$VGS_CLIENT_ID" \
    -d client_secret="$VGS_CLIENT_SECRET" | jq -r '.access_token // empty') || true
  [ -n "$tok" ] || die "could not get an access token; check VGS_CLIENT_ID / VGS_CLIENT_SECRET"
  echo "$tok"
}
