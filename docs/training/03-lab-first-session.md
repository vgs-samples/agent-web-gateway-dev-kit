# 3. Lab: your first session

**When you finish this lab you will have** created a reveal session, sent a request through it, read it back and ended it, using only `curl` and `jq`. No browser, no checkout and no adapter.

> **Status: preview.** These steps follow the API reference and the kit's code and have not yet been validated end to end. If a step does not behave as written, tell your VGS contact.

## What you need

1. A [service account](https://docs.verygoodsecurity.com/enterprise-platform/access-management/service-accounts-for-programmatic-access) on a sandbox tenant enabled for AWG, with the scopes `reveal-sessions:write` and `reveal-sessions:read`. You need both: write does not include read.
2. Your tenant id. It starts with `tnt`.
3. The aliases of a **test card** already stored in that tenant, with the card's first six digits (BIN) and its length. The [Cards API](https://docs.verygoodsecurity.com/cmp/developer-resources/api/cards) stores one. Lab 4's script stores one.
4. A website to call. Pick any site you would be happy to load in a browser.
5. A terminal running `bash`, with `curl` and `jq`. On macOS, type `bash` first.

These commands use Sandbox.

## Steps

### 1. Set up your shell

```bash
mkdir -p ~/awg-lab && cd ~/awg-lab
export VGS_API=https://sandbox.vgsapi.com
export VGS_AUTH_URL=https://auth.verygoodsecurity.com/auth/realms/vgs/protocol/openid-connect/token
export TENANT_ID=tnt...
read -r  VGS_CLIENT_ID
read -rs VGS_CLIENT_SECRET
```

Replace `tnt...` with your tenant id. Each `read` waits for you to paste a value and press Enter. The secret is not shown and is not saved to a file.

### 2. Get an access token

```bash
TOKEN=$(curl -sS -X POST "$VGS_AUTH_URL" \
  -d grant_type=client_credentials \
  -d client_id="$VGS_CLIENT_ID" \
  -d client_secret="$VGS_CLIENT_SECRET" | jq -r '.access_token // empty')
[ -n "$TOKEN" ] && echo "token ok"
```

**Success:** it prints `token ok`. If it prints nothing, the client id or secret is wrong.

### 3. Create the session

You send VGS the card's aliases and the host the session may reach. Replace the two aliases and the host.

```bash
umask 077
curl -sS "$VGS_API/reveal-sessions" \
  -H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $TENANT_ID" \
  -H 'Content-Type: application/vnd.api+json' \
  -o session.json -w '%{http_code}\n' \
  -d '{"data": {"type": "reveal-sessions", "attributes": {
        "allowed_hosts": ["www.example-shop.com"],
        "cards": [{"label": "main",
                   "number": {"alias": "tok_sandbox_...", "bin": "411111", "length": 16},
                   "cvc": {"alias": "tok_sandbox_...", "length": 3}}]}}}'
```

**Success:** it prints `201`. The response is saved to `session.json`, which only you can read. It holds the session's proxy login, and VGS returns that only this once.

| If you get | It means |
|---|---|
| `400` | The response's `code` names the problem, for example `invalid_host`, `never_host` or `missing_aliases` |
| `403` | The service account is missing a scope |

### 4. Pull out what you need

```bash
SESSION_ID=$(jq -r .data.id session.json)
PROXY_URL=$(jq -r .data.attributes.proxy.url session.json)
jq -r .data.attributes.proxy.ca_bundle session.json > vgs-session-ca.pem
jq '.data | {id, expires_at: .attributes.expires_at, mode: .attributes.unlisted_host_mode}' session.json
```

**Success:** it prints the session id (starting `RS`), when the session expires, and the tenant's unlisted-host mode.

Do not print `PROXY_URL`. It contains the session's password.

### 5. Send a request through the session

```bash
curl -sS -o /dev/null -D - \
  --proxy "$PROXY_URL" --proxy-cacert vgs-session-ca.pem --cacert vgs-session-ca.pem \
  https://www.example-shop.com/ | grep -i -E '^HTTP|vgs-request-id'
```

**Success:** the output includes a `vgs-request-id` line. That header means the request went through VGS. Every request is traced by that id.

| If you get | It means |
|---|---|
| `407` | The proxy did not accept the session's login. If the session is new, the tenant may not be enabled for AWG; contact VGS support |
| The request is refused by VGS | The host may also need to be an agent destination. See "Details" |

### 6. Read the session back

```bash
curl -sS "$VGS_API/reveal-sessions/$SESSION_ID" \
  -H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $TENANT_ID" \
  -H 'Accept: application/vnd.api+json' \
  | jq '.data.attributes | {state, expires_at, allowed_hosts, reveal_count, refusal_count, unlisted_host_mode}'
```

**Success:** `state` is `active`. Expect `reveal_count` to be `0`, because you loaded a page and sent no session token. Notice there is no proxy login in this response.

### 7. End the session

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X DELETE "$VGS_API/reveal-sessions/$SESSION_ID" \
  -H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $TENANT_ID"
```

**Success:** it prints `204`.

### 8. Prove it ended

Run the command from step 5 again.

**Success:** the proxy now answers `407`. The session's login no longer works.

### 9. Clean up

```bash
rm -f session.json vgs-session-ca.pem
unset TOKEN PROXY_URL VGS_CLIENT_SECRET
```

## What you just saw

- You sent VGS aliases and a host. You got back a proxy login and session tokens.
- A request through the session carries a `vgs-request-id`.
- Reading a session never returns its secrets.
- Ending a session stops its login at once.

Next: [lab 4](04-lab-browser-checkout.md) does the same with a real browser.

---

## Details

- **CVC storage.** If the card was stored with `POST /cards`, as lab 4's script does, its CVC alias is volatile: add `"storage": "VOLATILE"` to the `cvc` part in step 3.
- **Hosts.** The developer guide's quickstart asks for the host to be added as an agent destination as well as listed in `allowed_hosts`. This lab relies on `allowed_hosts` alone; if the request is refused, add the destination (`POST /agent-gateway-destinations`, which needs `agent-gateway:write`). Public echo and request-bin services such as `httpbin.org` are refused with `never_host`.
- **Lifetime.** Sessions last 5 minutes unless the tenant's setting says otherwise. After `expires_at` the proxy answers `407`. The documents do not settle whether reading a session after it expires returns `state: expired` or `404`; the session kit treats `404` as "already ended or expired".
- **Deleting twice.** A repeated delete also returns `204`.

