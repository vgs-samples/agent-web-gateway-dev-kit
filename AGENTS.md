# Instructions for AI coding agents

You are setting up and running the VGS Agent Web Gateway dev kit for a developer. Everything goes through one script, `./awg`. Do not install Python, create virtual environments or edit the tools; `./awg` handles that.

## Set it up

Run these in order. Stop and tell the developer if a step fails; do not work around it.

1. `./awg doctor`
   - If it reports `uv` missing, ask before installing it, then run `brew install uv` (macOS) or `curl -LsSf https://astral.sh/uv/install.sh | sh`.
   - If it reports `jq` missing, ask, then install it with the system package manager.
2. `./awg test`
   - Runs the kit's offline tests. Expect every test to pass. Nothing is sent to VGS.
3. Credentials. **Never ask the developer to paste a secret into the chat, and never print one.**
   - If `./awg doctor` shows "Sandbox credentials saved", skip this step.
   - Otherwise ask the developer to run `./awg setup` in their own terminal. It asks for the tenant id, client id and client secret at hidden prompts.
   - If they already have a file with `VGS_TENANT=`, `VGS_CLIENT_ID=` and `VGS_CLIENT_SECRET=` lines, you may run `./awg setup --from /path/to/that/file` instead.
4. `./awg start https://<the site to test>/`
   - Creates a reveal session for the VGS test card, starts the control panel helper, and opens CloakBrowser with the control panel in the first tab and the site in the second.
   - It runs until the browser is closed, so start it in the background or ask the developer to run it.
   - If it says CloakBrowser needs a license key, ask the developer to run `./awg cloak-login` in their own terminal. A free key is enough.

## What success looks like

- `./awg doctor` ends with "Ready."
- `./awg test` reports no failures.
- `./awg start` prints "Helper is running. Opening CloakBrowser..." and a browser window opens on the control panel.
- In the control panel, the session is listed and a route can be selected. Pages on the session's allowed hosts return a `vgs-request-id` response header.

## Rules

- **Sandbox and test cards only.** `./awg session` and `./awg start` store the VGS test card `4111 1111 1111 1111`. Never enter, request or store a real card number.
- **Never place an order or submit a payment** unless the developer has approved that item and a maximum total in writing in this conversation.
- **Never print or share** the client secret, access tokens, the session's proxy URL or password, the PAC link, or the contents of `~/.awg-dev-kit`.
- **Never commit** anything from `~/.awg-dev-kit`, `.private-extension`, `sites.yaml`, `card.json`, `.env` files or `runs/`.
- At a payment form, type the session's stand-in values shown in the control panel, never a real card and never a vault alias.
- A person completes any 3-D Secure challenge or CAPTCHA.
- Report what you observed: status codes, the `vgs-request-id`, the session's `reveal_count`. Say "unknown" instead of guessing why a site blocks.

## Where things are

| Need | Look at |
|---|---|
| What AWG is and how it works | `README.md`, then `docs/training/01-what-is-awg.md` |
| Other commands | `./awg --help` |
| The API | `openapi/awg-tenant-api.yaml`, `docs/reference/04-developer-guide.md` |
| Error codes | `docs/reference/error-codes.md` |
| Something went wrong | `docs/training/07-troubleshooting.md` |
| Writing an adapter for a payment provider | `docs/training/05-adapters-and-functions.md` |
| Testing a merchant site | `docs/training/06-testing-merchant-sites.md`, `tools/sitecheck/AGENTS.md` |
| The control panel | `tools/vgs-proxy-controls/README.md` |

Private files (credentials, sessions, the browser profile, the helper's log) live in `~/.awg-dev-kit`, readable only by the developer.
