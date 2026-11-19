# API error codes

API errors arrive in one envelope:

```json
{"errors": [{"status": "400", "code": "invalid_host", "title": "…", "detail": "…", "href": "…"}]}
```

- `400` (validation) and `409` (conflict) errors carry a `code`. The `detail` text usually names the field at fault.
- `403` means a missing scope. It carries no code.
- `404` means an unknown or deleted id, or one that belongs to another tenant. It carries no code.

The [API specification](../../openapi/awg-tenant-api.yaml) lists the codes each operation can return, in that operation's description. The same reference is published in the [VGS documentation](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway). This page explains the most common ones.

## Sessions

| Code | Status | Meaning |
|---|---|---|
| `missing_attributes` | 400 | The body has no `data.attributes` |
| `missing_aliases`, `too_many_aliases` | 400 | A session needs at least one card or alias, and at most 20 alias parts |
| `invalid_host`, `never_host`, `too_many_hosts` | 400 | An allowed host is not an exact host name, can never be allowed, or there are more than 20 |
| `invalid_context` | 400 | A context key or value breaks the limits: 32 keys, 512 characters per value, 4096 in total |
| `invalid_adapter`, `adapter_unavailable` | 400 | The session's adapter does not exist or is not visible to your tenant |
| `ttl_not_configurable`, `unlisted_host_mode_not_configurable`, `step_up_not_configurable` | 400 | These come from your tenant's settings, not from the request |
| `invalid_egress_proxy_settings`, `invalid_egress_proxy_hostname`, `invalid_egress_proxy_port`, `invalid_egress_proxy_credentials` | 400 | The egress proxy settings were rejected |
| `revocation_list_disabled` | 409 | A stateless session cannot be revoked without the tenant's revocation list |
| `session_not_active` | 409 | Credentials were requested again for a revoked or expired session |
| `approval_closed` | 409 | The step-up approval was already decided or has expired |

## Destinations

| Code | Status | Meaning |
|---|---|---|
| `invalid_host_pattern`, `invalid_action` | 400 | The agent destination's host pattern or action was rejected |
| `destination_exists` | 409 | An agent destination for that host already exists |
| `too_many_destinations` | 400 | A tenant can hold at most 1000 agent destinations |

## Functions

| Code | Status | Meaning |
|---|---|---|
| `invalid_source`, `source_too_large` | 400 | The source must parse as Larky, be at most 256 KiB, and load `vault` as a module |
| `invalid_extension_point`, `invalid_inputs` | 400 | The extension point or the declared inputs were rejected |
| `invalid_invocation`, `invalid_function` | 400 | A dry-run request does not fit the function's extension point |
| `invocations_unavailable` | 503 | The function runtime is unavailable. Retry, then contact VGS support |
| `function_in_use` | 409 | Delete blocked: an adapter still bundles the function |

## Adapters and bindings

| Code | Status | Meaning |
|---|---|---|
| `adapter_exists`, `adapter_version_conflict` | 409 | An adapter of that name exists, or a version was created at the same time |
| `adapter_not_found`, `name_immutable` | 400 | The adapter cannot be versioned or renamed. VGS-owned adapters are read-only |
| `unknown_host`, `destination_blocked` | 400 | A binding's host is not one of your agent destinations, or is blocked |
| `function_not_in_adapter`, `invalid_adapter_version` | 400 | The binding names a function outside its pinned adapter version, or a version that does not exist |
| `destination_overlap` | 409 | Another enabled binding runs a function in the same phase on traffic both could match |
| `concurrent_change`, `adapter_conflict` | 409 | The binding was changed at the same time, or conflicts with another adapter |
| `adapter_in_use` | 409 | Delete blocked: a binding still uses the adapter |

## Service errors

| Code | Status | Meaning |
|---|---|---|
| `stateless_unavailable` | 503 | A backing service is down. Retry, then contact VGS support if it persists |

## Through the proxy

These are not API errors. The agent sees them on requests sent through a session.

| Response | Meaning |
|---|---|
| `407` | The proxy did not accept the session's login: wrong password, or the session expired or was ended |
| `422 Request processing error. Request id: …` | A function stopped the request |
| `403` from the merchant | The merchant's bot protection, not VGS |

[Troubleshooting](../training/07-troubleshooting.md) covers what to do for each.
