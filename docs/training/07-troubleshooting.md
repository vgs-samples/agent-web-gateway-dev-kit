# 7. Troubleshooting

Start from what the agent saw, then check the session before anything else. Most cases are an expired session or a host that did not go through VGS.

## First three checks

1. **Is there a `vgs-request-id` response header?** Requests that went through VGS carry it; direct ones do not. No header means the browser ignored the PAC file or the host is not in the PAC list.
2. **What does the session say?**

```bash
curl -sS "$VGS_API/reveal-sessions/$SESSION_ID?include=values" \
  -H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $VAULT_ID" -H 'Accept: application/vnd.api+json' \
  | jq '.data.attributes | {state, expires_at, allowed_hosts, adapter, unlisted_host_mode, reveal_count, refusal_count, values}'
```

3. **Does the same request fail without VGS?** If it does, the cause is the merchant or the exit IP.

## Symptom to cause

| Symptom | Likely cause | Fix |
|---|---|---|
| `407 Proxy Authentication Required` | Session expired or revoked; wrong password; or the vault is not enabled for the AWG cell, so its proxy host reaches the shared proxy, which refuses session logins | Create a new session. If a fresh session also gets `407`, escalate (cell enablement) |
| `422 Request processing error. Request id: …` | A function stopped the request: `fail()`, a missing session value, or a reveal of an alias the card does not have, such as a CVC | Look up the request id in the operation logs; dry-run the function on the same body |
| `403` with `"error": "reveal_refused"` | VGS refused to reveal. The `reason` says why; see the table below | Depends on the reason |
| Checkout went out with the stand-in card; `reveal_count` is `0` | The function ran but did not match the body (different field names or nesting), or no binding matched the request's host, method and path | Compare the binding's `when` and the function's expected body shape with the real request; reproduce with `awg-sitecheck verify` |
| Session `values` empty | The payment page did not go through VGS, so the capture function never ran | Put the PSP's page host (for Adyen, `checkoutshopper-live.adyen.com`) in `allowed_hosts` or a binding; check the browser used the PAC file |
| `403` from the merchant, `server: AkamaiGHost` | The merchant's bot protection, not VGS | A real browser through the PAC file; `agentGatewayBrowserEmulation=true` on the vault; a residential, sticky egress proxy |
| Browser ignores the PAC file | Playwright's default headless shell, or a new browser context, which does not inherit the command-line PAC | `channel: 'chromium'` or Chrome, with a persistent context |
| `502` pages in the browser | VGS could not use the session's egress proxy. It does not fall back to its own addresses | Check the egress host, port and login |
| Pages on the merchant's site are slow | The PAC file routes by host, so every page on the checkout host goes through VGS | Expected |
| `409 function_in_use` / `adapter_in_use` on delete | Something still uses it | Delete in order: bindings, adapters, functions |
| `409 destination_overlap` on a binding | Another enabled binding runs a same-phase function on traffic both could match | Narrow `when.path` or `method`, or disable the other binding |

### `reveal_refused` reasons

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

Three rows on this page do not come from the 2026-11-12 bundle, so confirm them against the running system:

- The `reveal_refused` body, its reasons and their meanings come from the October 2026 doc set. The "what to do" column is this page's reading of those meanings. Sandbox test notes of 2026-11-10 (not in this repository) record `reveal_refused` with `session_store_unavailable`, and the session kit's notes of 2026-11-13 (`skills/vgs-checkout-adapter/references/fresh-session.md`) still refer to `SESSION_STORE_UNAVAILABLE`.
- The `502` row comes from the October 2026 doc set; its fix is this page's reading.
- The `agentGatewayBrowserEmulation` and sticky-egress fixes come from `tools/sitecheck/docs/lessons.md`. The runbook's own advice for a merchant `403` is a real browser through the PAC file, residential `egress_proxy_settings`, and that a reload often passes.

## Tracing one request

Every request through VGS gets a `vgs-request-id`; a `422` body contains it too. With a credential that has `access-logs:read`:

```bash
vgs logs access -R <request id>                                 # the request as VGS saw it
vgs logs operations -V <vault id> -R <request id>               # the functions and operations that ran
vgs logs reveal-decisions -V <vault id> -R <request id>         # each reveal allowed or refused
```

Without that scope these answer `403`. Proxy application logs, including Larky stack traces, are in Grafana Cloud and are for VGS engineers only.

Other evidence: `GET /reveal-sessions/{id}?include=values` (counters and what functions stored), a dry run of the function on the same body, and the level 2 harness.

## API errors

API errors use one envelope: `{"errors": [{"status", "code", "title", "detail", "href"}]}`. `400` and `409` carry a `code`; `403` means a missing scope and `404` an unknown, deleted or another vault's id. The full code table is in [the support runbook](../reference/03-support-runbook.md#reference-error-codes).

## Escalating

Escalate to AWG engineering (Jira AR-193) when the cause is on VGS's side: a `5xx` from the API, a `407` for a vault that should be enabled, a `422` whose operation logs show no customer-function error, or proxy behavior that contradicts the runbook.

Collect first:

- [ ] Vault id and environment
- [ ] Request id(s), from the `vgs-request-id` header or the `422` body
- [ ] Session id (`RS…`), its `state`, `expires_at`, `adapter` and `unlisted_host_mode`
- [ ] The binding (`AX…`) and function (`FN…`) ids involved, with the adapter version
- [ ] The time of the failure, with time zone
- [ ] What the agent saw (status and body), with card values and aliases removed

Never include card numbers, CVCs, session proxy passwords or `proxy.url`.

---

Sources: `docs/reference/03-support-runbook.md` (Troubleshooting by symptom, Escalation, error codes), `docs/reference/04-developer-guide.md` (Testing and debugging, Errors and limits), `docs/reference/01-internal-engineering-spec.md` (Observability), `tools/sitecheck/docs/lessons.md` (bot walls), `skills/vgs-checkout-adapter/references/fresh-session.md`.
