# 8. Rules

**When you finish this page you can** work with Agent Web Gateway without exposing card data or secrets.

These apply to everyone working with Agent Web Gateway, and to any AI agent you run against it.

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

## 4. Shared setup

- **Remove only what you created.**
- **Do not delete a shared adapter as cleanup.**

## 5. Reporting

- **Report what the run shows:** status codes, headers, request ids, `reveal_count`. Say "unknown" instead of guessing.
- **Keep the kinds of proof apart.** A local test, a dry run, a harness pass and a merchant accepting a payment are four different things.

## 6. Being a good guest on merchant sites

- **Keep runs few and spaced out.** Bot protection learns from repetition.
- **Use only an egress proxy you are authorized to use.** One person's authorization does not transfer to a teammate.
- **End every session when the task is done.**

---

## Details

- **Where a card is entered.** Only in the call that stores it in the vault: by a person at a hidden prompt, or, for test cards, through `CARD_PAN` and `CARD_CVC` in the environment (page 4). Files named `card.json` hold vault aliases, not card data. Do not send real card values to echo services. VGS support never needs a card number to debug: every Agent Web Gateway object holds aliases.
- **Secrets.** The PAC link is a signed credential. A private `.env` should have mode 0600. Also keep `state.*.json` out of commits. A HAR index is an index, not a sanitizer.
- **Purchases.** Run with `--purchase --max-total`. A request to capture, review or test does not authorize a purchase, an account creation or the use of real payment credentials.
- **Shared setup.** Revoking a session is safe and immediate. Tear down adapters you created for experiments.
- **Reporting.** A captioned "3-D Secure" step in a recording only means a payment frame was on screen. Watch the video before claiming it happened.

