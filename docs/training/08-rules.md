# 8. Rules

**When you finish this page you can** work with AWG without exposing card data, secrets or other people's money.

These apply to everyone working with AWG, and to any AI agent you run against it.

## 1. Cards

- **Never type a real card into a payment form.** The form gets the session's tokens only.
- **Never print, log or store a card number or CVC** in a file, a ticket or a chat.
- **Use a test card in the labs.** Do not swap in a different card to get past a failure.

## 2. Secrets

- **Never print or share** access tokens, client secrets, proxy passwords, `proxy.url` or the PAC link.
- **Keep credentials out of this repository.** Put them in environment variables, the macOS Keychain, or a private `.env` file only you can read.
- **Check `git status` before every commit.** Never commit `sites.yaml`, `card.json`, `.env` files, `.state` folders, `runs/`, session files or HAR files.

## 3. Purchases

- **Place an order only when a person has approved that item and a maximum total, in writing.**
- **Never retry a payment.** Not automatically, and not after an order was submitted.
- **A person completes 3-D Secure and CAPTCHAs.**

## 4. Other people's setup

- **Do not change a customer's functions, adapters or bindings for them.** Read and advise.
- **Leave admin API changes to AWG engineering.** They reach every tenant.
- **Remove only what you created.**

## 5. Reporting

- **Report what the run shows:** status codes, headers, request ids, `reveal_count`. Say "unknown" instead of guessing.
- **Keep the kinds of proof apart.** A local test, a dry run, a harness pass and a merchant accepting a payment are four different things.

## 6. Being a good guest on merchant sites

- **Keep runs few and spaced out.** Bot protection learns from repetition.
- **Use only an egress proxy you are authorized to use.** One person's authorization does not transfer to a teammate.
- **End every session when the task is done.**

---

## Details and sources

- **Where a card is entered.** Only in the call that stores it in the vault: by a person at a hidden prompt, or, for test cards, through `CARD_PAN` and `CARD_CVC` in the environment (page 4). Files named `card.json` hold vault aliases, not card data. Do not send real card values to echo services. Support never needs a card number to debug: every AWG object holds aliases.
- **Secrets.** The PAC link is a signed credential. A private `.env` should have mode 0600. Also keep `state.*.json` out of commits. A HAR index is an index, not a sanitizer.
- **Purchases.** Run with `--purchase --max-total`. A request to capture, review or test does not authorize a purchase, an account creation or the use of real payment credentials.
- **Other people's setup.** Publishing a VGS adapter version or editing the registry is an admin API change. Revoking a session is safe and immediate. Do not delete a shared provider adapter as cleanup. Tear down adapters you created for experiments.
- **Reporting.** A captioned "3-D Secure" step in a recording only means a payment frame was on screen. Watch the video before claiming it happened.

Sources: `tools/sitecheck/AGENTS.md` (Hard rules; Typical flow for "in writing"), `tools/sitecheck/skills/awg-checkout-recipe/SKILL.md`, `docs/reference/03-support-runbook.md` (Rules for support, Escalation), `docs/reference/01-internal-engineering-spec.md` (the signed PAC link), `skills/vgs-checkout-adapter/SKILL.md` (Operating rules), `skills/vgs-checkout-adapter/references/har-review.md`, `skills/vgs-checkout-adapter/references/gateway-verification.md`, `skills/vgs-checkout-adapter/references/fresh-session.md` (card entry, `.env` mode), `skills/vgs-checkout-adapter/references/deploy-adapters.md` (shared adapters), `tools/sitecheck/docs/lessons.md` (Running demos), and this repository's `.gitignore`. Extending "a capture or review does not authorize a purchase" to testing is this page's own reading.
