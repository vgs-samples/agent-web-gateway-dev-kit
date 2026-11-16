# 2. Concepts

## Three kinds of card value

Keep these apart; most mistakes in testing come from mixing them up.

| Value | Where it lives | Who may hold it |
|---|---|---|
| Real card number and CVC | The VGS vault and, during a request, inside VGS | Nobody in an AWG flow |
| Vault alias (for example `tok_sandbox_…`) | The customer's systems; passed in `cards` or `aliases` when creating a session | The customer's backend |
| Session token (also called stand-in or session alias) | Returned once, in the create response (`tokens`, `cards`) | The agent, which types it into the payment form |

The agent types session tokens at checkout, never vault aliases. Each session has its own tokens; they mean nothing outside that session. The October 2026 doc set describes their shape: a card-number token keeps the card's BIN and length and passes the Luhn check, and a security-code token is random digits.

## The seven objects

A session is short-lived. Everything else is configuration, set up once per merchant integration.

| Object | Id prefix | What it is |
|---|---|---|
| Reveal session | `RS` | One agent task's credential: a proxy login, a PAC file, the cards it may reveal, its context, and the values functions store |
| Agent destination | `AGD` | A host pattern the vault's agents may reach, and how VGS treats it: `trust`, `guarded` or `block` |
| Registry destination | UUID | VGS's global trusted-destination list, inherited by every vault |
| Function | `FN` | A Larky program for one extension point (`route.request`, `route.response` or `invoke`). Immutable: a new version is a new function |
| Adapter | `AD` | A named bundle of functions with numbered, immutable versions; one per integration, for example `adyen` |
| Adapter destination (binding) | `AX` | Runs one pinned adapter version's functions on traffic matching a host, method and path |
| Function invocation | `FI` | A recorded run of one function, for example a dry run |

Functions and adapters are owned either by the vault's tenant or by VGS. VGS-owned ones are written only through the admin API; tenants can read VGS functions and published VGS adapters, and use them in their own adapters and bindings.

## What a session carries

| Attribute | Rule |
|---|---|
| `cards` or `aliases` | One of the two is required. At most 20 alias parts per session |
| `allowed_hosts` | Optional. Exact host names, at most 20; no wildcards, ports or IP addresses |
| `adapter` | Optional. With an adapter, only that adapter's bindings run for the session. Without one, the session matches every enabled binding of the vault |
| `context` | Optional strings that functions read, for example `adyen_expiry_month`. At most 32 keys, 512 characters per value, 4096 in total |
| `allowed_client_cidrs` | Optional. Addresses the agent connects from, at most 10. Empty means any |
| `egress_proxy_settings` | Optional. The customer's own outbound proxy, so the merchant sees one IP for VGS-routed and direct traffic |

Two things cannot be set per session; they come from the vault's settings:

- **Lifetime.** Default 300 seconds, minimum 30. Setting it in the create request returns `ttl_not_configurable`. A vault can be configured for longer: the test kit README of 2026-11-07 says sessions on its sandbox vault lasted about an hour.
- **Unlisted-host mode** (below).

**Context versus values.** Context is set by whoever creates the session and is read-only to functions (`session.context(key)`). Values are what functions learn and store (`session.put` / `session.get`), kept per adapter. `GET /reveal-sessions/{id}?include=values` returns them keyed by adapter id.

A function that uses `session.card()` needs the session created with role-based `cards` (`number`, `cvc`); loose `aliases` are not enough.

## How the proxy decides, per request

In this order:

1. The client address, against `allowed_client_cidrs` when set.
2. The kill switch, then the session itself: revoked, expired or an unavailable session store refuses.
3. The host: the never-host list, then the session's `allowed_hosts`, a tenant `block`, trusted destinations (registry or tenant), auto-guarded routes, then the fallback set by the unlisted-host mode.
4. Bindings that match the host, method and path run their functions: `route.request` before the request leaves VGS, `route.response` on the way back.

## Unlisted hosts

A host outside `allowed_hosts` and the vault's destinations is handled by the session's `unlisted_host_mode`, which VGS derives from vault preferences when the session is created:

| Mode | What happens | When a vault gets it |
|---|---|---|
| `guarded` | Revealed to within the reveal guard's limits | `agentGatewayAutoGuardedRoutes` is `true`, or unset with no step-up webhook |
| `step_up` | The request is held, for 5 to 30 seconds (default 20), while VGS calls the customer's webhook. The customer approves or denies it with `PATCH /reveal-session-approvals/{id}`. A denial or a timeout refuses the request | A step-up webhook URL is set and `agentGatewayAutoGuardedRoutes` is not `true` |
| `strict` | Nothing is revealed. A request VGS can see is refused. An HTTPS connection to a host that no rule names is tunnelled without inspection, so that host receives the session tokens, which are worthless to it | `agentGatewayAutoGuardedRoutes` is explicitly `false` and there is no webhook. The API inventory also lists `strict` as the result when stored step-up settings are invalid or the preferences cannot be read |

## The PAC file

The PAC file sends the session's `allowed_hosts`, and the `when.host` of every enabled binding, through VGS. Every other host goes to the session's egress proxy when one is set, otherwise direct. It routes by host only: Chrome passes only the host to the PAC script for HTTPS URLs, so the split cannot select paths. For stateless sessions, lookup failures and unsafe host patterns it fails closed and sends everything through VGS.

A PAC file cannot carry credentials. The proxy asks for them with `407`; the username is the session id and the password is the one in `proxy.url`.

## Things that surprise people

- **Write scopes do not include read.** A token with `reveal-sessions:write` alone cannot `GET` a session.
- **Secrets are returned once.** `proxy.url`, the PAC link and the session tokens come only in the create response. The CA bundle can also be read from `GET /reveal-sessions/proxy-ca`.
- **A function that does nothing raises no error.** If it returns its input unchanged, the request goes out as the browser sent it. Check `reveal_count`.
- **A binding pins one adapter version** and runs only functions of that version.
- **Two enabled bindings may not run functions in the same phase on traffic both could match** (`409 destination_overlap`).
- **Delete order:** bindings, then adapters, then functions.

---

Sources: `docs/reference/01-internal-engineering-spec.md` (Concepts and data model, Proxy behavior, Session limits), `docs/reference/04-developer-guide.md` (Reveal sessions, Destinations, PAC), `docs/reference/api-inventory-full.md` (`tokens`), `skills/vgs-checkout-adapter/references/fresh-session.md` (role-based cards, type tokens not aliases), the test kit README of 2026-11-07 (one-hour sessions; not in this repository).
