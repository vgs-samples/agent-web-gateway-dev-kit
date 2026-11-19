# Agent Web Gateway dev kit

Opens a browser with the Agent Web Gateway Control Panel loaded, ready to test a checkout on any site with a card the browser never sees.

## Start

```sh
./awg start
```

That one command does everything:

1. Asks for your VGS Sandbox tenant id, client id and client secret, the first time only. The secret is typed at a hidden prompt and stays on your machine.
2. Stores the VGS test card and creates a reveal session.
3. Opens the browser with the control panel loaded.

To test a checkout, add the site's address. The session then allows that site, and it opens in a second tab:

```sh
./awg start https://the-shop-you-are-testing.com/
```

**Using a coding agent?** Open this folder in Claude Code, Codex or Cursor and say "set up this dev kit". It follows [AGENTS.md](AGENTS.md).

## What you need

- **A VGS Sandbox service account** on a tenant enabled for Agent Web Gateway: its tenant id, client id and client secret. Ask your VGS contact.
- **[uv](https://docs.astral.sh/uv/)**. If it is missing, `./awg start` offers to install it. It supplies Python and the browser, so there is no Python setup and no browser download.
- **`curl`, `jq` and `openssl`.** `./awg start` stops if one is missing, and `./awg doctor` says which. Install a missing one with your package manager, for example `brew install jq` on macOS.
- **A free [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) license key.** The kit fetches the browser itself; `./awg start` asks for the key the first time.

macOS and Linux. On macOS, allow the browser once in **System Settings → Privacy & Security** if it is blocked on first launch.

## What you see

![The control panel: a reveal session on the left, the four browser routes on the right](tools/vgs-proxy-controls/screenshots/control-panel.png)

Pick a session on the left and a route on the right. At a payment form, type the **session aliases** the panel shows, never a real card. VGS swaps them for the real card on the way to the sites the session allows.

## How Agent Web Gateway works

![The agent platform holds aliases for the card, creates a session, and gets back proxy settings and session tokens; the agent's browser types the session tokens at checkout; the Agent Web Gateway session swaps them for the real card on the way to the merchant](docs/images/awg-flow-token-swap.png)

The numbers match the diagram.

1. **The card** is stored in the VGS vault.
2. **Your platform keeps** only aliases for it.
3. **You send VGS** the card's aliases and the sites the agent may pay on. That creates a **reveal session**.
4. **You get back** proxy settings and stand-in card values that work only in that session.
5. **The agent types** the stand-ins into the payment form.
6. **The browser sends** the payment request, still carrying the stand-ins, through the session.
7. **VGS swaps** them for the real card as the request passes through.
8. **The merchant receives** the real card.

## If something goes wrong

```sh
./awg doctor
```

It checks your machine and says exactly what is missing. `./awg --help` lists every command.

## Going deeper

Everything else is optional: [training, the API reference, error codes and the rest of the tools](docs/README.md).

Use **Sandbox** and the test card while you build. This kit is a preview; where it and the running system differ, the running system is right.
