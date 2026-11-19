# Sources, disagreements and open points

The training pages in `docs/training/` were written on 2026-11-16 from the files below, plus the few external items listed under "Not included". Each numbered page ends with the sources it used. On 2026-11-16 every page was checked line by line against those sources by independent reviewers, corrected, and then audited a second time for facts, cross-references and consistency between pages. Nothing was tested against a live environment.

## Where each file came from

| Path here | Origin | Dated | Changed? |
|---|---|---|---|
| `docs/reference/01…04-*.md`, `request-path.svg`, `api-inventory-full.md` | AWG docs bundle (`awg-docs-bundle`), written from vault-management `awg/stack-top` at `d37e6452` and proxy `awg/stack-top` at `a02ccd315` | 2026-11-12 | Removed internal environment/deployment details and replaced an account example with a placeholder |
| `openapi/` | Same bundle | 2026-11-12 | No |
| `examples/functions/` | Same bundle, `harness/examples/` | 2026-11-12 | No |
| `docs/images/*.png` | Two slides exported from VGS's Google Slides deck "Agent Web Gateway" (dated Nov 2026, marked confidential): the token-swap flow and the client-side-encryption flow | 2026-11 | No |
| `tools/vgs-proxy-controls/` | Clean 1.7.6 source package plus maintained panel/helper changes, updated here as 1.10.0; `SHA256SUMS` covers the packaged files | 2026-11-19 | Current panel, recording/MCP tools, gateway views, session/CA fixes, publication checks and five synthetic screenshots |
| `tools/sitecheck/` | `awg-sitecheck` release of 2026-11-14, plus local changes made on 2026-11-15 and 2026-11-16 | 2026-11-16 | See below |
| `skills/vgs-checkout-adapter/` | The `vgs-checkout-adapter` skill, packaged 2026-11-13; its own provenance is in `references/source-notes.md` | 2026-11-19 | Session-kit compatibility fixes and adapter debugging reference |

Local changes in `tools/sitecheck/` relative to the 2026-11-14 release:

- `awg_sitecheck/browser.py`, `awg_sitecheck/purchase.py`: for recipes that call `run.require_success`, a failed page load now stops a checkout and records the status, a URL without credentials, the session id and the request id.
- `recipes/hm_us.py`: waits and retries when the checkout page's scripts are rate-limited.
- Added `recipes/ikea_us.py` and `tests/test_navigation_failures.py`.
- Replaced two machine-specific source paths in research documents with portable repository/commit references. Replaced account-bound tenant, adapter and binding examples with placeholders.
- Left out: four helper scripts tied to one person's Keychain and 1Password setup, and every credential, card, state and run-output file.

## Where the sources disagree

| Topic | Source A | Source B | How the training handles it |
|---|---|---|---|
| Session lifetime | Bundle: default 300 s, set per vault | Test kit README (2026-11-07): sessions on its sandbox vault "last about an hour (vault setting)" | Both stated: 300 s is the default, a vault can be set longer |
| What prod sandbox runs | Engineering spec, Environments (2026-11-12): a 2026-11-05 build that predates the PAC split, soft delete, session `values` reads and the Adyen 500 fix | `lessons.md`: an H&M US purchase on prod sandbox on 2026-11-14 that checked `include=values` | Both stated; the update between them is not recorded. Ask the AWG team |
| First real-merchant checkout | Engineering spec (2026-11-12): none yet | `lessons.md` (2026-11-14): H&M US order placed, $29.31 | Stated in date order |
| Adyen `generationtime` | v6 functions (JYSK, Dunelm, Alza) read it from session context | H&M's v7 function uses the page's `genTime` | Training recommends the page's time, as the bundle and `adapters/README.md` do |
| Stripe | `tools/sitecheck/adapters/README.md`: Stripe Elements needs no adapter | Skill `provider-notes.md`: a custom Stripe function exists for scoped reveal and space-formatted stand-ins | Page 5 states both: no adapter is the default, not a guarantee |
| Larky runtime | Engineering spec: Larky 1.1.0 | Skill `local-larky.md`: local tests pinned to the Larky 1.0.0 Linux binary | Not reconciled. Page 5 states both versions in its testing table |

## Stated in a source but not verified by anyone here

- The test kit README says an unlisted payment host gets `403 reveal_refused`. Per the bundle that holds only when VGS sees the request and the vault's mode refuses it; page 4 gives the full picture.
- That `session.card()` and aliases always fail in a dry run is stated in the developer guide and engineering spec, but its enforcement is open question 7 in `02-internal-api-detail.md`.
- Whether reading a session after `expires_at` returns `state: expired` or `404`.
- The commit hashes and origin paths in the first table come from the original bundle and its README, which are not copied here.
- The developer guide says three values are "returned only once", including the CA bundle, while its own API table lists `GET /reveal-sessions/proxy-ca`. The training says the CA bundle can also be read from that endpoint.
- The harness requires an explicit `--card` alias file for customer use. No card or account is bundled.
- The list of PSPs that need no adapter (Stripe, Braintree, Checkout.com, Shopify and others) comes from `tools/sitecheck/adapters/README.md`. Only Adyen CSE is recorded as tested end to end.
- 3-D Secure through AWG was listed as untested on 2026-11-12.
- Whether operation logs carry the text passed to `fail()` was listed as not yet checked.
- The ten open questions at the end of `docs/reference/02-internal-api-detail.md`.
- Which scope `POST /cards` needs (lab 4) is not stated in any source here.

## Not included

- Credentials, service accounts, vault secrets, egress proxy profiles, card alias files, session files, HAR captures and run recordings.
- The original `agent-gateway-test-kit` (2026-11-07). The session kit under `skills/vgs-checkout-adapter/scripts/session-kit/` is its portable successor. The training takes these from the original README, and says so where it does: sessions on that kit's vault lasted about an hour; a real merchant declines a test card, and what to check instead; the certificate issuer shows as Very Good Security; the exit IP should be a consumer ISP; and an unlisted payment host gets `403 reveal_refused`, which page 4 qualifies.
- Sandbox test notes of 2026-11-10, used for one statement on page 7.
- Customer names and the merchant research spreadsheet.

## Keeping this accurate

The control-panel update on 2026-11-19 publishes version 1.10.0 with recording,
MCP tools, gateway views, session/CA fixes, a build workflow, and five screenshots.
Only reviewed source was imported; private generated configuration and captures
were excluded. Documentation uses the official browser references linked in the
extension chapter and distribution guide.

Local verification passed 118 helper/privacy tests, 31 extension-worker tests and
24 session-kit tests. GitHub Actions passed isolated Chromium fixtures for MCP
capture, panel recording, gateway navigation, session aliases, activation and CA
downloads. The source and downloadable ZIP passed publication and secret scans.
Walkthrough screenshots use synthetic Sandbox data. No real VGS account, card
tokenization or merchant transaction was involved. Other browser/version
combinations and the end-to-end labs still need validation.

When the product changes, update `docs/reference/` from the new bundle first, then fix the training pages that cite the changed section, then update the dates in `README.md` and this file.
