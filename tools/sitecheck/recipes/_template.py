"""<Site name> (<checkout host>): <one line: the path from product page to card form>.

Copy this file to recipes/<site_id>.py, point the site's `recipe:` at it, and fill in to_payment(). Develop it with
`awg-sitecheck probe <site_id> --deep` (no card typed, nothing bought) until the verdict says payment-form-ok.

Rules:
  * Use run.goto(url), run.caption(text), run.browse() (bot-sensor warm-up), run.retry_post(url_part, click).
  * Prefer roles and labels (page.get_by_role / get_by_label) over CSS classes; sites rebuild class names.
  * Read the shopper's details from run.site.contact (sites.yaml), never hard-code PII here.
  * Never type real card data. fill_card() types the session's stand-ins (run.card_standins()).
  * Do not click the place-order button here: return it from place_order(); the runner decides.
"""
import re
from decimal import Decimal

# Substring of the request that carries the encrypted card (the encrypt binding's `when.path`), e.g. "/checkout/pay".
CHECKOUT_POST = None
# Session values the capture function must store before the card is typed (empty if the PSP needs no capture).
CAPTURE_KEYS = []


def to_payment(run):
    page, c = run.page, run.site.contact
    run.goto(run.site.urls[0])
    run.browse()
    # 1. choose options and add to cart
    # run.retry_post("/cart", lambda: page.get_by_role("button", name="Add to cart").click())
    # 2. go to checkout, guest checkout, contact, addresses, delivery
    # 3. choose card payment and wait for the card fields, e.g. for Adyen:
    # run.wait_frames("securedfields", "input[data-fieldtype]", count=3)
    raise NotImplementedError("write the steps for this site")


def fill_card(run):
    # Adyen Secured Fields:
    run.fill_adyen_card(expiry_mmyy="1030")
    # Stripe Elements (one iframe per field or a single card element):
    # num, cvc = run.card_standins()
    # run.type_in_frame("js.stripe.com", "input[name=cardnumber]", num)
    # run.type_in_frame("js.stripe.com", "input[name=exp-date]", "1030")
    # run.type_in_frame("js.stripe.com", "input[name=cvc]", cvc)


def order_total(run):
    text = run.page.get_by_text(re.compile(r"^\s*total", re.I)).last.locator("xpath=..").inner_text(timeout=5000)
    amounts = re.findall(r"([0-9][0-9,]*\.[0-9]{2})", text)
    return Decimal(amounts[-1].replace(",", "")) if amounts else None


def place_order(run):
    return run.page.get_by_role("button", name=re.compile("place order|complete purchase|pay now", re.I))


def confirmed(run):
    return "confirm" in run.page.url.lower() or run.page.get_by_text(re.compile("thank you", re.I)).count() > 0
