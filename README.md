# Agent Web Gateway (AWG): training and tools

**Internal to VGS. Do not share this repository outside VGS.** Two files are written for customers and may be shared: `docs/reference/04-developer-guide.md` and `openapi/awg-tenant-api.yaml`. Everything else names internal builds, hosts, vault ids and code locations.

AWG is pre-release. The reference docs describe it as of **2026-11-12**; the tools were last changed on 2026-11-16. Every statement in the training pages comes from the documents and code in this repository, except a few items taken from the test kit README of 2026-11-07 and from sandbox test notes, which are marked where they appear and listed in [SOURCES.md](SOURCES.md). That file also lists where each file came from, where the sources disagree, and what nobody has verified yet. The pages were checked line by line against those sources on 2026-11-16; nothing was run against a live environment. If the product has changed since those dates, the reference docs win over the training pages, and the running system wins over both.

## What AWG is

The Agent Web Gateway lets an AI agent pay on a merchant's website with a card stored in a VGS vault, without the agent, its browser or the customer's systems ever holding the card number.

1. The customer creates a **reveal session**: a short-lived proxy login scoped to the card or cards it may use, a list of hosts and a time window.
2. The agent's browser sends its traffic for those hosts through the VGS session proxy.
3. The agent types **session tokens** (stand-in values returned when the session is created) into the payment form, not the real card.
4. On the way to an allowed host, VGS puts the real card into the request. Where the payment provider encrypts the card in the browser (for example Adyen), an **adapter** made of small **functions** rebuilds the encrypted fields from the real card.
5. The merchant receives a normal payment request. If a function cannot run, the request fails rather than sending the stand-in or the card anywhere else.

### How a checkout flows

The first two pictures are slides from VGS's "Agent Web Gateway" deck (November 2026), unchanged. The deck is marked confidential, like this repository.

![Slide: the end-user card is stored as aliases on the agent platform; the platform creates a session and gets proxy settings and session tokens; the agent's browser types the session tokens at checkout; the Agent Web Gateway session swaps them for the real card on the way to the merchant](docs/images/awg-flow-token-swap.png)

Reading the numbers on the slide:

1. The end user's card.
2. The agent platform holds only aliases for it.
3. The platform creates a session.
4. The response returns the proxy settings and the session tokens. Here the card-number token keeps the first six and last four digits.
5. The agent's browser types the session tokens into the merchant's checkout form.
6. The purchase request, carrying the session tokens, goes to the session proxy.
7. The Agent Web Gateway session swaps the tokens for the real values.
8. The merchant receives the real card number and CVV.

The numbered reading is this page's; the slide itself has no legend.

### When the payment provider encrypts in the browser

![Slide: the checkout page's load-form response passes through the Agent Web Gateway session, which identifies the encryption key and stores it on the session; on purchase, the session reveals the card and replaces the encrypted token fields with fields encrypted from the original data](docs/images/awg-flow-client-side-encryption.png)

Here the browser encrypts what the agent typed before sending it, so a plain swap cannot work. The session does two things: when the payment form loads, it identifies the encryption key and stores it on the session; on purchase, it reveals the card and replaces the encrypted fields with fields built from the original data.

### The engineering view

![AWG request path for Adyen client-side encryption: the agent's browser holds aliases only; the VGS session proxy runs a capture function and a re-encrypt function, and only the re-encrypt function reveals the card from the vault; every other host goes direct](docs/reference/request-path.svg)

This diagram is taken unchanged from the engineering spec of 2026-11-12. It shows the same client-side-encryption flow for Adyen, the reference integration, with the parts named as they are in the API:

- The agent's browser holds stand-in values only, and reaches the payment hosts through the session proxy by way of the PAC file.
- The **capture function** reads the merchant's key and Adyen's `genTime` from the Adyen page and stores them as session values.
- The **re-encrypt function** is the only part that asks the vault for the card. It writes the encrypted fields into the checkout request.
- Every other host goes direct, per the PAC file, or through the session's egress proxy when one is set.

For merchants whose payment provider takes plain card fields, there are no functions: VGS swaps the session tokens for the real values on requests to allowed hosts. Page 1 explains both cases.

## Learning path

Read these in order. Budget about two hours for reading and half a day for the labs.

| # | Page | You will be able to |
|---|---|---|
| 1 | [What AWG is](docs/training/01-what-is-awg.md) | Explain the problem, the request path and what is and is not proven |
| 2 | [Concepts](docs/training/02-concepts.md) | Name the seven objects, the three kinds of card value and how a host is decided |
| 3 | [Lab: your first session](docs/training/03-lab-first-session.md) | Create, use, inspect and end a reveal session with `curl` |
| 4 | [Lab: a browser checkout](docs/training/04-lab-browser-checkout.md) | Open a browser through a session and type session tokens at a checkout |
| 5 | [Adapters and functions](docs/training/05-adapters-and-functions.md) | Decide whether a merchant needs an adapter, and configure and test one |
| 6 | [Testing merchant sites](docs/training/06-testing-merchant-sites.md) | Run the three test levels: probe, verify, purchase |
| 7 | [Troubleshooting](docs/training/07-troubleshooting.md) | Go from a symptom to a cause, and collect what an escalation needs |
| 8 | [Rules](docs/training/08-rules.md) | Work without exposing card data, secrets or other people's money |
| 9 | [Integration checklist](docs/training/09-integration-checklist.md) | Review a customer's integration, with the Playwright launch example |
| | [Self-check](docs/training/self-check.md) | Check what you learned; answers cite the page they come from |
| | [Glossary](docs/training/glossary.md) | Look up a term |

## What is in this repository

| Path | What it is |
|---|---|
| `docs/training/` | The training pages above |
| `docs/images/` | Two flow slides from VGS's "Agent Web Gateway" deck (November 2026) |
| `docs/comparison-evervault-browser-tokens.md` | AWG next to Evervault's Browser Tokens, row by row, from each side's own documents |
| `docs/reference/` | The engineering docs bundle of 2026-11-12, copied unchanged except for its README, which was rewritten: engineering spec, API detail, support runbook, customer developer guide, full API inventory |
| `openapi/` | OpenAPI 3.1 specs: 34 tenant operations and 15 admin operations |
| `examples/functions/` | H&M's Adyen re-encrypt function, and a deliberately broken copy for the harness demo |
| `tools/sitecheck/` | `awg-sitecheck`: a CLI that tests merchant sites at three levels, with the level 2 harness, adapter templates and recipes |
| `skills/vgs-checkout-adapter/` | A Claude Code / Codex skill for adapter authoring, with the `session-kit` scripts used in lab 4 |

## Before you start

You need these from the AWG team; none of them are in this repository:

- a service account (client id and secret) on a sandbox vault that is enabled for AWG, with the scopes `reveal-sessions:read`, `reveal-sessions:write`, `agent-gateway:read` and `agent-gateway:write`, plus the extra scopes named in lab 4 and page 6;
- the vault id (`tnt…`);
- for browser work against real merchants, a residential egress proxy you are authorized to use.

Never commit credentials, card files, session files or run output. Do the labs in a private folder outside this repository. The `.gitignore` files cover the tools' default locations; check `git status` before every commit.
