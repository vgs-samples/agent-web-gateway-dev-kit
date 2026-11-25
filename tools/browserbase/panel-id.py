#!/usr/bin/env python3
"""Print the Control Panel's extension ID in a running cloud browser.

    panel-id.py      the browser's connect address is read from standard input

Browserbase does not report the ID Chrome gave an uploaded extension, so this asks each extension's
background script for its name over the browser's Chrome DevTools connection.

The address controls the browser, so it is never taken from the command line or printed.
"""
import asyncio
import json
import sys

import websockets

PANEL = "Agent Web Gateway Control Panel"


async def panel_id(address):
    async with websockets.connect(address, max_size=None, open_timeout=20) as socket:
        counter = 0

        async def call(method, params=None, session=None):
            nonlocal counter
            counter += 1
            message = {"id": counter, "method": method, "params": params or {}}
            if session:
                message["sessionId"] = session
            await socket.send(json.dumps(message))
            while True:
                answer = json.loads(await asyncio.wait_for(socket.recv(), timeout=20))
                if answer.get("id") == counter:
                    return answer.get("result") or {}

        # The background script starts with the browser; give it a moment to appear.
        for _ in range(40):
            for target in (await call("Target.getTargets")).get("targetInfos", []):
                url = target.get("url", "")
                if target.get("type") != "service_worker" or not url.startswith("chrome-extension://"):
                    continue
                attached = await call("Target.attachToTarget", {"targetId": target["targetId"], "flatten": True})
                name = await call("Runtime.evaluate", {"expression": "chrome.runtime.getManifest().name",
                                                       "returnByValue": True}, attached.get("sessionId"))
                await call("Target.detachFromTarget", {"sessionId": attached.get("sessionId")})
                if (name.get("result") or {}).get("value") == PANEL:
                    return url.split("/")[2]
            await asyncio.sleep(0.5)
    return None


def main():
    address = sys.stdin.readline().strip()
    if not address.startswith(("ws://", "wss://")):
        sys.exit("No connect address was given.")
    try:
        found = asyncio.run(panel_id(address))
    except Exception:
        # The address is a secret and may appear in error text. Never print it.
        sys.exit("Could not ask the browser for its extensions.")
    if not found:
        sys.exit("The Control Panel is not among the browser's extensions.")
    print(found)


if __name__ == "__main__":
    main()
