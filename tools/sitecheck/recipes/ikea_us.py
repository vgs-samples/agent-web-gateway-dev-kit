"""IKEA US (www.ikea.com/us/en): product page -> bag -> guest checkout -> ZIP and delivery -> details -> ACI card form.

Written 2026-11-16 from a walk through the checkout without the gateway (no card typed). What IKEA needs:
  * Delivery is offered only for $35 or more of products; below that the only option is store pick-up. Set
    contact.quantity so the bag reaches $35 (5 ADILS legs = $37.50). The delivery option is "Small Order Shipping".
  * Guest checkout needs no account. The details form validates the address and may ask to confirm it.
  * The card form is ACI Worldwide COPYandPAY: card number and security code are iframes of eu-prod.oppwa.com
    (pciIframe.html); expiry and card holder are inputs on the IKEA page. Not yet run through the gateway.
  * One product page makes ~350 requests; the gateway's rate limit (429, no upstream status) can refuse some.
"""
import re
from decimal import Decimal

CHECKOUT_POST = "/v1/checkouts/"      # the card form posts to eu-prod.oppwa.com/v1/checkouts/<id>/payment
CAPTURE_KEYS = []
FRAMES = "oppwa.com/v1/pciIframe"


def _banner(page):
    """IKEA's cookie banner has no reject button and covers the page bottom: take it out of the way, accept nothing."""
    try:
        page.evaluate("document.querySelector('#onetrust-consent-sdk')?.remove()")
    except Exception:
        pass


def to_payment(run):
    site, page, c = run.site, run.page, run.site.contact
    a = c["shipping"]
    qty = int(c.get("quantity", 1))
    # 2026-11-16: one product page made 739 requests through the gateway, 89 answered 429 (gateway rate limit), and
    # the availability check never finished, so "Add to bag" never appeared. Pictures, video and fonts are most of
    # those requests and the checkout does not need them: don't request them.
    page.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image", "media", "font")
               else route.continue_())
    r = run.goto(site.urls[0])
    run.require_success(r, stage="product_page", url=site.urls[0])
    run.caption(f"Product page loaded through the gateway (HTTP {r.status if r else '?'}). Pictures are skipped "
                "to stay under the gateway's rate limit.")
    run.browse(max_ms=8000)
    _banner(page)
    add = page.locator("main").get_by_role("button", name="Add to bag").first
    for attempt in range(3):
        try:
            add.wait_for(timeout=45000)
            break
        except Exception:
            if attempt == 2:
                raise
            run.caption("Availability check did not finish (requests refused). Waiting, then reloading.")
            page.wait_for_timeout(75000)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            _banner(page)
    for _ in range(qty - 1):
        page.get_by_role("button", name="Increase quantity").first.click()
        page.wait_for_timeout(500)
    run.caption(f"Agent sets quantity {qty} and adds to bag.")
    status = run.retry_post("/api/v1/us/items", lambda: add.click())
    run.caption(f"Added to bag (HTTP {status}).", 2000)

    run.goto("https://www.ikea.com/us/en/shoppingcart/")
    _banner(page)
    page.locator("main").get_by_role("button", name="Continue to checkout").first.wait_for(timeout=60000)
    # Same reason as H&M (2026-11-15): let the gateway's request rate settle before the checkout app loads.
    run.caption("Pausing a minute so the checkout page's requests are not rate-limited.")
    page.wait_for_timeout(60000)
    run.caption("Shopping bag: continue to checkout as a guest.")
    page.locator("main").get_by_role("button", name="Continue to checkout").first.click()
    page.get_by_role("button", name="Continue as guest").click(timeout=30000)

    page.locator("#zipInInput").wait_for(timeout=60000)
    _banner(page)
    page.locator("#zipInInput").fill(a["postal_code"])
    page.get_by_role("button", name="Show delivery options").click()
    ship = page.get_by_role("button", name=re.compile(r"Small Order Shipping|Parcel|Delivery$", re.I)).first
    ship.wait_for(timeout=60000)
    ship.click()
    page.wait_for_timeout(5000)
    run.caption("Delivery: shipping to the office address.")
    page.get_by_role("button", name="Continue to details").click()

    f = "#REGULAR-shipping-"
    page.locator(f + "email").wait_for(timeout=60000)
    _banner(page)
    page.locator(f + "email").fill(c["email"])
    page.locator(f + "mobileNumber").fill(re.sub(r"\D", "", c["phone"])[-10:])
    page.locator(f + "firstName").fill(c["first_name"])
    page.locator(f + "lastName").fill(c["last_name"])
    page.locator("#shippingAddressAutocomplete").fill(a["line1"])
    page.keyboard.press("Escape")                       # close the address suggestions
    page.locator(f + "addressLine2").fill(a.get("line2", ""))
    page.locator(f + "zipCode").fill(a["postal_code"])
    page.locator(f + "city").fill(a["city"])
    page.locator(f + "stateCode").select_option(a["state"])
    run.caption("Contact and delivery address (billing is the same address).")
    page.get_by_role("button", name="Continue to payment").click()
    confirm = page.get_by_role("button", name="Confirm address")
    card = page.get_by_label("Credit or Debit card")
    confirm.or_(card).first.wait_for(timeout=60000)
    if confirm.count() and confirm.first.is_visible():
        confirm.first.click()
    card.wait_for(timeout=60000)
    _banner(page)
    if not card.is_checked():
        card.check()
    run.wait_frames(FRAMES, "input", count=2)
    run.caption("ACI's card form loaded through the gateway.", 1500)


def fill_card(run):
    page, c, ctx = run.page, run.site.contact, run.site.context or {}
    num, cvc = run.card_standins()
    run.type_in_frame(FRAMES, "input[name='card.number']", num)
    expiry = page.locator("input.wpwl-control-expiry")
    expiry.click()
    expiry.press_sequentially(f"{int(ctx['expiry_month']):02d}{str(ctx['expiry_year'])[-2:]}", delay=90)
    page.locator("input.wpwl-control-cardHolder").fill(f"{c['first_name']} {c['last_name']}")
    if cvc:
        run.type_in_frame(FRAMES, "input[name='card.cvv']", cvc)


def order_total(run):
    text = run.page.locator("main").inner_text(timeout=5000)
    m = re.search(r"Total \(Incl\. tax\)\s*\$([0-9,]+\.[0-9]{2})", text)
    return Decimal(m.group(1).replace(",", "")) if m else None


def place_order(run):
    return run.page.get_by_role("button", name=re.compile(r"^Pay \$[0-9]"))


def confirmed(run):
    return "confirmation" in run.page.url.lower()
