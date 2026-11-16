# 1. What AWG is

## The problem

An AI agent that shops for a person has to type a card number into a merchant's page. If the agent holds the real number, it can leak it or send it anywhere. AWG lets the agent complete the checkout while holding only stand-in values.

## The idea

The customer already stores the card in a VGS vault and keeps only **aliases** for it. When an agent is about to pay, the customer creates a **reveal session** for that card. The session is one agent task's credential: which card it may use, which hosts it may reach, for how long, and from where.

The create response returns:

- a proxy URL with the session's login (`proxy.url`);
- a link to a PAC file (`proxy.pac_url`), which tells a browser which hosts to send through VGS;
- a CA certificate (`proxy.ca_bundle`), which the browser must trust for those hosts;
- the session's stand-in card values (`tokens` and `cards`), which the agent types at checkout.

The proxy login, the PAC link and the stand-in values are returned only in this response; later reads never return secrets. (An endpoint that reissues the proxy password exists but is off by default.) The CA bundle can also be read from `GET /reveal-sessions/proxy-ca`.

VGS terminates TLS for the hosts that go through it. That is why the browser needs the CA, and it is what lets VGS change the payment request.

## The request path

```
agent's browser ──(PAC file)──▶ VGS session proxy ──▶ [customer's egress proxy, optional] ──▶ merchant / payment provider
                                 checks the session and the host,
                                 runs the adapter's functions,
                                 puts the real card into the request
all other hosts ─────────────────────────────────────────────────────────────────────────▶ direct (or through the egress proxy)
```

With the PAC file, the session's `allowed_hosts` and the host of every enabled adapter destination go through VGS. Everything else loads directly, or through the session's egress proxy when one is set. The PAC file falls back to sending everything through VGS for stateless sessions, lookup failures and unsafe host patterns, and builds that predate the PAC split send everything through VGS. The diagram the engineering spec uses is [request-path.svg](../reference/request-path.svg).

## Two ways the real card gets into the request

Which one a merchant needs depends on how its payment provider takes the card.

| How the card leaves the browser | What VGS does | Adapter needed? |
|---|---|---|
| Plain card fields posted to the provider's API | Replaces the session tokens in the request with the real values, for allowed hosts | No. Put the provider's API host in `allowed_hosts` |
| Client-side encryption: the browser encrypts the card with the provider's public key | Runs two functions: one stores the provider's key in the session, one replaces the browser's ciphertext with fields encrypted from the real card | Yes |

The Adyen client-side-encryption flow is the reference integration:

1. The browser loads the merchant's Adyen secured-fields page through the session proxy. A **capture function** reads the merchant's public key and Adyen's `genTime` from the page and stores them in the session.
2. The agent types the stand-in card into Adyen's fields. Adyen's iframe encrypts the stand-in.
3. The checkout request goes through the session proxy. A **re-encrypt function** reveals the session card from the vault, encrypts each value under the captured key, and replaces the browser's ciphertext. Nothing decrypts what the browser produced; it is discarded.
4. Only Adyen can decrypt the result.

## What AWG guarantees, and what it does not

- The card number exists in the vault and, for the moment of the request, inside VGS. The agent, its browser and the customer's servers handle aliases and session tokens.
- The session proxy refuses unless every check passes. No failure path reveals.
- If a function cannot run, the request fails. The stand-in card is not sent on and the real card is not sent anywhere else.
- A function that runs but does not recognise the request returns it unchanged, with no error. The request then goes out with the stand-in values, which are worthless to the receiver. This is the most common failure in testing.
- Some hosts can never receive real values (`never_host`), whatever a session says.
- A PAC file is a convenience, not enforcement. A browser that cannot fetch or apply it connects directly, and then nothing is revealed, refused or recorded.
- AWG does not get an agent past a merchant's bot protection. A `403` from the merchant comes from that protection, not from a VGS refusal. The gateway path can trigger it, through its TLS fingerprint, a `Via` header or the exit IP; page 6 shows how to tell and what to set.
- Wallets and redirects (PayPal, Klarna, Apple Pay) are out of scope for card reveal.

## Status

AWG is pre-release; both environments ran custom builds, not released versions, as of 2026-11-12.

| Date | What the sources record |
|---|---|
| 2026-11-12 | On dev, the harness decrypted re-encrypted bodies for H&M, JYSK, Dunelm and Alza bindings and found the test card number, the context expiry and the page's `generationtime`. The engineering spec states that no Adyen authorization through AWG on a real merchant had happened yet. |
| 2026-11-12 | The engineering spec states that prod sandbox ran a build from 2026-11-05 that "predates the PAC split, soft delete, session values reads and the Adyen 500 fix". |
| 2026-11-14 | `tools/sitecheck/docs/lessons.md` records an H&M US purchase through the gateway on prod sandbox: order placed, $29.31, with the confirmation page showing the real card's last four digits. |

The second and third rows do not fit together unless prod sandbox was updated between those dates. Nothing in this repository records that update, so ask the AWG team which build an environment runs before you rely on a feature there.

Known gaps listed in the engineering spec on 2026-11-12 include: a failed function reaches the client as a bare `422` with no reason; the PAC file splits by host only, so every page on a checkout host goes through VGS and loads more slowly; and 3-D Secure through AWG was untested. The full table is in [the engineering spec](../reference/01-internal-engineering-spec.md#known-gaps-and-open-work).

---

Sources: `docs/reference/04-developer-guide.md` (Overview, How it works), `docs/reference/01-internal-engineering-spec.md` (Overview, Proxy behavior, Environments, Known gaps), `docs/reference/README.md`, `tools/sitecheck/adapters/README.md`, `tools/sitecheck/docs/lessons.md`, `docs/reference/02-internal-api-detail.md` (credential reissue, `proxy-ca`).
