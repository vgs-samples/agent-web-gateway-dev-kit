# Gateway verification

Use a fresh synthetic card and session after local checks/registration, with the required residential egress and intended adapter. Session-card functions require role-based `cards`, while expiry/context stays ordinary data. Verify the observed exit IP; an IP/ISP lookup does not establish bot reputation.

Prefer a unique temporary binding/path on an approved echo host for transformation checks. Existing workspace suites include `validate-stripe-echo.py`, `validate-adyen-echo.py`, `run-adyen-tests.py`, `validate-adapter-smoke.sh` and merchant-specific tests. They are external, environment-specific tools: inspect credentials, routing, source ledgers and cleanup before reuse. Older smoke scripts can predate the residential-only constraint.

Check transformation output, unrelated data preservation, reveals of only intended fields and pass-through without reveals. For encryption capture a synthetic key and encrypt in the same session, then independently decrypt all fields with the owned private key. Do not send real card values to echo services. Avoid accidental session-token occurrences in synthetic key material; Default replacement may mutate the fixture before the response-capture function runs.

Record request IDs and correlate access/operation logs and function output through the available VGS CLI/API. Discover the installed CLI's commands rather than invent flags. Logs may be delayed or preview-truncated. An expired CLI login/403 means diagnostic coverage is incomplete, even if transport assertions pass. Preserve exact errors and distinguish expected failures from status-code mismatches.

Do not assume all echo routes mask responses the same way. Check observed behavior against the explicit synthetic expectation and function logs; neither an echo body nor `reveal_count` alone proves merchant acceptance. Compute invocation/dry test proves function execution but not adapter dispatch; gateway echo proves processing but not real checkout compatibility.

Revoke temporary sessions and remove only bindings created by the run. Preserve registered integrations and other users' resources. Record cleanup failures and any intentionally retained session. Synthetic card records may remain; do not claim they were removed unless actually deleted. Avoid forced process termination that bypasses cleanup.

For authorized merchant verification, navigate a fresh checkout through Agent Web Gateway and the required route. Merchant cookies/cart IDs expire separately from VGS sessions. A fresh session cannot refresh them. Do not auto-retry payment POSTs or follow checkout redirects as though they were harmless probes. Log in/recapture when required; parse pasted curl fixtures as data, never execute their shell text. Report merchant decline, authentication pending, blocking and completed acceptance separately.
