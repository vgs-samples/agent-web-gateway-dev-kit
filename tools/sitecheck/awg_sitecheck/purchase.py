"""Level 3: a recorded checkout through the gateway with the session's card, stopping before the order unless asked.

Safety rails (do not remove):
  * Without --purchase the run stops at the place-order button.
  * With --purchase, --max-total is required and the order is placed only if the shown total is not above it.
  * Nothing is retried once the order request has been sent.
  * The card form only ever receives the session's stand-ins; the real card is revealed inside the gateway.
"""
import json
import time
import traceback
from decimal import Decimal
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import recipes
from .browser import NetLog, PageAccessError, Run, launch, reject_cookies_handler
from .session import create


def run_purchase(api, cfg, site, run_dir, purchase=False, max_total=None, headless=False):
    if purchase and max_total is None:
        raise SystemExit("--purchase needs --max-total (the most you approve this order to cost)")
    if not site.recipe:
        raise SystemExit(f"site {site.id} has no recipe")
    recipe = recipes.load(cfg.path(site.recipe))
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    result = {"site": site.id, "purchase_requested": purchase, "max_total": str(max_total) if max_total else None,
              "submitted": False}
    session = None
    try:
        session = create(api, cfg, site, run_dir, with_card=True)
        result["session"] = session.summary()
        card = session.card()
        netlog = NetLog()
        with sync_playwright() as p:
            with launch(p, session.playwright_proxy(), session.ca_bundle(), record_dir=str(run_dir),
                        headless=headless) as (browser, ctx):
                netlog.attach(ctx)
                page = ctx.new_page()
                reject_cookies_handler(page, site.cookie_reject)
                run = Run(page, ctx, site, session, netlog, artifact_dir=run_dir)
                page.goto("about:blank")
                run.caption(f"VGS Agent Web Gateway: an AI agent checks out at {site.name} with a card it never sees.\n"
                            f"Reveal session {session.id}"
                            + (f", adapter {site.adapter}" if site.adapter else "")
                            + f". Allowed hosts: {', '.join(session.attrs.get('allowed_hosts') or [])}.", 4500)
                run.caption(f"The agent holds stand-ins only (card •••• {card['number']['value'][-4:]} stand-in). "
                            "The real card stays in the VGS vault.", 3500)
                ip = run.exit_ip()
                result["exit_ip"] = ip
                if "error" not in ip:
                    run.caption(f"Exit IP through the gateway: {ip.get('city')}, {ip.get('region')} "
                                f"({(ip.get('org') or '')[:40]})", 2500)

                try:
                    recipe.to_payment(run)
                except Exception:
                    result["failed_step"] = _failed_step(page, netlog, run_dir)
                    raise

                keys =getattr(recipe, "CAPTURE_KEYS", [])
                if site.adapter and keys:
                    missing = [k for k in keys if not run.wait_session_value(site.adapter, k)]
                    if missing:
                        raise RuntimeError(f"capture function did not store {missing}; not continuing")
                    run.caption("A VGS function captured the payment provider's key into the session.", 3000)

                run.caption("The agent types its STAND-IN card values; the browser encrypts them, and that "
                            "ciphertext never reaches the payment provider.", 2500)
                (getattr(recipe, "fill_card", None) or (lambda r: r.fill_adyen_card(_expiry(site))))(run)
                page.wait_for_timeout(1000)

                total = recipe.order_total(run) if hasattr(recipe, "order_total") else None
                result["total"] = str(total) if total is not None else None
                button = recipe.place_order(run) if hasattr(recipe, "place_order") else None
                run.caption(f"Order ready{': total ' + str(total) if total is not None else ''}.\n"
                            "On 'place order', a VGS function rebuilds the card fields from the REAL card "
                            "inside the gateway.", 5000)
                if button is not None:
                    button.scroll_into_view_if_needed()
                    button.hover()
                if purchase:
                    if button is None:
                        raise RuntimeError("recipe has no place_order(run)")
                    if total is None or Decimal(total) > Decimal(str(max_total)):
                        raise RuntimeError(f"total {total} is not within the approved {max_total}; not purchasing")
                    run.caption("A human approved this order. The agent places it.", 2500)
                    post = getattr(recipe, "CHECKOUT_POST", None)
                    if post:
                        with page.expect_response(lambda x: post in x.url and x.request.method == "POST",
                                                  timeout=90000) as resp:
                            result["submitted"] = True
                            button.click()
                        result["checkout_status"] = resp.value.status
                    else:
                        result["submitted"] = True
                        button.click()
                    done = getattr(recipe, "confirmed", None) or (lambda r: "confirm" in r.page.url.lower())
                    end = time.time() + 300
                    while time.time() < end and not done(run):
                        page.wait_for_timeout(2000)
                    page.wait_for_timeout(3000)
                    result["final_url"] = page.url
                    result["confirmed"] = bool(done(run))
                    result["session_counters"] = session.counters()
                    run.caption(f"Result: {'order placed' if result['confirmed'] else 'not confirmed'}  {page.url}\n"
                                f"Session {session.id}: {result['session_counters']}", 7000)
                else:
                    run.caption("Stopped before placing the order (human confirmation step).", 4000)
                page.screenshot(path=str(run_dir / "final.png"))
                result["video"] = page.video.path() if page.video else None
    except Exception as e:
        if isinstance(e, PageAccessError):
            result["failure"] = dict(e.details,
                                     browser_mode="headless" if headless else "headed",
                                     egress_profile=site.egress or cfg.defaults.get("egress"))
        result["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:400]}"
        result["trace"] = traceback.format_exc()[-1500:]
    finally:
        if session:
            result.setdefault("session_counters", session.counters())
            result["session_deleted"] = session.delete()
    (run_dir / "result.json").write_text(json.dumps(result, indent=1, default=str))
    return result


def _failed_step(page, netlog, run_dir):
    """Where a recipe step failed, captured while the browser is still open: URL, title, screenshot, failed requests."""
    out = {}
    try:
        out["url"] = page.url.split("?", 1)[0]
        out["title"] = page.title()[:200]
        shot = run_dir / "failed-step.png"
        page.screenshot(path=str(shot))
        out["screenshot"] = str(shot)
    except Exception as e:
        out["capture_error"] = type(e).__name__
    out["failed_requests"] = [{"status": e["status"], "method": e["method"], "type": e["type"],
                               "url": e["url"].split("?", 1)[0][:200],
                               # who answered: the site, the gateway or the egress proxy
                               "from": {k: v[:120] for k, v in (e.get("headers") or {}).items()
                                        if k.lower() in ("server", "via", "retry-after", "x-cache", "content-type")
                                        or "vgs" in k.lower() or "akamai" in k.lower()}}
                              for e in netlog.entries if e["status"] >= 400 or e["status"] == 0][-15:]
    return out


def _expiry(site):
    c = site.context or {}
    m, y = c.get("adyen_expiry_month") or c.get("expiry_month"), c.get("adyen_expiry_year") or c.get("expiry_year")
    if not (m and y):
        raise SystemExit(f"site {site.id}: set context.expiry_month/expiry_year (or adyen_*) for the card form")
    return f"{int(m):02d}{str(y)[-2:]}"
