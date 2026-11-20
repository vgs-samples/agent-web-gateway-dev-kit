# Instructions for AI coding agents

Help the developer set up and use the VGS Agent Web Gateway dev kit. `./awg` wraps setup, test sessions, the Control Panel helper, and the browser. Read [docs/setup.md](docs/setup.md) for the actual bootstrap behavior and validation limits.

## Set it up

1. Run `./awg test` for offline setup, helper, and extension coverage. Runtime/package downloads may be needed; test fixtures send nothing to VGS.
2. Run `./awg setup`. It installs its own VGS CLI on a prebuilt Python from `uv`, runs `vgs login`, discovers organizations, and asks which organization to use. The developer completes browser authentication. Never ask for a client ID or secret in chat.
   - Confirm only the organization. If the developer already chose it in this conversation, pass `--organization AC…`; do not ask again.
   - Setup automatically selects an existing Sandbox tenant in that organization, creates a tenant-scoped service account with the CLI, stores the output privately, and checks authentication and Agent Web Gateway read access. It never selects Live. An explicit `--tenant tnt…` may override the documented selection rule.
   - Reruns reuse saved credentials. If an earlier attempt failed or was interrupted, a plain rerun recovers or restarts it; do not edit the private setup files.
   - A documentation or code-editing task does not authorize actually provisioning an account. Test bootstrap offline when that is the task.
3. Run `./awg start` (or `./awg start https://<the site to test>/`). It creates or reuses an active test-card session, starts the helper, and opens CloakBrowser with the Control Panel and optional website tab. It runs until the browser closes, so run it in the background or the developer's terminal.
   - It opens a browser window and starts a helper on a local port. If your sandbox or permission mode refuses the command or blocks either of those, do not retry or work around it: ask the developer to run `./awg start` in their own terminal (in Claude Code, by typing `! ./awg start`).
   - `uv` supplies Python for the kit, the browser and VGS CLI. Do not substitute a system or unrelated existing VGS CLI installation.
   - Nothing is compiled, so no build prerequisites are needed. If credentials, tenant enablement, or permissions fail, report the failure without exposing private CLI output.
   - If CloakBrowser needs a license key, the developer saves it locally with `./awg cloak-login`.

## If a call is refused with 403

A `403` from VGS means the service account lacks a scope. It is not an installation problem.

1. Read the kit's own output. `./awg setup` and `./awg start` print `Note: … lacks: …` with the exact scope names, and on a Cards API `403` they say whether the account lacks `cards:create` or the tenant lacks the Cards API.
2. If the browser still opened, the kit stored the test card through the alias API and the session is complete. Report the missing scopes and continue.
3. If the kit stopped, tell the developer which scopes are missing and that `./awg setup --force` creates a new service account with every scope the kit uses. It creates an account in their organization, so run it only after they agree. Scopes cannot be added to an existing account.
4. If the new account is still missing scopes, or VGS rejects the creation, stop. The organization has not been granted those scopes, or the developer's login cannot create service accounts. Say which, and that it needs their organization administrator or VGS.

Do not work around a `403` by editing the kit, hand-writing `card.json` or `sandbox.env`, or dropping the CVC. See [missing scopes](docs/setup.md#missing-scopes).

## What success looks like

- Setup reports that Sandbox credentials authenticated and can read Agent Web Gateway resources.
- Offline tests pass. Report skipped optional tests; do not call them end-to-end validation.
- `./awg start` reports that the helper is running and opens the Control Panel.
- The session appears in the panel, a route can be selected, and observed requests through VGS have a `vgs-request-id` response header. Verify actual routing and transformation separately.

## Rules

- **Sandbox and public test cards only.** The wrapper stores the public VGS test card ending 1111. Never enter, request, or store a real card number in this workflow.
- **Never place an order or submit a payment** unless the developer approves that item and maximum total in this conversation.
- **Never print or share** client secrets, access tokens, session proxy credentials, PAC links, private HAR bodies, or private setup/session files.
- **Never commit** `~/.awg-dev-kit`, `.private-extension`, `sites.yaml`, `card.json`, `.env` files, or `runs/`. Keep an overridden `AWG_HOME` outside the repository.
- Type session stand-ins into payment forms, never raw card data or vault aliases.
- A person completes any 3-D Secure challenge or CAPTCHA. Do not bypass site controls.
- Report observed status codes, request IDs, and reveal counts. Say "unknown" when evidence does not establish the cause.
- MCP provides browser captures and gateway-resource tools. Use REST or the local panel helper for session details; do not invent MCP session tools. Keep captures private.

## Where things are

| Need | Look at |
|---|---|
| Overview and concepts | `README.md`, `docs/training/01-what-is-agent-web-gateway.md` |
| Setup and recovery | `docs/setup.md`, `./awg setup --help` |
| Other wrapper commands | `./awg --help` |
| API and errors | [official OpenAPI spec](https://openapi.gitbook.com/o/hcowjO8ckQ1K5fm3NPZH/spec/agent-web-gateway-api.yaml), `docs/reference/developer-guide.md`, `docs/reference/error-codes.md` |
| Troubleshooting | `docs/training/07-troubleshooting.md` |
| Provider adapters | `skills/vgs-checkout-adapter/SKILL.md`, `docs/training/05-adapters-and-functions.md` |
| Merchant tests | `docs/training/06-testing-merchant-sites.md`, `tools/sitecheck/AGENTS.md` |
| Control Panel and MCP | `docs/control-panel.md`, `docs/mcp.md`, `docs/browser-proxying.md` |
