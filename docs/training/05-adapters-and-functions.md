# 5. Adapters and functions

**When you finish this page you can** decide whether a merchant needs an adapter, and build, test and remove one.

> **Status: source-checked, not run.** The commands and code here come from the developer guide and the tool code. Nobody has run them as part of writing this page.

## What an adapter is for

Normally VGS finds the session tokens in the payment request and swaps in the real card. That fails when the payment provider **encrypts the card in the browser**, because the request then holds ciphertext, not tokens.

An **adapter** fixes that with two **functions**:

1. **Capture** runs when the payment page loads. It reads the provider's encryption key from the page and stores it in the session.
2. **Encrypt** runs on the checkout request. It gets the real card from the vault, encrypts it with the stored key, and replaces what the browser sent.

A **binding** tells VGS which function to run on which request: this host, this method, this path.

## Step 1. Decide whether you need one

Look at the request that carries the card in a real checkout. The provider's name alone is not enough.

| What the card-bearing request contains | Examples | What to do |
|---|---|---|
| Plain card fields, sent to the provider's API | Stripe Elements, Braintree Hosted Fields, Checkout.com Frames, Shopify | **No adapter.** Put the provider's API host in the session's `allowed_hosts` |
| Fields the browser encrypted with the provider's key | Adyen Secured Fields, CyberSource Flex Microform, Worldpay CSE | **Build an adapter.** Continue below |
| A wallet or a redirect | PayPal, Klarna, Apple Pay | Out of scope |

`awg-sitecheck probe --deep` (page 6, step 9) tells you which provider a site uses and whether it encrypts in the browser.

The rest of this page builds an adapter with the `awg-sitecheck` tool. Set the tool up first: page 6, steps 1 to 5.

## Step 2. Find the two requests

Use the browser's DevTools on the real checkout.

1. **The response that delivers the key.** For Adyen it is the Secured Fields page on `checkoutshopper-live.adyen.com`. You will save it as `fixtures/capture.json`.
2. **The checkout request that carries the encrypted fields.** Note its host, method and path, and where in the body the fields sit. You will save it as `fixtures/encrypt.json`, with placeholders where the ciphertext was.

`adapters/adyen-cse/fixtures/` shows the format of both files.

## Step 3. Copy a template

```sh
cd tools/sitecheck
cp -R adapters/_template-cse adapters/myprovider-myshop
```

For an Adyen site, copy `adapters/adyen-cse` instead. It is the worked example, built for H&M US, and its spec file is `hm-us.yaml`.

Create a `fixtures` folder inside your copy and put the two files from step 2 in it.

## Step 4. Fill in the spec

The spec is one YAML file. It names the hosts, the two functions and the two bindings. This is the Adyen example, `adapters/adyen-cse/hm-us.yaml`:

```yaml
name: hm-us-adyen
hosts: [www2.hm.com, checkoutshopper-live.adyen.com]
functions:
  capture:
    file: capture.star
    extension_point: route.response
  encrypt:
    file: encrypt.star
    extension_point: route.request
    inputs: [{name: adyen_form, required: true}, {name: card_label, required: false}]
bindings:
  - key: capture
    function: capture
    when: {host: checkoutshopper-live.adyen.com, method: GET, path: "/checkoutshopper/securedfields/*/*/securedFields*html"}
  - key: checkout
    function: encrypt
    when: {host: www2.hm.com, method: POST, path: "/*/v2/checkout/proceed"}
    inputs: {adyen_form: {from: request.body, path: "$.adyenData.encryptedAdyenForm"}}
```

Reading it:

- `route.response` means the function runs on a response coming back. `route.request` means it runs on a request going out.
- `when` is the binding's match: host, method and path. The path may use `*`.
- `inputs` hands the function a piece of the request. Here, the encrypted card form, picked out of the body by its path.

## Step 5. Write the two functions

A function is a short program in Larky, a dialect of Python. It has one entry point, `process(input, ctx)`, and returns the request or response, changed or not.

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

What you can call:

| Call | What it does |
|---|---|
| `input.body()`, `input.set_body(text)` | Read and replace the body |
| `adapter_input(input, "name")` | Read an input named in the binding |
| `session.put("key", value)`, `session.get("key")` | Store and read a value for the rest of the session. This is how capture hands the key to encrypt |
| `session.context("key")` | Read a value passed when the session was created |
| `session.card()` | The session's card. Its `.number` and `.cvc` are aliases |
| `vault.reveal([aliases])` | Get the real values for those aliases |
| `fail("message")` | Stop the request. The agent gets a `422` |

Four rules that save the most time:

1. **If the request is not the one you handle, return it unchanged.**
2. **Check the card has a CVC before you reveal it.** Revealing a CVC the card does not have fails the whole request.
3. **No secrets in the source.** No keys and no card values.
4. **Never edit a function in place.** A change is a new function; the tool handles that for you.

## Step 6. Create it in your tenant

```sh
uv run awg-sitecheck adapter plan  adapters/myprovider-myshop/adapter.yaml
uv run awg-sitecheck adapter apply adapters/myprovider-myshop/adapter.yaml
```

`plan` shows what would change. `apply` creates the functions, the adapter and the bindings, and adds any missing hosts as agent destinations.

**Success:** a file `state.<env>.<tenant>.json` appears next to the spec. It holds the ids of what was created, including the adapter's id, which starts with `AD`. You need that id in step 9. Git ignores this file; do not commit it.

| If you get | It means |
|---|---|
| `409 destination_overlap` | Another binding already runs a function on the same traffic. All Adyen merchants share `checkoutshopper-live.adyen.com`, so keep one capture binding per tenant and reuse it |

## Step 7. Dry-run each function

A dry run sends your saved fixture through the function inside VGS, with no session and no merchant.

```sh
uv run awg-sitecheck adapter dry-run adapters/myprovider-myshop/adapter.yaml capture adapters/myprovider-myshop/fixtures/capture.json
uv run awg-sitecheck adapter dry-run adapters/myprovider-myshop/adapter.yaml encrypt adapters/myprovider-myshop/fixtures/encrypt.json
```

**Success:** capture shows the key stored in the session values. Encrypt shows the fields that need no card, such as expiry, replaced with new ciphertext.

A dry run has **no card**. Anything that reveals the card number or CVC fails there. That part is tested in step 8.

## Step 8. Verify through the real proxy

Run level 2 from page 6, step 10, with a merchant file for your site: copy one in `harness/merchants/` and follow `harness/README.md`. It sends the merchant's request shape through the real session proxy and decrypts the result. Today this exists for Adyen adapters.

**Success:** every field reads `PASS`.

## Step 9. Use it in a checkout

1. Add `adapter: AD…` (the id from step 6) to the site's entry in `sites.yaml`.
2. Run the level 3 dry run from page 6, step 11.

**Success:** after the run, the session's `reveal_count` has gone up. If it is still `0`, the function ran but did not recognise the request: compare the field names and nesting it expects with the real request.

A rising `reveal_count` shows the card was revealed. It does not show the merchant accepted the payment.

## Step 10. Remove what you built

```sh
uv run awg-sitecheck adapter teardown adapters/myprovider-myshop/adapter.yaml
```

This removes the bindings, then the adapter, then the functions, in that order. Tear down adapters you made for experiments.

## Exercise: find the bug

`examples/functions/hm_reencrypt_buggy.star` is `examples/functions/hm_reencrypt.star` with one deliberate defect.

1. Diff the two files.
2. Say which card field the level 2 harness would report as `FAIL`.
3. Say which kind of dry run would show the defect, and which would not.

The answer is in [the self-check](self-check.md), question 15.

---

## Details and sources

- **"No adapter" is the default, not a guarantee.** The provider list comes from `tools/sitecheck/adapters/README.md`; `tools/sitecheck/AGENTS.md` marks only the Adyen adapter as tested end to end. The skill's `provider-notes.md` records a custom Stripe function, used for deliberately scoped field reveal and for card-number tokens typed with spaces. In a capture, intact token-shaped fields mean the default swap may be enough; encrypted fields plus a key exchange mean a custom function.
- **The API under the tool.** Four endpoints, all needing `agent-gateway:read` / `agent-gateway:write`, with the tenant id in the `VGS-Tenant` header: `/agent-gateway-destinations` (hosts, marked `trust`, `guarded` or `block`), `/functions`, `/agent-gateway-adapters`, `/agent-gateway-adapter-destinations` (bindings). Order: hosts, functions, adapter, bindings. `skills/vgs-checkout-adapter/assets/deployment/` has a payload example for each. A binding sent to the API looks like this:

```json
{"data": {"type": "agent-gateway-adapter-destinations", "attributes": {
  "adapter": "adyen", "adapter_version": 7, "enabled": true,
  "when": {"host": "www.example-shop.com", "method": "POST", "path": "/*/checkout/proceed"},
  "functions": [{"id": "FN…", "inputs": {
    "adyen_form": {"from": "request.body", "path": "$.paymentData.encryptedForm"}}}]}}}
```

- **Binding rules.** `when.host` must be one of the tenant's agent destinations that is not blocked. A binding runs only functions of the adapter version it names; to roll out a new version, `PATCH` the binding's `adapter_version`. Two enabled bindings cannot run functions in the same phase on traffic both could match. Input sources are `constant`, `request.body` / `response.body` (a JSONPath), `request.header` / `response.header` / `request.query`; a request function reads request sources only, a response function response sources only. New bindings take time to reach the proxy; the harness waits up to 120 seconds by default.
- **What the tool does.** `apply` creates a new function when the source changes, adds an adapter version and moves the bindings to it; it adds missing hosts as `guarded` agent destinations. `teardown` leaves agent destinations in place. `adapter list` shows the tenant's adapters and bindings. Deleting by hand in the wrong order returns `409 adapter_in_use` or `409 function_in_use`.
- **Function details.** `session.get` / `session.put` values are kept per adapter. `session.card("label")` picks one of several cards. `vault.reveal` returns values in order, and each reveal counts in `reveal_count`. With `fail()`, the client gets `422 Request processing error. Request id: <id>`; the message does not reach the client. A new function version links to the old one with `previous_version`. No `${` in the source.
- **Time.** Adyen checks the encryption's `generationtime`. Use the payment page's own time: the capture function can store the page's `genTime` with `session.put`.
- **The H&M example.** `examples/functions/hm_reencrypt.star` is specific to H&M's field names, and it does not check `card.cvc` before revealing it, which the engineering spec lists as a known gap. Do not copy that part.
- **Limits.** 256 KiB per function, 32 inputs per function, 32 functions per adapter version, 16 functions per binding, 100 bindings and 1000 agent destinations per tenant. A dry run has a 10 second deadline and bodies up to 1 MiB.
- **Dry runs through the API.** `POST /functions/{id}/invocations`. The response is `201` even when the run fails; read `status`. The developer guide and engineering spec say `session.card()` and aliases always fail in a dry run.

```json
{"data": {"type": "function-invocations", "attributes": {
  "request": {"method": "POST", "url": "https://www.example-shop.com/en_us/checkout/proceed",
              "headers": {"Content-Type": "application/json"}, "body": "{\"paymentMethod\": {}}"},
  "inputs": {"adyen_form": "{}"},
  "session": {"values": {"adyen_public_key": "10001|…"}, "context": {"adyen_expiry_month": "03"}}}}}
```

- **What each test proves.** Report them separately.

| Test | What it proves | What it does not prove |
|---|---|---|
| Local Larky run with stand-in `session` and `vault` objects (`skills/vgs-checkout-adapter/references/local-larky.md`) | The function's logic on a captured body | That the gateway's modules, routing or authorization behave the same. The local runner is pinned to the Larky 1.0.0 binary, while the engineering spec names Larky 1.1.0 as its reference runtime |
| Dry run (step 7) | The function runs in VGS on the request or response you supply | Anything involving the card, or that a binding dispatches to it |
| Level 2 harness (step 8) | The re-encrypt works through the real proxy | That the merchant or provider accepts the payment |
| Level 3 recorded checkout (step 9) | The whole flow on the real site, up to the order | Nothing beyond what the recording and the merchant's response show |

An HTTP 200, a loaded SDK or a rising `reveal_count` alone do not establish that a merchant accepted a payment.

Sources: `tools/sitecheck/adapters/README.md` (decision table, steps, rules), `tools/sitecheck/adapters/adyen-cse/hm-us.yaml`, `tools/sitecheck/AGENTS.md` and `tools/sitecheck/README.md`, `tools/sitecheck/sites.example.yaml`, `tools/sitecheck/awg_sitecheck/adapters.py` (what `plan`, `apply`, `teardown` and `list` do), `tools/sitecheck/skills/awg-adapter-authoring/SKILL.md` (dry-run expectations), `skills/vgs-checkout-adapter/references/provider-notes.md` (Stripe), `local-larky.md`, `har-review.md` (decide from the capture) and `gateway-verification.md`, `skills/vgs-checkout-adapter/SKILL.md`, `docs/reference/04-developer-guide.md` (Destinations, adapters and functions; Writing functions; Testing and debugging; Errors and limits), `docs/reference/01-internal-engineering-spec.md` (Function runtime), `tools/sitecheck/harness/README.md` (propagation).
