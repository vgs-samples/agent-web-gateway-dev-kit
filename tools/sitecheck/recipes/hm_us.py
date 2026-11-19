"""H&M US (www2.hm.com/en_us): product page -> bag -> guest checkout -> addresses -> delivery -> Adyen card form.

Reference recipe. It placed a real order through the gateway in Sandbox, and records what H&M needs:
  * The gateway must use browser emulation (tenant preference agentGatewayBrowserEmulation=true) and a sticky egress IP,
    or Akamai answers 403.
  * run.browse() before the cart POST and before the email step, so Akamai's sensor validates the session.
  * H&M blocks the email lookup (/v2/userExistence, 403) for an address used in many checkouts in a short time; use a
    fresh contact email per demo if that happens.
  * The first address form is the BILLING address; the shipping form after it is prefilled from billing.
"""
import re
from decimal import Decimal

CHECKOUT_POST = "/v2/checkout/proceed"
CAPTURE_KEYS = ["adyen_public_key", "adyen_generationtime"]


def to_payment(run):
    site, page, c = run.site, run.page, run.site.contact
    r = run.goto(site.urls[0])
    run.require_success(r, stage="product_page", url=site.urls[0])
    run.caption(f"Product page loaded through the gateway (HTTP {r.status if r else '?'}).")
    run.browse()
    page.get_by_label(f"Size {c.get('size', '6-8Y')}: Available. Select the size.").click(timeout=20000)
    run.caption(f"Agent selects size {c.get('size', '6-8Y')} and adds to bag.")
    status = run.retry_post("v1/carts/items", lambda: page.get_by_role("button", name="Add to bag").first.click())
    run.caption(f"Added to bag (HTTP {status}).", 2000)

    run.goto("https://www2.hm.com/en_us/cart")
    page.get_by_role("button", name="Continue to checkout").wait_for(timeout=60000)
    # 2026-11-15: the gateway answered 429 (no upstream status) when the checkout app's burst of script requests
    # followed the product and bag pages within the same minute. Let the request rate settle first.
    run.caption("Pausing a minute so the checkout page's requests are not rate-limited.")
    page.wait_for_timeout(60000)
    run.caption("Shopping bag: continue to checkout.")
    page.get_by_role("button", name="Continue to checkout").click()
    page.wait_for_timeout(4000)
    run.browse()
    email = page.locator("input[name=email], input[type=email], input#email").first
    for attempt in range(3):
        try:
            email.wait_for(timeout=30000)
            break
        except Exception:
            # 2026-11-15: the checkout app's script chunks answered 429 in a burst and the form never rendered.
            if attempt == 2:
                raise
            run.caption("Checkout form did not load (scripts refused). Waiting, then reloading.")
            page.wait_for_timeout(75000)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            run.browse()
    email.fill(c["email"])
    run.caption("Guest checkout: contact email.")
    run.retry_post("userExistence", lambda: page.get_by_role("button", name="Continue").click(), attempts=5,
                   pause_ms=15000)
    guest = page.get_by_role("button", name="Checkout as guest")
    guest.or_(page.locator("input[name=firstName]")).first.wait_for(timeout=60000)
    if guest.count():
        guest.click()
    page.locator("input[name=firstName]").wait_for(timeout=60000)

    page.locator("input[name=firstName]").fill(c["first_name"])
    page.locator("input[name=lastName]").fill(c["last_name"])
    run.caption("Name.")
    page.locator("#my-information-save-button").click()
    page.wait_for_timeout(5000)

    _address(page, c["billing"])
    run.caption("Billing address.")
    page.get_by_role("button", name="Save").click()
    page.wait_for_timeout(6000)

    _address(page, c["shipping"])
    run.caption("Shipping address.")
    page.locator("#address-form-submit-button").click()
    page.wait_for_timeout(6000)

    page.locator("input[name=cellPhone]").fill(re.sub(r"\D", "", c["phone"])[-10:])
    run.caption("Phone and standard delivery.")
    page.locator("#delivery-save-cta-button").click()
    page.wait_for_timeout(7000)

    page.get_by_text("CREDIT/DEBIT CARD").click()
    run.wait_frames("securedfields", "input[data-fieldtype]", count=3,
                    retry=lambda: page.get_by_text("CREDIT/DEBIT CARD").click())
    run.caption("Adyen's card form loaded through the gateway.", 1500)


def _address(page, a):
    page.locator("input[name=line1]").fill(a["line1"])
    page.locator("input[name=line2]").fill(a.get("line2", ""))
    page.locator("input[name=town]").fill(a["city"])
    page.locator("input[name=postalCode]").fill(a["postal_code"])
    page.locator("[name=province]").click()
    page.wait_for_timeout(400)
    try:
        page.get_by_role("option", name=a["state_name"]).click(timeout=3000)
    except Exception:
        pass


def order_total(run):
    text = run.page.get_by_text("TOTAL").locator("xpath=..").inner_text(timeout=5000)
    amounts = re.findall(r"\$([0-9,]+\.[0-9]{2})", text)
    return Decimal(amounts[-1].replace(",", "")) if amounts else None


def place_order(run):
    return run.page.get_by_role("button", name="Complete purchase")


def confirmed(run):
    return "orderconfirmation" in run.page.url.lower()
