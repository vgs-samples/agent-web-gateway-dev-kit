# awg-sitecheck

Use this to test merchant sites through the VGS Agent Web Gateway, at three levels:

- **probe:** can an agent reach the site, and what blocks it?
- **verify:** does the adapter's client-side encryption produce what the payment provider expects?
- **purchase:** a recorded checkout with a card the agent never sees.

AI agents: start with [AGENTS.md](AGENTS.md).

## Install

```sh
# needs Python 3.11+ and uv (https://docs.astral.sh/uv/)
uv sync
uv run playwright install chromium
cp sites.example.yaml sites.yaml
cp harness/card.example.json card.json
```

Run the commands from this folder with `uv run awg-sitecheck ...`.

## Credentials

Nothing secret goes in a file in this folder.

| What | How |
|---|---|
| VGS API (service account on the sandbox vault) | `VGS_CLIENT_ID` and `VGS_CLIENT_SECRET`, or `VGS_ACCESS_TOKEN`, or on macOS `VGS_KEYCHAIN=<Keychain service>` (account = client id; or `defaults.keychain` in `sites.yaml`) |
| Scopes needed | `reveal-sessions:write`, `reveal-sessions:read`, `agent-gateway:read`, `agent-gateway:write`; plus `aliases:write` to create the card aliases; plus `access-logs:read` for `vgs logs` |
| Vault preference | `agentGatewayBrowserEmulation=true`, set once per vault from the dashboard. Sites behind Akamai and similar bot walls need it. |
| Egress proxy password | The env variable named by the profile's `password_env` (for example `SOAX_PASSWORD`), or its `password_keychain` |

## Card

`card.json` holds **vault aliases**, never card data:

```json
{"label": "test", "number": {"alias": "tok_sandbox_…", "bin": "411111"}, "cvc": {"alias": "…", "length": 3}}
```

Create the aliases once, for example with `POST https://<tenant>.sandbox.vault-api.verygoodvault.com/aliases`
(classifiers `card-number`, `card-security-code`, storage `PERSISTENT`), entering the card yourself. The expiry goes in
`context` in `sites.yaml`.

## Commands

```sh
uv run awg-sitecheck probe                          # level 1, every site in sites.yaml
uv run awg-sitecheck probe hm-us --direct --deep    # one site: also without the gateway, and through the recipe to the card form
uv run awg-sitecheck report runs/probe-<time>       # rebuild the scorecard

uv run awg-sitecheck adapter plan     adapters/adyen-cse/hm-us.yaml
uv run awg-sitecheck adapter apply    adapters/adyen-cse/hm-us.yaml
uv run awg-sitecheck adapter dry-run  adapters/adyen-cse/hm-us.yaml capture adapters/adyen-cse/fixtures/capture.json
uv run awg-sitecheck adapter list
uv run awg-sitecheck adapter teardown adapters/adyen-cse/hm-us.yaml

uv run awg-sitecheck verify harness/merchants/hm-us-prod-sandbox.json --card card.json   # level 2 (harness/README.md)

uv run awg-sitecheck purchase hm-us                                    # level 3: stops before the order
uv run awg-sitecheck purchase hm-us --purchase --max-total 30.00       # places it (approved orders only)
```

Each run writes `runs/<kind>-<time>/<site>/` with `result.json`, a video (`.webm`) and `final.png`. Probe runs add
`scorecard.md` and `scorecard.html`. To turn a video into an MP4:
`ffmpeg -i <video>.webm -c:v libx264 -pix_fmt yuv420p out.mp4`.

## More

- [adapters/README.md](adapters/README.md): which sites need an adapter, and how to write one.
- [docs/lessons.md](docs/lessons.md): bot walls, sticky IPs, warm-up, and what failed and why.
- [docs/developer-guide.md](docs/developer-guide.md): the function runtime (`session`, `vault`, inputs, dry runs).
- [../../openapi/awg-tenant-api.yaml](../../openapi/awg-tenant-api.yaml): every endpoint, field and error code.
