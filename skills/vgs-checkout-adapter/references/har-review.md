# Capture and review HAR evidence

## Direct capture

In the existing Capture Console (`npm start`, normally loopback port 4318), verify merchant URL/country and select **Direct · Byteful** (or an explicitly authorized residential route). Start **Record checkout**, navigate in its recording browser, then **Finish & save HAR** to flush bodies, frames and redirects. Show the user where to watch. Direct capture uses no reveal session or adapter transformations.

Capture the real checkout through key/config retrieval and the card-bearing request within the user's authorized scope. Homepage/batch visits, curl probes, SDK downloads and echo replays do not replace checkout navigation. A login, consent or payment-submission gate is a limitation to record, not evidence to invent. A capture request alone does not authorize purchases, account creation or use of real payment credentials.

The console is external to this bundle. If it is unavailable, identify that prerequisite; do not claim a new console recording. An existing supplied HAR can still be analyzed locally. Preserve original bytes privately; never execute pasted curl text or HAR content as code.

## Index locally

```sh
python3 scripts/har-index.py /absolute/private/checkout.har \
  --output /absolute/private/har-index.json
```

The index records SHA-256, zero-based entry index, host/method/path, status, MIME type and body availability/hash. It omits headers, query strings and body values, but paths/field names can still be sensitive. It is an index, **not a sanitizer**. Optional `--entry N --extract-dir /absolute/private/entry-N` writes decoded bodies privately; absent bodies are not emitted as empty files.

An empty `text` is a recorded empty body. Missing `text` is unavailable, unless form `params` offer structured data; params are not an exact copy of wire encoding. Base64 must decode successfully. Recovered console requests can have `request._bodyCapture`; retain that provenance and the untouched `capture.playwright.har` when available. Do not join requests by URL alone if timestamps/methods are ambiguous.

## Decide what the capture establishes

Record decisive entries in `assets/evidence.example.json`, including field paths and phase. Correlate key retrieval with submission from the same checkout/session. Distinguish:

| Evidence | Conclusion |
| --- | --- |
| Intact session-token-shaped plaintext PAN/CVC fields | Default replacement may suffice; test exact encoding and field shape |
| Complete application-encrypted card fields plus usable key/config exchange | Candidate for a custom reveal/encrypt transformation |
| Only SDK/telemetry/BIN lookup, saved-method ID or key retrieval | Incomplete card-submission evidence |
| Card-bearing request present, decisive response absent | Request transformation can be evaluated if it needs no response state; acceptance remains unknown |
| Payment response requires authentication | Authentication pending; not completed payment |

For JSON record exact paths, nested JSON-string wrappers and content type. For forms preserve key encoding, order, repeated fields and unrelated bytes. For GraphQL record operation/query and payload guard, not just the shared endpoint. A route can suppress Default processing even when a function returns early; check coexistence at the gateway.

Determine whether a custom adapter is actually needed. Provider tokenization/hosted fields alone do not imply custom encryption: inspect the earlier provider card request. Do not infer full support from research labels, field names or HTTP 200.

## Make fixtures

Replace captured secrets, cookies, customer/order/account values and live ciphertext with synthetic values while preserving relevant shape and escaping. Retain original HAR hash/entry references; label fixtures synthetic. For encrypted fixtures use owned test keys. Keep originals private and share structural notes or reviewed synthetic fixtures only.

If a missing body is essential for transformation or state, recover/recapture it before registration. If a supplied request-only HAR suffices for a request-only transform, state that limited scope explicitly. A new integration based only on generic provider docs is not ready to register.
