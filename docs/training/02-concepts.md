# 2. Concepts

**When you finish this page you can** say which card value goes where, name the parts of an Agent Web Gateway integration, and predict what happens to a request.

## Three card values

Most mistakes in testing come from mixing these up.

| Value | Who holds it | Example |
|---|---|---|
| **Real card number and CVC** | Only the VGS vault and, during a request, VGS | `4111 1111 1111 1111` |
| **Vault alias** | Your backend. It sends aliases to VGS when it creates a session | `tok_sandbox_…` |
| **Session token** | The agent. It types the token into the payment form | A card-shaped number that works only in one session |

The agent types **session tokens**, never vault aliases and never the real card.

## The parts

A **reveal session** is created for each agent task and lasts minutes. Everything else is set up once per merchant.

| Part | Id starts with | What it is |
|---|---|---|
| Reveal session | `RS` | One agent task's pass: which card, which hosts, for how long |
| Agent destination | `AGD` | A host the tenant's agents may reach, marked `trust`, `guarded` or `block` |
| Function | `FN` | A VGS Compute function that processes a request or response inside the gateway |
| Adapter | `AD` | A named, versioned bundle of functions, for example `adyen` |
| Adapter destination (also called a binding) | `AX` | The rule that says "run these functions on requests to this host and path" |

You need functions, adapters and bindings only when the payment provider encrypts the card in the browser (page 5).

## What you set on a session

| Field | Required? | What to put |
|---|---|---|
| `cards` or `aliases` | One of them | The card's aliases. At most 20 alias parts |
| `allowed_hosts` | No | The exact hosts that may receive the real card. At most 20; no wildcards, ports or IP addresses |
| `adapter` | No | The adapter to use. The session then runs only that adapter's bindings |
| `context` | No | Extra strings for functions to read, such as the card's expiry month |
| `allowed_client_cidrs` | No | The addresses the agent connects from. At most 10 |
| `egress_proxy_settings` | No | Your own outbound proxy |

Two things you **cannot** set on a session. They come from the tenant's settings:

- **How long it lasts.** The default is 5 minutes.
- **What happens to hosts you did not list.** See below.

## What happens to a request

The session proxy checks each request in this order and stops at the first check that fails:

1. **Is the client address allowed?** Only checked if the session set `allowed_client_cidrs`.
2. **Is the session still active?** Not expired and not revoked.
3. **Is the host allowed?** A host in `allowed_hosts` is. A host on VGS's never-host list never is.
4. **Do any bindings match?** If so, their functions run: request functions before the request leaves VGS, response functions on the way back.

## Hosts you did not list

The tenant has one of three modes for hosts that nothing allows:

| Mode | What happens |
|---|---|
| `guarded` | The card may be revealed, within limits. This is the default |
| `step_up` | The request is held while VGS asks you to approve or deny it |
| `strict` | Nothing is revealed |

Do not rely on the mode. List the payment host in `allowed_hosts`.

## How the browser reaches VGS

The session's PAC file sends only the payment hosts through VGS: the session's `allowed_hosts` and the hosts that bindings name. Every other site loads directly, or through your egress proxy if the session set one.

A PAC file cannot carry a password. The proxy asks for one (`407`). The username is the session id, and the password is the one in `proxy.url`.

---

## Details

- **Session token shape.** A card-number token keeps the card's BIN and length and passes the Luhn check, and a security-code token is random digits. Some VGS documents also call session tokens "stand-ins" or "session aliases".
- **Two more objects.** VGS keeps a registry of trusted destinations that every tenant inherits. A function invocation (`FI`) records one run of a function, such as a dry run. Functions also have a third extension point, `invoke`.
- **Who owns functions and adapters.** The tenant or VGS. Tenants can read VGS functions and published VGS adapters, and use them in their own adapters and bindings.
- **Session lifetime.** Default 300 seconds, minimum 30. Setting it in the create request returns `ttl_not_configurable`.
- **Context limits.** At most 32 keys, 512 characters per value, 4096 in total.
- **Context versus values.** Context is what the session's creator passes; functions read it with `session.context(key)`. Values are what functions store with `session.put`; read them with `GET /reveal-sessions/{id}?include=values`.
- **`session.card()`** works only when the session was created with `cards` (with `number` and `cvc`), not loose `aliases`.
- **Without an `adapter`,** a session matches every enabled binding of the tenant.
- **Host check in full.** The never-host list, then the session's `allowed_hosts`, a tenant `block`, trusted destinations (registry or tenant), auto-guarded routes, then the unlisted-host mode. Step 2 also refuses when a kill switch is on or the session store is unavailable.
- **Which mode a tenant gets.** `guarded` when `agentGatewayAutoGuardedRoutes` is `true`, or unset with no step-up webhook. `step_up` when a webhook URL is set and that setting is not `true`. `strict` when the setting is explicitly `false` with no webhook; `strict` is also used when stored step-up settings are invalid or the preferences cannot be read.
- **`step_up` timing.** The request is held for 5 to 30 seconds (default 20). You answer with `PATCH /reveal-session-approvals/{id}`. A denial or a timeout refuses the request.
- **`strict` in full.** A request VGS can see is refused. An HTTPS connection to a host that no rule names is tunnelled without inspection, so that host receives the session tokens, which are worthless to it.
- **PAC in full.** It routes by host only, never by path. For stateless sessions, lookup failures and unsafe host patterns it sends everything through VGS.

