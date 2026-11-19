"""Legacy API client restricted to the internal environment; tenant comes from credentials."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KIT = Path(__file__).resolve().parent
CONSOLE = KIT.parent / "awg-capture-console"
REG = CONSOLE / "api-model/registrations"
TENANT = "tntFixture"  # Synthetic default for compatibility fixtures; never a real account.
API = "https://sandbox.vgsapi.io"
AUTH = "https://auth.verygoodsecurity.io/auth/realms/vgs/protocol/openid-connect/token"


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ApiError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class Client:
    def __init__(self, env_file=None):
        self.credentials_file = str(Path(env_file or KIT / ".env.dev").resolve())
        self.env = dict(line.split("=", 1) for line in Path(env_file or KIT / ".env.dev").read_text().splitlines()
                        if line and not line.startswith("#") and "=" in line)
        assert re.fullmatch(r"tnt[A-Za-z0-9]+", self.env["VGS_TENANT"]) and self.env["VGS_API"] == API
        assert self.env["VGS_AUTH_URL"] == AUTH
        self.tenant, self.environment = self.env["VGS_TENANT"], "dev"
        self.opener = urllib.request.build_opener(NoRedirect())
        self.access_token, self.deadline = None, 0

    def token(self):
        if self.access_token and time.monotonic() < self.deadline:
            return self.access_token
        data = urllib.parse.urlencode({"grant_type": "client_credentials",
                                       "client_id": self.env["VGS_CLIENT_ID"],
                                       "client_secret": self.env["VGS_CLIENT_SECRET"]}).encode()
        with self.opener.open(urllib.request.Request(self.env["VGS_AUTH_URL"], data=data), timeout=30) as r:
            value = json.load(r)
        self.access_token = value["access_token"]
        self.deadline = time.monotonic() + max(1, int(value.get("expires_in", 300)) - 30)
        return self.access_token

    def api(self, method, path, attributes=None, kind=None, accepted=(200, 201, 204), tenant=True):
        payload = None if attributes is None else {"data": {"attributes": attributes}}
        if kind:
            payload["data"]["type"] = kind
        headers = {"Authorization": "Bearer " + self.token(),
                   "Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}
        if tenant:
            headers["VGS-Tenant"] = self.env["VGS_TENANT"]
        req = urllib.request.Request(self.env["VGS_API"] + path, method=method, headers=headers,
                                     data=None if payload is None else json.dumps(payload).encode())
        try:
            with self.opener.open(req, timeout=45) as r:
                code, raw = r.status, r.read()
        except urllib.error.HTTPError as error:
            code, raw = error.code, error.read()
        value = json.loads(raw) if raw else None
        if code not in accepted:
            raise ApiError(code, f"{method} {path}: HTTP {code}: {json.dumps(value)[:2500]}")
        return value
