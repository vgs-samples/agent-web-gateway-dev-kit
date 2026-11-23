#!/usr/bin/env python3
"""A hosted Browser Use Cloud agent run that goes through a reveal session.

Browser Use starts the browser and runs the agent in its cloud. The reveal session is the browser's
custom proxy, and the session's stand-ins are secret bindings the agent types by name without seeing them.

Create a session for the site first:

    ./awg session <the site's host>

Then start the run:

    BROWSER_USE_API_KEY=… uv run --with browser-use-sdk examples/browser-use/cloud_run.py \\
        https://<the site to test>/ [<payment provider host> …]

Browser Use types a secret only into a frame on a host you list. Payment fields usually sit in the
payment provider's frame, so name that host (for example js.stripe.com) after the URL.

The Browser Use project needs custom proxies enabled; Browser Use turns that on per project on request.
The session's proxy address, proxy password, certificate authority and stand-ins go to Browser Use.
Sandbox and the public test card only.
"""
import json
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

from browser_use_sdk.v4 import BrowserUse

STATE = Path(os.environ.get("AWG_HOME", Path.home() / ".awg-dev-kit"))


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        sys.exit(__doc__)
    site, frame_hosts = sys.argv[1], sys.argv[2:]
    site_host = urlsplit(site).hostname
    if not site_host:
        sys.exit("Give the site as a full URL, for example https://shop.example/")
    try:
        session = json.loads(Path((STATE / "latest-session").read_text().strip()).read_text())["data"]["attributes"]
        proxy, card = session["proxy"], session["cards"][0]
        url = urlsplit(proxy["url"])
        custom_proxy = {
            "host": url.hostname, "port": url.port, "protocol": url.scheme,
            "username": unquote(url.username), "password": unquote(url.password),
            # The session's certificate authority, so the browser trusts pages re-signed by VGS and nothing else new.
            "caBundle": proxy["ca_bundle"],
        }
        stand_ins = {"card_number": card["number"]["value"]}
        if card.get("cvc"):
            stand_ins["card_cvc"] = card["cvc"]["value"]
    except (OSError, KeyError, IndexError, TypeError, ValueError):
        sys.exit("No usable session found. Create one with ./awg session <the site's host> first.")

    hosts = list(dict.fromkeys([site_host, *frame_hosts]))
    task = (f"Go to {site} and continue to the payment form. Enter card_number in the card number field"
            + (" and card_cvc in the security code field" if "card_cvc" in stand_ins else "")
            + ". Use any expiry date in the future. Stop before submitting the order and report what you see.")
    with BrowserUse() as client:
        run = client.runs.create(
            task,
            browser_settings={"customProxy": custom_proxy},
            secret_bindings=[{"alias": alias, "source": {"type": "inline", "value": value}, "allowedDomains": hosts}
                             for alias, value in stand_ins.items()],
        )
        # Browser Use's own identifier, for its dashboard and support.
        print("Browser Use run:", run.id)
        print(client.runs.wait_for_completion(run.id).result)


if __name__ == "__main__":
    main()
