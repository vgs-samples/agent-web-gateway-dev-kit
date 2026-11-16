# What real sites taught us

These are from the H&M US purchase through the gateway: prod sandbox, 2026-11-14, order placed, $29.31.

## Bot walls (Akamai, and likely Cloudflare, DataDome, PerimeterX)

| Symptom | Cause | Fix |
|---|---|---|
| 403 "Access Denied", `Server: AkamaiGHost`, on every page through the gateway, while direct is 200 | The gateway terminates TLS for allowed hosts, so the site sees the gateway's Java TLS fingerprint and `Via: 1.1 proxy` instead of Chrome | Turn on the vault preference `agentGatewayBrowserEmulation=true` (dashboard, or `PATCH /preferences/agentGatewayBrowserEmulation`; needs `preferences:write` + `agent-gateway:write`). Connections then use Chrome's TLS and HTTP/2 settings, with no `Via` header. |
| Pages 200 but the cart POST answers 403 | The egress proxy rotates the exit IP per connection, and Akamai binds its cookies to the client | Use a sticky egress session. For SOAX, append `-session-<id>` to the username; `sticky_suffix` in `sites.yaml` does this per run. |
| Cart POST 403 now and then | Akamai's sensor hadn't validated the session yet (`_abck` cookie without `~0~`) | Call `run.browse()` (mouse moves and scrolling until `~0~` appears) before cart and checkout POSTs; `run.retry_post` repeats after a warm-up. |
| Email lookup POST 403 every time, even without the gateway | The site rate-limits lookups of one email address | Use a fresh contact email for the run. |
| The `Save` button doesn't respond | The cookie banner came back and covers the page | The runner rejects banners automatically (`reject_cookies_handler`); add the site's selector to `cookie_reject` if needed. |

How to tell whose problem it is: `probe --direct` loads the same URLs through the egress proxy only. If direct is 200
and the gateway is 403, it's the gateway path (TLS, headers, IP). If both are 403, it's the site or the IP.

## Card forms and functions

- The card form receives only the session's **stand-ins**. On the H&M confirmation page the card shows the real
  card's last 4 digits, which proves the encrypt function used the real card.
- Adyen: the capture binding must see the Secured Fields page load **in the same session** before checkout. The
  runner waits up to 60 s for the three card iframes, and checks `include=values` for the key before typing.
- A function that silently does nothing is the most common failure. Check `reveal_count` and `refusal_count` after a
  run (`GET /reveal-sessions/{id}`), or use the level 2 harness.

## Running demos

- Record every run. The videos are in `runs/<kind>-<time>/<site>/`.
- With `--purchase`, the order is placed only if the shown total is at or below `--max-total`. Nothing is retried
  after the order request has been sent.
- A captioned "3-D Secure" step only means a payment frame was on screen. Look at the video before claiming 3DS
  happened.
