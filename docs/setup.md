# Set up the dev kit

Run `./awg setup` from the repository on macOS or Linux. Setup installs VGS CLI with a pyenv-managed Python even if another `vgs` executable is already on PATH. It uses Python **3.12.12**, a private virtual environment, and the stable **VGS CLI 1.36.0** release. It does not change your global Python version.

If pyenv is absent, setup uses Homebrew when available, otherwise it clones the official pyenv repository into the private kit directory. Python compilation requires the platform's compiler and libraries; a build failure links to [pyenv's build prerequisites](https://github.com/pyenv/pyenv/wiki#suggested-build-environment). The kit and browser runtime use `uv` separately. `./awg start` also checks for `curl`, `jq`, and `openssl`, with installation guidance if one is missing.

## Login and organization selection

Setup runs `vgs login`, which opens VGS authentication in your browser. Complete sign-in there, including any required operating-system keyring prompt. If the browser cannot open automatically, the CLI's private `login.log` contains the login URL. Never paste its contents into chat.

Setup lists organizations from `vgs get organizations` and asks for the organization ID, even when only one is available. This is the only configuration question. A coding assistant can confirm the organization in chat and pass the answer directly:

```sh
./awg setup --organization AC_YOUR_ORGANIZATION
```

The ID in this example is a placeholder; use the actual `AC…` ID. The script validates the choice against your login's organization list. It ignores inherited VGS service-account environment variables so that onboarding uses your personal login.

`vgs get tenants` lists all visible tenants. Setup filters them by the confirmed organization and `SANDBOX` environment. It prefers a tenant named **Agent Web Gateway Dev Kit**; otherwise it uses the first Sandbox tenant sorted by tenant ID. It prints the selected tenant before provisioning. An optional `--tenant tnt…` selects a particular existing Sandbox tenant without another prompt. Setup refuses Live tenants and tenants from other organizations. It does not create tenants or change tenant preferences. If the organization has no accessible Sandbox tenant, its administrator must provide one first.

## Automatic service-account creation

VGS CLI 1.36.0 supports `vgs generate service-account --template vgs-cli --tenant …` and `vgs apply service-account -O … --file …`, but does not ship the `agent-web-gateway-admin` template. Setup generates the supported template, replaces its permissions with the following scope list, and applies that definition to the selected tenant:

- `cards:create`, `cards:read`, `cards:update`
- `aliases:write`
- `reveal-sessions:read`, `reveal-sessions:write`
- `agent-gateway:read`, `agent-gateway:write`

If the Cards API answers `403` for the test card, `./awg start` stores the same test card through the vault alias API (`aliases:write`) instead, so the session still has the number and the CVC. It prints whether the account lacks `cards:create` or the tenant lacks the Cards API. Setup also lists any requested scope that VGS did not issue.

These scopes support test-card storage, sessions, and gateway authoring. They do not grant PCI card reads, card deletion, or tenant-preference changes. Your personal login needs permission to create the service account in that organization. See the [VGS service-account CLI documentation](https://docs.verygoodsecurity.com/enterprise-platform/access-management/service-accounts-for-programmatic-access/creating-service-accounts-using-the-vgs-cli).

The creation response contains the one-time client secret. Setup captures stdout and stderr privately, authenticates the new account, and checks read access to Sandbox sessions and destinations. It only replaces the kit's saved credentials after those checks succeed. It does not create a reveal session, tokenize a card, enable a binding, or submit a payment during setup.

Private state lives in `~/.awg-dev-kit` (override with `AWG_HOME`):

| Path | Purpose |
|---|---|
| `sandbox.env` | Verified service credentials used by the wrapper and helper |
| `setup-selection.json` | Organization, tenant, and creation-journal location |
| `setup/…/` | Private CLI output, account definition, and one-time creation response |
| `setup-pending.json` | Recovery marker for a creation attempt |
| `vgs-cli-…/` | VGS CLI installed under pyenv Python |
| `sessions/` | Original reveal-session creation responses |

Directories use mode 0700 and files use mode 0600. VGS CLI also maintains its own login/keyring state. Do not commit or share either location. Choose an `AWG_HOME` outside the repository.

## Reruns and recovery

A normal rerun verifies saved credentials and reuses them. `./awg setup --force` provisions a replacement after organization selection and retains the old credentials until the new account verifies. It does not delete the previous service account; an organization administrator can remove unused accounts separately.

If creation succeeds but authentication or the Agent Web Gateway checks fail, setup keeps the creation result and reuses it on the next run. Check tenant enablement and account permissions, then rerun without `--force`. If creation is interrupted or returns an uncertain result, setup refuses to repeat the write automatically. Inspect the private journal and the organization's service accounts first. Recover any complete output into `created.yaml` only after checking the result; remove a pending marker only after confirming that no account was created or reconciling it with the administrator. Do not print those files in chat.

## Validation coverage

`./awg` is a Bash wrapper around the bootstrap script, session REST calls, local helper, browser launcher, and sitecheck tool. It is a separate entry point from operating the Control Panel directly.

`./awg test` runs offline setup and wrapper tests plus the existing helper and Node extension tests. The bootstrap tests use synthetic CLI/API responses to check organization confirmation, Sandbox filtering, tenant-scoped permissions, private outputs, verification failure, and recovery without duplicate account creation. Wrapper tests exercise argument handling, pyenv installation selection, and session/start orchestration with stubbed external commands. The optional MCP and browser-fixture suites require their documented dependencies.

These checks do not validate interactive VGS login, actual service-account creation, Agent Web Gateway enablement, a fresh-machine Python build, CloakBrowser licensing, or a merchant payment end to end. Setup itself checks real authentication and Agent Web Gateway read access when a developer runs it.
