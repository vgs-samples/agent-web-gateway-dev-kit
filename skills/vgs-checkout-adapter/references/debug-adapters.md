# Debugging an adapter failure

Use the captured exchange to reproduce the failure before changing a function or
retrying checkout. A VGS `422` with `Request processing error. Request id: …`
indicates gateway processing failed; it is not a merchant decline. The status
alone does not identify the failing Larky line. Distinguish it from an explicit
reveal refusal and preserve the request ID.

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
