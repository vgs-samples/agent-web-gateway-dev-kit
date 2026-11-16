"""Recognise bot walls and payment providers from what the browser saw.

Extend the tables when a site shows something new; keep each signature specific enough not to fire on unrelated pages.
"""
import re

# name -> (response header predicates, cookie name prefixes, host substrings)
BOT_WALLS = {
    "akamai": ({"server": r"akamaighost", "akamai-grn": r".", "x-reference-error": r"."},
               ["_abck", "bm_sz", "ak_bmsc"], ["akamaihd.net", "akstat.io"]),
    "cloudflare": ({"cf-ray": r".", "server": r"^cloudflare$", "cf-mitigated": r"."}, ["__cf_bm", "cf_clearance"],
                   ["challenges.cloudflare.com"]),
    "datadome": ({"x-datadome": r".", "x-dd-b": r"."}, ["datadome"], ["captcha-delivery.com", "datadome.co"]),
    "perimeterx": ({"x-px": r"."}, ["_px", "_pxhd", "_pxvid"], ["perimeterx.net", "px-cdn.net", "px-cloud.net"]),
    "imperva": ({"x-iinfo": r".", "x-cdn": r"incapsula"}, ["visid_incap", "incap_ses", "reese84"], ["incapsula"]),
    "kasada": ({"x-kpsdk-ct": r"."}, ["x-kpsdk"], ["kasada", "/149e9513-01fa-4fb0-aad4-566afd725d1b/"]),
    "queue-it": ({}, ["QueueITAccepted"], ["queue-it.net"]),
}

# name -> (host substrings, client-side encryption?, notes for adapter authors)
PSPS = {
    "adyen": (["checkoutshopper-live.adyen.com", "checkoutshopper-test.adyen.com", "checkoutshopper-live-us.adyen.com",
               "checkoutshopper-live-au.adyen.com", "checkoutshopper-live-apse.adyen.com"],
              True, "Secured Fields encrypt in an iframe (JWE RSA-OAEP-256/A256GCM). Use adapters/adyen-cse."),
    "stripe": (["js.stripe.com", "api.stripe.com", "m.stripe.network"],
               False, "Elements posts the card to api.stripe.com (tokenize): put api.stripe.com in allowed_hosts; the "
                      "default stand-in swap reveals it. No function needed unless the merchant posts the card elsewhere."),
    "braintree": (["braintreegateway.com", "braintree-api.com", "assets.braintreegateway.com"],
                  False, "Hosted Fields tokenize via payments.braintree-api.com (GraphQL): allowed host + default swap. "
                         "Legacy braintree.js CSE needs a capture/encrypt pair."),
    "checkout.com": (["frames.checkout.com", "api.checkout.com", "checkout-web-components.checkout.com"],
                     False, "Frames tokenize via api.checkout.com/tokens: allowed host + default swap."),
    "cybersource": (["flex.cybersource.com", "testflex.cybersource.com", "secureacceptance.cybersource.com"],
                    True, "Flex Microform sends the PAN to flex.cybersource.com encrypted with a JWK from the capture "
                          "context (JWE RSA-OAEP-256). Capture the JWK from the capture-context JWT; re-encrypt."),
    "worldpay": (["secure.worldpay.com", "payments.worldpay.com", "access.worldpay.com"],
                 True, "Worldpay CSE encrypts in the browser with the merchant's public key: capture/encrypt pair."),
    "paypal": (["paypal.com/sdk", "www.paypal.com", "paypalobjects.com"], False, "PayPal wallet: no card fields."),
    "klarna": (["klarna.com", "klarnacdn.net", "klarnaservices.com"], False, "Klarna: no card fields."),
    "shopify": (["checkout.shopify.com", "deposit.shopifycs.com", "checkout.pci.shopifyinc.com"],
                False, "Shopify card fields post to deposit.shopifycs.com/sessions: allowed host + default swap."),
    "spreedly": (["core.spreedly.com"], False, "iFrame tokenizes via core.spreedly.com: allowed host + default swap."),
    "recurly": (["api.recurly.com", "js.recurly.com"], False, "recurly.js tokenizes via api.recurly.com/js/v1/token."),
    "authorize.net": (["js.authorize.net", "api2.authorize.net", "jstest.authorize.net"],
                      False, "Accept.js tokenizes via api2.authorize.net: allowed host + default swap."),
}


def bot_walls(headers: dict, cookies: list, hosts: list):
    """Vendors seen, each as "<vendor>:bot" (its bot-management cookies or sensor hosts are present: expect a
    challenge) or "<vendor>:edge" (only its CDN headers: the site is served through it, no bot manager seen)."""
    found = {}
    lower = {k.lower(): str(v) for k, v in (headers or {}).items()}
    for name, (hpreds, cprefixes, hostbits) in BOT_WALLS.items():
        if any(c.startswith(p) for c in cookies for p in cprefixes) or any(b in h for h in hosts for b in hostbits):
            found[name] = "bot"
        elif any(h in lower and re.search(pat, lower[h], re.I) for h, pat in hpreds.items()):
            found.setdefault(name, "edge")
    return sorted(f"{k}:{v}" for k, v in found.items())


def blocked(status, headers, body_head=""):
    """A response a bot wall produced instead of the page."""
    lower = {k.lower(): str(v) for k, v in (headers or {}).items()}
    if status in (403, 429) and ("akamaighost" in lower.get("server", "").lower() or "access denied" in body_head.lower()):
        return "akamai-403"
    if status in (403, 503) and ("cf-mitigated" in lower or "just a moment" in body_head.lower()):
        return "cloudflare-challenge"
    if "x-datadome" in lower and status in (403, 405):
        return "datadome-block"
    if status in (403, 429):
        return f"http-{status}"
    return None


def psps(urls: list):
    found = []
    for name, (bits, cse, _) in PSPS.items():
        if any(b in u for u in urls for b in bits):
            found.append({"psp": name, "client_side_encryption": cse})
    return found


def psp_notes(name):
    return PSPS.get(name, (None, None, ""))[2]
