#!/usr/bin/env python3
"""A vendor payment in a Browserbase browser, paid with a reveal session's stand-ins.

Create a session for the vendor's host and, if the payment form posts elsewhere, its payment provider's host:

    ./awg session <the vendor's host>[,<payment provider host>]

Then run the flow. It fills the payment form and stops; add --submit to also submit the payment:

    BROWSERBASE_API_KEY=… uv run --with playwright==1.49.0 examples/browserbase/payment_flow.py \\
        https://<the vendor's payment page>/ [--submit]

The script starts a Browserbase browser with the session as its external proxy, opens the page, and types
the session's stand-ins into the card fields. It never holds a card number: VGS replaces the stand-ins with
the card on the way to an approved destination, so neither this script nor Browserbase sees it.

The fields are found by their autocomplete attributes and common names, in the page and its frames. Name
them yourself with --number-field, --cvc-field, --expiry-field and --submit-button (CSS selectors) when the
page differs. A person completes any 3-D Secure challenge or CAPTCHA in the live view.

The session's proxy address, proxy password, certificate authority and stand-ins go to Browserbase.
Sandbox and the public test card only. BROWSERBASE_PROJECT_ID is optional.
"""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen
import uuid

STATE = Path(os.environ.get("AWG_HOME", Path.home() / ".vgs" / "awg")).expanduser() / os.environ.get("AWG_ENVIRONMENT", "sandbox")
API = os.environ.get("BROWSERBASE_API_URL", "https://api.browserbase.com/v1")

NUMBER = ('input[autocomplete="cc-number"], input[name*="cardnumber" i], input[name*="card-number" i], '
          'input[name*="card_number" i], input[id*="cardnumber" i], input[id*="card-number" i]')
CVC = ('input[autocomplete="cc-csc"], input[name*="cvc" i], input[name*="cvv" i], input[name*="securitycode" i], '
       'input[id*="cvc" i], input[id*="cvv" i]')
EXPIRY = 'input[autocomplete="cc-exp"], input[name*="expir" i], input[name*="exp-date" i], input[id*="expir" i]'
SUBMIT = 'button[type="submit"], input[type="submit"]'


def stand_ins(attributes):
    """The card number and security code stand-ins of a reveal session. Never the card, never the vault aliases."""
    card = attributes["cards"][0]
    values = {"number": card["number"]["value"]}
    if card.get("cvc"):
        values["cvc"] = card["cvc"]["value"]
    return values


def browser_request(attributes, certificate_id, project_id=None):
    """The Browserbase session to create: the reveal session as its external proxy, trusting the session's certificate authority."""
    url = urlsplit(attributes["proxy"]["url"])
    body = {
        "timeout": 900,
        "proxies": [{"type": "external", "server": f"{url.scheme}://{url.hostname}:{url.port}",
                     "username": unquote(url.username), "password": unquote(url.password)}],
        # Trust the session's certificate authority rather than ignoring certificate errors.
        "proxySettings": {"caCertificates": [certificate_id]},
    }
    if project_id:
        body["projectId"] = project_id
    return body


def browserbase(method, path, body=None, content_type="application/json"):
    request = Request(API + path, data=body, method=method, headers={
        "X-BB-API-Key": os.environ["BROWSERBASE_API_KEY"], "Content-Type": content_type, "User-Agent": "awg-dev-kit"})
    try:
        with urlopen(request, timeout=60) as response:
            text = response.read()
            return json.loads(text) if text else {}
    except HTTPError as error:
        # Only Browserbase's message: the request holds the session's proxy password.
        try:
            reason = str(json.loads(error.read()).get("message", ""))[:300]
        except (ValueError, AttributeError):
            reason = ""
        sys.exit(f"Browserbase answered HTTP {error.code} to {method} {path}: {reason}")
    except URLError:
        sys.exit("Could not reach Browserbase.")


def upload_certificate(pem):
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="session-ca.pem"\r\n'
            "Content-Type: application/x-pem-file\r\n\r\n").encode() + pem.encode() + f"\r\n--{boundary}--\r\n".encode()
    return browserbase("POST", "/certificates", body, f"multipart/form-data; boundary={boundary}")["id"]


def type_into(page, selector, value, wait_ms=30000):
    """Type into the first visible match in the page or any of its frames. Payment fields often sit in the provider's frame."""
    waited = 0
    while waited <= wait_ms:
        for frame in page.frames:
            try:
                field = frame.locator(selector).first
                if field.count() and field.is_visible():
                    field.click()
                    field.press_sequentially(value, delay=40)
                    return True
            except Exception:  # noqa: BLE001 - a frame can navigate away while it is being searched
                continue
        page.wait_for_timeout(500)
        waited += 500
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="The vendor's payment page")
    parser.add_argument("--submit", action="store_true", help="Submit the payment after filling the form")
    parser.add_argument("--number-field", default=NUMBER)
    parser.add_argument("--cvc-field", default=CVC)
    parser.add_argument("--expiry-field", default=EXPIRY)
    parser.add_argument("--submit-button", default=SUBMIT)
    args = parser.parse_args()
    if not os.environ.get("BROWSERBASE_API_KEY"):
        sys.exit("BROWSERBASE_API_KEY is not set. Copy the API key from your Browserbase project settings.")
    host = urlsplit(args.url).hostname
    if not host:
        sys.exit("Give the payment page as a full URL, for example https://vendor.example/pay")
    try:
        attributes = json.loads(Path((STATE / "latest-session").read_text().strip()).read_text())["data"]["attributes"]
        values = stand_ins(attributes)
        pem = attributes["proxy"]["ca_bundle"]
        browser_request(attributes, "")
    except (OSError, KeyError, IndexError, TypeError, ValueError):
        sys.exit("No usable session found. Create one with ./awg session <the vendor's host> first.")
    if host not in (attributes.get("allowed_hosts") or []):
        print(f"Note: {host} is not among the session's allowed hosts. VGS reveals the card only at an allowed host "
              "or one of your trusted destinations.")

    from playwright.sync_api import sync_playwright

    certificate = upload_certificate(pem)
    created = None
    try:
        created = browserbase("POST", "/sessions", json.dumps(
            browser_request(attributes, certificate, os.environ.get("BROWSERBASE_PROJECT_ID"))).encode())
        # Browserbase's own identifier, for its dashboard, session replay and support.
        print("Browserbase browser session:", created["id"])
        live = browserbase("GET", f"/sessions/{created['id']}/debug").get("debuggerFullscreenUrl")
        if live:
            print("Watch it here (keep this link private; it controls the browser):\n ", live)
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(created["connectUrl"])
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
            if not type_into(page, args.number_field, values["number"]):
                sys.exit("Found no card number field. Name it with --number-field.")
            print("Typed the card number stand-in.")
            expiry = f"12/{(date.today().year + 3) % 100:02d}"
            if type_into(page, args.expiry_field, expiry, wait_ms=3000):
                print("Typed the expiry date", expiry)
            if "cvc" in values and type_into(page, args.cvc_field, values["cvc"], wait_ms=3000):
                print("Typed the security code stand-in.")
            if not args.submit:
                print("Stopped before submitting. Run again with --submit to submit the payment.")
                return
            button = next((frame.locator(args.submit_button).first for frame in page.frames
                           if frame.locator(args.submit_button).count()), None)
            if button is None:
                sys.exit("Found no submit button. Name it with --submit-button.")
            button.click()
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:  # noqa: BLE001 - a page that keeps polling never goes idle
                pass
            print("Submitted. The page is now:", page.url)
            print("Check the session's reveal count in the Control Panel, or with GET /reveal-sessions/{id}.")
    finally:
        if created:
            browserbase("POST", f"/sessions/{created['id']}", json.dumps({"status": "REQUEST_RELEASE"}).encode())
        browserbase("DELETE", f"/certificates/{certificate}")


if __name__ == "__main__":
    main()
