# Provider lessons from the existing workflows

These are captured integration patterns, not claims that all merchants or SDK versions use them. Start from current HARs and readback/source ledgers.

## Stripe

Form fields may be `card[...]` or `payment_method_data[card][...]`. Reveal each submitted nonempty PAN/CVC stand-in; preserve blank fields, repeated values and unrelated encoded pairs. The current custom Stripe function does not select a replacement card through `session.card()`. Decode once; preserve browser expiry unless explicit string `stripe_expiry_month`/`stripe_expiry_year` context overrides it.

Default replacement can handle intact tokens. A custom function can support deliberately scoped field reveal and space-formatted PAN stand-ins. Saved methods, non-card forms and authentication calls pass through without reveal. `/v1/payment_intents/*/confirm`, `/v1/payment_methods`, `/v1/tokens`, `/v1/setup_intents/*/confirm` are distinct shapes: evidence for one does not verify the others. A `requires_action` result is not a completed payment.

## Adyen

Pair key/config response capture with the card submission from the same session. Current shared capture state uses `adyen_public_key`; one session holds one active key, so use separate sessions per checkout. Missing usable key markers pass through without state changes; matching encryption without required key/secret fails.

The observed secured-fields binding is GET `checkoutshopper-live.adyen.com` with `/checkoutshopper/securedfields/*/*/securedFields*html`. The suffix glob avoided an observed route-serialization failure around escaped literal dots. This is an environment observation, not a universal ban on dots: verify current dispatch and nearby nonmatches.

H&M captures public key and server `genTime` from secured-fields HTML in the same session and ignores creation-time `adyen_generationtime`. Its request mapping selects `$.adyenData.encryptedAdyenForm` as `adyen_form`, with optional `card_label`. It preserves browser expiry ciphertext unless explicit expiry context overrides it. It requires role-based `cards`.

Other existing JYSK/Dunelm/Alza functions retain creation-time `adyen_generationtime` and expiry context. JYSK's payload is a JSON string under `invokeCustomHandlerBody`; Dunelm shares a GraphQL URL and requires a payment-operation guard. Preserve outer envelopes and string wrappers. No expiry vault alias is needed for these current functions. Historical authoring packages still describe older slot mappings and expiry-alias requirements; do not deploy those blindly.

The native binary has known crypto limitations in these tests. Keep native capture/flow results and actual native errors distinct from supplemental JVM Larky crypto results. Independently decrypt RSA-OAEP-256/A256GCM output with an owned key and compare plaintext/header/time fields. A merchant public key cannot prove the encrypted plaintext.

## OPPWA form requests (IKEA example)

The supplied capture used separate `card.number`, `card.cvv`, then expiry/cardholder requests on `POST /v1/checkouts/{single-id}`. Support PAN-only and CVV-only submissions without requiring a complete card object. `/bins`, `/logs`, `/payment` and nested paths pass through inside the function even if a broad binding matches. Preserve unrelated form pairs byte-for-byte and browser expiry. Default replacement may suffice for intact tokens.

Missing response bodies did not prevent request-only local reveal tests, but they left merchant acceptance unverified. The example also demonstrated why an audit-incomplete gateway suite must not be labeled fully passed when transport assertions succeed.
