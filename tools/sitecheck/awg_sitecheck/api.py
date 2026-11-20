"""Minimal VGS API client (JSON:API, bearer token from client credentials)."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import die, keychain

JSONAPI = "application/vnd.api+json"


class ApiError(Exception):
    def __init__(self, status, body, what):
        super().__init__(f"{what}: HTTP {status}: {str(body)[:600]}")
        self.status, self.body = status, body


class Api:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg.endpoints["api"]
        self._token, self._exp = None, 0

    def token(self):
        if os.environ.get("VGS_ACCESS_TOKEN"):
            return os.environ["VGS_ACCESS_TOKEN"]
        if self._token and time.time() < self._exp - 30:
            return self._token
        cid, sec = os.environ.get("VGS_CLIENT_ID"), os.environ.get("VGS_CLIENT_SECRET")
        if not (cid and sec):
            svc = os.environ.get("VGS_KEYCHAIN") or self.cfg.defaults.get("keychain")
            if not svc:
                die("set VGS_CLIENT_ID/VGS_CLIENT_SECRET, VGS_ACCESS_TOKEN, or VGS_KEYCHAIN")
            cid, sec = keychain(svc, account=True), keychain(svc)
        data = urllib.parse.urlencode({"client_id": cid, "client_secret": sec,
                                       "grant_type": "client_credentials"}).encode()
        with urllib.request.urlopen(urllib.request.Request(self.cfg.endpoints["auth"], data=data), timeout=30) as r:
            doc = json.loads(r.read())
        self._token, self._exp = doc["access_token"], time.time() + int(doc.get("expires_in", 300))
        return self._token

    def call(self, method, path, body=None, timeout=90):
        h = {"Authorization": "Bearer " + self.token(), "VGS-Tenant": self.cfg.tenant, "Accept": JSONAPI}
        data = None
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), JSONAPI
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw[:800]

    def ok(self, method, path, body=None, what=None):
        st, doc = self.call(method, path, body)
        if st not in (200, 201, 204):
            raise ApiError(st, doc, what or f"{method} {path}")
        return doc

    def data(self, method, path, body=None, what=None):
        return (self.ok(method, path, body, what) or {}).get("data")

    @staticmethod
    def resource(rtype, **attributes):
        return {"data": {"type": rtype, "attributes": attributes}}
