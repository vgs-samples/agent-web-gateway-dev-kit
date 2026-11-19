# 6. Testing merchant sites

**When you finish this page you can** find out whether an agent can shop on a merchant's site through AWG, using the `awg-sitecheck` tool.

> **Status: source-checked, not run.** The commands here were checked against the tool code. Nobody has run them as part of writing this page.

## The three levels

Test in this order. Go up a level only when the one below passes.

| Level | Command | The question it answers | Does it touch the merchant? |
|---|---|---|---|
| 1. Probe | `probe` | Can an agent reach the site through AWG? What blocks it? Which payment provider does it use? | Loads pages only |
| 2. Verify | `verify` | Does the adapter's encryption produce what the payment provider expects? | No |
| 3. Purchase | `purchase` | Does a whole checkout work? | Yes, a full checkout |

## What you need

1. Python 3.11 or later, and [uv](https://docs.astral.sh/uv/).
2. A service account on a sandbox tenant, with the scopes `reveal-sessions:write`, `reveal-sessions:read`, `agent-gateway:read` and `agent-gateway:write`.
3. The aliases of a card stored in that tenant.
4. A residential egress proxy you are authorized to use, and its password.
5. The tenant setting `agentGatewayBrowserEmulation=true`. Sites with bot protection need it. Ask the AWG team whether your tenant has it.

## Set up, once

### 1. Install the tool

```sh
cd tools/sitecheck
uv sync
uv run playwright install chromium
```

### 2. Create your two private files

```sh
cp sites.example.yaml sites.yaml
cp harness/card.example.json card.json
```

Git ignores both files, and the `runs/` folder the tool writes. Keep it that way.

### 3. Fill in `card.json`

Put your card's **aliases** in it, with the card's first six digits. Never put a card number in this file.

```json
{"label": "test", "number": {"alias": "tok_sandbox_…", "bin": "411111"}, "cvc": {"alias": "…", "length": 3}}
```

### 4. Fill in the top of `sites.yaml`

Under `defaults`, set:

| Key | What to put |
|---|---|
| `env` | `prod-sandbox` for Sandbox tests |
| `tenant` | Your tenant id |
| `egress` | The name of an egress profile further down the file |
| `context` | The card's expiry month and year |
| `contact` | The shopper's details the checkout will need. Use test identities where the site allows it |

### 5. Put your credentials in the shell

Nothing secret goes in a file in this folder.

```sh
read -r  VGS_CLIENT_ID
read -rs VGS_CLIENT_SECRET
read -rs SOAX_PASSWORD
export VGS_CLIENT_ID VGS_CLIENT_SECRET SOAX_PASSWORD
```

Each `read` waits for you to paste a value and press Enter. `SOAX_PASSWORD` is the example profile's variable; use the name your egress profile's `password_env` gives.

## Level 1: probe a site

### 6. Add the site

In `sites.yaml`, under `sites`, add an entry with three things:

```yaml
  - id: example-shop
    name: Example shop
    urls: ["https://www.example-shop.com/", "https://www.example-shop.com/p/some-product"]
```

### 7. Run the probe

```sh
uv run awg-sitecheck probe example-shop --direct
```

`--direct` also loads the same pages without AWG, through the egress proxy only. That is how you tell whether a block comes from the gateway path or from the site itself.

**Success:** the tool writes a folder `runs/probe-<time>/` with a scorecard (`scorecard.md`, `scorecard.html`) and, for the site, a `result.json`, a video and a final screenshot.

### 8. Read the verdict

| Verdict | What it means | What to do next |
|---|---|---|
| `reachable` | Every page loaded through AWG | Go to step 9 |
| `blocked-by-gateway-path` | Blocked through AWG, fine without it | The gateway path is the cause. Check the tenant has `agentGatewayBrowserEmulation=true` and the egress profile has a `sticky_suffix` |
| `blocked-even-direct` | Blocked through AWG, and the direct load also failed | Look at `direct_pages[].error` in `result.json` first. If the direct page really was blocked, the site blocks that exit IP or region: try another egress profile. This is not a gateway bug |
| `blocked` | Blocked through AWG, with no direct comparison | Run again with `--direct` |
| `errors` | A page errored, or returned something like a `404` or `500` | Look at `pages[].error` and the video |
| `error` | The run failed before any page was tried | Read the error in `result.json` |

### 9. Find the payment provider

A **recipe** is a short Python file with the clicks from the product page to the card form.

1. Copy `recipes/_template.py` to `recipes/example_shop.py` and fill it in.
2. Add `recipe: recipes/example_shop.py` to the site's entry in `sites.yaml`.
3. Run:

```sh
uv run awg-sitecheck probe example-shop --deep
```

**Success:** the verdict ends in `; payment-form-ok`, and the result names the payment provider and says whether it encrypts the card in the browser.

- If it does **not** encrypt in the browser, you need no adapter. Add the provider's API host to the site's `allowed_hosts` and go to level 3.
- If it **does**, you need an adapter. Do page 5, then level 2.

## Level 2: verify an adapter

This level exists for Adyen adapters today. It never contacts the merchant.

### 10. Run the harness

```sh
uv run awg-sitecheck verify harness/merchants/hm-us-prod-sandbox.json --card card.json
```

Always pass `--card`.

The harness sends the merchant's checkout request, with placeholders where the browser's encrypted fields would be, through the real session proxy to a test host that echoes it back. It then decrypts the result with a key it owns, and checks each field. It deletes everything it creates.

**Success:** every field reads `PASS`.

| Status | What it means |
|---|---|
| `PASS` | The field decrypted to the right value |
| `FAIL` | The field was not replaced, did not decrypt, has the wrong value, or something else in the request changed |
| `UNTESTED` | The harness could not test the field. Today that means a CVC field with a card that has no CVC alias |
| `NOTE` | The request came back unchanged, so the function did nothing |
| `INFO` | Timing, and the session's `reveal_count` and `refusal_count` |

To test an edited function without touching the live one, add `--function FN…=path/to/edited.star`.

## Level 3: a recorded checkout

### 11. Do a dry run of the checkout

```sh
uv run awg-sitecheck purchase example-shop
```

This runs the whole checkout and **stops before placing the order**. Stand-in values are typed into the card form; AWG reveals the real card.

**Success:** `runs/purchase-<time>/example-shop/` holds a video and a `result.json`. Hand both to a person to review.

### 12. Place an order, only with written approval

**Place an order only when a person has approved that item and a maximum total, in writing.** See page 8.

```sh
uv run awg-sitecheck purchase example-shop --purchase --max-total 30.00
```

The order is placed only if the total on screen is at or below `--max-total`. Nothing is retried once the order request has been sent. A person completes any 3-D Secure step or CAPTCHA.

## If a site blocks you

These come from the H&M US purchase of 2026-11-14.

| What you see | Why | Fix |
|---|---|---|
| `403` on every page through AWG, while direct is `200` | The site sees the gateway's network fingerprint instead of Chrome's | The tenant setting `agentGatewayBrowserEmulation=true` |
| Pages load, but adding to the cart answers `403` | The egress proxy changes your exit IP on each connection, and the site ties its cookies to one client | A sticky egress session: `sticky_suffix` on the egress profile in `sites.yaml` |
| Adding to the cart answers `403` now and then | The site's bot check had not finished | Call `run.browse()` in the recipe before the cart and checkout steps |
| The email step answers `403` every time, even without AWG | The site limits how often one email address can be looked up | A fresh contact email for the run |

Keep runs few and spaced out per site. Bot protection learns from repetition, and a burned exit IP or email address blocks everyone.

---

## Details and sources

- **Other ways to give credentials.** `VGS_ACCESS_TOKEN`, or on macOS `VGS_KEYCHAIN=<Keychain service>`; an egress profile can use `password_keychain`. Creating card aliases needs `aliases:write`; `vgs logs` needs `access-logs:read`.
- **Probe without a site id** runs every site in `sites.yaml`. `uv run awg-sitecheck report runs/probe-<time>` rebuilds a scorecard.
- **Level 1 and the card.** No card is typed, but the session still carries the card aliases when `sites.yaml` names a card.
- **Verdicts in full.** `blocked-even-direct` is given when a direct page was blocked, failed to load, or returned a status outside 200–399; `--direct` needs an egress profile. `errors` covers any status outside 200–399 that is not a recognised bot-wall block. A page that fails to load gives `errors`, not `error`.
- **`--deep` in full.** Without a `recipe:` it does nothing extra. The other suffixes are `; capture-missing` and `; recipe-failed`. It reports whether the key was captured when the site has an `adapter:` and the recipe lists `CAPTURE_KEYS`.
- **What the harness checks.** It first dry-runs the capture function on a saved payment page and checks the merchant's public key ends up in the session. Then each placeholder must have become a JWE under the harness's key, carrying a number that matches the card's BIN and length, the expiry from the session context, a `generationtime` from the page or the context (the report says which), and a CVC of the card's CVC length. Every other field must be unchanged. New bindings take time to reach the proxy; the harness waits up to 120 seconds by default.
- **Merchant files.** The files in `harness/merchants/` illustrate merchant request shapes. Replace tenant, adapter and binding IDs with values from your Sandbox account before running them. To add a merchant, see `tools/sitecheck/harness/README.md`.
- **`--card`.** Always supply your own card alias file. No card or account is bundled.
- **Managing adapters with the tool.** `uv run awg-sitecheck adapter plan|apply|dry-run|teardown <spec.yaml>` and `adapter list`. Page 5 uses them.
- **For AI agents** working in that folder, `tools/sitecheck/AGENTS.md` and the three skills under `tools/sitecheck/skills/` give the same workflow as instructions.

Sources: `tools/sitecheck/README.md`, `tools/sitecheck/AGENTS.md`, `tools/sitecheck/harness/README.md`, `tools/sitecheck/adapters/README.md`, `tools/sitecheck/docs/lessons.md`, `tools/sitecheck/skills/awg-site-probe/SKILL.md`, `tools/sitecheck/skills/awg-checkout-recipe/SKILL.md` (recipes), `tools/sitecheck/sites.example.yaml`, `tools/sitecheck/.gitignore`, `tools/sitecheck/pyproject.toml`, and the code: `tools/sitecheck/awg_sitecheck/cli.py`, `probe.py` (verdicts, `--deep`, the session card), `session.py`, `purchase.py` (`--max-total`), `adapters.py`, `tools/sitecheck/harness/awg_harness.py` (`--card`), `tools/sitecheck/harness/merchants/*.json`.
