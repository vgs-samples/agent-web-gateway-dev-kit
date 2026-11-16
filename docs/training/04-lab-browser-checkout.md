# 4. Lab: a browser checkout

You will store a test card, create a session, and open a Chromium window that uses the session's PAC file. The hosts in the PAC file go through VGS; on a build without the PAC split, all traffic does. At the payment form you type the session tokens. This lab uses the `session-kit` scripts in `skills/vgs-checkout-adapter/scripts/session-kit/`.

**Use a test card for this lab**, such as `4111111111111111`. The test kit README of 2026-11-07 says a real merchant will decline a test card and that this is expected: what you check is that pages load through VGS, that you are not treated as a bot, and that the token is swapped on the payment request. Do not submit a payment unless someone has approved that purchase.

## You need

- macOS (Apple silicon or Intel) or Linux x86-64, with `curl`, `jq`, `openssl` and `unzip`.
- A service account, vault id and a test card, as in lab 3. Storing the card also needs a scope that allows `POST /cards` on the vault; ask the AWG team which one.
- An egress proxy you are authorized to use. The kit requires one: with no `EGRESS_PROXY` and no `--egress-profile` it stops, and it does not fall back to VGS's own addresses or another route. Its default is a Byteful residential endpoint. A different endpoint needs both `EGRESS_ALLOWED_HOST` and `EGRESS_ALLOWED_PORT` in `.env` plus `--egress-profile`, which `start.sh` cannot pass; see "Things to know".

## Set up, once

1. Copy the kit to a private folder outside this repository. It will hold credentials and session files.

```bash
cp -R skills/vgs-checkout-adapter/scripts/session-kit ~/awg-session-kit
cd ~/awg-session-kit
bash setup.sh
```

`setup.sh` checks the tools, creates `.env` from `.env.example` with mode 0600, and downloads Chrome for Testing into `./browsers`.

2. Fill in `.env`. Use plain `KEY=value` lines, with no quotes and no `export`.

| Key | Value |
|---|---|
| `VGS_CLIENT_ID`, `VGS_CLIENT_SECRET`, `VGS_TENANT` | Your service account and vault id |
| `VGS_API`, `VGS_AUTH_URL` | Preset for prod sandbox (`.com`). Dev uses the `.io` hosts |
| `EGRESS_PROXY` | Your Byteful proxy URL. `start.sh` needs it set here |
| `ALLOWED_HOSTS` | Optional default hosts |

For a second environment, create `.env.<name>` and prefix every command with `KIT_ENV=<name>`; its state goes to `.state-<name>/`. Variables already exported in your shell override the file, so clear stale `VGS_*` and `EGRESS_*` values before switching.

## Run a session

3. Start. This stores the card, creates a fresh session and opens Chromium.

```bash
./start.sh www.example-shop.com,payments.example-psp.com https://www.example-shop.com/
```

The script prompts for the card number, CVC and expiry; the number and CVC are hidden while you type. Without a terminal, supply `CARD_PAN`, `CARD_CVC` and `CARD_EXP=MM/YY` in the environment. The kit does not save the card number or CVC. `.state/` holds the aliases, the last four digits, BIN, expiry and card id, the full session response, and the session request including the egress proxy password.

The card step stops unless the card call returns `201` with both aliases and a card id different from the last one saved. If the vault already holds that card and answers `303`, the run stops there.

4. Read the output. It prints the session id, `expires_at`, `unlisted_host_mode`, the allowed hosts, the egress proxy, and:

```
tokens_to_type: { "card_number": "…", "card_cvc": "…" }
```

It also prints the card's vault aliases, the proxy username and password, and the PAC link. Treat the terminal output as secret: do not paste it into a ticket or a chat.

5. In the browser, go to the checkout and **type the `tokens_to_type` values**, not the real card and not the vault aliases. Use the card's real expiry date unless the adapter requires an override.

## Check it works

- **Traffic goes through VGS.** Responses from a host that went through VGS carry a `vgs-request-id` header (DevTools → Network), and the host's certificate is issued by the session's CA. The test kit README of 2026-11-07 says the issuer shows as Very Good Security.
- **Your egress IP.** Open `https://ipinfo.io/json` in the session browser to see the exit IP. The test kit README says that with an egress proxy it should show a consumer ISP, not a hosting company. An IP lookup does not tell you how a merchant's bot protection will rate it.
- **The payment host.** The card form may post to a different host than the page. In DevTools → Network, find the request that carries the tokens and check its host is in `allowed_hosts`. If it is not, what happens depends on the vault's unlisted-host mode and on the PAC file:
  - with the PAC split, the request goes direct and the provider receives the session tokens;
  - in `strict` mode, a request VGS can see is refused with `403 reveal_refused` (`session_host_not_allowed`), and an HTTPS host that no rule names is tunnelled untouched;
  - in `guarded` mode, the card may be revealed within the reveal guard's limits;
  - in `step_up` mode, the request is held for approval.

  In every case, start a new session that includes the payment host.
- **The session counters.**

```bash
./session-status.sh        # state, reveal_count, refusal_count of the latest session
```

`reveal_count` going up shows a reveal happened. On its own it does not prove the merchant accepted the payment.

6. End the session.

```bash
./end-session.sh
```

Ending a session does not delete the stored card or local files. Clean `.state/` when you are done with the kit.

## Things to know

- `start.sh` passes only the host list and the URL. For any other option, run `create-fresh-session.sh` with the options, then `launch-chromium.sh`:

```bash
bash ./create-fresh-session.sh --hosts payments.example-psp.com \
  --adapter AD... --egress-profile /absolute/private/proxy.json
./launch-chromium.sh "" https://www.example-shop.com/checkout   # "" = the latest session
```

- `--egress-profile` takes a private JSON file with `scheme`, `hostname`, numeric `port`, `username` and `password`.
- `--adapter AD…` sets the session's `adapter`, which limits the session to that adapter's bindings, and sends role-based `cards`, which functions that call `session.card()` require. The id must be registered in the vault. The named forms `--adapter adyen` and `--adapter stripe` need a registration ledger file; none is bundled.
- The CVC alias is volatile. A new session does not bring back a CVC alias that is no longer available; store the card again.
- `launch-chromium.sh` reopens the latest session in a new browser. `--insecure` skips all certificate checks; use it only to diagnose a CA problem.
- The launchers do not record HAR files.
- Do not run two fresh-session commands at once in one kit profile.

---

Sources: `skills/vgs-checkout-adapter/references/fresh-session.md`, `skills/vgs-checkout-adapter/references/gateway-verification.md`, the scripts in `skills/vgs-checkout-adapter/scripts/session-kit/` (`setup.sh`, `lib.sh`, `start.sh`, `create-card.sh`, `create-session.sh`, `launch-chromium.sh`, `session-status.sh`, `end-session.sh`, `.env.example`), and the test kit README of 2026-11-07 for the "Check it works" steps (not in this repository; quoted in `SOURCES.md`).
