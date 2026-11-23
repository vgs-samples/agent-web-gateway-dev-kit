#!/usr/bin/env python3
"""Answer the Control Panel's helper requests in a hosted browser, over its Chrome DevTools connection.

A hosted browser cannot reach the control panel helper on this machine, and the helper holds the
service-account credentials, so it is not exposed to the internet. Instead the panel's background
script hands each helper request to the awgHelperRelay function this script adds to it, the request
is made here against the local helper, and the result is returned with awgHelperAnswer.

The DevTools address controls the browser, so it is read from stdin and never printed.
Usage: helper-relay.py <helper port> <extension runtime id>
"""
import asyncio
import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import websockets

PORT, RUNTIME_ID = int(sys.argv[1]), sys.argv[2]
HELPER = f"http://127.0.0.1:{PORT}"
WORKER = f"chrome-extension://{RUNTIME_ID}/"


def browser_socket(address):
    if address.startswith(("ws://", "wss://")):
        return address
    base = address.rstrip("/")
    with urlopen(base + "/json/version", timeout=20) as response:
        socket = json.load(response)["webSocketDebuggerUrl"]
    # A hosted browser reports its own local address; keep the public host the caller was given.
    host = base.split("://", 1)[1]
    scheme = "wss" if base.startswith("https") else "ws"
    return f"{scheme}://{host}/{socket.split('/', 3)[3]}"


def ask_helper(call):
    """Make one request against the local helper. Only the helper's own address is ever requested."""
    url, method = call.get("url"), call.get("method") or "GET"
    if not isinstance(url, str) or not url.startswith(HELPER + "/") or method not in ("GET", "POST"):
        return 400, "{}"
    headers = {k: v for k, v in (call.get("headers") or {}).items()
               if k.lower() in ("authorization", "content-type") and isinstance(v, str)}
    body = call.get("body")
    request = Request(url, data=body.encode() if isinstance(body, str) else None, headers=headers, method=method)
    try:
        with urlopen(request, timeout=95) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except OSError:
        return 502, "{}"


async def relay(address):
    async with websockets.connect(browser_socket(address), max_size=None) as ws:
        counter = 0
        tasks, seen = set(), set()

        async def send(method, params=None, session=None):
            nonlocal counter
            counter += 1
            message = {"id": counter, "method": method, "params": params or {}}
            if session:
                message["sessionId"] = session
            await ws.send(json.dumps(message))

        async def answer(session, payload):
            try:
                call = json.loads(payload)
                status, text = await asyncio.to_thread(ask_helper, call)
                expression = f"awgHelperAnswer({json.dumps(str(call.get('id')))}, {status}, {json.dumps(text)})"
                await send("Runtime.evaluate", {"expression": expression}, session)
            except Exception:  # noqa: BLE001 - one failed request must not end the relay
                pass

        # The panel's background script stops when idle and starts again as a new target, so watch for each one.
        await send("Target.setDiscoverTargets", {"discover": True})
        async for raw in ws:
            message = json.loads(raw)
            method, params = message.get("method"), message.get("params", {})
            if method in ("Target.targetCreated", "Target.targetInfoChanged"):
                info = params["targetInfo"]
                if info.get("type") == "service_worker" and info.get("url", "").startswith(WORKER) and info["targetId"] not in seen:
                    seen.add(info["targetId"])
                    await send("Target.attachToTarget", {"targetId": info["targetId"], "flatten": True})
            elif method == "Target.attachedToTarget":
                session = params["sessionId"]
                if params["targetInfo"].get("url", "").startswith(WORKER):
                    await send("Runtime.enable", session=session)
                    await send("Runtime.addBinding", {"name": "awgHelperRelay"}, session)
            elif method == "Runtime.bindingCalled" and params.get("name") == "awgHelperRelay":
                task = asyncio.create_task(answer(message.get("sessionId"), params.get("payload", "")))
                tasks.add(task)
                task.add_done_callback(tasks.discard)


async def main():
    address = sys.stdin.readline().strip()
    if not address:
        sys.exit("No DevTools address was given.")
    failures = 0
    while failures < 5:
        try:
            await relay(address)
            failures = 0
        except Exception:  # noqa: BLE001 - never print the address or a URL that contains it
            failures += 1
        await asyncio.sleep(2)
    sys.exit("The connection to the browser was lost.")


if __name__ == "__main__":
    asyncio.run(main())
