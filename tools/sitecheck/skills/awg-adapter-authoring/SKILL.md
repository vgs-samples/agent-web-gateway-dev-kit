---
name: awg-adapter-authoring
description: Create or change AWG adapters and Larky functions for a merchant's payment provider, especially client-side encryption (Adyen Secured Fields, CyberSource Flex, Worldpay CSE). Use when a probed site's checkout encrypts the card in the browser, when asked to "write the adapter/functions" for a site, or when a level 2 verify fails.
---

# Author an adapter for client-side card encryption

Read `adapters/README.md` first: it decides whether the site needs an adapter at all. Plain tokenize APIs, such as Stripe, Braintree Hosted Fields and Checkout.com, need only `allowed_hosts`. For the Larky runtime, see `docs/developer-guide.md` ("Writing functions"). For every endpoint and error code, see `docs/api-inventory.md`.

## The model

- **capture** (`route.response`): bound to the response that delivers the PSP's public key. It stores the key with `session.put` in the reveal session, plus anything else the encryption needs, such as a server time.
- **encrypt** (`route.request`): bound to the checkout request. It ignores the browser's ciphertext, which was built from stand-ins and which nobody can decrypt. It reveals the real values with `vault.reveal([session.card().number, ...])` and encrypts them with the captured key in the PSP's exact format. Then it writes the fields back and calls `input.set_body(...)`.
- **adapter**: a named, versioned bundle of the functions. **bindings** (adapter destinations): `when` {host, method, path} plus input sources.

## Steps

1. **Collect evidence**, from the probe video, a HAR, or DevTools on a normal browser:
   - the key-delivering response, saved as `fixtures/capture.json` with `body_file`;
   - the checkout request: host, method, path, and the JSONPath to the encrypted fields, saved as `fixtures/encrypt.json`;
   - the PSP's public JS SDK, read to learn the exact plaintext and envelope. Adyen uses JWE `RSA-OAEP-256`/`A256GCM` with header `version: 1`, and the plaintext `{"<field>": value, "generationtime": ...}`.
2. **Scaffold:**
   - For Adyen sites, copy `adapters/adyen-cse/hm-us.yaml`. Usually only the checkout binding's `when` and the input JSONPath change. If the site wraps the form differently, copy `encrypt.star` and adjust the write-back.
   - For other CSE providers, copy `adapters/_template-cse/` and fill every TODO.
3. **Plan, then apply:** run `uv run awg-sitecheck adapter plan <spec>`, then `uv run awg-sitecheck adapter apply <spec>`. State lands in `state.<env>.<tenant>.json` next to the spec. Commit the spec and functions, not the state.
4. **Dry-run** each function: `uv run awg-sitecheck adapter dry-run <spec> <function-key> <fixture>`.
   - For capture: `result.session.values` must hold the key.
   - For encrypt: use `"destination": "$binding:<key>"` in the fixture so inputs come from the real binding. Expiry and time fields must come back as new ciphertext.
   - A dry run has no card: number and CVC reveals fail by design.
5. **Level 2 (real proxy, no merchant contact):** add `harness/merchants/<site>.json` (see `harness/README.md`), then run `uv run awg-sitecheck verify harness/merchants/<site>.json --card card.json`. Every field must be `PASS`.
6. **Hand over:**
   - put the adapter id on the site in `sites.yaml`;
   - run `uv run awg-sitecheck probe <site> --deep`, and expect `captured: yes`;
   - then run level 3 (skill `awg-checkout-recipe`).

## Rules

- **Functions are immutable.** Change the `.star` file and re-`apply`; the tool versions the adapter and moves the bindings. Do not delete a function another adapter uses (`409 function_in_use`).
- **Return the input unchanged** when the body isn't the one you handle. Never `fail()` on unrelated traffic.
- **Reveal only what the card has.** Check `card.cvc` before revealing a CVC.
- **Never put secrets in sources:** no keys, no card values, no `${` (rejected by the API). Never log revealed values.
- **One capture binding per PSP host per vault.** On `409 destination_overlap`, reuse the existing capture binding (same session value names) instead of adding one.
- **Tear down** what you created for experiments (`adapter teardown <spec>`).
