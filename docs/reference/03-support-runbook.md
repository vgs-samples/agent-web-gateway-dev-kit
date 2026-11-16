# Agent Web Gateway: Support Runbook

Nov 12, 2026 · @Mahmoud Abdelkader

## What AWG is

The Agent Web Gateway lets a customer's AI agent pay on a merchant website with a card stored in their vault; VGS puts the real card into the payment request in flight, so the agent only ever holds aliases. Almost every support case comes down to one of the parts below being missing, misconfigured or expired.

| Part | Id | What the customer configures | Where it goes wrong |
| --- | --- | --- | --- |
| Reveal session | `RS…` | Per agent task: card aliases, allowed hosts, context; returns a proxy login, CA and PAC link | Expired (default lifetime 5 minutes), revoked, wrong host list |
| Agent destination | `AGD…` | Hosts agents may reach, as `trust`, `guarded` or `block` | Merchant host missing or blocked |
| Function | `FN…` | Larky code that runs on requests or responses | Does not match the merchant's body, or fails (`422`) |
| Adapter | `AD…` | A versioned bundle of functions, e.g. `adyen` v7 | Destination pins a version without the function |
| Adapter destination | `AX…` | Which adapter version's functions run on which host, method and path | Path or host does not match the real traffic |
| VGS registry |  | VGS-managed trusted destinations, functions and adapters every vault inherits | Changed only by VGS through the admin API |

For an Adyen merchant the normal flow is: the agent's browser loads Adyen's payment page through VGS (a capture function stores the merchant's key in the session), the agent types a placeholder card, and on checkout a re-encrypt function swaps in the real card encrypted under that key.

## Access and tools

Support works through two APIs: the admin API for what VGS owns, and the tenant API (with the customer's vault id) for what the customer owns. The admin API cannot read a customer's sessions or bindings.

| Tool | Use it for | Access needed |
| --- | --- | --- |
| Tenant API (`https://sandbox.vgsapi.com`, header `VGS-Tenant: <vault id>`) | Read the customer's sessions, destinations, functions, adapters, bindings; revoke a session | A token with `reveal-sessions:read` / `agent-gateway:read` (`:write` to change) that OPA allows on that vault |
| Admin API (`/admin/agent-destinations`, `/admin/functions`, `/admin/agent-gateway-adapters`) | The VGS registry, VGS functions and adapters | Client role of `vault-mgmt-http-api`: `admin/agent-gateway:read` / `:write` (or `admin/agent-destinations:*` for the registry) |
| VGS CLI logs (`vgs logs access / operations / reveal-decisions -R <request id>`) | What happened to one request: functions run, reveals allowed or refused | `access-logs:read` on the vault |
| Grafana Cloud (cell logs) | Proxy app logs, including function stack traces | Engineering only; escalate |

Rules for support:

- **Never ask for or handle card data.** Every AWG object holds aliases; a customer never needs to send a PAN to debug.
- **Do not change a customer's functions, adapters or bindings for them.** Read and advise; the customer owns that configuration.
- **Revoking a session is safe and immediate** (`DELETE /reveal-sessions/{id}`, `204`); it stops new requests on that session.
- **Admin writes change every vault.** Publishing a VGS adapter version or editing the registry reaches all customers; leave those to engineering unless the runbook for that change says otherwise.

## Common tasks

Each task is one tenant-API call; set these once:

```bash
API=https://sandbox.vgsapi.com
H=(-H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $VAULT" -H 'Accept: application/vnd.api+json')
```

| Task | Call | What to look at |
| --- | --- | --- |
| Find the customer's live sessions | `curl "${H[@]}" "$API/reveal-sessions?state=active&limit=100"` | `expires_at`, `allowed_hosts`, `adapter`, `reveal_count`, `refusal_count` |
| Inspect one session | `curl "${H[@]}" "$API/reveal-sessions/RS…?include=values"` | `state`; `unlisted_host_mode`; `values["AD…"]` holds what functions stored (e.g. `adyen_public_key`); empty means the capture never ran |
| Revoke a session | `curl -X DELETE "${H[@]}" "$API/reveal-sessions/RS…"` | `204`; repeat is also `204` |
| List agent destinations | `curl "${H[@]}" "$API/agent-gateway-destinations"` | Is the merchant host there, and not `block`? |
| See VGS's registry as the customer sees it | `curl "${H[@]}" "$API/agent-gateway-registry"` | Hosts trusted or guarded for every vault |
| List bindings | `curl "${H[@]}" "$API/agent-gateway-adapter-destinations"` | `enabled`, `when.host` / `method` / `path`, `adapter_version`, function ids and inputs |
| Read an adapter version | `curl "${H[@]}" "$API/agent-gateway-adapters/AD…"` | `functions` of the version shown, `latest_version`, `published_version` |
| Read a function's code | `curl "${H[@]}" "$API/functions/FN…"` | `extension_point`, `inputs`, `source` |
| Re-run a function on a body | `POST $API/functions/FN…/invocations` with the body (see the developer guide) | `status`, `error`; cannot reveal cards |
| Held step-up requests | `curl "${H[@]}" "$API/reveal-session-approvals?filter[reveal_session]=RS…"` | `pending` approvals waiting on the customer's webhook |

Deleting configuration (with the customer's agreement): bindings first, then adapters, then functions. Functions and adapters are soft-deleted and their names become free; a function still bundled by an adapter returns `409 function_in_use`, an adapter still bound returns `409 adapter_in_use`.

## Troubleshooting by symptom

Start from what the agent saw, then check the session before anything else: most cases are an expired session or a host that is not routed through VGS.

| Symptom | Likely cause | Check | Fix |
| --- | --- | --- | --- |
| `407 Proxy Authentication Required` | Session expired or revoked; wrong password; or the vault is not enabled for the AWG cell, so `{vault}.sandbox.verygoodproxy.com` reaches the shared proxy, which refuses session logins | Session `state`, `expires_at`; whether other sessions of the vault work | New session; vault not enabled: escalate to engineering (cell enablement) |
| `422 Request processing error. Request id: …` | A customer function stopped the request: `fail()`, a missing session value, or a reveal of an alias the card does not have (e.g. CVC on a card without one) | `vgs logs operations -R <id>`; the session's `values`; the card's aliases | Customer fixes the function or the session; dry-run on the same body to confirm |
| Checkout went out with the placeholder card; `reveal_count` is `0` | The function ran but did not match the body (different field names or nesting), or no binding matched the request's host, method and path | Bindings' `when`; the function's expected body shape vs the real request | Customer adjusts the function or binding; the awg-harness `verify` reproduces this off the merchant |
| Session `values` empty | The payment page did not go through VGS, so the capture function never ran | Is the payment provider's host (e.g. `checkoutshopper-live.adyen.com`) in `allowed_hosts` or a binding? Did the browser use the PAC? | Add the host; fix the browser setup |
| `403` from the merchant (`server: AkamaiGHost`) | The merchant's bot protection, not VGS. Scripted clients and headless browsers are blocked even without VGS; the first page load through VGS was also blocked in tests | Does the same request fail without VGS? | Real browser through the PAC; residential `egress_proxy_settings`; a reload often passes |
| Browser ignores the PAC (traffic goes direct) | Playwright's default headless shell, or a new browser context (it does not inherit the command-line PAC) | Responses lack a `vgs-request-id` header | `channel: 'chromium'` or Chrome, persistent context |
| Pages on the merchant's site are slow | The PAC routes by host, so every page on the checkout host goes through VGS | Compare with direct load | Expected; only hosts in the PAC list are affected |
| `409 function_in_use` / `adapter_in_use` on delete | Something still uses it | Adapters bundling the function; bindings using the adapter | Delete in order: bindings, adapters, functions |
| `409 destination_overlap` on a binding | Another enabled binding runs a function in the same phase on traffic both could match | The vault's bindings with the same host | Narrow `when.path` / `method`, or disable the other binding |

## Escalation

Escalate to AWG engineering (Jira AR-193) when the cause is on VGS's side: a `5xx` from the API, a `407` for a vault that should be enabled, a `422` whose operation logs show no customer-function error, or proxy behavior that contradicts this runbook.

Collect before escalating:

- [ ] Vault id (tenant) and environment (sandbox or live)
- [ ] Request id(s) from the `vgs-request-id` header or the `422` body
- [ ] Session id (`RS…`), its `state`, `expires_at`, `adapter` and `unlisted_host_mode`
- [ ] The binding (`AX…`) and function (`FN…`) ids involved, with the adapter version
- [ ] The time of the failure, with time zone
- [ ] What the agent saw (status and body), with card values and aliases removed

Never include card numbers, CVCs, session proxy passwords or `proxy.url` (it carries the password).

## Reference: error codes

API errors arrive as `{"errors":[{status, code, title, detail, href}]}`; the `detail` text usually names the offending field. `403` (missing scope or role) and `404` (unknown, deleted or another vault's id) carry no code.

| Code | Status | Meaning |
| --- | --- | --- |
| `missing_attributes` | 400 | The body has no `data.attributes` |
| `reserved_tenant` | 400 | The request named the reserved tenant `vgs` |
| `missing_aliases`, `too_many_aliases` | 400 | Session needs at least one card or alias; at most 20 parts |
| `invalid_host`, `never_host`, `too_many_hosts` | 400 | An allowed host is not an exact host name, can never be allowed, or there are more than 20 |
| `invalid_context` | 400 | Context key or value breaks the limits (32 keys, 512 characters, 4096 total) |
| `invalid_adapter`, `adapter_unavailable` | 400 | The session's adapter does not exist or is not visible |
| `ttl_not_configurable`, `unlisted_host_mode_not_configurable`, `step_up_not_configurable` | 400 | These come from vault settings, not the request |
| `invalid_egress_proxy_settings`, `invalid_egress_proxy_hostname`, `invalid_egress_proxy_port`, `invalid_egress_proxy_credentials` | 400 | Egress proxy settings rejected |
| `revocation_list_disabled` | 409 | A stateless session cannot be revoked without the vault's revocation list |
| `session_not_active` | 409 | Credentials reissue on a revoked or expired session |
| `approval_closed` | 409 | The step-up approval was already decided or expired |
| `invalid_host_pattern`, `invalid_action`, `destination_exists`, `too_many_destinations` | 400/409 | Agent destination rejected; at most 1000 per vault |
| `invalid_source`, `source_too_large`, `invalid_extension_point`, `invalid_inputs` | 400 | Function rejected (must parse as Larky, at most 256 KiB, load `vault` as a module) |
| `invalid_invocation`, `invalid_function` | 400 | Dry-run request does not fit the function's extension point |
| `invocations_unavailable` | 503 | The function runtime is unavailable; retry, then escalate |
| `adapter_exists`, `adapter_version_conflict`, `adapter_not_found`, `name_immutable` | 400/409 | Adapter create or version rejected; VGS adapters are read-only to customers |
| `unknown_host`, `destination_blocked` | 400 | A binding's host is not an agent destination of the vault, or is blocked |
| `function_not_in_adapter`, `invalid_adapter_version` | 400 | The binding names a function outside its pinned adapter version, or a version that does not exist |
| `destination_overlap`, `concurrent_change`, `adapter_conflict` | 409 | Binding conflicts with another binding, or was changed at the same time |
| `function_in_use`, `adapter_in_use` | 409 | Delete blocked: still bundled or still bound |
| `preferences_unavailable`, `stateless_unavailable` | 503 | A backing service is down; escalate if it persists |
| `agent_gateway_admin_disabled`, `agent_destinations_admin_disabled` | 503 | Admin API needs OPA (and the database) on that environment |
