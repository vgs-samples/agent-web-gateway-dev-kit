# Agent Web Gateway Testing

**Internal to VGS. Do not share outside VGS.** Only two files here are written for customers: `docs/reference/04-developer-guide.md` and `openapi/awg-tenant-api.yaml`.

Testing tools, a browser control panel and hands-on training for Agent Web Gateway.

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

## Testing with the control panel

The current **Agent Web Gateway Control Panel** source and local helper are in
[`tools/vgs-proxy-controls/`](tools/vgs-proxy-controls/). For a CLI-first lab, page 10 includes
[launch examples for Chrome for Testing, Chromium, Chrome, Edge and Brave](docs/training/10-proxy-controls-extension.md#browser-launch-examples).

**Download a build:** open **Actions → Build control panel**, select a successful
run for the branch you want, then download **agent-web-gateway-control-panel** from
its **Artifacts** section. It contains the versioned source/helper ZIP and its
checksum. Artifacts are kept for 30 days and require repository access and a
GitHub sign-in. During draft review, choose the PR branch; after merge, use `main`.
See [download and build instructions](docs/training/extension-distribution.md#download-or-build-the-kit)
for the CLI equivalent and local builds.

The download contains source, not a configured extension. Run its helper with
your own credentials and an active saved session, then load the generated
`.private-extension` directory. The [distribution guide](docs/training/extension-distribution.md)
also covers a future store release and simpler first-run onboarding.

Use the same browser and configuration when reproducing an existing result.
The alternative launch examples do not make those browsers equivalent to
CloakBrowser or provide anonymity.

### Launch it from the command line

Requires Python 3.10+, Chrome for Testing, your service-account credentials and an
**active session's original creation response**. The launcher needs that initial
session; after setup, the panel can create additional sessions. Set up the VGS CA
through your approved browser process before using the VGS routes.

From a checkout, copy the tool to a new working folder. In Terminal 1:

```bash
cp -R tools/vgs-proxy-controls "$HOME/vgs-proxy-controls"
cd "$HOME/vgs-proxy-controls"

# Replace these with your own private files, kept outside the repository.
AWG_ACCOUNT_FILE="/absolute/path/to/service-account-credentials.yaml"
AWG_SESSION_FILE="/absolute/path/to/sessions/RS_EXAMPLE.json"
AWG_SESSION_DIR="/absolute/path/to/sessions"

python3 start-proxy-controls.py \
  --environment sandbox \
  --credentials-file "$AWG_ACCOUNT_FILE" \
  --session "$AWG_SESSION_FILE" \
  --sessions-dir "$AWG_SESSION_DIR"
```

Keep the helper running. For an artifact download, use its extracted folder instead
of the copy step. In Terminal 2 on macOS, with Chrome for Testing in `/Applications`:

```bash
AWG_EXTENSION_DIR="$HOME/vgs-proxy-controls/.private-extension"
"/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" \
  --user-data-dir="$HOME/Library/Application Support/AWG Testing/chrome-for-testing" \
  --load-extension="$AWG_EXTENSION_DIR" \
  --no-first-run
```

Use a new dedicated profile. The control-panel tab opens automatically. Regular
Chrome, Edge and Brave use a one-time **Load unpacked** step; see the
[browser-specific commands](docs/training/10-proxy-controls-extension.md#browser-launch-examples).

### What you should see

These screenshots use synthetic Sandbox data and local fixtures. They show the
interface, not a real account, merchant transaction or completed tokenization.

**1. Controls:** confirm the tenant and session, then choose a routing diagram.
Choose **No Proxy** to turn proxying off for this browser profile.

![Control panel: session selection and four routing diagrams](tools/vgs-proxy-controls/screenshots/control-panel.png)

**2. Settings:** check the environment and connected account. Use **Browse…** to
select a dashboard or CLI credentials export. The service-account section includes
copyable CLI setup instructions.

![Settings: Sandbox and the local service-account file picker](tools/vgs-proxy-controls/screenshots/settings.png)

**3. New session:** open **New session…** when needed, add a card through Collect
or use existing aliases, choose the session options, and create it. Select the new
session separately when ready.

![Create reveal session with synthetic aliases](tools/vgs-proxy-controls/screenshots/create-session.png)

**4. Diagnostics:** inspect the actual PAC script and the HAR export setting.
Enabling sensitive-HAR export does not start a recording. The optional MCP setup
appears under **Connect an assistant with MCP**.

![Diagnostics: PAC script and HAR export information](tools/vgs-proxy-controls/screenshots/diagnostics.png)

When finished, select **No Proxy**, close the test browser and stop the helper with
Ctrl-C. Keep credentials, generated extensions, saved sessions and HAR files private.

### Use with a coding assistant

Give your assistant this repository and the following setup request:

> Help me install the Agent Web Gateway Control Panel using the repository's
> browser walkthrough. Check my Python and browser versions, use my local Sandbox
> credentials and original saved session response, and create a dedicated browser
> profile. Keep credential contents out of chat and source control. Start the helper,
> launch the browser, and help me verify the tenant, selected session, and proxy route.
> Do not submit a merchant payment.

The assistant needs access to your computer to execute those steps. The repository
and extension alone do not grant it browser control or access to HAR recordings.

### Connect Claude to captures and gateway tools

The optional [MCP companion](tools/vgs-proxy-controls/MCP.md) connects to the
dedicated browser and the panel's local helper. It can record one selected tab,
read unredacted HAR headers and bodies, and inspect functions, adapters,
destinations and bindings using the account configured in Settings. Gateway
authoring and route-function dry-runs are available with `--mcp-write`.

The [setup guide](tools/vgs-proxy-controls/MCP.md) includes the helper command,
browser debugging flags, Claude Code registration command and a sample recording
prompt. Start with capture/read access, then enable writes when ready to author
configuration. Service-account credentials stay in the helper; captured traffic
is intentionally available to the connected assistant. Browser captures precede
VGS transformations and need separate gateway or echo evidence to verify reveal.

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
| 10 | [Agent Web Gateway Control Panel](docs/training/10-proxy-controls-extension.md) | Load the extension, connect an account, create/select sessions and switch routes |

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
| `tools/vgs-proxy-controls/` | Agent Web Gateway Control Panel source, local helper, tests and package builder (page 10) |
| `.github/workflows/control-panel-package.yml` | Tests the helper/worker and builds a downloadable source/helper artifact |
| `skills/vgs-checkout-adapter/` | A Claude Code skill for writing adapters, with the scripts lab 4 uses |
| `examples/functions/` | A real adapter function, and a broken copy for an exercise |
| `docs/images/` | Two slides from VGS's AWG deck |
| `docs/comparison-evervault-browser-tokens.md` | AWG next to Evervault's Browser Tokens |

## How far to trust this

- AWG is pre-release. The reference documents describe it as of **2026-11-12**.
- Every training page was checked line by line against those documents and the tool code.
- **Nothing was run against a live environment, and the labs have not been run end to end as written.** Code in the labs is source-checked, not tested.
- The control panel has local helper, worker and browser-fixture tests. Its screenshots use synthetic data; these checks do not validate a live integration.
- If the product has changed, the reference documents win over the training pages, and the running system wins over both.

[SOURCES.md](SOURCES.md) lists where each file came from, where the sources disagree, and what nobody has verified.

A note on words: these pages say **tenant** for the VGS account an integration runs in, identified by its `tnt…` id. The reference documents often say "vault" for the same thing. "Vault" here means only the place the card is stored.
