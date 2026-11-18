# 5. Adapters and functions

**When you finish this page you can** decide whether a merchant needs an adapter, set one up, and test a function.

> **Status: source-checked, not run.** The requests and code here come from the developer guide and the tool code. Nobody has run them as part of writing this page.

## Does this merchant need an adapter?

It depends on how the merchant's payment provider (PSP) takes the card.

| How the card leaves the browser | Examples | What to do |
|---|---|---|
| Plain card fields posted to a PSP API | Stripe Elements (`api.stripe.com`), Braintree Hosted Fields (`payments.braintree-api.com`), Checkout.com Frames (`api.checkout.com`), Shopify (`deposit.shopifycs.com`) | No adapter. Put the PSP's API host in `allowed_hosts`. The default swap replaces the session tokens in that request. Confirm with a level 3 run that `reveal_count` goes up |
| Client-side encryption (CSE): the browser encrypts the card with the PSP's public key | Adyen Secured Fields, CyberSource Flex Microform, Worldpay CSE | An adapter with two functions: `capture` (on the response that delivers the key) and `encrypt` (on the checkout request) |
| Wallet or redirect | PayPal, Klarna, Apple Pay | Out of scope for card reveal |

Do not decide from the provider's name alone. Look at the actual card-bearing request in a capture of the real checkout: intact session-token-shaped fields mean the default swap may be enough; application-encrypted fields plus a key exchange mean a custom function. The list of providers above comes from `tools/sitecheck/adapters/README.md`; `tools/sitecheck/AGENTS.md` marks only the Adyen CSE adapter as tested end to end.

"No adapter" is the default, not a guarantee. The skill's `provider-notes.md` records a custom Stripe function, used for deliberately scoped field reveal and for card-number stand-ins typed with spaces.

`awg-sitecheck probe --deep` reports which PSP a site loaded and whether it is a CSE one (page 6).

## The four pieces of configuration

| Piece | Endpoint | Purpose |
|---|---|---|
| Agent destination | `/agent-gateway-destinations` | Names a host agents may use: `trust`, `guarded` or `block` |
| Function | `/functions` | Larky code for `route.request` or `route.response` |
| Adapter | `/agent-gateway-adapters` | A named, versioned bundle of functions |
| Adapter destination (binding) | `/agent-gateway-adapter-destinations` | Runs chosen functions of one adapter version on a host, method and path |

All four need `agent-gateway:read` / `agent-gateway:write`. The API is JSON:API with the tenant id in the `VGS-Tenant` header.

Setting up a merchant, in order:

1. **Add the hosts** as agent destinations: the merchant's checkout host and its PSP's page host (for Adyen, `checkoutshopper-live.adyen.com`).
2. **Create the functions.** An edit is a new function; link it to the old one with `previous_version`.
3. **Create the adapter**, or add a version to it, with those functions.
4. **Bind** the functions to traffic with adapter destinations.

A binding looks like this:

```json
{"data": {"type": "agent-gateway-adapter-destinations", "attributes": {
  "adapter": "adyen", "adapter_version": 7, "enabled": true,
  "when": {"host": "www.example-shop.com", "method": "POST", "path": "/*/checkout/proceed"},
  "functions": [{"id": "FN…", "inputs": {
    "adyen_form": {"from": "request.body", "path": "$.paymentData.encryptedForm"}}}]}}}
```

Rules:

- `when.host` must be one of the tenant's agent destinations that is not blocked. `path` may use `*`.
- A binding runs only functions of the adapter version it names. To roll out a new version, `PATCH` the binding's `adapter_version`.
- Two enabled bindings cannot run functions in the same phase on traffic both could match (`409 destination_overlap`). All Adyen merchants share `checkoutshopper-live.adyen.com`, so keep one capture binding per tenant and reuse it.
- Input sources: `constant`, `request.body` / `response.body` (a JSONPath), `request.header` / `response.header` / `request.query`. A request function reads request sources only; a response function reads response sources only.
- Delete in order: bindings, then adapters, then functions. Otherwise you get `409 adapter_in_use` or `409 function_in_use`.
- New bindings take time to reach the proxy. The harness waits up to 120 seconds by default.

`awg-sitecheck adapter plan|apply|dry-run|teardown` manages functions, adapters and bindings from a YAML spec (page 6). `apply` also adds any missing hosts as `guarded` agent destinations; `teardown` leaves agent destinations in place. `adapter list` shows the tenant's adapters and bindings. `skills/vgs-checkout-adapter/assets/deployment/` has payload examples for each call.

## Writing a function

A function is a Larky program (a Python dialect) with one entry point, `process(input, ctx)`, which returns the request or response, changed or not.

```python
load("@vgs//agent_gateway", session="session")
load("@vgs//vault", vault="vault")
load("@stdlib//json", json="json")
adapter_input = None   # filled in by VGS with this binding's inputs

def process(input, ctx):
    body = json.loads(input.body())
    form = body.get("paymentMethod")
    if type(form) != "dict" or "encryptedCardNumber" not in form:
        return input                              # not ours: pass it on unchanged
    key = session.get("adyen_public_key")         # stored by the capture function
    if not key:
        fail("Load the payment page in this session first")
    number, = vault.reveal([session.card().number])
    form["encryptedCardNumber"] = encrypt(number, key)   # your encryption helper
    input.set_body(json.dumps(body))
    return input
```

| Call | What it does |
|---|---|
| `input.body()`, `input.set_body(text)` | Read and replace the body, as text |
| `adapter_input(input, "name")` | The value of an input, as bound on the adapter destination |
| `session.context("key")` | A value passed when the session was created; read-only |
| `session.get("key")`, `session.put("key", value)` | Values functions share across requests of one session, kept per adapter |
| `session.card()`, `session.card("label")` | The session's card: `.number` and `.cvc` aliases |
| `vault.reveal([aliases])` | The real values for those aliases, in order. Each reveal counts in `reveal_count` |
| `fail("message")` | Stops the request. The client gets `422 Request processing error. Request id: <id>`; the message does not reach the client |

A complete example is H&M's re-encrypt function, [`examples/functions/hm_reencrypt.star`](../../examples/functions/hm_reencrypt.star). It is specific to H&M's field names, and it does not check `card.cvc` before revealing it, which the engineering spec lists as a known gap. Do not copy that part. Templates are in `tools/sitecheck/adapters/_template-cse/` and `tools/sitecheck/adapters/adyen-cse/`.

Rules that come from real integrations:

- **Return the input unchanged when the request is not one you handle.** That raises no error, so prove the function acts on the merchant's real request body.
- **Check `card.cvc` before revealing it.** Revealing a CVC the card does not have fails the whole request with `422`.
- **Use the payment page's own time.** Adyen checks the encryption's `generationtime`; the capture function can store the page's `genTime` with `session.put`.
- **No secrets in the source:** no keys, no card values, no `${`. Read the card only with `vault.reveal` on `session.card()` aliases.
- **Functions are immutable.** Never try to edit one in place.

Source limits: 256 KiB per function, 32 inputs per function, 32 functions per adapter version, 16 functions per binding, 100 bindings and 1000 agent destinations per tenant.

## Testing a function

There are four ways, and each proves a different thing. Report them separately.

| Test | What it proves | What it does not prove |
|---|---|---|
| Local Larky run with stand-in `session` and `vault` objects (`skills/vgs-checkout-adapter/references/local-larky.md`) | The function's logic on a captured body | That the gateway's modules, routing or authorization behave the same. The local runner is pinned to the Larky 1.0.0 binary, while the engineering spec names Larky 1.1.0 as the runtime on dev |
| Dry run: `POST /functions/{id}/invocations` | The function runs in VGS on the request or response you supply; returns `status`, `error` and the rewritten `result` | Anything involving the card: the developer guide and engineering spec say `session.card()` and aliases always fail in a dry run. Not that a binding dispatches to it |
| Level 2 harness: `awg-sitecheck verify` | The re-encrypt works through the real proxy: the harness plants a key it owns, sends the merchant's request shape to an echo host and decrypts the result | That the merchant or PSP accepts the payment |
| Level 3 recorded checkout: `awg-sitecheck purchase` | The whole flow on the real site, up to the order | Nothing beyond what the recording and the merchant's response show |

A dry-run request:

```json
{"data": {"type": "function-invocations", "attributes": {
  "request": {"method": "POST", "url": "https://www.example-shop.com/en_us/checkout/proceed",
              "headers": {"Content-Type": "application/json"}, "body": "{\"paymentMethod\": {}}"},
  "inputs": {"adyen_form": "{}"},
  "session": {"values": {"adyen_public_key": "10001|…"}, "context": {"adyen_expiry_month": "03"}}}}}
```

The response is `201` even when the run fails; read `status`. A dry run has a 10 second deadline and bodies up to 1 MiB.

An HTTP 200, a loaded SDK or a rising `reveal_count` alone do not establish that a merchant accepted a payment.

## Exercise: find the bug

`examples/functions/hm_reencrypt_buggy.star` is `hm_reencrypt.star` with one deliberate defect. Diff the two files and say which card field the harness would report as `FAIL`, and which kind of dry run would and would not show the defect. The answer is in [the self-check](self-check.md).

---

Sources: `tools/sitecheck/adapters/README.md` (decision table, rules), `tools/sitecheck/AGENTS.md` and `tools/sitecheck/README.md`, `tools/sitecheck/awg_sitecheck/adapters.py` (what `apply`, `teardown` and `list` do), `skills/vgs-checkout-adapter/references/provider-notes.md` (Stripe), `skills/vgs-checkout-adapter/references/local-larky.md`, `skills/vgs-checkout-adapter/references/har-review.md` (decide from the capture), `docs/reference/04-developer-guide.md` (Destinations, adapters and functions; Writing functions; Testing and debugging; Errors and limits), `docs/reference/01-internal-engineering-spec.md` (Function runtime), `tools/sitecheck/harness/README.md` (propagation), `skills/vgs-checkout-adapter/SKILL.md` and `references/gateway-verification.md` (what each test proves).
