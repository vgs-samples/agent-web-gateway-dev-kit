# AWG and Evervault Browser Tokens

**Internal. Do not share outside VGS, and do not quote to a customer without re-checking both columns.**

Evervault's Browser Tokens solve the same problem as AWG: an agent types stand-in values, and a forward proxy puts the real values into the request for approved destinations only. This page sets the two side by side so you can answer "how is this different?" accurately.

How to read it:

- The **Evervault** column is what Evervault's public documentation page said when it was read on 2026-11-16 (`https://docs.evervault.com/browser-tokens`). Text in quotation marks is quoted from that page. Nothing was tested against Evervault's product. Their page will change; re-read it before relying on a row.
- The **AWG** column is what the AWG sources in this repository say, as of 2026-11-12 for the reference docs and 2026-11-14 for `lessons.md`; rows that rely on the October 2026 doc set say so. AWG is pre-release.
- "Not stated" means the source read does not say. It does not mean the feature is absent.

## Side by side

| Topic | Evervault Browser Tokens (public docs, read 2026-11-16) | AWG (sources in this repository) |
|---|---|---|
| Stand-in values | Format-preserving tokens. Card number: "Luhn-valid, and preserves the original card length and BIN where applicable." CVV: "Preserves digit length" | Session tokens. Per the October 2026 doc set, a card-number token keeps the BIN and length and passes the Luhn check; a security-code token is random digits |
| How you create them | `POST https://api.evervault.com/browser-tokens` with `data`, `permissions`, `ttl` and `proxySettings` | `POST /reveal-sessions` with `cards` or `aliases`, `allowed_hosts`, optional `adapter`, `context`, `allowed_client_cidrs`, `egress_proxy_settings` |
| Lifetime | Set per request with `ttl` | A vault setting, default 300 seconds, minimum 30. It cannot be set per session |
| Reuse within the lifetime | "A token can be used more than once within its `ttl`" | Not stated explicitly. Each request is checked while the session is active; no source describes single-use tokens, and `guarded` mode applies reveal-guard limits |
| Server-side state | "Evervault never stores the plaintext or a server-side token mapping." | Sessions are stored by default, so they can be read, listed and counted. Storage can instead be stateless: the October 2026 doc set describes that as a vault setting, the 2026-11-12 inventory as a platform setting. A stateless session cannot be read |
| Ending early | Not stated | `DELETE /reveal-sessions/{id}` revokes a stored session at once. A stateless session can be revoked only when the vault's revocation list is on |
| Which destinations may receive real values | Per-token `permissions`: an exact hostname, a subdomain wildcard or `*`; an optional path; or an Evervault-managed allowlist of payment-related hosts (payment providers, gateways, wallets, 3-D Secure servers, card networks, fraud and bot vendors) | Per-session `allowed_hosts` (exact hosts, at most 20); per-vault agent destinations (`trust`, `guarded`, `block`); a VGS registry every vault inherits; and a never-host list that, per the October 2026 doc set, no session or tenant setting overrides |
| A host nothing allows | "the proxy behaves like a normal forward proxy and doesn't reveal the sensitive value" | Set by the vault's unlisted-host mode: `strict`, `guarded` or `step_up` (page 2) |
| Human approval of a new host | Not stated | `step_up` mode: the request is held while the customer's webhook is called, and approved or denied through the API |
| Restricting who may use the session | Not stated | `allowed_client_cidrs`, at most 10 ranges |
| Payment providers that encrypt in the browser | "some PSP-specific flows need shims, which Evervault manages on your behalf" | Adapters made of functions. VGS publishes some; customers can write, version and test their own. Adyen client-side encryption is the reference integration |
| Outbound IP | Evervault's addresses by default; a custom proxy; or managed residential egress, which "isn't enabled by default" and is turned on by their support team | VGS's own egress for hosts routed through VGS, unless the session sets the customer's own proxy in `egress_proxy_settings`; hosts outside the PAC list go to the session's egress proxy when one is set, otherwise direct from the browser. No AWG source describes a residential egress managed by VGS |
| Looking like a browser to the merchant | "It uses TLS and HTTP client impersonation techniques, so network fingerprints such as JA4 match expected browser behavior." | The vault preference `agentGatewayBrowserEmulation`: connections use Chrome's TLS and HTTP/2 settings, with no `Via` header (`lessons.md`) |
| Routing the browser | An HTTP CONNECT proxy, with a US and an EU endpoint | A proxy URL, plus a PAC file that sends the session's `allowed_hosts` and the hosts of enabled adapter destinations through VGS. No customer-selectable region is stated; the engineering spec names only the cell regions (dev in us-west-2, prod sandbox in us-east-1) |
| CAPTCHAs, MFA, 3-D Secure challenges | Not solved: "Evervault doesn't attempt to solve browser-level automation challenges such as CAPTCHAs, MFA, 3D Secure, or human-in-the-loop flows." "Frictionless 3D Secure works normally" | The test tool's rules require a human to complete 3-D Secure and CAPTCHAs (`AGENTS.md`). 3-D Secure through AWG was listed as untested on 2026-11-12 |
| Values other than cards | Passwords and other credentials are covered: "This applies to credentials as well as card data." | Sessions accept loose `aliases` with format `text` as well as card number and CVC. No AWG source describes a login flow |
| Seeing what happened | Guidance to "log which token categories were revealed and to which destinations"; each value's `id` is "reflected in the Evervault logs". No per-request decision record is described | `reveal_count` and `refusal_count` on the session; per-request access, operation and reveal-decision logs by `vgs-request-id` |
| Browser platforms named | Browserbase, Browserless, Kernel, Steel, local Chromium and Playwright | A Playwright example in the developer guide. No hosted platform is named in the sources here |
| PCI scope | A "PCI scope reduction" section with a production checklist | Not stated in any AWG source here |
| Spending limits | Not provided: "transaction authorization stays with the issuer or payment processor" | Not stated. The only amount cap in this repository is the test tool's `--max-total`, which is a guard in the CLI, not a gateway feature |

## What this means when you explain AWG

Where the AWG sources describe something Evervault's page does not:

- a stored session can be revoked at once, read back, and counted;
- every reveal or refusal is a recorded decision you can look up by request id, with a credential that has `access-logs:read`. Evervault's page mentions logs but describes no per-request decision record;
- a host can be held for human approval (`step_up`), and a session can be tied to client addresses;
- customers can write and test their own functions for a merchant; a harness that decrypts the result exists for Adyen today. Evervault's page says it manages provider-specific shims itself.

Where Evervault's page describes something the AWG sources do not:

- a lifetime chosen per request, down to seconds;
- path-level and wildcard destination rules on the token itself;
- residential egress managed by the vendor;
- a published statement on PCI scope, and a list of hosted browser platforms;
- public documentation. AWG's customer guide exists (`docs/reference/04-developer-guide.md`) but AWG is pre-release.

Neither side's documents claim to get an agent past a 3-D Secure challenge or a CAPTCHA without a person. Evervault's page says it does not enforce spending controls; no AWG source here describes a spending limit in the gateway.

## Where this repository goes further than a product page

Evervault's page is a single reference page with code samples. This repository adds two hands-on labs, a page on deciding whether a merchant needs an adapter, a three-level test tool with recordings, a symptom-to-cause troubleshooting page with an escalation checklist, working rules, a self-check, and a sources page that records what is unverified.

---

Sources: Evervault, "Browser Tokens", `https://docs.evervault.com/browser-tokens`, read 2026-11-16. AWG: `docs/reference/04-developer-guide.md`, `docs/reference/01-internal-engineering-spec.md`, `docs/reference/api-inventory-full.md`, `tools/sitecheck/docs/lessons.md`, `tools/sitecheck/AGENTS.md`.
