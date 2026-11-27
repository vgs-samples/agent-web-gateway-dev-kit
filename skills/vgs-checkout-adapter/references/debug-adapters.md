# Debugging an adapter failure

Use the captured exchange to reproduce the failure before changing a function or
retrying checkout. A VGS `422` with `Request processing error. Request id: …`
indicates gateway processing failed; it is not a merchant decline. The status
alone does not identify the failing Larky line. Distinguish it from an explicit
reveal refusal and preserve the request ID.

## CyberSource Flex stage evidence

Run the stage report locally on the supplied HAR. From the repository root, this
example uses the bundled synthetic token request.

```sh
python3 skills/vgs-checkout-adapter/scripts/har-index.py --cybersource \
  examples/adapters/cybersource/fixtures/encrypt.synthetic.har
```

The [redacted payment-decline capture](../assets/cybersource-relay-payment-decline.har) shows a patched SDK and an `AWGCS1` token request from the same iframe document. The token endpoint returned 201 and the merchant payment endpoint returned 400 with `PaymentDeclined`. The capture retains the observed marker classifications. The private bodies used to compute them have been removed.

The bundled example has three bindings. Deployments can add more capture or
payment routes. Use the bindings from the version under investigation. Read them
back from VGS with the session kit, which needs its `.env` service account and
makes only read requests:

```sh
cd skills/vgs-checkout-adapter/scripts/session-kit
./read-bindings.sh cybersource --session RS… --output /private/routes.json
```

It prints the adapter's published version and, for each binding, its stage, exact
route and whether it is enabled. With `--session` it adds the session's state,
reveal and refusal counts, and whether the session selected this adapter, another
one, or automatic matching. `--output` writes the route list for the report below.
Function inputs, session values and credentials are not printed. Bindings whose
path has a wildcard are counted in `bindingsNotExactRoutes` and left out, because
the report compares exact routes. The vault route's content-type policy is not
readable with a kit service account and is listed under `notChecked`.

Without API access, keep the bindings' order and copy only the classification
stage and exact route into a local JSON file by hand. This example describes two
bindings that share a stage:

```json
{"bindings":[
  {"key":"encrypt","when":{"host":"flex.cybersource.com","method":"POST","path":"/flex/v2/tokens"}},
  {"key":"encrypt","when":{"host":"www.alaskaair.com","method":"POST","path":"/book/api/bsmPayments"}}
]}
```

Use `capture`, `bridge-sdk`, or `encrypt` for each `key`. Each `when` needs a
literal hostname, uppercase method, and absolute path without wildcards, query,
or fragment. Omit credentials, input mappings, and session or card values.
From a standalone or installed skill directory, pass the file explicitly:

```sh
python3 scripts/har-index.py --cybersource-bindings /private/routes.json /private/capture.har
```

`bindingsSource` identifies `explicit-file` or `bundled-example`. Each row gives
the zero-based HAR `entry` and the zero-based `bindingIndex` in the selected
file's `bindings` array. An empty `mismatchedFields` list means host, method
and path matched. Otherwise the row lists which fields differed for a candidate
with the same final path component. An exact match suppresses near misses for
that entry within its stage. An empty stage has no candidate. When the file came
from `read-bindings.sh`, each row also carries `bindingEnabled`; a matched request
on a disabled binding was not processed by its function. Confirm the effective
vault content-type policy separately.

Exact rows indicate whether the response recorded nonempty `VGS-Request-Id`,
`VGS-Upstream` and `VGS-Upstream-Response-Time` headers. If the HAR records
an unambiguous HTTP code in `VGS-Upstream-Status-Code`, the report includes
that code separately from the browser status. Cached responses can retain
these headers. Their presence does not identify which adapter function ran.

| Stage | What the HAR can establish |
| --- | --- |
| Capture | The checkout response was recorded. The function returns it unchanged, so confirming a context write requires same-session gateway evidence. |
| Bridge SDK | For the SDK, `cacheControlNoStorePrivate` means the recorded directives were exactly `no-store` and `private`. That policy, a cache flag or 304, and transfer size are auxiliary evidence. The injected marker in the recorded body identifies patched bytes. |
| Encrypt | On exact `POST /flex/v2/tokens` rows (`flex-tokens`), the helper classifies the browser **request** bytes. An `AWGCS1` envelope with paired letters matches the relay encoding. A compact JWS- or JWE-shaped request bypasses the function’s relay guard if delivered as recorded. A 201 or response MIME type cannot establish the request shape. Exact `POST /book/api/bsmPayments` rows carry the label `bsm-payments` and describe the separate merchant payment request. |

A native-looking `eyJ…` payload in a failing token POST leaves the
cache and root cause unknown. If the HAR also contains patched SDK bytes, first
correlate the failing frame's loaded script with that SDK entry and its token
POST. If the same frame used the patch and produced a normal payload, check the
bridge guard privately. It requires at least one submitted card field and exact
string equality for every submitted `number` or `securityCode`. Compare each
with the stand-in used by that SDK and the expected stand-in for the same
session and selected card label, if configured. Report only field presence and
equality booleans. Mark unavailable comparisons unknown. Keep the card values,
stand-ins and label private. Correlate gateway dispatch, reveal count and upstream
transformation to the specific request before attributing a downstream failure.

## Capture and establish the baseline

Export the browser HAR with the failing request body and available response body,
plus the preceding key/configuration responses from the same checkout. Follow
[HAR review](har-review.md): preserve the original privately, record its SHA-256
and zero-based entry indices, and decode bodies according to their encoding.
Sanitized exports may still contain private body data. Never print whole bodies,
cookies, credentials, aliases or session files in shared reports.

Read back the function source, destination mappings and version that handled the
request. Inspect the session's relevant structure and captured values. Preserve
missing state in the failing fixture; do not silently add a card, key or context
that the real session lacked. In particular, `session.card()` requires role-based
`cards`; loose `aliases` with card formats are not the same contract. Automatic
adapter selection does not remove that requirement. Do not guess which PAN/CVC
belong together when multiple cards are present.

## Run the function without sending a payment

Use the target environment's supported function-invocation API. For route
functions, the usual endpoint is `POST /functions/{id}/invocations`, with JSON:API
type `function-invocations`. Supply:

- `request: {method, url, headers, body}` for a request function, or
  `response: {status, headers, body}` for a response function;
- `destination` with the adapter-destination ID to use its mappings, **or**
  `inputs` with the function's named values;
- `session: {values, context}` only where the target API supports that fixture.

Use the captured payload and only headers needed to reproduce processing. This
dry run sends nothing upstream. Inspect `attributes.status` and `attributes.error`:
HTTP `201` can contain a failed invocation. Save its ID and error privately and
include a redacted error in the diagnostic report. Inspect output on success;
unchanged output may mean the function did not match.

Dry runs may have no card/reveal access or may lack a gateway module available in
the proxy runtime. Record the exact boundary reached. A missing-module error in
Compute is not proof that the merchant request failed for the same reason.
Do not change valid imports or bypass session controls merely to make Compute pass.

When dry-run capabilities are insufficient, use [local Larky](local-larky.md) with
the exact deployed source and HAR-derived fixture. Replace only unavailable host
APIs with explicitly documented session/vault doubles. Record each substitution;
never translate function logic into another language. First reproduce the failure
with the original session shape, then change only the candidate fix. Use synthetic
secrets and an owned key for independent decryption. Report native runtime limits
and supplemental JVM results separately.

## Repair, verify and resume

Fix the layer the evidence identifies: source, destination mappings, captured
state, or session creation. A session setup defect does not require an encryption
rewrite. Test the captured failure and relevant regression/pass-through cases;
verify intended fields change, unrelated bytes and browser expiry remain intact,
and only intended values are revealed. A passing double proves modeled behavior,
not the exact live exception or gateway authorization.

Publish only within the user's existing authorization, after validation, and read
back source hashes and mappings. Correlate available operation/access logs by
request ID; distinguish unavailable logs from a confirmed root cause. Use a fresh
properly configured session for an authorized gateway check. Do not replay or
automatically retry a merchant payment POST as a diagnostic. Report separately
what was reproduced, repaired, locally validated, deployed and merchant-verified.
