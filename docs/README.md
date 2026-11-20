# Going deeper

You do not need any of this to get started; `./awg start` is enough. These pages are for when you want to understand or extend what the kit does.

- [Setup, credential provisioning, and validation coverage](setup.md)
- [Control Panel: installation, sessions, recording, and troubleshooting](control-panel.md)
- [MCP companion: connect an assistant to captures and gateway tools](mcp.md)
- [Browser proxying: egress, PAC routing, and checkout timing](browser-proxying.md)

## Learn Agent Web Gateway

Work through the pages in order. Reading takes about two hours; the two labs take about half a day.

| # | Page | When you finish you can |
|---|---|---|
| 1 | [What is the Agent Web Gateway?](training/01-what-is-agent-web-gateway.md) | Explain what Agent Web Gateway does and what it does not do |
| 2 | [Concepts](training/02-concepts.md) | Name the parts and say which card value goes where |
| 3 | [Lab: your first session](training/03-lab-first-session.md) | Create, use and end a session with `curl` |
| 4 | [Lab: a browser checkout](training/04-lab-browser-checkout.md) | Open a browser through a session and type session tokens at a checkout |
| 5 | [Adapters and functions](training/05-adapters-and-functions.md) | Decide whether a merchant needs an adapter, and set one up |
| 6 | [Testing merchant sites](training/06-testing-merchant-sites.md) | Test a merchant site at three levels |
| 7 | [Troubleshooting](training/07-troubleshooting.md) | Go from a symptom to a cause |
| 8 | [Rules](training/08-rules.md) | Work without exposing card data or secrets |
| 9 | [Integration checklist](training/09-integration-checklist.md) | Check your integration before it goes live |
| 10 | [Agent Web Gateway Control Panel](training/10-proxy-controls-extension.md) | Load the extension, connect an account, create/select sessions and switch routes |
| 11 | [Browser proxying best practices](browser-proxying.md) | Browse through egress, prepare a fresh session near checkout, and switch to VGS for the payment flow |

Then take the [self-check](training/self-check.md). The [glossary](training/glossary.md) defines every term.

## Build adapters with your coding assistant

The [checkout adapter skill](../skills/vgs-checkout-adapter/SKILL.md) includes the instructions, scripts, and smoke-test fixtures for the full workflow:

1. [Read the checkout HAR](../skills/vgs-checkout-adapter/references/har-review.md) and identify the card request, encryption format, and key exchange.
2. [Test VGS Compute functions locally](../skills/vgs-checkout-adapter/references/local-larky.md) with the pinned Starlarky/Larky runtime and synthetic fixtures.
3. [Register the functions, adapter, and bindings](../skills/vgs-checkout-adapter/references/deploy-adapters.md), then [verify them through the gateway](../skills/vgs-checkout-adapter/references/gateway-verification.md).
4. [Debug a failing adapter](../skills/vgs-checkout-adapter/references/debug-adapters.md) by reproducing the captured request and testing the repair.

The local runner tests function logic; it does not establish gateway or merchant compatibility. Runtime setup requires Docker. The separate Capture Console mentioned in the capture guide is not bundled; you can also start with an existing HAR.

## What you need before the labs

Run `./awg setup` to log in, confirm your organization, and automatically provision the Sandbox service account. [The setup guide](setup.md) explains tenant selection and the granted scopes. Your organization needs an accessible Sandbox tenant enabled for Agent Web Gateway; contact its administrator if setup reports missing access. The saved credentials and tenant ID remain in the private kit directory.

For lab 4 and page 6, use an egress proxy you are authorized to use and have explicitly selected for that test.

Do the labs in a private folder outside this repository, and never commit credentials, card files, session files or run output.

## VGS documentation

The official documentation is at [docs.verygoodsecurity.com](https://docs.verygoodsecurity.com). These pages go with this kit:

| Topic | Page |
|---|---|
| Agent Web Gateway API | [API reference](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway): [reveal sessions](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway/reveal-sessions), [step-up approvals](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway/step-up-approvals), [destinations](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway/destinations), [functions](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway/functions), [adapters](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway/adapters), [adapter destinations](https://docs.verygoodsecurity.com/agentic-commerce/developer-resources/api-reference/agent-web-gateway/adapter-destinations) |
| OpenAPI | [Official API specification](https://openapi.gitbook.com/o/hcowjO8ckQ1K5fm3NPZH/spec/agent-web-gateway-api.yaml) |
| Agentic commerce | [Overview](https://docs.verygoodsecurity.com/agentic-commerce/agentic-commerce-overview), [agentic payments with a merchant user interface](https://docs.verygoodsecurity.com/agentic-commerce/agentic-payments-with-a-merchant-user-interface) |
| Getting set up | [Create a VGS vault](https://docs.verygoodsecurity.com/agentic-commerce/create-a-vgs-vault), [collect card data from a user](https://docs.verygoodsecurity.com/agentic-commerce/collect-card-data-from-user) |
| Service accounts and access tokens | [Authentication](https://docs.verygoodsecurity.com/cmp/platform/authentication), [service accounts](https://docs.verygoodsecurity.com/enterprise-platform/access-management/service-accounts-for-programmatic-access), [creating one with the VGS CLI](https://docs.verygoodsecurity.com/enterprise-platform/access-management/service-accounts-for-programmatic-access/creating-service-accounts-using-the-vgs-cli) |
| Storing a card | [Cards API](https://docs.verygoodsecurity.com/cmp/developer-resources/api/cards), [create a card using VGS Collect](https://docs.verygoodsecurity.com/cmp/developer-resources/guides/create-a-card-using-vgs-collect), [aliases](https://docs.verygoodsecurity.com/vault/tokens) |
| VGS CLI | [Getting started](https://docs.verygoodsecurity.com/vault/developer-tools/vgs-cli/getting-started), [commands](https://docs.verygoodsecurity.com/vault/developer-tools/vgs-cli/commands) |
| VGS Compute | [Overview and runtime](https://docs.verygoodsecurity.com/vault/developer-tools/larky), [function syntax](https://docs.verygoodsecurity.com/vault/developer-tools/larky/larky_overview) |
| Proxying a browser | [Proxying websites via browser settings](https://docs.verygoodsecurity.com/vault/example-integrations/browser-proxy) |
| Going live | [Going live](https://docs.verygoodsecurity.com/vault/developer-tools/vault-management/going-live) |

## What is in this repository

| Path | What it is |
|---|---|
| `awg` | The launcher: `./awg start`, `./awg setup` and the other commands `./awg --help` lists |
| `tools/cloak/` | The script `./awg start` uses to open CloakBrowser with the control panel loaded |
| `docs/training/` | The training pages |
| `docs/reference/` | The Agent Web Gateway developer guide, the API error codes, and a diagram of the request path |
| `tools/sitecheck/` | `awg-sitecheck`, the tool that tests merchant sites (page 6) |
| `tools/vgs-proxy-controls/` | Agent Web Gateway Control Panel source, local helper, tests and package builder (page 10) |
| `.github/workflows/control-panel-package.yml` | Tests the helper/worker and builds a downloadable source/helper artifact |
| `skills/vgs-checkout-adapter/` | A coding-agent skill for creating adapters from HAR evidence, with local runtime setup, a test runner, smoke fixtures, registration and verification guides, and the session scripts lab 4 uses |
| `tools/bootstrap/`, `tests/` | CLI onboarding and offline bootstrap/wrapper coverage |
| `examples/adapters/` | Adyen, CyberSource, Stripe, and OPPWA examples, each with its own functions, bindings, tests, and synthetic HAR fixtures |
| `docs/images/` | Payment-flow and egress-routing diagrams |

## Status

- Start in **Sandbox** and validate your integration there before using Live.
- The labs and tool walkthroughs are a preview: they follow the API reference and the tools' code and have not yet been validated end to end. Tell your VGS contact if a step does not behave as written.
- The control panel has local helper, worker and browser-fixture tests. Its screenshots use synthetic data.
- Where this kit and the running system differ, the running system is right.

A note on words: these pages say **tenant** for the VGS account an integration runs in, identified by its `tnt…` id. Some VGS documents say "vault" for the same thing. "Vault" here means only the place the card is stored.
