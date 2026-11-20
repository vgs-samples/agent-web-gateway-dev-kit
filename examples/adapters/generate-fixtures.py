#!/usr/bin/env python3
"""Build public HAR teaching fixtures from constants, never from private captures."""
import base64
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
TIME = "2030-01-01T00:00:00Z"
KEY = "10001|" + "ab" * 256

def segment(value):
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")

CONTEXT = segment({"alg": "RS256", "typ": "JWT"}) + "." + segment({
    "flx": {"origin": "https://flex.cybersource.com", "path": "/flex/v2/tokens",
            "jwk": {"kty": "RSA", "e": "AQAB", "n": base64.urlsafe_b64encode(bytes.fromhex("ab" * 256)).decode().rstrip("="), "kid": "synthetic-key"}},
    "exp": 1893456000,
}) + ".synthetic"

ADYEN_SCRIPT = '''<script>
var exampleAlgorithm="RSA-OAEP-256";
var exampleEncrypt=function(){var args=arguments,
enc=args.length>2&&void 0!==args[2]?args[2]:"A256GCM",
alg=args.length>3&&void 0!==args[3]?args[3]:exampleAlgorithm;
return new Encrypt().setProtectedHeader({alg:alg,enc:enc,version:"1"});};
exampleEncrypt(payload,key);
</script>'''

# A tiny authored SDK double, not a copy of CyberSource's proprietary SDK.
SDK = 'function je(e,t){let r=arguments.length>2&&void 0!==arguments[2]?arguments[2]:0;return Promise.resolve("ORIGINAL_PROVIDER_PATH");}'

def entry(method, url, body="", mime="application/json", response="", response_mime="application/json", status=200):
    return {"startedDateTime": TIME, "time": 0,
            "request": {"method": method, "url": url, "httpVersion": "HTTP/1.1",
                        "cookies": [], "headers": [{"name": "Content-Type", "value": mime}], "queryString": [],
                        "headersSize": -1, "bodySize": len(body.encode()),
                        "postData": {"mimeType": mime, "text": body}},
            "response": {"status": status, "statusText": "Synthetic fixture", "httpVersion": "HTTP/1.1",
                         "cookies": [], "headers": [{"name": "Content-Type", "value": response_mime}],
                         "content": {"size": len(response.encode()), "mimeType": response_mime, "text": response},
                         "redirectURL": "", "headersSize": -1, "bodySize": len(response.encode())},
            "cache": {}, "timings": {"send": 0, "wait": 0, "receive": 0}}

def relay(value):
    data = json.dumps(value, separators=(",", ":")).encode()
    return "AWGCS1:" + "".join(chr(97 + (b >> 4)) + chr(97 + (b & 15)) for b in data)

def fixtures():
    page = "Object.defineProperty(window, 'adyen', { value: Object.freeze({key: '" + KEY + "'})});\n"
    page += "Object.defineProperty(window, 'genTime', { value: '" + TIME + "'});" + ADYEN_SCRIPT
    adyen_body = {"adyenData": {"encryptedAdyenForm": {
        "encryptedCardNumber": "synthetic-browser-number", "encryptedSecurityCode": "synthetic-browser-cvc",
        "encryptedExpiryMonth": "synthetic-browser-month", "encryptedExpiryYear": "synthetic-browser-year"}},
        "order": "synthetic-order"}
    flows = {
        "adyen": [entry("GET", "https://checkoutshopper-live.adyen.com/checkoutshopper/securedfields/SYNTHETIC/4.5.0/securedFields.html", response=page, response_mime="text/html"),
                  entry("POST", "https://www2.hm.com/en_us/v2/checkout/proceed", json.dumps(adyen_body), response='{"synthetic":true}')],
        "cybersource": [entry("GET", "https://www.alaskaair.com/book/checkout", response='<script>const context="' + CONTEXT + '";</script>', response_mime="text/html"),
                        entry("GET", "https://flex.cybersource.com/microform/bundle/v2.12.1/iframe.min.js", response=SDK, response_mime="application/javascript"),
                        entry("POST", "https://flex.cybersource.com/flex/v2/tokens", relay({"data": {"CARD": {"number": "4242424242424242", "securityCode": "999", "expirationMonth": "12", "expirationYear": "2030"}, "keep": "synthetic"}, "context": CONTEXT, "index": 2}), "application/jwt", '{"synthetic":true}', status=201)],
        "stripe": [entry("POST", "https://api.stripe.com/v1/payment_intents/pi_SYNTHETIC/confirm",
                         "payment_method_data%5Bcard%5D%5Bnumber%5D=4242+4242+4242+4242&payment_method_data%5Bcard%5D%5Bcvc%5D=999&payment_method_data%5Bcard%5D%5Bexp_month%5D=12&payment_method_data%5Bcard%5D%5Bexp_year%5D=30&note=synthetic%2Bexample",
                         "application/x-www-form-urlencoded", '{"synthetic":true}')],
        "oppwa": [entry("POST", "https://eu-prod.oppwa.com/v1/checkouts/SYNTHETIC", "card.number=4242424242424242", "application/x-www-form-urlencoded", '{"synthetic":true}'),
                  entry("POST", "https://eu-prod.oppwa.com/v1/checkouts/SYNTHETIC", "card.cvv=999", "application/x-www-form-urlencoded", '{"synthetic":true}'),
                  entry("POST", "https://eu-prod.oppwa.com/v1/checkouts/SYNTHETIC", "card.expiryMonth=12&card.expiryYear=2030&card.holder=TEST+USER", "application/x-www-form-urlencoded", '{"synthetic":true}')],
    }

    return {
        "adyen": {"capture": [flows["adyen"][0]], "encrypt": [flows["adyen"][1]]},
        "cybersource": {"capture": [flows["cybersource"][0]], "bridge-sdk": [flows["cybersource"][1]], "encrypt": [flows["cybersource"][2]]},
        "stripe": {"reveal": flows["stripe"]},
        "oppwa": {"reveal": flows["oppwa"]},
    }

def encoded(provider, function, entries):
    return (json.dumps({"log": {"version": "1.2", "creator": {"name": "Agent Web Gateway synthetic fixture generator", "version": "1"},
                               "_synthetic": True, "_provider": provider, "_function": function, "comment": "Authored teaching fixture. No real capture, credential, private key, customer or payment result. Test cards only.",
                               "entries": entries}}, indent=2) + "\n").encode()

if __name__ == "__main__":
    for provider, functions in fixtures().items():
        for function, entries in functions.items():
            file = ROOT / provider / "fixtures" / (function + ".synthetic.har")
            data = encoded(provider, function, entries)
            if "--check" in sys.argv:
                if not file.exists() or file.read_bytes() != data:
                    raise SystemExit(f"Fixture differs from the public generator: {provider}/{function}")
            else:
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(data)
    print("Seven synthetic function HAR fixtures " + ("verified." if "--check" in sys.argv else "generated."))
