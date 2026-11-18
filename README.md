# Agent Web Gateway (AWG): training

**Internal to VGS. Do not share outside VGS.** Only two files here are written for customers: `docs/reference/04-developer-guide.md` and `openapi/awg-tenant-api.yaml`.

## What AWG does

AWG lets an AI agent pay on a merchant's website with a card stored in VGS, without the agent or its browser ever holding the card number.

![The agent platform holds aliases for the card, creates a session, and gets back proxy settings and session tokens; the agent's browser types the session tokens at checkout; the Agent Web Gateway session swaps them for the real card on the way to the merchant](docs/images/awg-flow-token-swap.png)

1. **You send VGS** the card's aliases and the hosts the agent may pay on. This creates a **reveal session**.
2. **You get back** a proxy login for the agent's browser and **session tokens**: stand-in card values that work only in that session.
3. **The agent types** the session tokens into the merchant's payment form.
4. **VGS swaps** the session tokens for the real card as the payment request passes through, for the allowed hosts only.
5. **The merchant receives** a normal payment request.

Some payment providers encrypt the card in the browser. For those, VGS runs an **adapter** that rebuilds the encrypted fields from the real card. Page 1 shows that case.

*Slide from VGS's "Agent Web Gateway" deck, November 2026.*

## Start here

Work through the pages in order. Reading takes about two hours; the two labs take about half a day.

| # | Page | When you finish you can |
|---|---|---|
| 1 | [What AWG is](docs/training/01-what-is-awg.md) | Explain what AWG does and what it does not do |
| 2 | [Concepts](docs/training/02-concepts.md) | Name the parts and say which card value goes where |
| 3 | [Lab: your first session](docs/training/03-lab-first-session.md) | Create, use and end a session with `curl` |
| 4 | [Lab: a browser checkout](docs/training/04-lab-browser-checkout.md) | Open a browser through a session and type session tokens at a checkout |
| 5 | [Adapters and functions](docs/training/05-adapters-and-functions.md) | Decide whether a merchant needs an adapter, and set one up |
| 6 | [Testing merchant sites](docs/training/06-testing-merchant-sites.md) | Test a merchant site at three levels |
| 7 | [Troubleshooting](docs/training/07-troubleshooting.md) | Go from a symptom to a cause |
| 8 | [Rules](docs/training/08-rules.md) | Work without exposing card data or secrets |
| 9 | [Integration checklist](docs/training/09-integration-checklist.md) | Review a customer's integration |
| 10 | [Proxy Controls extension](docs/training/10-proxy-controls-extension.md) | Switch a test browser between sessions and routes with one click (DEV only) |

Then take the [self-check](docs/training/self-check.md). The [glossary](docs/training/glossary.md) defines every term.

## What you need before the labs

Ask the AWG team for these. None of them are in this repository.

1. A service account (client id and secret) on a sandbox tenant that is enabled for AWG.
2. The tenant id. It starts with `tnt`.
3. These scopes on the service account: `reveal-sessions:read`, `reveal-sessions:write`, `agent-gateway:read`, `agent-gateway:write`. Lab 4 and page 6 name a few more.
4. For lab 4 and page 6, a residential egress proxy you are authorized to use.

Do the labs in a private folder outside this repository, and never commit credentials, card files, session files or run output.

## What is in this repository

| Path | What it is |
|---|---|
| `docs/training/` | The training pages |
| `docs/reference/` | VGS's AWG documents of 2026-11-12: engineering spec, API detail, support runbook, customer developer guide |
| `openapi/` | The API specs: 34 tenant operations and 15 admin operations |
| `tools/sitecheck/` | `awg-sitecheck`, the tool that tests merchant sites (page 6) |
| `tools/vgs-proxy-controls/` | A browser extension that switches a test browser between reveal sessions and routes (page 10) |
| `skills/vgs-checkout-adapter/` | A Claude Code skill for writing adapters, with the scripts lab 4 uses |
| `examples/functions/` | A real adapter function, and a broken copy for an exercise |
| `docs/images/` | Two slides from VGS's AWG deck |
| `docs/comparison-evervault-browser-tokens.md` | AWG next to Evervault's Browser Tokens |

## How far to trust this

- AWG is pre-release. The reference documents describe it as of **2026-11-12**.
- Every training page was checked line by line against those documents and the tool code.
- **Nothing was run against a live environment, and the labs have not been run end to end as written.** Code in the labs is source-checked, not tested.
- If the product has changed, the reference documents win over the training pages, and the running system wins over both.

[SOURCES.md](SOURCES.md) lists where each file came from, where the sources disagree, and what nobody has verified.

A note on words: these pages say **tenant** for the VGS account an integration runs in, identified by its `tnt…` id. The reference documents often say "vault" for the same thing. "Vault" here means only the place the card is stored.
