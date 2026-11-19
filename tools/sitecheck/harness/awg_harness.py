#!/usr/bin/env python3
"""awg-harness verify: test an adapter's capture and re-encrypt functions without touching the merchant.

  python3 awg_harness.py verify merchants/hm.json [merchants/jysk.json ...]
  python3 awg_harness.py verify merchants/hm.json --function FN_REPLACE_WITH_YOUR_FUNCTION_ID=my_edit.star
  python3 awg_harness.py verify merchants/*.json --card card.json

For each merchant file:
  1. capture: dry-runs the capture binding's functions on the saved page/response and checks that the merchant's
     public key lands in the session (no proxy, no network beyond the VGS API).
  2. re-encrypt, through the real session proxy: copies the checkout binding (same adapter version, functions and
     inputs) onto a unique echo path, plants a key the harness owns into a fresh reveal session, sends the merchant's
     checkout body, and decrypts what the upstream would have received. Every `browser-jwe-<role>` placeholder must
     come back as a JWE under the harness key carrying the right value; everything else must be unchanged.
Everything created (bindings, functions, sessions, the echo agent destination) is deleted at the end.

Credentials: VGS_ACCESS_TOKEN, or VGS_CLIENT_ID + VGS_CLIENT_SECRET (client credentials); VGS_TENANT (vault id).
Card: --card FILE with {"number": {"alias", "bin", "length"}, "cvc": {"alias", "length"}} as a session takes it.
Without --card the dev smoke card is used; it has no CVC alias, so CVC fields are reported as untested.
"""
import argparse, base64, hashlib, json, os, re, signal, subprocess, sys, tempfile, time, urllib.error, urllib.parse
import urllib.request
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

API = os.environ.get("VGS_API", "https://sandbox.vgsapi.com")
AUTH = os.environ.get("VGS_AUTH_URL", "https://auth.verygoodsecurity.com/auth/realms/vgs/protocol/openid-connect/token")
ECHO = os.environ.get("HARNESS_ECHO_HOST", "echo.apps.verygood.systems")
# the binding whose capture function plants the harness key: an Adyen secured-fields page capture
# The binding whose capture function plants the harness key: HARNESS_PLANT_BINDING, else the merchant's own capture binding.
PLANT_BINDING = os.environ.get("HARNESS_PLANT_BINDING")
KEY_MARKER = "Object.defineProperty(window, 'adyen', { value: Object.freeze({key: '"
TIME_MARKER = "Object.defineProperty(window, 'genTime', { value: '"
PLACEHOLDER = re.compile(r"^browser-jwe-(number|cvc|expiryMonth|expiryYear)$")
HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- VGS API
class Api:
    def __init__(self):
        self.tenant = os.environ.get("VGS_TENANT")
        self.token = os.environ.get("VGS_ACCESS_TOKEN") or self._client_token()

    def _client_token(self):
        cid, secret = os.environ.get("VGS_CLIENT_ID"), os.environ.get("VGS_CLIENT_SECRET")
        if not (cid and secret):
            cid, secret, self.tenant = self._dev_keychain()
        data = urllib.parse.urlencode({"client_id": cid, "client_secret": secret,
                                       "grant_type": "client_credentials"}).encode()
        with urllib.request.urlopen(urllib.request.Request(AUTH, data=data), timeout=30) as r:
            return json.loads(r.read())["access_token"]

    def _dev_keychain(self):
        # fallback for the AWG dev workstation: the smoke service account in the macOS keychain
        sys.path.insert(0, os.path.join(HERE, "..", "awg-cd"))
        import awg_cd
        p = subprocess.run(["security", "find-generic-password", "-s", awg_cd.KEYCHAIN_SERVICE],
                           capture_output=True, text=True)
        m = re.search(r'"acct"<blob>="([^"]+)"', p.stdout)
        if not m:
            raise SystemExit("set VGS_ACCESS_TOKEN or VGS_CLIENT_ID/VGS_CLIENT_SECRET, and VGS_TENANT")
        secret = subprocess.run(["security", "find-generic-password", "-s", awg_cd.KEYCHAIN_SERVICE, "-w"],
                                capture_output=True, text=True).stdout.strip()
        return m.group(1), secret, self.tenant or awg_cd.SMOKE_ENV["TENANT"]

    def call(self, method, path, body=None):
        if not self.tenant:
            raise SystemExit("set VGS_TENANT")
        h = {"Authorization": "Bearer " + self.token, "VGS-Tenant": self.tenant, "Accept": "application/vnd.api+json"}
        data = None
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/vnd.api+json"
        req = urllib.request.Request(API + path, data=data, method=method, headers=h)
        for attempt in (1, 2, 3):
            try:
                with urllib.request.urlopen(req, timeout=150) as r:
                    raw = r.read()
                    return r.status, (json.loads(raw) if raw else None)
            except urllib.error.HTTPError as e:
                raw = e.read()
                try:
                    return e.code, json.loads(raw)
                except ValueError:
                    return e.code, raw[:500].decode("utf-8", "replace")
            except urllib.error.URLError as e:
                # urllib raises URLError while connecting (DNS, TCP, TLS handshake): the request was not sent,
                # so even a create is safe to repeat
                if attempt == 3:
                    raise HarnessError(f"{method} {path}: VGS API unreachable ({e.reason})")
                time.sleep(2 * attempt)
            except (TimeoutError, ConnectionError) as e:
                # after the request was sent: only reads and deletes are safe to repeat
                if attempt == 3 or method not in ("GET", "DELETE"):
                    raise HarnessError(f"{method} {path}: no answer from the VGS API ({e})")
                time.sleep(2 * attempt)

    def ok(self, method, path, body=None, what=""):
        st, doc = self.call(method, path, body)
        if st not in (200, 201, 204):
            raise HarnessError(f"{what or method + ' ' + path} -> HTTP {st}: {json.dumps(doc)[:500]}")
        return doc


class HarnessError(Exception):
    pass


# ---------------------------------------------------------------- crypto
class HarnessKey:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.adyen = "10001|" + format(self.key.public_key().public_numbers().n, "X").rjust(512, "0")

    def decrypt(self, token):
        b = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        h, ek, iv, ct, tag = token.split(".")
        cek = self.key.decrypt(b(ek), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(),
                                                   label=None))
        plain = AESGCM(cek).decrypt(b(iv), b(ct) + b(tag), h.encode("ascii"))
        return json.loads(b(h)), json.loads(plain)


def is_jwe(value):
    return isinstance(value, str) and value.count(".") == 4 and value.startswith("eyJ")


# ---------------------------------------------------------------- merchant files
def resolve(value, binding_inputs, key):
    """Fill a merchant body template: $binding_input:NAME, $harness_key and {"$json_string": X}."""
    if isinstance(value, dict):
        if set(value) == {"$json_string"}:
            return json.dumps(resolve(value["$json_string"], binding_inputs, key))
        return {k: resolve(v, binding_inputs, key) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, binding_inputs, key) for v in value]
    if isinstance(value, str):
        if value == "$harness_key":
            return key
        if value.startswith("$binding_input:"):
            name = value.split(":", 1)[1]
            spec = binding_inputs.get(name) or {}
            if spec.get("from") != "constant":
                raise HarnessError(f"body template needs binding input {name!r} as a constant")
            return spec["value"]
    return value


def drop_placeholders(value, role):
    """Remove every field whose value is the placeholder for role (also inside JSON-string wrappers)."""
    if isinstance(value, dict):
        return {k: drop_placeholders(v, role) for k, v in value.items() if v != f"browser-jwe-{role}"}
    if isinstance(value, list):
        return [drop_placeholders(v, role) for v in value]
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            return json.dumps(drop_placeholders(json.loads(value), role))
        except ValueError:
            return value
    return value


# ---------------------------------------------------------------- the run
class Run:
    def __init__(self, api, args):
        self.api, self.args = api, args
        self.cleanup = []
        self.id = "harness-" + os.urandom(4).hex()
        self.work = tempfile.mkdtemp(prefix="awg-harness-")
        os.chmod(self.work, 0o700)
        self.function_overrides = {}  # original function id -> harness copy id

    def created(self, prefix, rid):
        self.cleanup.append((prefix, rid))

    def close(self, keep=()):
        """Delete what this run created, except resources under the `keep` path prefixes."""
        kept = []
        for prefix, rid in reversed(self.cleanup):
            if prefix in keep:
                kept.append((prefix, rid))
                continue
            try:
                st, _ = self.api.call("DELETE", prefix + rid)
            except HarnessError as e:
                st = str(e)
            if st not in (200, 204, 404):
                print(f"  cleanup DELETE {prefix}{rid} -> {st} (delete it by hand)")
        self.cleanup[:] = list(reversed(kept))

    def binding(self, bid):
        return self.api.ok("GET", "/agent-gateway-adapter-destinations/" + bid, what="binding " + bid)["data"]["attributes"]

    def override_functions(self):
        """--function FNid=file.star: the edited source as a function the mirrored bindings use instead of FNid.

        A source identical to an existing function (same sha256 and extension point) reuses that function; anything
        else is uploaded for this run and deleted at its end."""
        if not self.args.function:
            return
        existing = self.api.ok("GET", "/functions", what="list functions")["data"]
        for spec in self.args.function:
            fid, path = spec.split("=", 1)
            orig = self.api.ok("GET", "/functions/" + fid, what="function " + fid)["data"]["attributes"]
            source = open(path).read()
            sha = hashlib.sha256(source.encode()).hexdigest()
            same = next((f for f in existing if f["attributes"].get("sha256") == sha
                         and f["attributes"].get("extension_point") == orig.get("extension_point")), None)
            if same:
                self.function_overrides[fid] = same["id"]
                print(f"  function {fid} replaced by {same['id']} from {path} (identical source exists, reused)")
                continue
            attrs = {k: orig[k] for k in ("language", "inputs", "extension_point") if k in orig}
            attrs["name"] = f"{orig.get('name', fid)} [harness {sha[:8]}]"
            attrs["source"] = source
            doc = self.api.ok("POST", "/functions", {"data": {"type": "functions", "attributes": attrs}},
                              what=f"upload {path} as a copy of {fid}")
            self.created("/functions/", doc["data"]["id"])
            self.function_overrides[fid] = doc["data"]["id"]
            print(f"  function {fid} replaced by {doc['data']['id']} from {path} (uploaded for this run)")

    def harness_adapter_version(self, function_ids):
        """A version of this run's own adapter bundling function_ids (edited functions are not in the merchant's
        adapter, and a binding can only run functions of its adapter version). The adapter is deleted at the end."""
        ids = list(dict.fromkeys(function_ids))
        if not getattr(self, "harness_adapter", None):
            doc = self.api.ok("POST", "/agent-gateway-adapters", {"data": {"type": "agent-gateway-adapters",
                              "attributes": {"name": "awg-" + self.id, "functions": ids}}}, what="create the run's adapter")
            self.harness_adapter = doc["data"]["id"]
            self.created("/agent-gateway-adapters/", self.harness_adapter)
        else:
            doc = self.api.ok("POST", "/agent-gateway-adapters/" + self.harness_adapter, {"data": {
                "type": "agent-gateway-adapters", "attributes": {"functions": ids}}}, what="new version of the run's adapter")
        a = doc["data"]["attributes"]
        return doc["data"]["id"], a.get("version") or a.get("latest_version")

    def functions_of(self, b):
        return [{"id": self.function_overrides.get(f["id"], f["id"]), "inputs": f.get("inputs", {})}
                for f in b["functions"]]

    # ---- 1. capture, as a dry run
    def check_capture(self, merchant, key):
        cap = merchant.get("capture")
        if not cap:
            return [("capture", "SKIP", "no capture binding in the merchant file")]
        b = self.binding(cap["binding"])
        resp = cap["response"]
        if "body_file" in resp:
            body = open(os.path.join(os.path.dirname(merchant["_path"]), resp["body_file"]),
                        encoding="utf-8", errors="replace").read()
        else:
            body = resp["body"]
            body = json.dumps(resolve(body, {}, key.adyen)) if not isinstance(body, str) else body
        expected = key.adyen if "$harness_key" in json.dumps(resp.get("body", "")) else None
        if expected is None:
            found = {p.split("'", 1)[0] for p in body.split(KEY_MARKER)[1:]}
            expected = next(iter(found)) if len(found) == 1 else None
        rows = []
        for f in self.functions_of(b):
            inputs = {}
            for name, spec in f["inputs"].items():
                if spec.get("from") == "constant":
                    inputs[name] = spec["value"]
            st, doc = self.api.call("POST", f"/functions/{f['id']}/invocations", {"data": {
                "type": "function-invocations", "attributes": {
                    "response": {"status": resp.get("status", 200), "headers": resp.get("headers", {}), "body": body},
                    "inputs": inputs, "session": {"values": {}, "context": {}}}}})
            a = ((doc or {}).get("data") or {}).get("attributes") or {} if isinstance(doc, dict) else {}
            if st not in (200, 201) or a.get("error"):
                rows.append(("capture " + f["id"], "FAIL", f"dry run HTTP {st}: {a.get('error') or json.dumps(doc)[:300]}"))
                continue
            values = ((a.get("result") or {}).get("session") or {}).get("values") or {}
            got = values.get("adyen_public_key")
            if not got:
                rows.append(("capture " + f["id"], "FAIL", f"no adyen_public_key stored (values: {sorted(values)})"))
            elif expected and got != expected:
                rows.append(("capture " + f["id"], "FAIL", "stored a key that is not the page's key"))
            else:
                extra = sorted(k for k in values if k != "adyen_public_key")
                rows.append(("capture " + f["id"], "PASS",
                             f"stored the merchant key ({got[:12]}...{got[-6:]})" + (f" and {extra}" if extra else "")))
        return rows

    # ---- 2. re-encrypt, through the session proxy
    def via(self, proxy_url, ca, method, url, body, headers):
        cafile, out = os.path.join(self.work, "ca.pem"), os.path.join(self.work, "out.txt")
        with open(cafile, "w") as fh:
            fh.write(ca or "")
        q = lambda v: '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
        cfg = [f"proxy = {q(proxy_url)}", f"proxy-cacert = {q(cafile)}", f"cacert = {q(cafile)}",
               f"request = {method}", f"output = {q(out)}", 'write-out = "%{http_code}"', "silent", "show-error", "max-time = 60",
               f"url = {q(url)}"]
        for k, v in headers.items():
            cfg.append(f"header = {q(k + ': ' + v)}")
        if body is not None:
            cfg.append(f"data-binary = {q(body)}")
        if os.path.exists(out):
            os.remove(out)
        r = subprocess.run(["curl", "-K", "-"], input="\n".join(cfg) + "\n", capture_output=True, text=True)
        text = open(out, encoding="utf-8", errors="replace").read() if os.path.exists(out) else ""
        return int((r.stdout or "0").strip() or 0), text, r.stderr.strip()

    def check_reencrypt(self, merchant, key, card, ensure_echo):
        co = merchant["checkout"]
        b = self.binding(co["binding"])
        version = b["adapter_version"]
        plant_id = PLANT_BINDING or (merchant.get("capture") or {}).get("binding")
        if not plant_id:
            raise HarnessError("no capture binding to plant the key with: set capture.binding or HARNESS_PLANT_BINDING")
        plant = self.binding(plant_id)
        ensure_echo()
        path = urllib.parse.urlsplit(co["url"]).path
        # one path prefix per merchant: bindings for one echo path would overlap across merchants in the same run
        prefix = f"/anything/{self.id}-{os.urandom(3).hex()}"
        mirror_path, plant_path = prefix + path, prefix + "/plant-key"
        # each copy keeps its own binding's adapter version, as the live bindings do (a live session pairs the
        # adapter's capture binding with the merchant's checkout binding, whatever versions they pin). Edited
        # functions are not in the merchant's adapter: then both copies run under a version of `awg-harness`.
        adapter = merchant["adapter"]
        versions = {"plant": plant["adapter_version"], "checkout": version}
        if self.function_overrides:
            adapter, v = self.harness_adapter_version(
                [f["id"] for f in self.functions_of(plant)] + [f["id"] for f in self.functions_of(b)])
            versions = {"plant": v, "checkout": v}
            print(f"  edited functions run under this run's adapter {adapter} v{v}")
        for what, p, src, method in [("plant", plant_path, plant, "POST"),
                                     ("checkout", mirror_path, b, co.get("method", "POST"))]:
            d = self.api.ok("POST", "/agent-gateway-adapter-destinations", {"data": {
                "type": "agent-gateway-adapter-destinations", "attributes": {
                    "adapter": adapter, "adapter_version": versions[what], "enabled": True,
                    "when": {"host": ECHO, "method": method, "path": p}, "functions": self.functions_of(src)}}},
                what=what + " binding")
            self.created("/agent-gateway-adapter-destinations/", d["data"]["id"])
        print(f"  mirrored {co['binding']} (adapter v{versions['checkout']}, {[f['id'] for f in self.functions_of(b)]}) "
              f"onto {ECHO}{mirror_path}; key planted by {plant_id} (adapter v{versions['plant']})")

        sent = resolve(co["body"], b["functions"][0].get("inputs", {}), key.adyen)
        rows = []
        if "cvc" not in card and "browser-jwe-cvc" in json.dumps(sent):
            if self.args.keep_cvc:
                rows.append(("cvc", "NOTE", "card has no CVC alias; CVC field kept (--keep-cvc), expect a failure"))
            else:
                sent = drop_placeholders(sent, "cvc")
                rows.append(("cvc", "UNTESTED", "card has no CVC alias (pass --card with one); CVC field left out"))

        gen_page = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        gen_context = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        context = dict(merchant.get("context", {}), adyen_generationtime=gen_context)
        s = self.api.ok("POST", "/reveal-sessions", {"data": {"type": "reveal-sessions", "attributes": {
            "adapter": adapter, "allowed_hosts": [ECHO], "cards": [card], "context": context}}},
            what="reveal session")["data"]
        self.created("/reveal-sessions/", s["id"])
        proxy = s["attributes"]["proxy"]
        page = KEY_MARKER + key.adyen + "' }) });" + TIME_MARKER + gen_page + "' });"
        # new bindings take a while to reach the proxy: repeat the plant page until the session holds the harness key
        start, planted = time.monotonic(), False
        while time.monotonic() - start < self.args.propagation:
            st, text, err = self.via(proxy["url"], proxy.get("ca_bundle"), "POST", f"https://{ECHO}{plant_path}",
                                     json.dumps({"page": page}), {"Content-Type": "application/json"})
            if st == 0:
                # curl never got an answer from the session proxy (connect or read timeout): try again
                rows.append(("plant key", "NOTE", f"no answer from the session proxy, retrying: {err[:120]}"))
                continue
            if st != 200:
                return rows + [("plant key", "FAIL", f"HTTP {st} {text[:200]} {err[:200]}")]
            # session values are kept per adapter: {"<adapter id>": {"adyen_public_key": ...}}
            values = self.api.ok("GET", f"/reveal-sessions/{s['id']}?include=values")["data"]["attributes"].get("values") or {}
            if (values.get(adapter) or {}).get("adyen_public_key") == key.adyen:
                planted = True
                break
            time.sleep(5)
        if not planted:
            return rows + [("plant key", "FAIL", f"the plant binding did not take effect within {self.args.propagation}s")]
        rows.append(("plant key", "INFO", f"harness key in the session after {time.monotonic() - start:.0f}s"))

        # the checkout copy was created with the plant copy; give it the same grace before calling it a function failure
        body_text, start = json.dumps(sent), time.monotonic()
        while True:
            st, text, err = self.via(proxy["url"], proxy.get("ca_bundle"), co.get("method", "POST"),
                                     f"https://{ECHO}{mirror_path}", body_text, co.get("headers", {}))
            if st != 200:
                return rows + [("checkout", "FAIL", f"HTTP {st}: {text[:300] or err[:300]}")]
            try:
                received = json.loads(text)["json"]
            except (ValueError, KeyError, TypeError):
                return rows + [("checkout", "FAIL", f"echo did not return a JSON body: {text[:200]}")]
            if json.dumps(received, sort_keys=True) != json.dumps(sent, sort_keys=True):
                break
            if time.monotonic() - start > self.args.propagation:
                rows.append(("checkout", "NOTE", f"body came back unchanged for {self.args.propagation}s: the "
                                                 "function did not act on it (or its binding never went live)"))
                break
            time.sleep(5)
        counters = self.api.ok("GET", "/reveal-sessions/" + s["id"])["data"]["attributes"]
        rows += self.compare(sent, received, key, context, gen_page, gen_context, card)
        rows.append(("session", "INFO", f"reveal_count={counters.get('reveal_count')} "
                                        f"refusal_count={counters.get('refusal_count')} session {s['id']}"))
        return rows

    def compare(self, sent, got, key, context, gen_page, gen_context, card, where=""):
        rows = []
        if isinstance(sent, dict) and isinstance(got, dict):
            for k in sorted(set(sent) | set(got)):
                p = f"{where}/{k}"
                if k not in got:
                    rows.append((p, "FAIL", "field removed"))
                elif k not in sent:
                    rows.append((p, "FAIL", "field added"))
                else:
                    rows += self.compare(sent[k], got[k], key, context, gen_page, gen_context, card, p)
            return rows
        if isinstance(sent, list) and isinstance(got, list) and len(sent) == len(got):
            for i, (a, b) in enumerate(zip(sent, got)):
                rows += self.compare(a, b, key, context, gen_page, gen_context, card, f"{where}/{i}")
            return rows
        if isinstance(sent, str) and isinstance(got, str) and sent.strip().startswith("{") and got.strip().startswith("{"):
            try:
                return self.compare(json.loads(sent), json.loads(got), key, context, gen_page, gen_context, card,
                                    where + " (JSON string)")
            except ValueError:
                pass
        m = PLACEHOLDER.match(sent) if isinstance(sent, str) else None
        if sent == got:
            return [(where, "FAIL", f"placeholder not replaced: {sent}")] if m else []
        if not m:
            return [(where, "FAIL", f"changed a field that is not a card placeholder: {str(sent)[:60]!r}")]
        role = m.group(1)
        if not is_jwe(got):
            return [(where, "FAIL", f"{role}: replaced with something that is not a JWE: {str(got)[:60]!r}")]
        try:
            header, payload = key.decrypt(got)
        except Exception as e:  # noqa: BLE001 - any failure here means Adyen could not decrypt it either
            return [(where, "FAIL", f"{role}: not decryptable with the captured key ({type(e).__name__})")]
        problems = []
        if (header.get("alg"), header.get("enc"), str(header.get("version"))) != ("RSA-OAEP-256", "A256GCM", "1"):
            problems.append(f"header {header}")
        value = payload.get(role)
        if value is None:
            problems.append(f"payload has no {role!r} key: {sorted(payload)}")
        elif role == "number":
            n = card["number"]
            if not (value.isdigit() and len(value) == n.get("length", len(value)) and value.startswith(str(n.get("bin", "")))):
                problems.append("number does not match the card's bin/length")
        elif role == "expiryMonth" and value != str(context.get("adyen_expiry_month")):
            problems.append(f"expiryMonth {value!r} != context {context.get('adyen_expiry_month')!r}")
        elif role == "expiryYear" and value != str(context.get("adyen_expiry_year")):
            problems.append(f"expiryYear {value!r} != context {context.get('adyen_expiry_year')!r}")
        elif role == "cvc" and not (value.isdigit() and len(value) == card.get("cvc", {}).get("length", len(value))):
            problems.append("cvc is not the card's CVC length")
        gt = payload.get("generationtime")
        source = "Adyen page genTime" if gt == gen_page else "session context" if gt == gen_context else "UNKNOWN"
        if source == "UNKNOWN":
            problems.append(f"generationtime {gt!r} is neither the page's genTime nor the session context")
        shown = (value[:6] + "..." + value[-4:]) if role in ("number",) and value else ("***" if role == "cvc" else value)
        detail = f"{role}={shown} generationtime from {source}"
        return [(where, "FAIL" if problems else "PASS", detail + ("; " + "; ".join(problems) if problems else ""))]


def verify(args):
    api = Api()
    card = json.load(open(args.card)) if args.card else None
    if card is None:
        sys.path.insert(0, os.path.join(HERE, "..", "awg-cd"))
        try:
            import awg_cd
        except ImportError:
            raise SystemExit("pass --card card.json: the session card (see card.example.json)")
        card = {"label": "harness", "number": {"alias": awg_cd.SMOKE_ENV["ALIAS_CARD"], "bin": "411111", "length": 16}}
    run = Run(api, args)
    echo_state = {}

    def ensure_echo():
        if echo_state:
            return
        st, dests = api.call("GET", "/agent-gateway-destinations")
        if st == 200 and any(d["attributes"].get("host_pattern") == ECHO for d in dests["data"]):
            echo_state["ok"] = True
            return
        d = api.ok("POST", "/agent-gateway-destinations", {"data": {"type": "agent-gateway-destinations",
                   "attributes": {"host_pattern": ECHO, "action": "trust"}}}, what="echo agent destination")
        run.created("/agent-gateway-destinations/", d["data"]["id"])
        echo_state["ok"] = True

    failed = False
    try:
        run.override_functions()
        for path in args.merchants:
            merchant = json.load(open(path))
            merchant["_path"] = os.path.abspath(path)
            key = HarnessKey()
            print(f"\n== {merchant.get('name', path)}  ({path})")
            try:
                rows = run.check_capture(merchant, key) + run.check_reencrypt(merchant, key, card, ensure_echo)
            except HarnessError as e:
                rows = [("harness", "FAIL", str(e))]
            for where, status, detail in rows:
                print(f"  {status:8} {where or '/'}: {detail}")
            verdict = "FAIL" if any(s == "FAIL" for _, s, _ in rows) else "PASS"
            failed |= verdict == "FAIL"
            print(f"  -> {verdict}")
            # this merchant's bindings and session go now; the echo agent destination, the run's adapter and uploaded
            # functions stay for the next merchant (the final close deletes them, bindings before adapter before functions)
            run.close(keep=("/agent-gateway-destinations/", "/agent-gateway-adapters/", "/functions/"))
    finally:
        run.close()
    return 1 if failed else 0


def _terminated(signum, frame):
    # SIGTERM (e.g. a `timeout` wrapper) would end Python without running `finally`: turn it into an exception so
    # the run still deletes what it created
    raise KeyboardInterrupt(f"signal {signum}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="check capture and re-encrypt for one or more merchant files")
    v.add_argument("merchants", nargs="+")
    v.add_argument("--card", help="JSON file with the session card (number and cvc aliases)")
    v.add_argument("--function", action="append", metavar="FNid=file.star",
                   help="use edited source for a function (uploaded as a temporary copy)")
    v.add_argument("--keep-cvc", action="store_true", help="send CVC placeholders even if the card has no CVC alias")
    v.add_argument("--propagation", type=int, default=120,
                   help="seconds to wait for new bindings to reach the proxy (default 120)")
    args = p.parse_args()
    signal.signal(signal.SIGTERM, _terminated)
    sys.exit(verify(args))


if __name__ == "__main__":
    main()
