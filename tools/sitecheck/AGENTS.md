# AGENTS.md: testing merchant sites through the VGS Agent Web Gateway

You are helping test whether AI agents can shop at real merchant sites through the VGS Agent Web Gateway, with
a card they never see. This folder is a CLI (`awg-sitecheck`), three skills, adapter templates and reference docs.

## What Agent Web Gateway does, in one paragraph

A **reveal session** (`POST /reveal-sessions`) gives the agent a proxy URL and **stand-in** card values. The agent's
browser goes through the proxy, which terminates TLS for the session's **allowed hosts**. Toward those hosts it swaps
stand-ins for the real values from the vault, and runs **functions** (Larky) that an **adapter** binds to specific
requests and responses. Payment providers that encrypt the card in the browser (client-side encryption, for example
Adyen) need a capture function, which stores the provider's public key in the session, and an encrypt function, which
rebuilds the encrypted fields from the real card.

## The three levels (pick the skill)

| Level | Command | Skill | Touches the merchant? | Card? |
|---|---|---|---|---|
| 1. Probe: reachable? bot wall? which PSP? | `awg-sitecheck probe [site...] [--deep] [--direct]` | `skills/awg-site-probe` | Pages only | No |
| 2. Verify adapter crypto | `awg-sitecheck verify harness/merchants/<site>.json --card card.json` | `skills/awg-adapter-authoring` | No (echo host) | Session card, through the proxy |
| 3. Recorded checkout | `awg-sitecheck purchase <site> [--purchase --max-total N]` | `skills/awg-checkout-recipe` | Full checkout | Stand-ins typed; real card revealed by the gateway |

Adapters and functions: `awg-sitecheck adapter plan|apply|dry-run|teardown|list <spec>`. Read `adapters/README.md`,
then `skills/awg-adapter-authoring/SKILL.md`.

## Setup

```sh
uv sync && uv run playwright install chromium
cp sites.example.yaml sites.yaml           # fill tenant, egress, contact; add sites
cp harness/card.example.json card.json     # aliases from your vault (see README "Card")
uv run awg-sitecheck probe hm-us           # smoke test
```

Credentials: see README.md, "Credentials". They come only from environment variables or the macOS Keychain.

## Hard rules

1. **Card data.** Never type, print, log or store a real card number or CVC. The card form gets the session's
   stand-ins only. `card.json` holds vault aliases, not card data.
2. **Purchases.** Place an order only when a human has approved the item and a maximum total in this conversation.
   Run with `--purchase --max-total`. Never retry after `submitted: true`. A human completes 3-D Secure and CAPTCHAs.
3. **Secrets.** Never print tokens, client secrets, proxy passwords or the session proxy URL. `session.secret.json`
   files are 0600 and deleted when the run ends. Don't commit `sites.yaml`, `card.json`, `runs/` or `state.*.json`.
4. **Evidence.** Report what the run shows: status codes, response headers, `result.json` fields, video timestamps,
   `reveal_count`. Say "unknown" instead of guessing why a site blocks.
5. **Be a polite client.** Keep runs few and spaced per site. Bot walls learn from repetition, and a burned egress IP
   or email address blocks everyone (see `docs/lessons.md`).
6. **Clean up.** Every run deletes its reveal session. Tear down adapters you created for experiments.

## Where things are

```
awg_sitecheck/     the CLI: config, api, session, browser (recording, warm-up, frames), probe, purchase, adapters, report, detect
recipes/           per-site checkout clicks (hm_us.py = worked example, _template.py)
adapters/          adapter specs + Larky: adyen-cse (tested end to end), _template-cse (other CSE providers), README (decision tree)
harness/           level 2: awg_harness.py + merchants/*.json + fixtures
skills/            awg-site-probe, awg-adapter-authoring, awg-checkout-recipe
docs/              developer-guide.md (function runtime), lessons.md (what real sites taught us)
```

## Typical flow for a new site

1. Add the site to `sites.yaml` (id, name, urls), then run `probe <id> --direct`.
2. If it's `reachable`, write `recipes/<id>.py` up to the card form and run `probe <id> --deep`, which reports the PSP.
3. If the PSP uses client-side encryption, write the adapter from the template, then `apply`, `dry-run` and
   `verify`.
4. Run `purchase <id>` (it stops before the order). Hand the video and `result.json` to a human.
5. Purchase only with written approval and a `--max-total`.
