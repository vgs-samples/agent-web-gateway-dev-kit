"""Configuration: environments, credentials and the sites file.

Secrets never live in files of this package. They come from the environment or, on macOS, from the Keychain:

  VGS client credentials   VGS_CLIENT_ID / VGS_CLIENT_SECRET, or VGS_KEYCHAIN=<service> (account = client id)
  Egress proxy password    the egress profile's `password_env` variable, or its `password_keychain` service
"""
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ENVIRONMENTS = {
    "prod-sandbox": {
        "api": "https://sandbox.vgsapi.com",
        "auth": "https://auth.verygoodsecurity.com/auth/realms/vgs/protocol/openid-connect/token",
        "vault_api": "https://{tenant}.sandbox.vault-api.verygoodvault.com",
    },
    "dev": {
        "api": "https://sandbox.vgsapi.io",
        "auth": "https://auth.verygoodsecurity.io/auth/realms/vgs/protocol/openid-connect/token",
        "vault_api": "https://{tenant}.sandbox.vault-api.verygoodvault.io",
    },
}


def die(msg):
    sys.exit(f"awg-sitecheck: {msg}")


def keychain(service, account=False):
    """Read a macOS Keychain generic password (or its account name). Never prints the secret."""
    args = ["security", "find-generic-password", "-s", service] + ([] if account else ["-w"])
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0:
        die(f"no Keychain item {service!r}")
    if not account:
        return out.stdout.strip()
    for line in out.stdout.splitlines():
        if '"acct"<blob>=' in line:
            return line.split("=", 1)[1].strip().strip('"')
    die(f"Keychain item {service!r} has no account")


def secret(env_name=None, keychain_service=None, what="secret"):
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    if keychain_service:
        return keychain(keychain_service)
    die(f"{what}: set {env_name or 'an env variable'}" + (f" or Keychain {keychain_service!r}" if keychain_service else ""))


@dataclass
class Egress:
    """A customer egress proxy for reveal sessions (session `egress_proxy_settings`)."""
    name: str
    scheme: str
    hostname: str
    port: int
    username: str
    password_env: str | None = None
    password_keychain: str | None = None
    # appended to the username to pin one exit IP for a whole session, e.g. "-session-{id}" (SOAX).
    # Akamai and similar bot walls bind their cookies to the client IP; a rotating exit IP gets 403s.
    sticky_suffix: str | None = None

    def settings(self, sticky_id=None):
        user = self.username + (self.sticky_suffix.format(id=sticky_id) if self.sticky_suffix and sticky_id else "")
        return {"type": "custom", "scheme": self.scheme, "hostname": self.hostname, "port": self.port,
                "username": user,
                "password": secret(self.password_env, self.password_keychain, f"egress {self.name} password")}


@dataclass
class Site:
    id: str
    name: str
    urls: list
    allowed_hosts: list = field(default_factory=list)
    adapter: str | None = None
    psp: str | None = None
    recipe: str | None = None
    card: str | None = None
    context: dict = field(default_factory=dict)
    cookie_reject: list = field(default_factory=list)
    contact: dict = field(default_factory=dict)
    egress: str | None = None
    notes: str = ""

    def hosts(self):
        from urllib.parse import urlsplit
        hs = list(self.allowed_hosts)
        for u in self.urls:
            h = urlsplit(u).hostname
            if h and h not in hs:
                hs.append(h)
        return hs


@dataclass
class Config:
    env: str
    tenant: str
    sites: list
    egress: dict
    defaults: dict
    base_dir: Path

    @property
    def endpoints(self):
        e = ENVIRONMENTS.get(self.env)
        if not e:
            die(f"unknown env {self.env!r}; one of {', '.join(ENVIRONMENTS)}")
        return {k: v.format(tenant=self.tenant) for k, v in e.items()}

    def site(self, site_id):
        for s in self.sites:
            if s.id == site_id:
                return s
        die(f"no site {site_id!r} in the sites file")

    def select(self, ids):
        return [self.site(i) for i in ids] if ids else list(self.sites)

    def egress_for(self, site):
        name = site.egress or self.defaults.get("egress")
        if not name or name == "none":
            return None
        if name not in self.egress:
            die(f"site {site.id}: unknown egress profile {name!r}")
        return self.egress[name]

    def path(self, p):
        p = Path(p)
        return p if p.is_absolute() else (self.base_dir / p)

    def card(self, site):
        """The session card file: {"label", "number": {"alias", "bin", "length"}, "cvc": {"alias", "length"}}."""
        f = site.card or self.defaults.get("card")
        if not f:
            die(f"site {site.id}: no card file (set `card:` on the site or under defaults)")
        return json.loads(self.path(f).read_text())


def load(path):
    path = Path(path)
    if not path.exists():
        die(f"sites file {path} not found (copy sites.example.yaml)")
    doc = yaml.safe_load(path.read_text()) or {}
    d = doc.get("defaults", {})
    env = os.environ.get("AWG_ENV") or d.get("env", "prod-sandbox")
    tenant = os.environ.get("VGS_TENANT") or d.get("tenant")
    if not tenant:
        die("set defaults.tenant in the sites file or VGS_TENANT")
    egress = {name: Egress(name=name, **cfg) for name, cfg in (doc.get("egress") or {}).items()}
    sites = []
    for s in doc.get("sites", []):
        merged = {"cookie_reject": d.get("cookie_reject", []), **s,
                  "contact": {**d.get("contact", {}), **s.get("contact", {})}}
        if "context" in d:
            merged["context"] = {**d["context"], **s.get("context", {})}
        sites.append(Site(**merged))
    return Config(env=env, tenant=tenant, sites=sites, egress=egress, defaults=d, base_dir=path.parent)
