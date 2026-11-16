# Reference docs

Copied unchanged from the AWG docs bundle of 2026-11-12. The bundle's own README, which this file replaces, states that all content reflects vault-management `awg/stack-top` at `d37e6452` and proxy `awg/stack-top` at `a02ccd315`, as of that date.

| File | Audience | What it is |
|---|---|---|
| `01-internal-engineering-spec.md` | VGS engineering | Architecture, data model, API summary, proxy check order and PAC rules, function runtime, auth, environments, known gaps |
| `02-internal-api-detail.md` | VGS engineering | Every endpoint's attributes, rules and error codes with `file:line` citations; open questions at the end |
| `03-support-runbook.md` | Support | Parts and ids, access, common lookups, symptom to cause to fix, escalation checklist, error codes |
| `04-developer-guide.md` | Customers | How it works, quickstart, sessions, adapters, PAC browser setup, writing functions, debugging, limits, API reference |
| `request-path.svg` | All | The request-path diagram used by the engineering spec |
| `api-inventory-full.md` | Engineering | The full code inventory the OpenAPI specs were built from |

The OpenAPI specs are in [`../../openapi/`](../../openapi/).

Before sharing outside VGS:

- **Share only `04-developer-guide.md` and `openapi/awg-tenant-api.yaml` with customers.** Everything else is internal: it names cells, builds, internal hosts and code locations.
- **The customer docs were ahead of prod sandbox on 2026-11-12.** Check which build an environment runs before telling a customer a feature is available there.
