"""Level 1: can an agent reach this site through the gateway, what walls it, and which payment provider does it use.

No card is typed and nothing is bought. Per site: a reveal session, a recorded browser through the gateway, each URL
loaded (with the bot-sensor warm-up), optionally the site's recipe up to the card form (`--deep`), optionally the same
URLs straight through the egress proxy (`--direct`) to tell gateway problems from site/IP problems.
"""
import json
import time
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import detect, recipes
from .browser import NetLog, Run, egress_relay, launch, reject_cookies_handler
from .session import create


def _visit(run, url):
    try:
        r = run.goto(url)
        status = r.status if r else 0
        headers = r.headers if r else {}
        body_head = ""
        try:
            body_head = run.page.inner_text("body", timeout=3000)[:400]
        except Exception:
            pass
        title = ""
        try:
            title = run.page.title()[:120]
        except Exception:
            pass
        run.browse(max_ms=15000)
        return {"url": url, "status": status, "title": title, "blocked": detect.blocked(status, headers, body_head),
                "server": headers.get("server"), "request_id": headers.get("vgs-request-id")}
    except Exception as e:
        return {"url": url, "status": 0, "error": str(e).splitlines()[0][:300]}


def _cookies(ctx):
    try:
        return [c["name"] for c in ctx.cookies()]
    except Exception:
        return []


def probe_site(api, cfg, site, run_dir, deep=False, direct=False, headless=False):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    result = {"site": site.id, "name": site.name, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "pages": [],
              "direct_pages": [], "deep": None}
    session = None
    try:
        has_card = bool(site.card or cfg.defaults.get("card"))
        session = create(api, cfg, site, run_dir, with_card=has_card)
        result["session"] = session.summary()
        netlog = NetLog()
        with sync_playwright() as p:
            with launch(p, session.playwright_proxy(), session.ca_bundle(), record_dir=str(run_dir),
                        headless=headless) as (browser, ctx):
                netlog.attach(ctx)
                page = ctx.new_page()
                reject_cookies_handler(page, site.cookie_reject)
                run = Run(page, ctx, site, session, netlog, captions=not headless, step_pause_ms=800)
                result["exit_ip"] = run.exit_ip()
                for url in site.urls:
                    result["pages"].append(_visit(run, url))
                if deep and site.recipe:
                    result["deep"] = _deep(run, cfg, site, session)
                result["cookies"] = _cookies(ctx)
                page.screenshot(path=str(run_dir / "final.png"))
                video = page.video.path() if page.video else None
        result["video"] = video
        result["hosts"] = netlog.hosts()
        all_urls = [e["url"] for e in netlog.entries]
        doc_headers = {}
        for e in netlog.entries:
            if e.get("type") == "document" and e.get("headers"):
                doc_headers.update(e["headers"])
        result["bot_walls"] = detect.bot_walls(doc_headers, result.get("cookies", []), list(result["hosts"]))
        result["psps"] = detect.psps(all_urls)
        if direct:
            result["direct_pages"] = _direct(cfg, site, headless)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:400]}"
        result["trace"] = traceback.format_exc()[-1500:]
    finally:
        if session:
            result["session_counters"] = session.counters()
            result["session_deleted"] = session.delete()
    result["verdict"] = verdict(result)
    (run_dir / "result.json").write_text(json.dumps(result, indent=1, default=str))
    return result


def _deep(run, cfg, site, session):
    out = {"reached_payment": False}
    try:
        recipe = recipes.load(cfg.path(site.recipe))
        recipe.to_payment(run)
        out["reached_payment"] = True
        out["payment_frames"] = sorted({f.url.split("?")[0][:120] for f in run.page.frames if f.url.startswith("http")
                                        and f != run.page.main_frame})
        keys = getattr(recipe, "CAPTURE_KEYS", [])
        if site.adapter and keys:
            vals = {}
            end = time.time() + 30
            while time.time() < end and not all(k in vals for k in keys):
                vals = session.values(site.adapter)
                time.sleep(2)
            out["captured"] = {k: bool(vals.get(k)) for k in keys}
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:300]}"
    return out


def _direct(cfg, site, headless):
    eg = cfg.egress_for(site)
    if not eg:
        return [{"error": "no egress profile: --direct compares against the egress proxy without the gateway"}]
    pages = []
    with egress_relay(eg, sticky_id=f"direct{int(time.time())}") as proxy:
        with sync_playwright() as p:
            with launch(p, proxy, headless=headless) as (browser, ctx):
                page = ctx.new_page()
                reject_cookies_handler(page, site.cookie_reject)
                run = Run(page, ctx, site, captions=False, step_pause_ms=500)
                for url in site.urls:
                    pages.append(_visit(run, url))
    return pages


def verdict(r):
    if r.get("error") and not r.get("pages"):
        return "error"
    pages = r.get("pages", [])
    if pages and all(p.get("status", 0) and 200 <= p["status"] < 400 and not p.get("blocked") for p in pages):
        base = "reachable"
    elif any(p.get("blocked") for p in pages):
        direct = r.get("direct_pages") or []
        if direct and any(d.get("blocked") or not (200 <= d.get("status", 0) < 400) for d in direct):
            base = "blocked-even-direct"
        elif direct:
            base = "blocked-by-gateway-path"
        else:
            base = "blocked"
    else:
        base = "errors"
    deep = r.get("deep")
    if deep:
        if not deep.get("reached_payment"):
            base += "; recipe-failed"
        elif deep.get("captured") and not all(deep["captured"].values()):
            base += "; capture-missing"
        else:
            base += "; payment-form-ok"
    return base
