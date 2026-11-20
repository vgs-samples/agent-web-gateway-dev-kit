# Use a Kernel cloud browser

`./awg start` opens CloakBrowser on your machine. `./awg kernel` is an alternative for teams that run their agents on [Kernel](https://kernel.sh): the browser runs in Kernel's cloud and its traffic passes through your reveal session. No browser or Docker is needed locally; the kit uses `curl`, `jq` and `uv`.

> Run against Kernel's service once: the browser started on the session's proxy and the Control Panel loaded and opened. The panel's controls and a full checkout have not been exercised there yet.

## What you need

- Sandbox credentials from `./awg setup`.
- A Kernel account on the Start-Up or Enterprise plan, and an API key. Kernel requires one of those plans for custom proxies, and bills browser usage to the account.

## Run it

```sh
KERNEL_API_KEY=… ./awg kernel https://<the site to test>/
```

The command:

1. Creates or reuses a reveal session with the VGS test card, the same way `./awg start` does.
2. Registers that session with Kernel as a [custom proxy](https://www.kernel.sh/docs/proxies/custom), including the session's certificate authority so the browser trusts pages re-signed by VGS.
3. Uploads the Control Panel extension to Kernel, built for this session without its local helper. If Kernel does not accept it, the command says so and continues without the panel.
4. Starts a Kernel browser that uses the proxy and loads the panel and prints its live view link, along with Kernel's browser session ID and proxy ID in case you need Kernel support.
5. Removes the browser, the panel and the proxy entry when you press Enter. Without a terminal, it runs until the browser closes after 30 minutes idle.

Type the session's stand-ins into the payment form, as in any other session. Read them with `./awg session` output or the Control Panel.

## What is different from `./awg start`

| | `./awg start` | `./awg kernel` |
|---|---|---|
| Browser | CloakBrowser on your machine | Kernel's cloud, viewed through a link |
| Needs | CloakBrowser license key | Kernel API key |
| Control Panel | Loaded, with the local helper | Loaded without the helper; open it from the browser's extensions menu |
| Session details and route switching | In the panel | In the panel |
| Creating sessions, adding cards, scopes, recording, gateway views | In the panel | Not available: they need the helper, which a cloud browser cannot reach |

## What Kernel receives

The session's proxy address, proxy username and password, and certificate authority are sent to Kernel's API, both as the proxy definition and inside the uploaded panel, and the browser's traffic runs in Kernel's cloud. The live view link controls the browser, so keep it private. Use Sandbox and the public test card only. Your VGS client secret is never sent to Kernel.

## If it fails

| Output | Meaning |
|---|---|
| `KERNEL_API_KEY is not set` | Export the key or put it in front of the command. |
| `Kernel answered HTTP 401` | Kernel did not accept the key. |
| `Kernel did not create the proxy` | Kernel rejected the proxy definition; the line above it has Kernel's reason. |
| `insufficient_plan` | Custom proxies need Kernel's Start-Up or Enterprise plan. Upgrade the Kernel account. |
| Pages fail to load in the Kernel browser | The session expired, or Kernel cannot reach the session's proxy host and port. |
