# Agent Web Gateway: Developer Guide

## Overview

The Agent Web Gateway lets your AI agent check out on any website with a card stored in your VGS vault, without the agent, its browser or your systems ever holding the card number. You give the agent a **reveal session**: a short-lived proxy login scoped to the sites it may pay on and the card it may use. When the agent submits a payment form through that session, VGS puts the real card details into the request on its way to the merchant, in the format the merchant expects.

Use it when:

- an agent shops or pays on a merchant's site with a customer's stored card;
- the merchant encrypts card fields in the browser (for example Adyen client-side encryption), so a plain alias swap is not enough;
- you need each payment limited to known sites, one card and a short time window, with every reveal recorded.

The card number exists only in your VGS vault and, for the moment of the request, inside VGS. Your agent, its browser and your servers handle aliases.

## How it works

A checkout through the gateway has three parts: a session, a route for the agent's traffic, and functions that rewrite the payment request.

1. **Create a reveal session** with the card's aliases, the hosts the agent may reach, and any context the merchant needs (for example the card's expiry). The response gives you a proxy URL, a PAC file URL and a CA certificate.
2. **Route the agent's traffic.** Point the agent's browser at the PAC file, or set the proxy URL on an HTTP client. With the PAC file, only the merchant's payment hosts go through VGS; every other site loads directly.
3. **Functions do the merchant-specific work.** An adapter (for example `adyen`) holds functions that run on matching requests and responses. For Adyen client-side encryption, one function reads the merchant's encryption key from Adyen's payment page, and another replaces the encrypted card fields in the checkout request with the real card, encrypted under that key.
4. **The merchant receives a normal payment request.** Only the payment provider can decrypt the card fields.

The agent types a placeholder card into the payment form. If a function cannot run, the request fails rather than sending the placeholder or the card anywhere else.

## Quickstart

Create a session for a card you already store in VGS, then send a request through it. You need a service account with the `reveal-sessions:write` scope (and `agent-gateway:*` to configure adapters), and the destination host added as an agent destination.

1. Create the session. Replace the aliases with your card's.

```bash
curl -sS https://sandbox.vgsapi.com/reveal-sessions \
  -H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $VAULT_ID" \
  -H 'Content-Type: application/vnd.api+json' \
  -d '{"data": {"type": "reveal-sessions", "attributes": {
        "adapter": "adyen",
        "allowed_hosts": ["checkoutshopper-live.adyen.com", "www.example-shop.com"],
        "cards": [{"label": "main",
                   "number": {"alias": "tok_sandbox_...", "bin": "411111", "length": 16},
                   "cvc": {"alias": "tok_sandbox_...", "length": 3}}],
        "context": {"adyen_expiry_month": "03", "adyen_expiry_year": "2030"}}}}'
```

2. Keep three values from the `201` response; they are returned only once: `data.attributes.proxy.url` (proxy address with the session's login), `proxy.ca_bundle` (save it as `vgs-session-ca.pem`) and `proxy.pac_url`.
3. Send a request through the session from any HTTP client:

```bash
curl --proxy "$PROXY_URL" --proxy-cacert vgs-session-ca.pem --cacert vgs-session-ca.pem \
  https://www.example-shop.com/
```

A response that carries a `vgs-request-id` header went through VGS. For a browser, use the PAC file instead (see Using the PAC file in a browser).

4. End the session when the task is done: `DELETE /reveal-sessions/{id}` returns `204`. Sessions also expire on their own (by default after 5 minutes; your vault's settings can change this).

## Reveal sessions

A reveal session is one agent task's credential: which card it may use, which hosts it may reach, for how long, and from where. Create one per task and delete it when the task ends.

| Attribute | Required | Rules |
| --- | --- | --- |
| `cards` | `cards` or `aliases` | Each card: `label` (needed when there is more than one), `number` (`alias`, `bin`, `length`), optional `cvc`, `expiry`, `holder`. At most 20 alias parts per session. |
| `aliases` | `cards` or `aliases` | Loose aliases: `alias`, `format` (`card_number`, `card_cvc` or `text`), `bin`, `length`, `storage` (`PERSISTENT` or `VOLATILE`), `label` (text only). |
| `allowed_hosts` | no | Exact host names, at most 20; no wildcards, ports or IP addresses. Some hosts can never be allowed. |
| `adapter` | no | Adapter id or name. With an adapter, only its bindings run for the session. |
| `context` | no | Strings your functions read, e.g. `adyen_expiry_month`. At most 32 keys (`[a-z][a-z0-9_]*`), values up to 512 characters, 4096 characters in total. |
| `allowed_client_cidrs` | no | Addresses or ranges the agent connects from, at most 10. Empty means any. |
| `egress_proxy_settings` | no | Your own outbound proxy: `type: custom`, `scheme` (`http`/`https`), `hostname`, `port`, `username`, `password` (write-only). |

You cannot set the lifetime or the unlisted-host behavior per session; both come from your vault's settings. The lifetime defaults to 5 minutes (minimum 30 seconds).

**What the create response returns once:** `proxy.url` (with the session's password), `proxy.ca_bundle`, `proxy.pac_url`, and the session alias values in `tokens` and `cards`. Store what you need; later reads never return secrets.

**Reading a session:** `GET /reveal-sessions/{id}` returns `state` (`active`, `revoked`, `expired`), `expires_at`, `allowed_hosts`, `context`, `adapter`, `reveal_count`, `refusal_count` and `unlisted_host_mode`. Add `?include=values` to see what your functions stored, keyed by adapter id:

```json
"values": { "AD…your adapter id…": { "adyen_public_key": "10001|ACBF0D…", "adyen_generationtime": "2026-11-12T11:22:48Z" } }
```

**Unlisted hosts.** A request to a host outside `allowed_hosts` and your agent destinations follows your vault's mode: `strict` refuses it, `guarded` allows it within guard limits, and `step_up` holds it until you approve it through your step-up webhook and `PATCH /reveal-session-approvals/{id}`.

## Destinations, adapters and functions

Four pieces of configuration decide what happens to the agent's traffic; you set them up once per merchant integration, not per session.

| Piece | What it does | Endpoint |
| --- | --- | --- |
| Agent destination | Names a host your agents may use and how VGS treats it: `trust`, `guarded` or `block` | `/agent-gateway-destinations` |
| Function | A VGS Compute function that processes requests (`route.request`) or responses (`route.response`) inside the gateway | `/functions` |
| Adapter | A named bundle of functions with numbered versions, e.g. `adyen` v7 | `/agent-gateway-adapters` |
| Adapter destination | Runs chosen functions of one adapter version on traffic that matches a host, method and path | `/agent-gateway-adapter-destinations` |

VGS also publishes a registry of trusted destinations and VGS-owned functions and adapters. Your vault inherits the registry (`GET /agent-gateway-registry`), and you can use VGS functions and adapters in your own adapters and destinations.

Setting up a merchant, in order:

1. **Add the hosts** as agent destinations: the merchant's checkout host and its payment provider's page host (for Adyen, `checkoutshopper-live.adyen.com`).
2. **Create the functions.** Functions are immutable: an edit is a new function; link it to the old one with `previous_version`.
3. **Create or version the adapter** with those functions (`POST /agent-gateway-adapters`, or `POST /agent-gateway-adapters/{id}` for a new version).
4. **Bind them with adapter destinations.** Example: run the re-encrypt function on the merchant's checkout POST, reading the card form from the request body.

```json
{"data": {"type": "agent-gateway-adapter-destinations", "attributes": {
  "adapter": "adyen", "adapter_version": 7, "enabled": true,
  "when": {"host": "www.example-shop.com", "method": "POST", "path": "/*/checkout/proceed"},
  "functions": [{"id": "FN…", "inputs": {
    "adyen_form": {"from": "request.body", "path": "$.paymentData.encryptedForm"}}}]}}}
```

Rules to know:

- `when.host` must be one of your agent destinations that is not blocked; `path` may use `*`.
- A destination runs only functions of the adapter version it names. To roll out a new version, `PATCH` the destination's `adapter_version`.
- Two enabled destinations cannot run functions in the same phase on traffic both could match (`409 destination_overlap`).
- Input sources: `constant`, `request.body` / `response.body` (a JSONPath), `request.header` / `response.header` / `request.query`. A request function reads request sources only; a response function reads response sources only.
- Deleting a function that an adapter still uses returns `409 function_in_use`; deleting an adapter a destination uses returns `409 adapter_in_use`. Delete destinations first, then adapters, then functions.

## Using the PAC file in a browser

Point the browser at the session's `proxy.pac_url` and answer the proxy's login with the session's credentials; only the session's allowed hosts and its adapter's payment hosts then go through VGS. Every other site loads directly, which keeps browsing fast.

Three things to get right:

- **Use a full Chromium or Chrome.** The browser must honor `--proxy-pac-url`. Playwright's default headless shell ignores it; launch with `channel: 'chromium'` (or `'chrome'`).
- **Answer the proxy login.** A PAC file cannot carry credentials, so the proxy asks for them (`407`). The username is the session id and the password is the password in `proxy.url`. In Playwright, answer through the DevTools protocol, as below.
- **Trust the session's CA** (`proxy.ca_bundle`) for the hosts that go through VGS: VGS terminates TLS for those hosts to run your functions.

```javascript
import { chromium } from '@playwright/test';

const session = /* POST /reveal-sessions response */.data.attributes;
const proxy = new URL(session.proxy.url);

// a persistent context is the default profile, which the command-line PAC applies to
const context = await chromium.launchPersistentContext(profileDir, {
  channel: 'chromium',
  args: [`--proxy-pac-url=${session.proxy.pac_url}`],
});
const page = context.pages()[0] ?? await context.newPage();
const cdp = await context.newCDPSession(page);
await cdp.send('Fetch.enable', { handleAuthRequests: true, patterns: [{ urlPattern: '*' }] });
cdp.on('Fetch.requestPaused', e => cdp.send('Fetch.continueRequest', { requestId: e.requestId }));
cdp.on('Fetch.authRequired', e => cdp.send('Fetch.continueWithAuth', {
  requestId: e.requestId,
  authChallengeResponse: e.authChallenge.source === 'Proxy'
    ? { response: 'ProvideCredentials',
        username: decodeURIComponent(proxy.username),
        password: decodeURIComponent(proxy.password) }
    : { response: 'CancelAuth' },
}));
```

To check the routing, look for the `vgs-request-id` response header: requests that went through VGS carry it, direct ones do not. Pages on a host that goes through VGS load more slowly than direct ones, because the PAC file can route by host only, not by path.

## Writing functions

A VGS Compute function processes a request or response inside the gateway. It can transform a provider payload, retrieve authorized vault data, and save values in the session for later requests. Its entry point, `process(input, ctx)`, returns the request or response, changed or not. It runs at one extension point: `route.request` (before a request leaves VGS) or `route.response` (when the response comes back).

[VGS Compute](https://docs.verygoodsecurity.com/vault/developer-tools/larky) uses the Starlarky runtime. Functions are written in Larky, which has Python-like syntax.

```python
load("@vgs//agent_gateway", session="session")
load("@vgs//vault", vault="vault")
load("@stdlib//json", json="json")
adapter_input = None   # filled in by VGS with this binding's inputs

def process(input, ctx):
    body = json.loads(input.body())
    form = body.get("paymentMethod")
    if type(form) != "dict" or "encryptedCardNumber" not in form:
        return input                              # not ours: pass it on unchanged
    key = session.get("adyen_public_key")         # stored by the capture function
    if not key:
        fail("Load the payment page in this session first")
    number, = vault.reveal([session.card().number])
    form["encryptedCardNumber"] = encrypt(number, key)   # your encryption helper
    input.set_body(json.dumps(body))
    return input
```

| Call | What it does |
| --- | --- |
| `input.body()`, `input.set_body(text)` | Read and replace the body (text) |
| `adapter_input(input, "name")` | The value of an input, as bound on the adapter destination |
| `session.context("key")` | A value you passed when creating the session |
| `session.get("key")`, `session.put("key", value)` | Values functions share across requests of one session |
| `session.card()`, `session.card("label")` | The session's card: `.number` and `.cvc` aliases |
| `vault.reveal([aliases])` | The card values for those aliases, in order |
| `fail("message")` | Stops the request; the agent receives `422` with a request id |

Good practice, from real integrations:

- **Return the input unchanged when the request is not one you handle.** A function that does nothing raises no error, so test that it acts on your merchant's real request body.
- **Check what the card has before revealing it.** Revealing a CVC the card does not have fails the whole request; check `card.cvc` first.
- **Use the payment page's own time where the provider needs one.** Adyen checks the encryption's `generationtime`; the capture function can store the page's `genTime` with `session.put`.

## Testing and debugging

Test a function with a dry run before you bind it, then trace live requests by their request id.

**Dry run a function.** `POST /functions/{id}/invocations` runs it on a request or response you supply, without a session or a merchant. Give the inputs as plain values and, if the function reads them, the session values and context it would see:

```json
{"data": {"type": "function-invocations", "attributes": {
  "request": {"method": "POST", "url": "https://www.example-shop.com/en_us/checkout/proceed",
              "headers": {"Content-Type": "application/json"}, "body": "{\"paymentMethod\": {}}"},
  "inputs": {"adyen_form": "{}"},
  "session": {"values": {"adyen_public_key": "10001|…"}, "context": {"adyen_expiry_month": "03"}}}}}
```

The response is `201` with `status` `succeeded` or `failed`, the `error` text if it failed, and `result` with the rewritten request (or response) and `result.session.values`. A `route.response` function takes a `response` only. A dry run has no card: `session.card()` and aliases always fail there, so test reveals with a real session.

**Trace a live request.** Every request through VGS gets a `vgs-request-id` response header; a failed function's `422` body contains it too. With that id:

- `vgs logs operations -T <vault id> -R <request id>`: the operation logs for that request;
- `vgs logs access -T <vault id> --since=1h`: the vault's access logs. This command has no request-id option; narrow it with `--since`, `--until` or `--tail`.

These need a credential with `access-logs:read`. They are the commands in VGS CLI 1.36.0 and the public CLI reference; that release has no `vgs logs reveal-decisions` command, so ask your VGS contact how to see the reveal decisions for a request.

**Check the session.** `GET /reveal-sessions/{id}?include=values` shows whether the capture function stored the payment key, and `reveal_count` / `refusal_count` show whether a reveal happened. A request that came back unchanged with `reveal_count` still `0` means your function ran but did not act on that body: compare its field names and nesting with the merchant's real request.

## Errors and limits

API errors use one envelope: `{"errors": [{"status", "code", "title", "detail", "href"}]}`. Validation (`400`) and conflict (`409`) errors carry a `code`; `403` means a missing scope and `404` an unknown or foreign id.

Errors the agent sees through the proxy:

| Response | Meaning | What to do |
| --- | --- | --- |
| `407` | The proxy did not accept the session login: wrong password, expired or revoked session, or a vault not enabled for sessions | Check `state` and `expires_at`; create a new session |
| Request refused by VGS | The host is not allowed for the session and your vault's mode refuses it, or the client address is outside `allowed_client_cidrs` | Add the host to `allowed_hosts` or as an agent destination |
| `422 Request processing error. Request id: …` | A function stopped the request (`fail()` or an error) | Look up the request id in the operation logs; dry-run the function on the same body |
| `403` from the merchant | The merchant's bot protection blocked the request; this is not a VGS error | Use a real browser through the PAC file and, if needed, `egress_proxy_settings` |

Common API codes: `invalid_host`, `never_host`, `too_many_hosts`, `invalid_context`, `invalid_adapter`, `ttl_not_configurable` (sessions); `unknown_host`, `function_not_in_adapter`, `invalid_inputs`, `destination_overlap` (adapter destinations); `invalid_source`, `source_too_large` (functions); `function_in_use`, `adapter_in_use` (deletes).

| Limit | Value |
| --- | --- |
| Alias parts per session | 20 |
| Allowed hosts per session | 20 |
| Client ranges per session | 10 |
| Context | 32 keys, 512 characters per value, 4096 in total |
| Session lifetime | Vault setting; default 5 minutes, minimum 30 seconds |
| Agent destinations per vault | 1000 |
| Adapter destinations per vault | 100 |
| Functions per adapter version | 32 |
| Functions per adapter destination | 16 |
| Function source | 256 KiB |
| Function inputs | 32 |
| Dry run | 10 s, 1 MiB per body |

## API reference

All endpoints are JSON:API on `https://sandbox.vgsapi.com` (sandbox) and `https://vgsapi.com` (live), with your vault id in the `VGS-Tenant` header. Write scopes do not include read.

| Method and path | Scope | Purpose |
| --- | --- | --- |
| `POST /reveal-sessions` | `reveal-sessions:write` | Create a session (`201`; returns the proxy login, CA and PAC link once) |
| `GET /reveal-sessions?state=active\|revoked` | `reveal-sessions:read` | List sessions, paged (`offset`, `limit` up to 100) |
| `GET /reveal-sessions/{id}[?include=values]` | `reveal-sessions:read` | Read a session, optionally with function values |
| `DELETE /reveal-sessions/{id}` | `reveal-sessions:write` | Revoke a session (`204`) |
| `GET /reveal-sessions/proxy-ca` | `reveal-sessions:read` | The proxy's CA bundle and address |
| `GET /reveal-sessions/{id}.pac?…` | none (signed link) | The session's PAC file, from `proxy.pac_url` |
| `GET /reveal-session-approvals?filter[reveal_session]={id}` | `reveal-sessions:read` | Held step-up requests of a session |
| `GET /reveal-session-approvals/{id}` | `reveal-sessions:read` | One held request |
| `PATCH /reveal-session-approvals/{id}` | `reveal-sessions:write` | Approve or deny (`state`), for one request or the session (`scope`) |
| `GET`, `POST /agent-gateway-destinations`; `GET`, `PATCH`, `DELETE /agent-gateway-destinations/{id}` | `agent-gateway:read` / `:write` | Your agent destinations (`host_pattern`, `action`) |
| `GET /agent-gateway-registry` | `agent-gateway:read` | VGS's trusted destinations, inherited by your vault |
| `GET`, `POST /functions`; `GET`, `DELETE /functions/{id}` | `agent-gateway:read` / `:write` | Your functions and VGS's |
| `POST /functions/{id}/invocations` | `agent-gateway:write` | Dry-run a function (`201`, with `result`) |
| `GET /function-invocations`, `GET /function-invocations/{id}` | `agent-gateway:read` | Past runs (without results) |
| `GET`, `POST /agent-gateway-adapters`; `GET`, `DELETE /agent-gateway-adapters/{id}` | `agent-gateway:read` / `:write` | Adapters |
| `POST /agent-gateway-adapters/{id}` | `agent-gateway:write` | Add a version (`functions`) |
| `PATCH /agent-gateway-adapters/{id}` | `agent-gateway:write` | Publish the latest version (`publish_at`: `now` or a time) |
| `GET`, `POST /agent-gateway-adapter-destinations`; `GET`, `PATCH`, `DELETE /agent-gateway-adapter-destinations/{id}` | `agent-gateway:read` / `:write` | Bind adapter functions to traffic (`when`, `functions`, `adapter_version`) |
