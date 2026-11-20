---
name: awg-site-probe
description: Level 1 of Agent Web Gateway site testing. Use when asked whether a merchant site works through the VGS Agent Web Gateway, to triage a list of sites, to find which bot wall or payment provider a site uses, or to build the scorecard of many sites. No card is typed and nothing is bought.
---

# Probe sites through the Agent Web Gateway

Goal: for each site, one row of evidence. It records whether pages load through the gateway, whether a bot wall answers instead, whether the same happens without the gateway, which payment provider the checkout loads, and whether the adapter captured the provider's key.

## Steps

1. **Set up** (once): `uv sync && uv run playwright install chromium`. Check that `sites.yaml` exists (copy `sites.example.yaml`) and that credentials are set (README "Credentials"). Never print or commit secrets.
2. **Add the sites.** One entry per site in `sites.yaml`, with `id`, `name`, and `urls` (home page plus one product page). Add `allowed_hosts` only when you know them; the probe adds the URLs' hosts itself.
3. **Run:**
   ```sh
   uv run awg-sitecheck probe <site-id> ...            # or no ids for all sites
   uv run awg-sitecheck probe <site-id> --direct       # also without the gateway, to tell gateway problems from site problems
   ```
   Output goes to `runs/probe-<time>/`: `scorecard.md` and `scorecard.html`, plus per site `result.json`, a video and `final.png`.
4. **Read each verdict:**
   | Verdict | Next step |
   |---|---|
   | `reachable` | Write a recipe (skill `awg-checkout-recipe`), then `probe --deep`. |
   | `blocked`, or `blocked-by-gateway-path` with direct 200 | Check that the vault has `agentGatewayBrowserEmulation=true` and that the egress profile has a `sticky_suffix`. Then look at the 403 response headers in `result.json` (`server`, `akamai-grn`, `cf-ray`). See `docs/lessons.md`. |
   | `blocked-even-direct` | The site blocks the exit IP or region. Try another egress profile, for example a different country. This isn't a gateway bug. |
   | `errors` | Look at `pages[].error` and the video. |
5. **Go deeper (`--deep`):** this runs the site's recipe up to the card form and records `payment_frames`, `psps` and `captured`. `payment-form-ok` means the site is ready for level 2 and level 3.
6. **Report** the scorecard table and your reading of each `blocked` or `errors` row. Every claim needs evidence: the status code, the header, a video timestamp.

## Rules

- **Never type card data** at this level. Probes use no card fields.
- **Keep load low:** a site that rate-limits shows up as 403s after repeated runs. Don't loop probes on one site; wait and vary the run.
- **Clean up:** each run deletes its reveal session (`session_deleted: 204` in `result.json`). If a run was killed, delete leftovers with `DELETE /reveal-sessions/{id}`.
- **Keep detections current:** add new bot-wall or PSP signatures to `awg_sitecheck/detect.py` when you see one; keep each signature specific.
