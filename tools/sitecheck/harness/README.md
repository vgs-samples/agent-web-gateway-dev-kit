# awg-harness

Test an Agent Gateway adapter's Adyen functions against a merchant's real request shapes, through the real session
proxy, without sending anything to the merchant and without a real card.

## What `verify` does

For each merchant file:

1. **Capture (dry run).** Runs the capture binding's functions on a saved page or response (for H&M, Adyen's live
   secured-fields page) through `POST /functions/{id}/invocations`, and checks that the merchant's public key is the
   value stored in the session.
2. **Re-encrypt (real proxy).**
   - Copies the merchant's checkout binding (same adapter version, functions and inputs) onto a unique path on the
     echo host. The echo returns each request exactly as the upstream received it.
   - Opens a reveal session with the card and context, and plants a key **the harness owns** through the adapter's
     capture function.
   - Sends the merchant's checkout body. Every `browser-jwe-<role>` placeholder in it stands for the browser's
     Adyen ciphertext.
   - Decrypts what came back. Each placeholder must have become an `RSA-OAEP-256`/`A256GCM`/`version 1` JWE under
     the planted key, carrying:
     - `number`: matches the card's BIN and length;
     - `expiryMonth`/`expiryYear`: match the session context;
     - `generationtime`: the Adyen page's `genTime` or the session context, and the report says which;
     - `cvc`: the card's CVC length.
   - Every other field must be unchanged.

The harness deletes everything it creates (bindings, function copies, sessions, the echo agent destination). The
merchant is never contacted.

## Run it

```sh
pip install cryptography
export VGS_API=https://sandbox.vgsapi.com
export VGS_TENANT=YOUR_TENANT_ID
export VGS_ACCESS_TOKEN=...  # token for this Sandbox tenant
python3 awg_harness.py verify merchants/hm.json --card card.json
python3 awg_harness.py verify merchants/*.json --card card.json
```

`card.json` is the card the session uses (copy `card.example.json`): `{"number": {"alias": "tok_...", "bin": "411111", "length": 16},
"cvc": {"alias": "tok_...", "length": 3}}`. Always pass `--card` with your own aliases. If the supplied card has no CVC
alias, CVC fields are reported `UNTESTED` and left out of the body. `--keep-cvc` sends them anyway, to see the
failure a CVC-less card causes.

## Iterate on a function

```sh
python3 awg_harness.py verify merchants/hm.json --card card.json --function FN_REPLACE_WITH_YOUR_FUNCTION_ID=hm_reencrypt.star
```

This uploads the edited source as a temporary copy of that function, under a temporary adapter of its own; the mirrored bindings use it for this run
only. The live binding is not touched. When the run passes, update the real function.

## Add a merchant

Copy a file in `merchants/` and set:

- `capture.binding`: the binding that captures the key.
- `capture.response`: the page or response to dry-run it on. Use `body_file` for a saved page, or `body` for JSON. In
  `body`, `"$harness_key"` stands for a fresh key.
- `checkout.binding`: the merchant's checkout binding.
- `checkout.url`, `checkout.method`, `checkout.headers`, `checkout.body`: the merchant's checkout request, with
  `browser-jwe-number`, `browser-jwe-expiryMonth`, `browser-jwe-expiryYear` and `browser-jwe-cvc` in place of the
  browser's ciphertext. Two template forms are available:
  - `"$binding_input:NAME"` copies a constant input of the binding (for example Dunelm's GraphQL query).
  - `{"$json_string": {...}}` sends a JSON document as a string (for example JYSK's `invokeCustomHandlerBody`).
- `context`: the session context, such as `adyen_expiry_month` and `adyen_expiry_year`. The harness adds
  `adyen_generationtime`.

## Reading the report

| Status | Meaning |
|---|---|
| `PASS` | The field decrypted to the right value. |
| `FAIL` | The field wasn't replaced, didn't decrypt, carries the wrong value, or something else in the body changed. |
| `UNTESTED` | The harness could not test the field. Today that means a CVC field with a CVC-less card. |
| `NOTE` | The body came back unchanged for the whole propagation window, so the function did not act on it. |
| `INFO` | How long the bindings took to go live, and the session's `reveal_count` and `refusal_count`. |

The process exits 0 only when every merchant passes.

New bindings take time to reach the proxy. The harness waits up to `--propagation` seconds (default 120): it repeats
the plant step until the session holds the harness key, and repeats the checkout while the body comes back unchanged.
