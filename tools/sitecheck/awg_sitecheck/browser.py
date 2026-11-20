"""A recorded Chromium routed through a reveal session (or, for comparison, straight through the egress proxy).

Trust: the session's CA is trusted by SPKI pin (`--ignore-certificate-errors-spki-list`), so only certificates the
gateway mints are accepted; set AWG_IGNORE_HTTPS_ERRORS=1 to fall back to ignoring all certificate errors.
"""
import base64
import hashlib
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from cryptography import x509
from cryptography.hazmat.primitives import serialization

CAPTION_JS = """(t) => {
  let d = document.getElementById('__awg_caption');
  if (!d) {
    d = document.createElement('div'); d.id = '__awg_caption';
    d.style.cssText = 'position:fixed;left:16px;right:16px;bottom:16px;z-index:2147483647;background:rgba(17,24,39,.92);'
      + 'color:#fff;font:600 18px/1.4 -apple-system,Helvetica,Arial,sans-serif;padding:14px 18px;border-radius:10px;'
      + 'box-shadow:0 6px 24px rgba(0,0,0,.35);pointer-events:none;white-space:pre-line';
    document.documentElement.appendChild(d);
  }
  d.textContent = t;
}"""

DEFAULT_COOKIE_REJECT = ["#onetrust-reject-all-handler", "#banner-reject-btn", "button#CybotCookiebotDialogBodyButtonDecline",
                         "[data-testid='uc-deny-all-button']", "button:has-text('Reject all')",
                         "button:has-text('Reject All')", "button:has-text('Only necessary')"]


def spki_pins(pem_bundle):
    pins = []
    for block in (pem_bundle or "").split("-----END CERTIFICATE-----"):
        if "BEGIN CERTIFICATE" not in block:
            continue
        cert = x509.load_pem_x509_certificate((block + "-----END CERTIFICATE-----\n").encode())
        spki = cert.public_key().public_bytes(serialization.Encoding.DER,
                                              serialization.PublicFormat.SubjectPublicKeyInfo)
        pins.append(base64.b64encode(hashlib.sha256(spki).digest()).decode())
    return pins


class NetLog:
    """Every response the page saw: host, status, method, type; headers of documents and blocked responses."""

    def __init__(self):
        self.entries = []

    def attach(self, page_or_ctx):
        page_or_ctx.on("response", self._on_response)
        page_or_ctx.on("requestfailed", lambda r: self.entries.append(
            {"url": r.url, "host": urlsplit(r.url).hostname, "status": 0, "method": r.method,
             "type": r.resource_type, "failure": r.failure}))

    def _on_response(self, r):
        e = {"url": r.url, "host": urlsplit(r.url).hostname, "status": r.status, "method": r.request.method,
             "type": r.request.resource_type}
        if r.request.resource_type == "document" or r.status >= 400:
            try:
                e["headers"] = r.headers
            except Exception:
                pass
        self.entries.append(e)

    def hosts(self):
        seen = {}
        for e in self.entries:
            h = e["host"] or "?"
            s = seen.setdefault(h, {"requests": 0, "errors": 0, "statuses": {}})
            s["requests"] += 1
            s["statuses"][str(e["status"])] = s["statuses"].get(str(e["status"]), 0) + 1
            if e["status"] == 0 or e["status"] >= 400:
                s["errors"] += 1
        return seen


class PageAccessError(RuntimeError):
    """A navigation failed before subsequent checkout actions could start."""

    def __init__(self, *, status, url, stage, session_id=None, request_id=None):
        parts = urlsplit(url)
        safe_url = urlunsplit((parts.scheme, parts.netloc.rsplit('@', 1)[-1], parts.path, '', ''))
        self.details = {"stage": stage, "http_status": status, "url": safe_url,
                        "session_id": session_id, "vgs_request_id": request_id,
                        "response_origin": "unconfirmed"}
        outcome = f"HTTP {status}" if status is not None else "no HTTP response"
        super().__init__(f"{stage.replace('_', ' ').capitalize()} request returned {outcome}; "
                         "stopped before subsequent checkout actions. "
                         "Inspect the response and destination policy before retrying.")


class Run:
    """A browser run: page, captions, warm-up, cookie banners and a few payment-field helpers."""

    def __init__(self, page, ctx, site, session=None, netlog=None, captions=True, step_pause_ms=1500,
                 artifact_dir=None):
        self.page, self.ctx, self.site, self.session = page, ctx, site, session
        self.netlog = netlog
        self.captions = captions
        self.step_pause_ms = step_pause_ms
        self.log = []
        self.artifact_dir = Path(artifact_dir) if artifact_dir is not None else None

    def caption(self, text, pause_ms=None):
        print("  >", text.replace("\n", " | "), flush=True)
        self.log.append(text)
        if self.captions:
            try:
                self.page.evaluate(CAPTION_JS, text)
            except Exception:
                pass
        self.page.wait_for_timeout(self.step_pause_ms if pause_ms is None else pause_ms)

    def browse(self, max_ms=30000):
        """Move and scroll like a person until a bot sensor validates the session (Akamai `_abck` with `~0~`).

        Sites without a sensor return after a few seconds. Call it before cart and checkout POSTs.
        """
        end, i = time.time() + max_ms / 1000, 0
        while time.time() < end:
            self.page.mouse.move(250 + 60 * (i % 6), 280 + 35 * (i % 5), steps=12)
            self.page.mouse.wheel(0, 180 if i % 2 == 0 else -180)
            self.page.wait_for_timeout(1500)
            names = {c["name"]: c["value"] for c in self.ctx.cookies()}
            if "_abck" not in names and i >= 2:
                return True
            if "_abck" in names and "~0~" in names["_abck"] and i >= 2:
                return True
            i += 1
        print("  ! bot sensor not validated after", max_ms, "ms", flush=True)
        return False

    def exit_ip(self):
        """Where the site sees us coming from (loaded in a tab, so it uses the same proxy and CA pin as the pages)."""
        tab = self.ctx.new_page()
        try:
            tab.goto("https://ipinfo.io/json", timeout=30000)
            import json as _json
            d = _json.loads(tab.inner_text("body"))
            return {k: d.get(k) for k in ("ip", "city", "region", "country", "org")}
        except Exception as e:
            return {"error": str(e).splitlines()[0][:200]}
        finally:
            tab.close()

    def goto(self, url, timeout=90000):
        r = self.page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        self.page.wait_for_timeout(2500)
        return r

    def require_success(self, response, *, stage, url):
        """Stop a checkout on a failed page; probes can still inspect non-2xx responses."""
        status = response.status if response is not None else None
        if status is not None and 200 <= status < 400:
            return
        headers = response.headers if response is not None else {}
        error = PageAccessError(status=status, url=url, stage=stage,
                                session_id=getattr(self.session, 'id', None),
                                request_id=headers.get('vgs-request-id'))
        if self.artifact_dir is not None:
            try:
                self.artifact_dir.mkdir(parents=True, exist_ok=True)
                path = self.artifact_dir / 'failure.png'
                self.page.screenshot(path=str(path))
                error.details['screenshot'] = str(path)
            except Exception as screenshot_error:
                error.details['screenshot_error'] = type(screenshot_error).__name__
        raise error

    def retry_post(self, url_part, click, attempts=4, ok=(200, 201, 204), pause_ms=10000):
        """Click something that POSTs to `url_part`; on a non-OK answer, warm up and click again."""
        status = None
        for attempt in range(attempts):
            with self.page.expect_response(lambda x: url_part in x.url and x.request.method != "GET",
                                           timeout=30000) as resp:
                click()
            status = resp.value.status
            if status in ok:
                return status
            print(f"  ! {url_part} answered {status}; retrying ({attempt + 1}/{attempts})", flush=True)
            self.browse()
            self.page.wait_for_timeout(pause_ms)
        raise RuntimeError(f"{url_part} kept answering {status}")

    # --- payment fields -----------------------------------------------------------------------------------------
    def card_standins(self, label=None):
        c = self.session.card(label)
        return c["number"]["value"], (c.get("cvc") or {}).get("value")

    def frames(self, host_part):
        return [f for f in self.page.frames if host_part in f.url]

    def wait_frames(self, host_part, selector, count=1, timeout_ms=60000, retry=None):
        end = time.time() + timeout_ms / 1000
        while time.time() < end:
            ready = [f for f in self.frames(host_part) if f.locator(selector).count()]
            if len(ready) >= count:
                return ready
            if retry and time.time() > end - timeout_ms / 1000 * 0.6:
                retry()
                retry = None
            self.page.wait_for_timeout(1500)
        raise RuntimeError(f"{count} frame(s) of {host_part} with {selector} did not load")

    def type_in_frame(self, host_part, selector, value, delay=90):
        for f in self.frames(host_part):
            i = f.locator(selector)
            if i.count():
                i.first.focus()
                i.first.press_sequentially(value, delay=delay)
                i.first.blur()
                return
        raise RuntimeError(f"no {selector} in a {host_part} frame")

    def fill_adyen_card(self, expiry_mmyy, label=None):
        """Type the session's stand-ins into Adyen Secured Fields (number, expiry, CVC)."""
        num, cvc = self.card_standins(label)
        host = "securedfields"
        self.type_in_frame(host, "input[data-fieldtype=encryptedCardNumber]", num)
        self.type_in_frame(host, "input[data-fieldtype=encryptedExpiryDate]", expiry_mmyy)
        if cvc:
            self.type_in_frame(host, "input[data-fieldtype=encryptedSecurityCode]", cvc)

    def wait_session_value(self, adapter, key, timeout_ms=30000):
        end = time.time() + timeout_ms / 1000
        while time.time() < end:
            v = self.session.values(adapter).get(key)
            if v:
                return v
            self.page.wait_for_timeout(2000)
        return None


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def egress_relay(egress, sticky_id=None):
    """A local unauthenticated CONNECT proxy chained to the egress proxy (Chromium cannot authenticate to HTTPS
    proxies). Used only for `--direct` comparisons that bypass the gateway. Listens on 127.0.0.1 only."""
    import asyncio
    import ssl
    import threading

    s = egress.settings(sticky_id)
    auth = base64.b64encode(f"{s['username']}:{s['password']}".encode()).decode()
    tls = ssl.create_default_context() if s["scheme"] == "https" else None
    port = _free_port()
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    async def pipe(r, w):
        try:
            while data := await r.read(65536):
                w.write(data)
                await w.drain()
        except Exception:
            pass
        finally:
            try:
                w.close()
            except Exception:
                pass

    async def handle(cr, cw):
        try:
            head = await cr.readuntil(b"\r\n\r\n")
            line = head.split(b"\r\n", 1)[0].decode()
            method, target = line.split(" ")[:2]
            if method != "CONNECT":
                cw.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
                await cw.drain()
                cw.close()
                return
            ur, uw = await asyncio.open_connection(s["hostname"], s["port"], ssl=tls,
                                                   server_hostname=s["hostname"] if tls else None)
            uw.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\nProxy-Authorization: Basic {auth}\r\n\r\n".encode())
            await uw.drain()
            resp = await ur.readuntil(b"\r\n\r\n")
            cw.write(resp)
            await cw.drain()
            if b" 200" not in resp.split(b"\r\n", 1)[0]:
                cw.close()
                uw.close()
                return
            await asyncio.gather(pipe(cr, uw), pipe(ur, cw))
        except Exception:
            try:
                cw.close()
            except Exception:
                pass

    def serve():
        asyncio.set_event_loop(loop)
        server = loop.run_until_complete(asyncio.start_server(handle, "127.0.0.1", port))
        ready.set()
        loop.run_forever()
        server.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    ready.wait(5)
    async def shutdown():
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        loop.stop()

    try:
        yield {"server": f"http://127.0.0.1:{port}"}
    finally:
        asyncio.run_coroutine_threadsafe(shutdown(), loop)
        t.join(5)


@contextmanager
def launch(p, proxy, ca_pem=None, record_dir=None, headless=False, locale="en-US", timezone="America/Los_Angeles"):
    args = ["--disable-blink-features=AutomationControlled"]
    ignore = os.environ.get("AWG_IGNORE_HTTPS_ERRORS") == "1"
    if ca_pem and not ignore:
        args.append("--ignore-certificate-errors-spki-list=" + ",".join(spki_pins(ca_pem)))
    browser = p.chromium.launch(headless=headless, proxy=proxy, args=args)
    opts = dict(viewport={"width": 1280, "height": 800}, locale=locale, timezone_id=timezone,
                ignore_https_errors=ignore)
    if record_dir:
        opts.update(record_video_dir=record_dir, record_video_size={"width": 1280, "height": 800})
    ctx = browser.new_context(**opts)
    try:
        yield browser, ctx
    finally:
        try:
            ctx.close()
        finally:
            browser.close()


def reject_cookies_handler(page, selectors):
    for sel in selectors or DEFAULT_COOKIE_REJECT:
        try:
            page.add_locator_handler(page.locator(sel).first, lambda loc: loc.click(), no_wait_after=True)
        except Exception:
            pass
