# 8. Rules

These apply to everyone working with AWG, and to any AI agent you run against it.

## Card data

- Never type a real card number or CVC into a payment form, and never print, log or store one in a file, a ticket or a chat. The payment form gets the session's tokens only.
- A card is entered only in the call that stores it in the vault: by a person at a hidden prompt, or, for test cards, through `CARD_PAN` and `CARD_CVC` in the environment (page 4).
- Files named `card.json` hold vault aliases, not card data.
- Use a test card in the labs. Do not swap in a different card to get past a failure.
- Do not send real card values to echo services.
- Support never needs a card number to debug: every AWG object holds aliases.

## Secrets

- Never print or share access tokens, client secrets, egress proxy passwords, session proxy passwords or `proxy.url`. The PAC link is a signed credential too.
- Credentials come from environment variables or the macOS Keychain, or a private `.env` with mode 0600 outside this repository.
- Do not commit `sites.yaml`, `card.json`, `.env*`, `.state*/`, `runs/`, `state.*.json`, HAR files or session files. A HAR index is an index, not a sanitizer.

## Purchases

- Place an order only when a human has approved that item and a maximum total in writing. Run with `--purchase --max-total`.
- A request to capture, review or test does not authorize a purchase, an account creation or the use of real payment credentials.
- Never retry a payment request automatically, and never retry after an order was submitted.
- A human completes 3-D Secure and CAPTCHAs.

## Other people's configuration

- Do not change a customer's functions, adapters or bindings for them. Read and advise.
- Admin API writes reach every vault. Publishing a VGS adapter version or editing the registry is for AWG engineering.
- Revoking a session is safe and immediate.
- Remove only what your run created. Do not delete a shared provider adapter as cleanup.

## Evidence

- Report what the run shows: status codes, response headers, `result.json` fields, request ids, `reveal_count`. Say "unknown" instead of guessing why a site blocks.
- Keep the kinds of proof apart: a local test, a dry run, a harness pass and a merchant's acceptance are four different things.
- A captioned "3-D Secure" step in a recording only means a payment frame was on screen. Watch the video before claiming it happened.

## Being a polite client

- Keep runs few and spaced per site. Bot walls learn from repetition.
- Use only an egress proxy you are authorized to use. One person's authorization does not transfer to a teammate.
- End every session when the task is done, and tear down adapters you created for experiments.

---

Sources: `tools/sitecheck/AGENTS.md` (Hard rules; Typical flow for "in writing"), `tools/sitecheck/skills/awg-checkout-recipe/SKILL.md`, `docs/reference/03-support-runbook.md` (Rules for support, Escalation), `docs/reference/01-internal-engineering-spec.md` (the signed PAC link), `skills/vgs-checkout-adapter/SKILL.md` (Operating rules), `skills/vgs-checkout-adapter/references/har-review.md`, `skills/vgs-checkout-adapter/references/gateway-verification.md`, `skills/vgs-checkout-adapter/references/fresh-session.md` (card entry, `.env` mode), `skills/vgs-checkout-adapter/references/deploy-adapters.md` (shared adapters), `tools/sitecheck/docs/lessons.md` (Running demos), and this repository's `.gitignore`. Extending "a capture or review does not authorize a purchase" to testing is this page's own reading.
