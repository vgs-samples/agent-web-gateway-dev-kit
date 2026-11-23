#!/usr/bin/env python3
"""Open tabs in a running cloud browser through its Chrome DevTools address.

    open-tabs.py URL [URL...]      the DevTools address is read from standard input

The address controls the browser, so it is never taken from the command line or printed.
"""
import asyncio
import json
import sys
from urllib.parse import urlsplit
from urllib.request import urlopen

import websockets


def websocket_address(address):
    """Chrome serves the DevTools socket address at /json/version when given an HTTP address."""
    parts = urlsplit(address)
    if parts.scheme in ("ws", "wss"):
        return address
    if parts.scheme not in ("http", "https"):
        raise ValueError("Not a DevTools address")
    with urlopen(address.rstrip("/") + "/json/version", timeout=20) as response:
        return json.load(response)["webSocketDebuggerUrl"]


async def open_tabs(address, urls):
    async with websockets.connect(websocket_address(address), max_size=None, open_timeout=20) as socket:
        for number, url in enumerate(urls, 1):
            await socket.send(json.dumps({"id": number, "method": "Target.createTarget", "params": {"url": url}}))
            while True:
                message = json.loads(await asyncio.wait_for(socket.recv(), timeout=20))
                if message.get("id") == number:
                    if "error" in message:
                        raise RuntimeError("The browser refused the tab")
                    break


def main():
    urls = sys.argv[1:]
    address = sys.stdin.readline().strip()
    if not urls or not address:
        sys.exit("usage: open-tabs.py URL [URL...] with the DevTools address on standard input")
    try:
        asyncio.run(open_tabs(address, urls))
    except Exception:
        # The address is a secret and may appear in error text. Never print it.
        sys.exit("Could not open the tabs through the browser's DevTools address.")


if __name__ == "__main__":
    main()
