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

### The request path

![AWG request path for Adyen client-side encryption: the agent's browser holds aliases only; the VGS session proxy runs a capture function and a re-encrypt function, and only the re-encrypt function reveals the card from the vault; every other host goes direct](docs/reference/request-path.svg)

This is VGS's own diagram, taken unchanged from the engineering spec of 2026-11-12. It shows the Adyen client-side-encryption flow, which is the reference integration:

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
