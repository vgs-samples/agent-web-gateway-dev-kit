"""Reveal sessions: create one per run, read its captured values and counters, delete it afterwards."""
import json
import os
import secrets
import urllib.parse
from datetime import datetime, timezone

from .api import Api


class RevealSession:
    def __init__(self, api: Api, doc, secret_file=None):
        self.api = api
        self.id = doc["id"]
        self.attrs = doc["attributes"]
        self.secret_file = secret_file

    # --- what the browser needs -------------------------------------------------------------------------------------
    def playwright_proxy(self):
        u = urllib.parse.urlsplit(self.attrs["proxy"]["url"])
        return {"server": f"{u.scheme}://{u.hostname}:{u.port}",
                "username": urllib.parse.unquote(u.username), "password": urllib.parse.unquote(u.password)}

    def ca_bundle(self):
        return self.attrs["proxy"].get("ca_bundle")

    def card(self, label=None):
        cards = self.attrs.get("cards") or []
        for c in cards:
            if label is None or c.get("label") == label:
                return c
        raise KeyError(f"no session card {label!r}")

    # --- what the API says ------------------------------------------------------------------------------------------
    def values(self, adapter=None):
        st, doc = self.api.call("GET", f"/reveal-sessions/{self.id}?include=values")
        vals = ((doc or {}).get("data", {}).get("attributes", {}).get("values") or {}) if st == 200 else {}
        return vals.get(adapter, {}) if adapter else vals

    def counters(self):
        st, doc = self.api.call("GET", f"/reveal-sessions/{self.id}")
        a = (doc or {}).get("data", {}).get("attributes", {}) if st == 200 else {}
        return {k: a.get(k) for k in ("reveal_count", "refusal_count", "state") if k in a}

    def delete(self):
        st, _ = self.api.call("DELETE", f"/reveal-sessions/{self.id}")
        if self.secret_file and os.path.exists(self.secret_file):
            os.remove(self.secret_file)
        return st

    def summary(self):
        eg = dict(self.attrs.get("egress_proxy_settings") or {})
        eg.pop("password", None)
        eg.pop("username", None)
        return {"id": self.id, "expires_at": self.attrs.get("expires_at"),
                "allowed_hosts": self.attrs.get("allowed_hosts"), "egress": eg or None,
                "unlisted_host_mode": self.attrs.get("unlisted_host_mode")}


def create(api: Api, cfg, site, run_dir, with_card=True, sticky=True):
    """Create a reveal session for `site`. The response (with the proxy secret) is kept only in a 0600 file."""
    attrs = {"allowed_hosts": site.hosts()}
    if site.adapter:
        attrs["adapter"] = site.adapter
    if with_card:
        attrs["cards"] = [cfg.card(site)]
    ctx = dict(site.context or {})
    if site.adapter and "adyen_generationtime" not in ctx and (site.psp or "").startswith("adyen"):
        ctx["adyen_generationtime"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if ctx:
        attrs["context"] = ctx
    eg = cfg.egress_for(site)
    if eg:
        attrs["egress_proxy_settings"] = eg.settings(secrets.token_hex(6) if sticky else None)
    doc = api.data("POST", "/reveal-sessions", Api.resource("reveal-sessions", **attrs), f"create session for {site.id}")
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, "session.secret.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(doc, f)
    return RevealSession(api, doc, path)
