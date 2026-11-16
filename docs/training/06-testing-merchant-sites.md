# 6. Testing merchant sites

`tools/sitecheck/` holds `awg-sitecheck`, a CLI that tests a merchant site through AWG at three levels. Start at level 1 and go up only when the level below passes.

| Level | Command | Question it answers | Touches the merchant? | Card? |
|---|---|---|---|---|
| 1. Probe | `awg-sitecheck probe [site...] [--deep] [--direct]` | Can an agent reach the site through the gateway? What blocks it? Which PSP? | Pages only | None typed. The session still carries the card aliases when `sites.yaml` names a card |
| 2. Verify | `awg-sitecheck verify harness/merchants/<site>.json --card card.json` | Does the adapter's encryption produce what the PSP expects? | No (echo host) | Session card, through the proxy |
| 3. Purchase | `awg-sitecheck purchase <site> [--purchase --max-total N]` | Does a recorded checkout work end to end? | Full checkout | Stand-ins typed; real card revealed by the gateway |

## Install

Needs Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

```sh
cd tools/sitecheck
uv sync
uv run playwright install chromium
cp sites.example.yaml sites.yaml
cp harness/card.example.json card.json
```

`sites.yaml`, `card.json` and `runs/` are git-ignored. Keep them that way.

## Credentials

Nothing secret goes in a file in that folder.

| What | How |
|---|---|
| VGS API | `VGS_CLIENT_ID` and `VGS_CLIENT_SECRET`, or `VGS_ACCESS_TOKEN`, or on macOS `VGS_KEYCHAIN=<Keychain service>` |
| Scopes | `reveal-sessions:write`, `reveal-sessions:read`, `agent-gateway:read`, `agent-gateway:write`; `aliases:write` to create card aliases; `access-logs:read` for `vgs logs` |
| Vault preference | `agentGatewayBrowserEmulation=true`, set once per vault. Sites behind Akamai and similar bot walls need it |
| Egress proxy password | The environment variable named by the profile's `password_env`, or its `password_keychain` |

`card.json` holds vault aliases, never card data. `sites.yaml` sets the environment (`prod-sandbox` or `dev`), the vault, the egress profile, the session context and the shopper's contact details.

## Level 1: probe

```sh
uv run awg-sitecheck probe                          # every site in sites.yaml
uv run awg-sitecheck probe hm-us --direct --deep    # one site; also without the gateway, and through the recipe to the card form
uv run awg-sitecheck report runs/probe-<time>       # rebuild the scorecard
```

A new site needs only `id`, `name` and `urls` in `sites.yaml`. Each run writes `runs/probe-<time>/` with `scorecard.md`, `scorecard.html`, and per site a `result.json`, a video and `final.png`.

| Verdict | Meaning | Next step |
|---|---|---|
| `reachable` | Every page loaded through the gateway and none was blocked | Write a recipe, then `probe --deep` |
| `blocked-by-gateway-path` | Blocked through the gateway, fine with `--direct` | The gateway path is the cause. Check the vault has `agentGatewayBrowserEmulation=true` and the egress profile has a `sticky_suffix` |
| `blocked-even-direct` | Blocked through the gateway, and a direct page was also blocked or failed to load | Check `direct_pages[].error` first: `--direct` needs an egress profile. If the direct page really was blocked, the site blocks the exit IP or region; try another egress profile. Not a gateway bug |
| `blocked` | Blocked through the gateway, and no direct comparison was run | Run again with `--direct` |
| `errors` | A page errored, or returned a status outside 200–399 that is not a recognised bot-wall block (a `404` or `500`, for example) | Look at `pages[].error` and the video |
| `error` | The run failed before any page loaded | Read the error in `result.json` |

`--direct` is how you tell whose problem it is: it loads the same URLs through the egress proxy only. If direct is 200 and the gateway is 403, it is the gateway path. If both are 403, it is the site or the IP.

`--deep` runs the recipe named by the site's `recipe:` field in `sites.yaml` (the clicks from product page to card form) and reports the payment frames and the PSP. Without a `recipe:` it does nothing extra. It reports whether the key was captured when the site has an `adapter:` and the recipe lists `CAPTURE_KEYS`. With `--deep` the verdict gains a suffix: `; payment-form-ok` (ready for levels 2 and 3), `; capture-missing` or `; recipe-failed`.

## Level 2: verify

For Adyen adapters today. The files in `harness/merchants/` hold one vault's binding ids: `hm.json`, `jysk.json`, `dunelm.json` and `alza.json` belong to the dev vault, and the `*-prod-sandbox.json` files to a prod sandbox vault. For each merchant file you pass, the harness:

1. dry-runs the capture binding's function on a saved payment page and checks that the merchant's public key is what ends up in the session;
2. copies the merchant's checkout binding onto a unique path on an echo host, opens a session, plants a key **the harness owns** through the capture function, sends the merchant's checkout body with placeholders where the browser's ciphertext would be, and decrypts what comes back.

Each placeholder must have become a JWE under the planted key carrying a number that matches the card's BIN and length, the expiry from the session context, a `generationtime` from the page or the context (the report says which), and a CVC of the card's CVC length. Every other field must be unchanged. The merchant is never contacted, and the harness deletes everything it creates.

| Status | Meaning |
|---|---|
| `PASS` | The field decrypted to the right value |
| `FAIL` | The field was not replaced, did not decrypt, carries the wrong value, or something else in the body changed |
| `UNTESTED` | The harness could not test the field; today, a CVC field with a CVC-less card |
| `NOTE` | The body came back unchanged for the whole propagation window, so the function did not act on it |
| `INFO` | How long the bindings took to go live, and the session's `reveal_count` and `refusal_count` |

To iterate on a function without touching the live binding:

```sh
uv run awg-sitecheck verify harness/merchants/hm-us-prod-sandbox.json --card card.json --function FN…=path/to/edited.star
```

Always pass `--card`. Without it the harness looks for a dev smoke card through a module that is not in this repository, and exits.

Details and how to add a merchant: `tools/sitecheck/harness/README.md`.

## Level 3: purchase

```sh
uv run awg-sitecheck purchase hm-us                                 # stops before the order
uv run awg-sitecheck purchase hm-us --purchase --max-total 30.00    # places it
```

Without `--purchase` the run stops before the order. With `--purchase`, `--max-total` is required, and the order is placed only if the total shown is at or below it. Nothing is retried after the order request has been sent. A human completes 3-D Secure and CAPTCHAs.

**Place an order only when a human has approved that item and that maximum total in writing.** See page 8.

## Adapters as code

```sh
uv run awg-sitecheck adapter plan     adapters/adyen-cse/hm-us.yaml
uv run awg-sitecheck adapter apply    adapters/adyen-cse/hm-us.yaml
uv run awg-sitecheck adapter dry-run  adapters/adyen-cse/hm-us.yaml capture adapters/adyen-cse/fixtures/capture.json
uv run awg-sitecheck adapter list
uv run awg-sitecheck adapter teardown adapters/adyen-cse/hm-us.yaml
```

`apply` creates a new function when the source changes, adds an adapter version and moves the bindings to it. `teardown` removes bindings, then the adapter, then the functions.

## Typical flow for a new site

1. Add the site to `sites.yaml`, then run `probe <id> --direct`.
2. If it is `reachable`, write a recipe up to the card form (copy `recipes/_template.py`), set `recipe:` on the site in `sites.yaml`, and run `probe <id> --deep`, which reports the PSP.
3. If the PSP uses client-side encryption, write the adapter from the template, then `apply`, `dry-run` and `verify`.
4. Run `purchase <id>`; it stops before the order. Hand the video and `result.json` to a human.
5. Purchase only with written approval and a `--max-total`.

## What real sites taught the team

From the H&M US purchase of 2026-11-14 (`tools/sitecheck/docs/lessons.md`):

| Symptom | Cause | Fix |
|---|---|---|
| `403`, `Server: AkamaiGHost`, on every page through the gateway while direct is `200` | The site sees the gateway's TLS fingerprint and a `Via` header instead of Chrome's | Vault preference `agentGatewayBrowserEmulation=true` |
| Pages `200` but the cart POST answers `403` | The egress proxy rotates the exit IP per connection, and Akamai binds its cookies to the client | A sticky egress session (`sticky_suffix` in `sites.yaml`) |
| Cart POST `403` now and then | Akamai's sensor had not validated the session yet | `run.browse()` before cart and checkout POSTs |
| Email lookup POST `403` every time, even without the gateway | The site rate-limits lookups of one email address | A fresh contact email for the run |

Keep runs few and spaced per site. Bot walls learn from repetition, and a burned egress IP or email address blocks everyone.

For AI agents working in that folder, `tools/sitecheck/AGENTS.md` and the three skills under `tools/sitecheck/skills/` give the same workflow as instructions.

---

Sources: `tools/sitecheck/README.md`, `tools/sitecheck/AGENTS.md`, `tools/sitecheck/harness/README.md`, `tools/sitecheck/adapters/README.md`, `tools/sitecheck/docs/lessons.md`, `tools/sitecheck/skills/awg-site-probe/SKILL.md`, `tools/sitecheck/awg_sitecheck/probe.py` (verdicts), `tools/sitecheck/awg_sitecheck/purchase.py` (`--max-total`), `tools/sitecheck/pyproject.toml`.
