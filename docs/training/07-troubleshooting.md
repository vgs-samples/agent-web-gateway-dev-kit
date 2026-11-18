# 7. Troubleshooting

**When you finish this page you can** go from what the agent saw to a likely cause, and collect what an escalation needs.

Most problems are one of two things: the session expired, or the request did not go through VGS.

## Start with three checks

### 1. Did the request go through VGS?

Look for a `vgs-request-id` header on the response. Requests that went through VGS have it. If it is missing, the browser ignored the PAC file or the host is not in the session.

### 2. What does the session say?

```bash
curl -sS "$VGS_API/reveal-sessions/$SESSION_ID?include=values" \
  -H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $TENANT_ID" -H 'Accept: application/vnd.api+json' \
  | jq '.data.attributes | {state, expires_at, allowed_hosts, adapter, reveal_count, refusal_count, values}'
```

Read three things:

- `state` and `expires_at`: is the session still active?
- `reveal_count`: did VGS reveal the card at all?
- `values`: did the capture function store the provider's key?

### 3. Does it fail without VGS too?

If the same request fails on a direct connection, the cause is the merchant or the exit IP, not AWG.

## Find your symptom

| What you see | Most likely cause | What to do |
|---|---|---|
| `407 Proxy Authentication Required` | The session expired or was ended | Create a new session. If a brand-new session also gets `407`, escalate: the tenant may not be enabled for AWG |
| `422 Request processing error. Request id: …` | A function stopped the request | Look up the request id in the logs (below). Then dry-run the function on the same request |
| The checkout went out with the stand-in card, and `reveal_count` is `0` | A function ran but did not recognise the request, or no binding matched it | Compare the binding's host, method and path, and the field names the function expects, with the real request |
| The session's `values` are empty | The payment page did not go through VGS, so the capture function never ran | Add the provider's page host to `allowed_hosts`, and check the browser is using the PAC file |
| `403` from the merchant | The merchant's bot protection, not VGS | Use a real browser, a residential egress proxy that keeps one IP, and the tenant setting `agentGatewayBrowserEmulation=true` |
| `403` with `"error": "reveal_refused"` | VGS refused to reveal the card. The `reason` field says why | Usually: add the payment host to `allowed_hosts`. All reasons are in "Details" |
| The browser ignores the PAC file | Playwright's default headless browser, or a new browser context | Use full Chromium or Chrome, with a persistent context |
| The merchant's pages are slow | Every page on a host in the session goes through VGS | Expected |

## Trace one request

Every request through VGS has a `vgs-request-id`. A `422` response contains it too. With that id and the `access-logs:read` scope, run:

```bash
vgs logs access -R <request id>
vgs logs operations -V <tenant id> -R <request id>
vgs logs reveal-decisions -V <tenant id> -R <request id>
```

In order, these show the request as VGS saw it, the functions that ran, and each reveal that was allowed or refused.

## Escalate

Escalate to AWG engineering (Jira AR-193) when the cause is on VGS's side:

- a `5xx` from the API;
- a `407` for a tenant that should be enabled;
- a `422` when the logs show no error in the customer's function;
- anything that contradicts the runbook.

Collect these first:

- [ ] Tenant id and environment
- [ ] The request id or ids
- [ ] The session id, with its `state`, `expires_at`, `adapter` and `unlisted_host_mode`
- [ ] The binding (`AX…`) and function (`FN…`) ids involved, with the adapter version
- [ ] The time of the failure, with time zone
- [ ] What the agent saw: the status and the body, with card values and aliases removed

**Never include** card numbers, CVCs, the session's proxy password or `proxy.url`.

---

## Details and sources

**More symptoms**

| What you see | Cause | What to do |
|---|---|---|
| `502` pages in the browser | VGS could not use the session's egress proxy. It does not fall back to its own addresses | Check the egress host, port and login |
| `409 function_in_use` or `adapter_in_use` on delete | Something still uses it | Delete in order: bindings, adapters, functions |
| `409 destination_overlap` on a binding | Another enabled binding runs a same-phase function on traffic both could match | Narrow the binding's path or method, or disable the other binding |

**More on the main symptoms**

- `407` can also mean a wrong password. A tenant that is not enabled reaches the shared proxy, which refuses session logins.
- `422` causes include `fail()`, a missing session value, and revealing an alias the card does not have, such as a CVC.
- For Adyen, the provider's page host is `checkoutshopper-live.adyen.com`.
- For a merchant `403`, the runbook's own advice is a real browser through the PAC file, residential `egress_proxy_settings`, and that a reload often passes. The browser-emulation setting and the one-IP ("sticky") egress come from `tools/sitecheck/docs/lessons.md`.
- Without `access-logs:read` the `vgs logs` commands answer `403`. Proxy application logs, including function stack traces, are in Grafana Cloud and are for VGS engineers only.
- Other evidence: a dry run of the function on the same request, and the level 2 harness (page 6).

**`reveal_refused` reasons**

| `reason` | Meaning | What to do |
|---|---|---|
| `session_host_not_allowed` | The host is not in `allowed_hosts` and nothing else allowed it (strict mode) | Add the host to `allowed_hosts` or as an agent destination |
| `tenant_destination_blocked` | A tenant `block` destination matches the host | Change the destination, if the block is not intended |
| `never_host` | The host can never receive real values | Nothing; such a host cannot be allowed |
| `client_ip_not_allowed` | The client address is outside `allowed_client_cidrs` | Correct the session's client ranges |
| `session_expired`, `revoked` | The session ended after the connection was authenticated | Create a new session |
| `guard_refused` | Guarded mode: the reveal guard's limits were reached | Add the host explicitly instead of relying on guarded mode |
| `step_up_rejected`, `step_up_timeout`, `step_up_unavailable`, `step_up_limit` | Step-up was denied, timed out, could not call the webhook, or hit its limit | Check the webhook and the approval |
| `session_store_unavailable` | VGS could not check the session or read the value; the request fails closed | Retry, then escalate with the request id |
| `destinations_unavailable` | VGS could not load the destination settings; the request fails closed | Retry, then escalate with the request id |
| `replacement_failed` | VGS could not place the real value in the request | Escalate with the request id |

**Confirm these against the running system.** They do not come from the 2026-11-12 documents:

- The `reveal_refused` body, its reasons and their meanings come from the October 2026 doc set. The "what to do" column is this page's reading. Sandbox test notes of 2026-11-10 (not in this repository) record `reveal_refused` with `session_store_unavailable`, and the session kit's notes of 2026-11-13 (`skills/vgs-checkout-adapter/references/fresh-session.md`) still refer to `SESSION_STORE_UNAVAILABLE`.
- The `502` row comes from the October 2026 doc set; its fix is this page's reading.

**API errors** use one envelope: `{"errors": [{"status", "code", "title", "detail", "href"}]}`. `400` and `409` carry a `code`; `403` means a missing scope and `404` an unknown, deleted or another tenant's id. The full code table is in [the support runbook](../reference/03-support-runbook.md#reference-error-codes).

Sources: `docs/reference/03-support-runbook.md` (Troubleshooting by symptom, Escalation, error codes), `docs/reference/04-developer-guide.md` (Testing and debugging, Errors and limits), `docs/reference/01-internal-engineering-spec.md` (Observability), `tools/sitecheck/docs/lessons.md` (bot walls), `skills/vgs-checkout-adapter/references/fresh-session.md`.
