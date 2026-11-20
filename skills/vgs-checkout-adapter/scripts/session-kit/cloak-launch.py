#!/usr/bin/env python3
"""Open CloakBrowser using a reveal-session JSON, its PAC, CA, and proxy credentials."""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "CloakBrowser"))

from cloakbrowser import launch_persistent_context
from cloakbrowser.license import CloakBrowserLicenseError
from playwright.sync_api import Error as BrowserError

KIT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    state = KIT / (".state-" + os.environ["KIT_ENV"] if os.environ.get("KIT_ENV") else ".state")
    parser.add_argument("session", nargs="?", type=Path, default=state / "latest-session.json")
    parser.add_argument("url", nargs="?", default="https://ipinfo.io/json")
    parser.add_argument("--humanize", action="store_true")
    args = parser.parse_args()
    args.session = args.session.expanduser().resolve()
    os.umask(0o077)
    session = json.loads(args.session.read_text())
    attrs = session["data"]["attributes"]
    if datetime.fromisoformat(attrs["expires_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        parser.error("Reveal session expired; create a fresh session first")
    args.pac_url = attrs["proxy"]["pac_url"]
    if urlsplit(args.pac_url).scheme != "https":
        parser.error("Session PAC URL must use HTTPS")
    vgs = urlsplit(attrs["proxy"]["url"])
    if not (vgs.scheme == "https" and vgs.hostname and vgs.port and vgs.username and vgs.password):
        parser.error("Session JSON must include the authenticated HTTPS proxy URL")
    credentials = {
        f"{vgs.hostname}:{vgs.port}": {"username": unquote(vgs.username), "password": unquote(vgs.password)}
    }
    egress = attrs.get("egress_proxy_settings") or {}
    if egress.get("type") == "custom":
        candidates = []
        request_path = args.session.with_suffix(".request.json")
        if request_path.is_file():
            candidates.append(json.loads(request_path.read_text())["data"]["attributes"].get("egress_proxy_settings") or {})
        # API responses normally mask the egress password. Prefer the saved creation
        # request, never invent credentials or change routes.
        selected = next((c for c in candidates
                         if all(c.get(k) == egress.get(k) for k in ("scheme", "hostname", "port", "username"))
                         and isinstance(c.get("password"), str) and c["password"]), None)
        if egress.get("has_password") or egress.get("username"):
            if selected is None:
                parser.error("Missing egress credentials: keep the matching .request.json beside the session JSON")
            credentials[f"{selected['hostname']}:{selected['port']}"] = {
                "username": selected["username"], "password": selected["password"]}

    root = args.session.parent.parent / "cloak-sessions"
    root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="browser-", dir=root))
    ext = run / "extension"
    ext.mkdir()
    ca = run / "vgs-ca.pem"
    ca.write_text(attrs["proxy"]["ca_bundle"])
    pub = subprocess.check_output(["openssl", "x509", "-in", str(ca), "-pubkey", "-noout"])
    der = subprocess.check_output(["openssl", "pkey", "-pubin", "-outform", "der"], input=pub)
    pin = base64.b64encode(hashlib.sha256(der).digest()).decode()
    (ext / "manifest.json").write_text(json.dumps({
        "manifest_version": 3, "name": "VGS session PAC and proxy authentication", "version": "1.0",
        "permissions": ["proxy", "webRequest", "webRequestAuthProvider"],
        "host_permissions": ["<all_urls>"],
        "background": {"service_worker": "background.js"},
    }))
    (ext / "background.js").write_text(
        "const PAC_URL = " + json.dumps(args.pac_url) + ";\n"
        "const CREDENTIALS = " + json.dumps(credentials) + ";\n" + r'''
const attempted = new Map();
globalThis.proxyErrors = [];
chrome.proxy.onProxyError.addListener(error => globalThis.proxyErrors.push(error));
chrome.webRequest.onAuthRequired.addListener((details, callback) => {
    if (!details.isProxy) return callback({});
    const key = details.challenger.host.toLowerCase() + ":" + details.challenger.port;
    const tried = attempted.get(details.requestId) || new Set();
    if (!CREDENTIALS[key] || tried.has(key)) return callback({cancel: true});
    tried.add(key);
    attempted.set(details.requestId, tried);
    callback({authCredentials: CREDENTIALS[key]});
}, {urls: ["<all_urls>"]}, ["asyncBlocking"]);
chrome.webRequest.onCompleted.addListener(d => attempted.delete(d.requestId), {urls: ["<all_urls>"]});
chrome.webRequest.onErrorOccurred.addListener(d => attempted.delete(d.requestId), {urls: ["<all_urls>"]});
globalThis.pacReady = new Promise((resolve, reject) => {
    chrome.proxy.settings.set({
        value: {mode: "pac_script", pacScript: {url: PAC_URL, mandatory: true}},
        scope: "regular"
    }, () => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else resolve(true);
    });
});
''')
    profile_dir = run / "profile"
    (profile_dir / "Default").mkdir(parents=True)
    (profile_dir / "Default/Preferences").write_text(json.dumps({"extensions":{"ui":{"developer_mode":True}}}))
    context = None
    record = {"sessionId": session["data"]["id"], "expiresAt": attrs["expires_at"],
              "pacUrl": args.pac_url, "runDirectory": str(run), "pid": os.getpid(), "status": "starting"}
    latest = root / "latest.json"

    def save():
        text = json.dumps(record, indent=2) + "\n"
        (run / "state.json").write_text(text)
        latest.write_text(text)

    save()
    try:
        context = launch_persistent_context(
            profile_dir, headless=False, timezone=os.environ.get("CLOAK_TZ", "UTC"),
            locale=os.environ.get("CLOAK_LOCALE", "en-US"), humanize=args.humanize,
            geoip=False, extension_paths=[str(ext)],
            # Block initial traffic until the extension applies the mandatory PAC.
            args=["--proxy-server=http://127.0.0.1:9", "--disable-quic",
                  "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                  "--ignore-certificate-errors-spki-list=" + pin],
        )
        worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker", timeout=20000)
        worker.evaluate("() => globalThis.pacReady")
        config = worker.evaluate("() => new Promise(resolve => chrome.proxy.settings.get({incognito:false}, resolve))")
        value = config["value"]
        if value.get("mode") != "pac_script" or value.get("pacScript") != {"url": args.pac_url, "mandatory": True}:
            raise RuntimeError("Browser did not confirm the required PAC configuration")
        record.update(status="open", proxyConfig=value)
        save()
        page = context.pages[0] if context.pages else context.new_page()
        try:
            response = page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
            record.update(pageUrl=page.url, pageStatus=response.status if response else None,
                          proxyErrors=worker.evaluate("() => globalThis.proxyErrors"))
            if args.url == "https://ipinfo.io/json" and response and response.ok:
                try:
                    info = json.loads(page.locator("body").inner_text())
                    record["observedEgress"] = {k: info[k] for k in ("ip", "city", "region", "country", "org") if k in info}
                except (ValueError, BrowserError):
                    pass
        except BrowserError as error:
            record.update(pageError=type(error).__name__)
            print("Page did not load; the browser remains open. Check the session and egress proxy.", flush=True)
        save()
        page.bring_to_front()
        print("Session: " + session["data"]["id"] + "  expires " + attrs["expires_at"], flush=True)
        print("Profile: " + str(profile_dir), flush=True)
        print("CloakBrowser is open. Close its window to stop.", flush=True)
        closed = []
        context.on("close", lambda *_: closed.append(True))
        try:
            while context.pages and not closed:
                context.pages[0].wait_for_timeout(1000)
        except BrowserError:
            if not closed:
                raise
    except KeyboardInterrupt:
        pass
    except CloakBrowserLicenseError as error:
        record.update(status="error", error=str(error))
        save()
        print(str(error), file=sys.stderr, flush=True)
        return 1
    except (BrowserError, RuntimeError) as error:
        record.update(status="error", errorType=type(error).__name__)
        save()
        # Browser launch traces can contain license or proxy credentials.
        print("CloakBrowser setup failed: " + type(error).__name__, file=sys.stderr, flush=True)
        return 1
    finally:
        if context is not None:
            try:
                context.close()
            except BrowserError:
                pass
        if record["status"] != "error":
            record["status"] = "closed"
            save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
