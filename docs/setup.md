# Set up the dev kit

Run `./awg setup` from the repository on macOS or Linux. Setup installs VGS CLI into a private virtual environment even if another `vgs` executable is already on PATH. It uses a prebuilt Python **3.12** from `uv` and the stable **VGS CLI 1.37.0** release. Nothing is compiled, and your global Python is not changed.

If `uv` is absent, setup installs it with Homebrew when available, otherwise with the official installer. The kit and browser runtime use the same `uv`. `./awg start` also checks for `curl`, `jq`, and `openssl`, with installation guidance if one is missing.

## Login and organization selection

Setup runs `vgs login`, which opens VGS authentication in your browser. Complete sign-in there, including any required operating-system keyring prompt. If the browser cannot open automatically, the CLI's private `login.log` contains the login URL. Never paste its contents into chat.

Setup lists organizations from `vgs get organizations` and asks for the organization ID, even when only one is available. This is the only configuration question. A coding assistant can confirm the organization in chat and pass the answer directly:

```sh
./awg setup --organization AC_YOUR_ORGANIZATION
```

The ID in this example is a placeholder; use the actual `AC…` ID. The script validates the choice against your login's organization list. It ignores inherited VGS service-account environment variables so that onboarding uses your personal login.

`vgs get tenants` lists all visible tenants. Setup filters them by the confirmed organization and `SANDBOX` environment. It prefers a tenant named **Agent Web Gateway Dev Kit**; otherwise it uses the first Sandbox tenant sorted by tenant ID. It prints the selected tenant before provisioning. An optional `--tenant tnt…` selects a particular existing Sandbox tenant without another prompt. Setup refuses Live tenants and tenants from other organizations. It does not create tenants or change tenant preferences. If the organization has no accessible Sandbox tenant, its administrator must provide one first.

## Automatic service-account creation

VGS CLI 1.37.0 ships the `agent-web-gateway-admin` service-account template. Setup generates the account from it with `vgs generate service-account --template agent-web-gateway-admin --tenant …` and creates it with `vgs apply service-account -O … --file …`. If a CLI without that template is used, setup generates the `vgs-cli` template and replaces its permissions. Either way the account gets exactly the following scope list, never the broader `cards:write`, and is applied to the selected tenant:

- `cards:create`, `cards:read`, `cards:update`
- `aliases:write`
- `reveal-sessions:read`, `reveal-sessions:write`
- `agent-gateway:read`, `agent-gateway:write`

If the Cards API answers `403` for the test card, `./awg start` stores the same test card through the vault alias API (`aliases:write`) instead, so the session still has the number and the CVC. It prints whether the account lacks `cards:create` or the tenant lacks the Cards API. Setup also lists any requested scope that VGS did not issue. `AWG_CARD_STORE=aliases ./awg start` skips the Cards API and goes straight to the alias API.

If the saved credentials belong to a service account that setup did not create, `./awg start` lists the scopes it lacks before making any call and works with the ones it has. Sessions need `reveal-sessions:write`; the test card needs `cards:create`, `cards:write` or `aliases:write`.

These scopes support test-card storage, sessions, and gateway authoring. They do not grant PCI card reads, card deletion, or tenant-preference changes. Your personal login needs permission to create the service account in that organization. See the [VGS service-account CLI documentation](https://docs.verygoodsecurity.com/enterprise-platform/access-management/service-accounts-for-programmatic-access/creating-service-accounts-using-the-vgs-cli).

The creation response contains the one-time client secret. Setup captures stdout and stderr privately, authenticates the new account, and checks read access to Sandbox sessions and destinations. It only replaces the kit's saved credentials after those checks succeed. It does not create a reveal session, tokenize a card, enable a binding, or submit a payment during setup.

Private state lives in `~/.awg-dev-kit` (override with `AWG_HOME`):

| Path | Purpose |
|---|---|
| `sandbox.env` | Verified service credentials used by the wrapper and helper |
| `setup-selection.json` | Organization, tenant, and creation-journal location |
| `setup/…/` | Private CLI output, account definition, and one-time creation response |
| `setup-pending.json` | Recovery marker for a creation attempt |
| `vgs-cli-…/` | VGS CLI in its private virtual environment |
| `sessions/` | Original reveal-session creation responses |

Directories use mode 0700 and files use mode 0600. VGS CLI also maintains its own login/keyring state. Do not commit or share either location. Choose an `AWG_HOME` outside the repository.

## Missing scopes

Setup and `./awg start` read the access token and print the kit scopes the account lacks. What each gap means:

| Missing | Effect | Who can fix it |
| --- | --- | --- |
| `cards:create` (and no `cards:write`) | The Cards API answers `403`. The kit stores the test card through the alias API instead. | You, with `./awg setup --force` |
| `cards:create` and `aliases:write` | The kit cannot store a test card. | You, with `./awg setup --force` |
| `reveal-sessions:write` | Session creation answers `403`. | You, with `./awg setup --force` |
| Any scope, again, on the account `--force` just created | VGS has not granted that scope to your organization. | VGS |
| A scope the kit reports as "granted, but VGS leaves them out of its access token" | The account holds the scope as a role, but the token's `scope` claim, which the APIs read, omits it. The call is refused as if the scope were missing. A new account is likely to get the same token. | VGS |

Scopes cannot be added to an existing service account. `./awg setup --force` creates a new one with every scope the kit uses, and keeps the old credentials until the new account verifies. It needs a VGS login that is allowed to create service accounts in the organization; if yours is not, VGS rejects the creation and an organization administrator has to grant that permission or run setup. The previous account is left in place, unused, until an administrator deletes it.

## Reruns and recovery

A normal rerun verifies saved credentials and reuses them. `./awg setup --force` provisions a replacement after organization selection and retains the old credentials until the new account verifies. It does not delete the previous service account; an organization administrator can remove unused accounts separately.

If creation succeeds but authentication or the Agent Web Gateway checks fail, setup keeps the creation result and reuses it on the next run. Check tenant enablement and account permissions, then rerun without `--force`. If VGS answers the creation with an error, fix the cause named in the private `apply-output.yaml.stderr` and rerun `./awg setup`. If setup stops before VGS returns the account's one-time secret, that attempt cannot be recovered, so the next run starts again and names the account that may have been left unused; an administrator can delete it. If setup stops after VGS answered, the next run reuses the saved result. Do not print the private files in chat.

## Validation coverage

`./awg` is a Bash wrapper around the bootstrap script, session REST calls, local helper, browser launcher, and sitecheck tool. It is a separate entry point from operating the Control Panel directly.

`./awg test` runs offline setup and wrapper tests plus the existing helper and Node extension tests. The bootstrap tests use synthetic CLI/API responses to check organization confirmation, Sandbox filtering, tenant-scoped permissions, private outputs, verification failure, and recovery without duplicate account creation. Wrapper tests exercise argument handling, VGS CLI installation, and session/start orchestration with stubbed external commands. The optional MCP and browser-fixture suites require their documented dependencies.

These checks do not validate interactive VGS login, actual service-account creation, Agent Web Gateway enablement, a fresh-machine Python build, CloakBrowser licensing, or a merchant payment end to end. Setup itself checks real authentication and Agent Web Gateway read access when a developer runs it.
