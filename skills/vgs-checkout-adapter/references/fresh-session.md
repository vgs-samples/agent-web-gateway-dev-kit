# Fresh checkout sessions

Copy `scripts/session-kit/` to a private working directory. Shell dependencies and browser launchers are included; CloakBrowser itself is external.

## Configuration

Copy `.env.example` to `.env`, mode 0600. For a named profile use `.env.<name>` and `KIT_ENV=<name>` consistently for creation, status, relaunch and revocation. State lives in `.state/` or `.state-<name>/`. Exported variables override the file: clear stale `VGS_*`/`EGRESS_*` overrides before switching targets. Use simple `KEY=value` lines without shell quotes, `export` or substitutions.

API/auth endpoints must belong to your Sandbox or Live environment. No credentials are included.

There is no embedded egress provider or endpoint. Read the user-approved route from private local configuration. A private proxy JSON has `scheme`, `hostname`, numeric `port`, `username`, `password`. `--egress-profile` overrides `EGRESS_PROXY`. Both methods must match `EGRESS_ALLOWED_HOST` and `EGRESS_ALLOWED_PORT` configured locally. Invalid or missing configuration stops without route fallback.

## Fresh attempt

From the private kit, using hidden prompts:

```sh
KIT_ENV=sandbox bash ./create-fresh-session.sh \
  --hosts merchant.example,payments.example \
  --egress-profile /absolute/private/proxy.json
```

For explicit synthetic tests, supply `CARD_PAN`, `CARD_CVC`, `CARD_EXP=MM/YY` through the environment. Do not choose another card if intended details are missing. PAN/CVC prompts are hidden.

The wrapper calls `create-card.sh --require-new`, then immediately creates a session. It rejects old alias/bin/length overrides and requires HTTP 201, a nonempty card ID different from the last saved ID, and both returned aliases. PAN aliases may deduplicate. HTTP 303 or a repeated card ID stops even if aliases exist. Lower-level `create-card.sh` may accept 303 with both aliases; do not bypass the fresh wrapper for ordinary checkout.

CVC is volatile. A fresh session does not refresh an unavailable CVC alias. Missing CVC stops without cached fallback, another card or an automatic retry loop. Resolve storage for the supplied card. The check compares only the last saved card ID, not an entire vault history.

## Adapter and browser

Pass `--adapter AD...` registered in this tenant to send role-based `cards` with `number`/`cvc`. Omission keeps aliases-based automatic selection. Functions using `session.card()` require role-based cards; aliases-only is insufficient.

`--adapter stripe|adyen` reads `<ADAPTER_REGISTRY_DIR>/<profile>-<tenant>-<provider>.json` containing `adapterId`. Default directory: `registrations/` beside the scripts; default profile name: `sandbox`. Create ledgers from verified registration readback. None are bundled. An ID matching the Adyen ledger adds string expiry context and current `adyen_generationtime`; without its ledger the kit cannot infer those requirements. Read [provider notes](provider-notes.md).

For CloakBrowser:

```sh
KIT_ENV=sandbox CLOAK_PYTHON=/absolute/path/to/venv/bin/python \
  bash ./create-fresh-session.sh --adapter AD_REPLACE_WITH_REGISTERED_ID \
  --hosts payments.example --egress-profile /absolute/private/proxy.json \
  --launch-browser --url https://merchant.example/checkout
```

It stays attached until the browser closes. The exact new session and matching `.request.json` supply credentials; preserve both because API responses may mask egress passwords. `CLOAK_TZ`/`CLOAK_LOCALE` override UTC/en-US. A missing runtime stops session creation, though the outer wrapper may already have stored a card. Browser failure preserves the created session for inspection/revocation.

For Chromium run `bash setup.sh`, then `bash start.sh payments.example https://merchant.example/checkout` with `EGRESS_PROXY` set. This creates a fresh card/session. `launch-chromium.sh <session.json> <url>` intentionally reopens an existing one. Launchers do not record HARs; use Capture Console.

Type `tokens_to_type.card_number`/`.card_cvc`, not vault aliases. Use actual expiry unless the adapter requires an override. Keep proxy credentials, PAC URLs and saved requests private; verify egress and certificate route.

## Inspect and end

```sh
KIT_ENV=sandbox bash ./session-status.sh
KIT_ENV=sandbox bash ./end-session.sh
```

Supply an explicit session ID when needed. Revocation does not delete cards or local evidence. Do not run concurrent fresh commands in one kit/profile.

`create-session.sh --no-cvc` is an intentional PAN-only diagnostic, not a missing-CVC workaround. Correlate request IDs and logs for `alias_unavailable`/`SESSION_STORE_UNAVAILABLE`; those errors alone do not prove expiry.
