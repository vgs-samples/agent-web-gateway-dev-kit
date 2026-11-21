# Use Browser Use

[Browser Use](https://github.com/browser-use/browser-use) agents and [Browser Harness](https://github.com/browser-use/browser-harness) drive a browser through its Chrome DevTools address. `./awg browser-use` opens the kit's browser on a reveal session with that address available, so the agent's traffic passes through the session.

> Run so far: the local browser opens with the Control Panel and answers on its Chrome DevTools address, and Browser Use Cloud accepts the Control Panel upload. Not yet exercised: a Browser Use agent driving the browser, and a cloud browser on a session, which needs a Browser Use project with custom proxies enabled.

## Run it

```sh
./awg browser-use https://<the site to test>/
```

This is `./awg start` with one addition: the browser also listens for Chrome DevTools on `127.0.0.1:9222`. It needs the same things as `./awg start`, and the full Control Panel is loaded with its helper. Set `AWG_CDP_PORT` to use another port.

Point the agent at that address.

Browser Use library:

```python
from browser_use import Agent, Browser

browser = Browser(cdp_url='http://127.0.0.1:9222')
agent = Agent('<your task>', browser=browser)
print(agent.run_sync().final_result())
```

Browser Harness (the `browser-use` command line):

```sh
BU_CDP_URL=http://127.0.0.1:9222 browser-use <<'PY'
print(page_info())
PY
```

Browser Use releases change quickly, so pin the version you test with. These examples follow `browser-use==1.0.8rc1`, which needs Python 3.11 or newer.

## Give the agent the stand-ins

Give the agent the session's stand-ins, never a real card or the vault aliases. VGS replaces the stand-ins on the way to an approved destination. The Control Panel shows them, and the saved session file has them under `data.attributes.cards`.

Pass them through Browser Use's `sensitive_data`, so the agent types them with `type_secret(…)` and they stay out of its output and results:

```python
agent = Agent(
    "Fill the payment form: card number with type_secret('card_number'), security code with type_secret('card_cvc').",
    browser=Browser(cdp_url='http://127.0.0.1:9222', keep_alive=True),
    sensitive_data={'card_number': '<number stand-in>', 'card_cvc': '<security code stand-in>'},
)
```

`keep_alive=True` leaves the kit's browser open when the run ends. If you scope `sensitive_data` to domains, include the payment provider's host: payment fields usually sit in the provider's frame, not the shop's page.

[`examples/browser-use/checkout_agent.py`](../examples/browser-use/checkout_agent.py) does this end to end: it reads the stand-ins from the current session and stops before submitting the order.

```sh
uv run --with 'browser-use==1.0.8rc1' examples/browser-use/checkout_agent.py https://<the site to test>/
```

Browser Use 1.0 does not take a proxy for a browser it launches locally, so connecting it to a browser that is already on the session is the supported local route.

Any program on your machine can drive the browser through the DevTools address while it is open. Use it on a machine you control, and close the browser when you are done.

## Browser Use Cloud

```sh
BROWSER_USE_API_KEY=… ./awg browser-use --cloud https://<the site to test>/
```

The command:

1. Creates or reuses a reveal session with the VGS test card.
2. Starts a Browser Use Cloud browser with the session as its [custom proxy](https://docs.browser-use.com/cloud/browser/proxies), including the session's certificate authority so the browser trusts pages re-signed by VGS.
3. Uploads the Control Panel and opens it in a tab. Browser Use refuses extensions that ask for the `proxy` permission, so this build of the panel leaves it out: it shows the session, and the route stays on the session's proxy. The panel's helper is not reachable from Browser Use Cloud, so creating sessions, adding cards and the gateway views are not available there.
4. Prints a live view link and the browser's Chrome DevTools address. Pass that address to `Browser(cdp_url=…)`, or set it as `AWG_CDP_URL` to run the example agent against the cloud browser.
5. Stops the browser and removes the uploaded panel when you press Enter. Without a terminal, it runs until the browser stops (30 minutes).

### In your own code

The same thing is the `customProxy` field of `POST /api/v4/browsers`, or `browserSettings.customProxy` on an agent run: `host`, `port`, `protocol`, `username` and `password` from the session's proxy URL, and `caBundle` from the session's `ca_bundle`. With Browser Use's Python SDK, a hosted agent run on a reveal session looks like this:

```python
import json
from urllib.parse import unquote, urlsplit

from browser_use_sdk.v4 import BrowserUse

proxy = json.load(open("RS….json"))["data"]["attributes"]["proxy"]   # the reveal session you created
url = urlsplit(proxy["url"])

run = BrowserUse().runs.create(
    "<your task>",
    browser_settings={"customProxy": {
        "host": url.hostname, "port": url.port, "protocol": url.scheme,
        "username": unquote(url.username), "password": unquote(url.password),
        "caBundle": proxy["ca_bundle"],
    }},
)
```

Send `caBundle` rather than `ignoreCertErrors`: the browser then trusts only the session's certificate authority in addition to the public ones. A follow-up run that starts a new browser needs the proxy sent again.

### What Browser Use receives

The session's proxy address, proxy username and password, and certificate authority go to Browser Use's API, and the browser's traffic runs in its cloud. The live view link and the DevTools address each control the browser, so keep them private. Use Sandbox and the public test card only. Your VGS client id and secret are not sent.

### If it fails

| Output | Meaning |
|---|---|
| `BROWSER_USE_API_KEY is not set` | Export the key or put it in front of the command. |
| `HTTP 401` | Browser Use did not accept the key. |
| `HTTP 403` when starting the browser | Custom proxies are not enabled for the Browser Use project. They are an enterprise feature that Browser Use enables on request. |
| `Browser Use did not accept the Control Panel` | The browser still starts on the session, without the panel. |
| Pages fail to load | The session expired, or Browser Use cannot reach the session's proxy host and port. |
