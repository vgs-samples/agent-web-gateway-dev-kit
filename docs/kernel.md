# Use a Kernel cloud browser

`./awg start` opens CloakBrowser on your machine. `./awg kernel` is an alternative for teams that run their agents on [Kernel](https://kernel.sh): the browser runs in Kernel's cloud and its traffic passes through your reveal session. Nothing is installed locally beyond `curl` and `jq`.

> This command has offline tests only. It has not yet been run against Kernel's service. Treat it as experimental until that note is removed.

## What you need

- Sandbox credentials from `./awg setup`.
- A Kernel account and an API key. Kernel bills browser usage to that account.

## Run it

```sh
KERNEL_API_KEY=… ./awg kernel https://<the site to test>/
```

The command:

1. Creates or reuses a reveal session with the VGS test card, the same way `./awg start` does.
2. Registers that session with Kernel as a [custom proxy](https://www.kernel.sh/docs/proxies/custom), including the session's certificate authority so the browser trusts pages re-signed by VGS.
3. Starts a Kernel browser that uses the proxy and prints its live view link.
4. Removes the browser and the proxy entry when you press Enter. Without a terminal, it runs until the browser closes after 30 minutes idle.

Type the session's stand-ins into the payment form, as in any other session. Read them with `./awg session` output or the Control Panel.

## What is different from `./awg start`

| | `./awg start` | `./awg kernel` |
|---|---|---|
| Browser | CloakBrowser on your machine | Kernel's cloud, viewed through a link |
| Needs | CloakBrowser license key | Kernel API key |
| Control Panel | Loaded, with the local helper | Not loaded |
| Route switching, recording, gateway views | In the panel | Not available |

## What Kernel receives

The session's proxy address, proxy username and password, and certificate authority are sent to Kernel's API, and the browser's traffic runs in Kernel's cloud. The live view link controls the browser, so keep it private. Use Sandbox and the public test card only. Your VGS client secret is never sent to Kernel.

## If it fails

| Output | Meaning |
|---|---|
| `KERNEL_API_KEY is not set` | Export the key or put it in front of the command. |
| `Kernel answered HTTP 401` | Kernel did not accept the key. |
| `Kernel did not create the proxy` | Kernel rejected the proxy definition; the line above it has Kernel's reason. |
| Pages fail to load in the Kernel browser | The session expired, or Kernel cannot reach the session's proxy host and port. |
