# Adapters: which sites need one, and how to write it

The gateway swaps the session's stand-ins for the real card values in requests to **allowed hosts**. Whether a site
needs an adapter depends on how its payment provider (PSP) takes the card:

| How the card leaves the browser | Examples | What to do |
|---|---|---|
| **Plain** card fields posted to a PSP API (tokenize) | Stripe Elements (`api.stripe.com`), Braintree Hosted Fields (`payments.braintree-api.com`), Checkout.com Frames (`api.checkout.com`), Shopify (`deposit.shopifycs.com`), Spreedly, Recurly, Authorize.Net Accept.js | **No adapter.** Put the PSP's API host in `allowed_hosts`. The default swap reveals the stand-ins in that request. Confirm with level 3 (`reveal_count` goes up). |
| **Client-side encryption (CSE)**: the browser encrypts the card with the PSP's public key | Adyen Secured Fields, CyberSource Flex Microform, Worldpay CSE, legacy Braintree.js | **Adapter with two functions**: `capture` (response: store the public key in the session) and `encrypt` (request: replace the encrypted fields with fields encrypted from the real card). Nothing decrypts the browser's ciphertext; it is thrown away. |
| Wallet or redirect (PayPal, Klarna, Apple Pay) | | Out of scope for card reveal. |

`awg-sitecheck probe --deep` reports the PSP each site loaded, and whether it is a CSE one (`detect.py` holds the
signatures).

## Writing a CSE adapter

1. **Find the key.** Use the browser's DevTools (or the probe's `video` and the HAR you save) to find the response
   that delivers the public key. For Adyen it is the Secured Fields page on `checkoutshopper-live.adyen.com`, with
   `window.adyen = {key: '10001|…'}` and a `genTime`. Save that response as a fixture.
2. **Find the checkout request.** This is the request that carries the encrypted fields: its host, method and path,
   and the JSONPath of the object holding the fields. Save its body as a fixture, with placeholders where the
   ciphertexts were.
3. **Copy** `_template-cse/` (or `adyen-cse/` for an Adyen site) to `adapters/<psp>-<site>/`. Fill in the TODOs.
4. **Plan, apply, then dry-run** each function on the fixtures:
   ```sh
   awg-sitecheck adapter plan     adapters/<x>/adapter.yaml
   awg-sitecheck adapter apply    adapters/<x>/adapter.yaml
   awg-sitecheck adapter dry-run  adapters/<x>/adapter.yaml capture adapters/<x>/fixtures/capture.json
   awg-sitecheck adapter dry-run  adapters/<x>/adapter.yaml encrypt adapters/<x>/fixtures/encrypt.json
   ```
   A dry run has no card: number and CVC reveals fail there. Test them at level 2.
5. **Level 2 (Adyen today):** add `harness/merchants/<site>.json` and run `awg-sitecheck verify
   harness/merchants/<site>.json --card card.json`. The harness plants a key it owns, sends the merchant's request
   shape through the real proxy to an echo host, and decrypts what comes back. The merchant is never contacted.
6. **Level 3:** add the adapter id to the site in `sites.yaml`, write the recipe, then run `awg-sitecheck purchase
   <site>`. It stops before the order.

Rules that bite:

- **Functions are immutable.** `apply` creates a new function when the source changes, adds an adapter version, and
  moves the bindings to it. Never edit a function in place.
- **`destination_overlap` (409):** two enabled bindings may not run same-phase functions on traffic both could match.
  All Adyen merchants share `checkoutshopper-live.adyen.com`, so keep one capture binding per vault and reuse it, or
  use separate vaults.
- **Return the input unchanged** when a request or response isn't the one you handle. A function that does nothing
  raises no error, so prove it acts by checking `reveal_count` or by using the level 2 harness.
- **Never reveal a CVC the card doesn't have:** check `card.cvc` first. A failed reveal fails the whole request.
- **Fresh times:** if the PSP encrypts a timestamp (Adyen's `generationtime`), use the page's server time, which
  capture stores in the session, not the session creator's clock.
- **No secrets in sources:** no keys, no card values, no `${`. Read the card only with `vault.reveal` on
  `session.card()` aliases.
- **Teardown order:** bindings, then the adapter, then the functions (`awg-sitecheck adapter teardown`).

API details: `../docs/developer-guide.md` (function runtime) and `../../../openapi/awg-tenant-api.yaml` (every endpoint, field and error code).
