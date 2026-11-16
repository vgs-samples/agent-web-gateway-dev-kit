# 3. Lab: your first session

You will create a reveal session, send one request through it, inspect it and end it, using only `curl` and `jq`. No browser, no merchant checkout and no adapter.

## You need

- A service account on a sandbox vault enabled for AWG, with `reveal-sessions:write` and `reveal-sessions:read`. Write does not include read; you need both for this lab.
- The vault id (`tnt…`).
- The aliases of a **test card** already stored in that vault (number, and CVC if it has one), with the card's BIN and length. Use a test card such as `4111111111111111`. Lab 4 shows a script that stores one.
- A terminal running `bash` (type `bash` first on macOS, where the default shell is zsh).
- A host to call. Use a site you would be content to load in a browser, and add it to `allowed_hosts`. The developer guide's quickstart also asks for the host to be added as an agent destination; this lab relies on `allowed_hosts` alone, so if the request is refused, add the destination. Public echo and request-bin services such as `httpbin.org` are refused with `never_host`.

The commands below use prod sandbox (`.com`). On dev, the API is `https://sandbox.vgsapi.io` and the token URL is on `auth.verygoodsecurity.io`.

## Steps

1. Work in a private folder outside this repository, and put your credentials in the shell without writing them to a file. `read -s` keeps the secret off the screen and out of shell history.

```bash
mkdir -p ~/awg-lab && cd ~/awg-lab
export VGS_API=https://sandbox.vgsapi.com
export VGS_AUTH_URL=https://auth.verygoodsecurity.com/auth/realms/vgs/protocol/openid-connect/token
export VAULT_ID=tnt...
read -r  VGS_CLIENT_ID
read -rs VGS_CLIENT_SECRET
```

Replace `tnt...` with your vault id. Each `read` waits for you to paste a value and press Enter; the secret is not shown.

2. Get an access token (client-credentials grant).

```bash
TOKEN=$(curl -sS -X POST "$VGS_AUTH_URL" \
  -d grant_type=client_credentials \
  -d client_id="$VGS_CLIENT_ID" \
  -d client_secret="$VGS_CLIENT_SECRET" | jq -r '.access_token // empty')
[ -n "$TOKEN" ] && echo "token ok"
```

3. Create the session. Replace the aliases and the host. Save the response to a private file, because it is the only response that contains the proxy login.

```bash
umask 077
curl -sS "$VGS_API/reveal-sessions" \
  -H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $VAULT_ID" \
  -H 'Content-Type: application/vnd.api+json' \
  -o session.json -w '%{http_code}\n' \
  -d '{"data": {"type": "reveal-sessions", "attributes": {
        "allowed_hosts": ["www.example-shop.com"],
        "cards": [{"label": "main",
                   "number": {"alias": "tok_sandbox_...", "bin": "411111", "length": 16},
                   "cvc": {"alias": "tok_sandbox_...", "length": 3}}]}}}'
```

If the card was stored with `POST /cards`, as lab 4's script does, its CVC alias is volatile: add `"storage": "VOLATILE"` to the `cvc` part.

Expect `201`. A `400` carries a `code` that names the problem, for example `invalid_host`, `never_host` or `missing_aliases`. A `403` means a missing scope.

4. Take what you need from the response.

```bash
SESSION_ID=$(jq -r .data.id session.json)
PROXY_URL=$(jq -r .data.attributes.proxy.url session.json)
jq -r .data.attributes.proxy.ca_bundle session.json > vgs-session-ca.pem
jq '.data | {id, expires_at: .attributes.expires_at, mode: .attributes.unlisted_host_mode}' session.json
```

Do not print `PROXY_URL`: it contains the session's password.

5. Send a request through the session.

```bash
curl -sS -o /dev/null -D - \
  --proxy "$PROXY_URL" --proxy-cacert vgs-session-ca.pem --cacert vgs-session-ca.pem \
  https://www.example-shop.com/ | grep -i -E '^HTTP|vgs-request-id'
```

A response with a `vgs-request-id` header went through VGS. Keep that id: it is how every request is traced.

6. Read the session back. Later reads never return secrets.

```bash
curl -sS "$VGS_API/reveal-sessions/$SESSION_ID" \
  -H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $VAULT_ID" \
  -H 'Accept: application/vnd.api+json' \
  | jq '.data.attributes | {state, expires_at, allowed_hosts, reveal_count, refusal_count, unlisted_host_mode}'
```

Expect `reveal_count` to be `0`: you loaded a page and sent no session token.

7. End the session.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X DELETE "$VGS_API/reveal-sessions/$SESSION_ID" \
  -H "Authorization: Bearer $TOKEN" -H "VGS-Tenant: $VAULT_ID"
```

Expect `204`. The runbook says a repeat is also `204`.

8. Run step 5 again. The proxy now answers `407`: it no longer accepts the session's login.

9. Remove the files and the secrets from your shell.

```bash
rm -f session.json vgs-session-ca.pem
unset TOKEN PROXY_URL VGS_CLIENT_SECRET
```

## Things to know

- The default lifetime is 5 minutes unless the vault's setting says otherwise. After `expires_at` the proxy answers `407`. The API defines an `expired` state, but the sources do not settle whether a read after expiry returns `state: expired` or `404`; the session kit treats `404` as "already ended or expired".
- If step 5 returns `407` on a brand-new session, the vault may not be enabled for the AWG cell. That is an escalation, not something you can fix.

---

Sources: `docs/reference/04-developer-guide.md` (Quickstart, Reveal sessions, Errors and limits), `skills/vgs-checkout-adapter/scripts/session-kit/lib.sh` (token request), `end-session.sh` (`404`) and `create-session.sh` (CVC storage), `tools/sitecheck/awg_sitecheck/config.py` (environment URLs), `docs/reference/03-support-runbook.md` (`407`, repeat delete).
