# Going deeper

You do not need any of this to get started; `./awg start` is enough. These pages are for when you want to understand or extend what the kit does.

- [The control panel in detail](control-panel.md)

## Learn Agent Web Gateway

Work through the pages in order. Reading takes about two hours; the two labs take about half a day.

| # | Page | When you finish you can |
|---|---|---|
| 1 | [What AWG is](training/01-what-is-awg.md) | Explain what AWG does and what it does not do |
| 2 | [Concepts](training/02-concepts.md) | Name the parts and say which card value goes where |
| 3 | [Lab: your first session](training/03-lab-first-session.md) | Create, use and end a session with `curl` |
| 4 | [Lab: a browser checkout](training/04-lab-browser-checkout.md) | Open a browser through a session and type session tokens at a checkout |
| 5 | [Adapters and functions](training/05-adapters-and-functions.md) | Decide whether a merchant needs an adapter, and set one up |
| 6 | [Testing merchant sites](training/06-testing-merchant-sites.md) | Test a merchant site at three levels |
| 7 | [Troubleshooting](training/07-troubleshooting.md) | Go from a symptom to a cause |
| 8 | [Rules](training/08-rules.md) | Work without exposing card data or secrets |
| 9 | [Integration checklist](training/09-integration-checklist.md) | Check your integration before it goes live |
| 10 | [Agent Web Gateway Control Panel](training/10-proxy-controls-extension.md) | Load the extension, connect an account, create/select sessions and switch routes |
| 11 | [Browser proxying best practices](../tools/vgs-proxy-controls/BROWSER-PROXY-BEST-PRACTICES.md) | Browse through egress, prepare a fresh session near checkout, and switch to VGS for the payment flow |

Then take the [self-check](training/self-check.md). The [glossary](training/glossary.md) defines every term.

## What you need before the labs

Ask your VGS contact for these. None of them are in this repository.

1. A service account (client id and secret) on a sandbox tenant that is enabled for AWG.
2. The tenant id. It starts with `tnt`.
3. These scopes on the service account: `reveal-sessions:read`, `reveal-sessions:write`, `agent-gateway:read`, `agent-gateway:write`. Lab 4 and page 6 name a few more.
4. For lab 4 and page 6, a residential egress proxy you are authorized to use.

Do the labs in a private folder outside this repository, and never commit credentials, card files, session files or run output.

## VGS documentation

The official documentation is at [docs.verygoodsecurity.com](https://docs.verygoodsecurity.com). These pages go with this kit:

| Topic | Page |
|---|---|
| Agent Web Gateway API | [API reference](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway): [reveal sessions](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway/reveal-sessions), [step-up approvals](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway/step-up-approvals), [destinations](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway/destinations), [functions](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway/functions), [adapters](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway/adapters), [adapter destinations](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway/adapter-destinations) |
| Agentic commerce | [Overview](https://docs.verygoodsecurity.com/agentic-commerce/agentic-commerce-overview), [agentic payments with a merchant user interface](https://docs.verygoodsecurity.com/agentic-commerce/agentic-payments-with-a-merchant-user-interface) |
| Getting set up | [Create a VGS vault](https://docs.verygoodsecurity.com/agentic-commerce/create-a-vgs-vault), [collect card data from a user](https://docs.verygoodsecurity.com/agentic-commerce/collect-card-data-from-user) |
| Service accounts and access tokens | [Authentication](https://docs.verygoodsecurity.com/cmp/platform/authentication), [service accounts](https://docs.verygoodsecurity.com/enterprise-platform/access-management/service-accounts-for-programmatic-access), [creating one with the VGS CLI](https://docs.verygoodsecurity.com/enterprise-platform/access-management/service-accounts-for-programmatic-access/creating-service-accounts-using-the-vgs-cli) |
| Storing a card | [Cards API](https://docs.verygoodsecurity.com/cmp/developer-resources/api/cards), [create a card using VGS Collect](https://docs.verygoodsecurity.com/cmp/developer-resources/guides/create-a-card-using-vgs-collect), [aliases](https://docs.verygoodsecurity.com/vault/tokens) |
| VGS CLI | [Getting started](https://docs.verygoodsecurity.com/vault/developer-tools/vgs-cli/getting-started), [commands](https://docs.verygoodsecurity.com/vault/developer-tools/vgs-cli/commands) |
| Proxying a browser | [Proxying websites via browser settings](https://docs.verygoodsecurity.com/vault/example-integrations/browser-proxy) |
| Going live | [Going live](https://docs.verygoodsecurity.com/vault/developer-tools/vault-management/going-live) |

## What is in this repository

| Path | What it is |
|---|---|
| `docs/training/` | The training pages |
| `docs/reference/` | The Agent Web Gateway developer guide, the API error codes, and a diagram of the request path |
| `openapi/` | The API specification |
| `tools/sitecheck/` | `awg-sitecheck`, the tool that tests merchant sites (page 6) |
| `tools/vgs-proxy-controls/` | Agent Web Gateway Control Panel source, local helper, tests and package builder (page 10) |
| `.github/workflows/control-panel-package.yml` | Tests the helper/worker and builds a downloadable source/helper artifact |
| `skills/vgs-checkout-adapter/` | A Claude Code skill for writing adapters, with the scripts lab 4 uses |
| `examples/functions/` | A real adapter function, and a broken copy for an exercise |
| `docs/images/` | The two flow diagrams used in the README and page 1 |

## Status

- Start in **Sandbox** and validate your integration there before using Live.
- The labs and tool walkthroughs are a preview: they follow the API reference and the tools' code and have not yet been validated end to end. Tell your VGS contact if a step does not behave as written.
- The control panel has local helper, worker and browser-fixture tests. Its screenshots use synthetic data.
- Where this kit and the running system differ, the running system is right.

A note on words: these pages say **tenant** for the VGS account an integration runs in, identified by its `tnt…` id. Some VGS documents say "vault" for the same thing. "Vault" here means only the place the card is stored.
