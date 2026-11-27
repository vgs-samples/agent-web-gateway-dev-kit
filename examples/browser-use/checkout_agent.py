#!/usr/bin/env python3
"""A Browser Use agent that fills a payment form with a reveal session's stand-ins.

Start the browser first, in another terminal:

    ./awg browser-use https://<the site to test>/

Then run the agent against it:

    uv run --with 'browser-use==1.0.8rc1' examples/browser-use/checkout_agent.py https://<the site to test>/

For a Browser Use cloud browser, start it with ./awg browser-use --cloud and put the DevTools address
it prints in AWG_CDP_URL before running the agent.

The agent types the session's stand-ins, never a card. VGS replaces them with the test card on the
way to an approved destination. Sandbox and the public test card only.

The default model is Browser Use's own, which needs BROWSER_USE_API_KEY. Pass llm= to Agent to use another.
"""
import json
import os
from pathlib import Path
import sys

from browser_use import Agent, Browser

STATE = Path(os.environ.get("AWG_HOME", Path.home() / ".vgs" / "awg")).expanduser() / os.environ.get("AWG_ENVIRONMENT", "sandbox")
# The local browser by default. For ./awg browser-use --cloud, set AWG_CDP_URL to the DevTools address it prints.
CDP = os.environ.get("AWG_CDP_URL") or "http://127.0.0.1:" + os.environ.get("AWG_CDP_PORT", "9222")


def stand_ins():
    """The card number and security code stand-ins of the session ./awg browser-use is running on."""
    session = json.loads(Path((STATE / "latest-session").read_text().strip()).read_text())
    card = session["data"]["attributes"]["cards"][0]
    values = {"card_number": card["number"]["value"]}
    if card.get("cvc"):
        values["card_cvc"] = card["cvc"]["value"]
    return values


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        secrets = stand_ins()
    except (OSError, KeyError, IndexError, ValueError):
        sys.exit("No usable session found. Start the browser with ./awg browser-use first.")
    task = (f"Go to {sys.argv[1]} and continue to the payment form. Enter the card number with "
            "type_secret('card_number')" + (" and the security code with type_secret('card_cvc')" if "card_cvc" in secrets else "")
            + ". Use any expiry date in the future. Stop before submitting the order and report what you see.")
    # Browser Use keeps sensitive_data values out of its output and results. They are not scoped to a
    # domain here because payment fields usually sit in the payment provider's frame, on another host.
    agent = Agent(task, browser=Browser(cdp_url=CDP, keep_alive=True), sensitive_data=secrets)
    print(agent.run_sync().final_result())


if __name__ == "__main__":
    main()
