# 4. Lab: a browser checkout

**When you finish this lab you will have** stored a test card, created a session, opened a browser that goes through VGS, and typed session tokens at a checkout.

> **Status: preview.** These steps follow the API reference and the kit's code and have not yet been validated end to end. If a step does not behave as written, tell your VGS contact.

For the recommended interactive workflow, follow [Browser proxying best
practices](../../tools/vgs-proxy-controls/BROWSER-PROXY-BEST-PRACTICES.md): browse
through egress first, then add the card and create a fresh reveal session near
checkout. This older CLI lab creates the card and session before launching its
browser; it demonstrates the gateway path, rather than the recommended timing for
an extended browsing task.

**Use a test card**, such as `4111111111111111`. A real merchant will decline it, and that is expected. You are checking three things: pages load through VGS, the site does not treat you as a bot, and the token is swapped on the payment request. Do not submit a payment unless someone has approved that purchase.

## What you need

1. macOS or Linux (x86-64), with `curl`, `jq`, `openssl` and `unzip`.
2. A service account and tenant id, as in lab 3. Storing the card needs one more scope, for `POST /cards`; ask your VGS contact which.
3. A residential egress proxy you are authorized to use. The kit will not run without one.

## Set up, once

### 1. Copy the kit to a private folder

The kit will hold credentials and session files, so keep it outside this repository.

```bash
cp -R skills/vgs-checkout-adapter/scripts/session-kit ~/awg-session-kit
cd ~/awg-session-kit
bash setup.sh
```

**Success:** it creates a `.env` file that only you can read, and downloads a test copy of Chrome into `./browsers`.

### 2. Fill in `.env`

Use plain `KEY=value` lines, with no quotes and no `export`.

| Key | What to put |
|---|---|
| `VGS_CLIENT_ID`, `VGS_CLIENT_SECRET` | Your service account |
| `VGS_TENANT` | Your tenant id |
| `EGRESS_PROXY` | Your egress proxy URL |
| `VGS_API`, `VGS_AUTH_URL` | Leave as they are for Sandbox |

## Run a checkout

### 3. Start

Give the hosts that may receive the real card, then the page to open. Include the payment provider's host as well as the merchant's.

```bash
./start.sh www.example-shop.com,payments.example-psp.com https://www.example-shop.com/
```

The script asks for the card number, CVC and expiry. The number and CVC are hidden as you type. It then stores the card, creates a session and opens the browser.

**Success:** a browser window opens, and the terminal prints the session and a line like this:

```
tokens_to_type: { "card_number": "…", "card_cvc": "…" }
```

The terminal also shows the card's aliases, the proxy password and the PAC link. **Treat the terminal output as secret.** Do not paste it into a ticket or a chat.

### 4. Type the session tokens at checkout

In the browser, go to the merchant's checkout. In the card form, type the `tokens_to_type` values: the token for the card number, and the token for the CVC. Use the card's real expiry date.

Do not type the real card. Do not type the vault aliases.

### 5. Check it worked

1. **Traffic goes through VGS.** Open DevTools → Network. Responses from the allowed hosts carry a `vgs-request-id` header.
2. **The payment host is allowed.** Find the request that carries the tokens. Its host must be one you listed in step 3. If it is not, start again and add it.
3. **A reveal happened.**

```bash
./session-status.sh
```

**Success:** `reveal_count` has gone up. That shows VGS swapped a token. It does not show that the merchant accepted the payment.

### 6. End the session

```bash
./end-session.sh
```

When you are done with the kit, delete its `.state/` folder. Ending a session does not delete the stored card or the local files.

## If something goes wrong

| What you see | What to do |
|---|---|
| The script stops at the card step | The kit insists on a newly stored card each time. If the tenant already holds that card, the run stops. See "Details" |
| The script says an egress proxy is required | Set `EGRESS_PROXY` in `.env` |
| No `vgs-request-id` on the merchant's pages | That host is not in the session. Start again with it in the host list |
| The site blocks you (`403`) | That is the merchant's bot protection. Page 6 shows how to tell whether the gateway path caused it |
| `reveal_count` stays `0` after you submit | The payment host was not allowed, or the provider encrypts the card in the browser and needs an adapter (page 5) |

Tip: page 10 covers a browser extension that switches between sessions and routes without restarting the browser. The extension walkthrough uses Sandbox.

---

## Details

- **What the kit saves.** It does not save the card number or CVC. `.state/` holds the aliases, the last four digits, BIN, expiry and card id, the full session response, and the session request including the egress proxy password.
- **Without a terminal,** supply `CARD_PAN`, `CARD_CVC` and `CARD_EXP=MM/YY` in the environment.
- **The card step** stops unless the card call returns `201` with both aliases and a card id different from the last one saved. If the tenant already holds the card and answers `303`, the run stops there.
- **Egress.** With no `EGRESS_PROXY` and no `--egress-profile` the kit stops; it does not fall back to VGS's own addresses. Its default is a Byteful residential endpoint. A different endpoint needs `EGRESS_ALLOWED_HOST` and `EGRESS_ALLOWED_PORT` in `.env` plus `--egress-profile`.
- **More options.** `start.sh` passes only the host list and the URL. For anything else, run `create-fresh-session.sh` and then the launcher:

```bash
bash ./create-fresh-session.sh --hosts payments.example-psp.com \
  --adapter AD... --egress-profile /absolute/private/proxy.json
./launch-chromium.sh "" https://www.example-shop.com/checkout
```

  The empty first argument means the latest session. `--egress-profile` takes a private JSON file with `scheme`, `hostname`, numeric `port`, `username` and `password`.

- **`--adapter AD…`** sets the session's `adapter` and sends the card as `cards`, which functions that call `session.card()` need. The id must be registered in the tenant. The named forms `--adapter adyen` and `--adapter stripe` need a registration ledger file; none is bundled.
- **Expiry.** Use the card's real expiry unless the adapter requires an override.
- **A second environment.** Create `.env.<name>` and prefix every command with `KIT_ENV=<name>`; its state goes to `.state-<name>/`. Use the API and authentication endpoints for your Sandbox or Live account. Variables already exported in your shell override the file.
- **Which traffic goes through VGS.** The hosts in the session's PAC file. On a build without the PAC split, all of it.
- **If the payment host is not allowed,** what happens depends on the tenant's unlisted-host mode: the request may bypass VGS and deliver the worthless tokens, be refused (`403 reveal_refused`, reason `session_host_not_allowed`), be revealed within the guard's limits, or be held for approval. Page 2 explains the modes.
- **The CVC alias is volatile.** A new session does not bring back a CVC alias that is no longer available; store the card again.
- **Other checks.** The host's certificate is issued by the session's CA. `https://ipinfo.io/json` in the session browser shows your exit IP; an IP lookup does not tell you how a merchant's bot protection will rate it.
- **`launch-chromium.sh --insecure`** skips all certificate checks. Use it only to diagnose a CA problem.
- The launchers do not record HAR files. Do not run two fresh-session commands at once in one kit profile.

