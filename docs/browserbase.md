# Use a Browserbase cloud browser

`./awg start` opens CloakBrowser on your machine. `./awg browserbase` is an alternative for teams that run their agents on [Browserbase](https://www.browserbase.com): the browser runs in Browserbase's cloud and its traffic passes through your reveal session. No browser or Docker is needed locally; the kit uses `curl`, `jq` and `uv`.

> Run so far, against a Browserbase project on the free plan: Browserbase accepted the session's certificate authority and the Control Panel upload, then refused to start the browser because the free plan has no proxies. The rest follows Browserbase's published API and passes the kit's offline tests, which stub Browserbase and VGS. Not yet exercised: the browser starting on a session's proxy, the Control Panel in a Browserbase browser, the relay to the local helper, and a submitted payment.

## What you need

- Sandbox credentials from `./awg setup`.
- A Browserbase project on the Developer plan or higher, and its API key. Browserbase requires that plan for custom proxies and keep-alive browsers, and bills browser usage to the account.

| Variable | Purpose |
|---|---|
| `BROWSERBASE_API_KEY` | Required. The project's API key. Export it in your own terminal; the kit does not save it. |
| `BROWSERBASE_PROJECT_ID` | Optional. Browserbase reads the project from the key; set this when the key covers more than one. |

## Run it

```sh
export BROWSERBASE_API_KEY=…
./awg browserbase https://<the site to test>/
```

The command:

1. Creates or reuses a reveal session with the VGS test card, the same way `./awg start` does.
2. Starts the Control Panel's helper on your machine and uploads the Control Panel extension to Browserbase. If Browserbase does not accept it, the command says so and continues without the panel.
3. Uploads the session's certificate authority to Browserbase's [certificates](https://docs.browserbase.com/platform/browser/security/certificate-validation), so the browser trusts pages re-signed by VGS and nothing else new.
4. Starts a Browserbase browser that uses the session as its [external proxy](https://docs.browserbase.com/platform/identity/proxies), trusts that certificate authority, and loads the panel.
5. Opens the kit's relay so the panel in the cloud browser reaches the helper on your machine. The helper holds your service-account credentials, and they stay local. The kit keeps a connection to the browser's connect address open and the panel hands each helper request to the kit over it ([`tools/browser-use/helper-relay.py`](../tools/browser-use/helper-relay.py)). The relay only ever calls the helper's own address.
6. Prints the browser's live view link and connect address, along with Browserbase's session ID for its dashboard, session replay and support. Pass the connect address to Playwright's `connect_over_cdp`, Stagehand, or your own agent.
7. Releases the browser, removes the panel and the certificate, and stops the helper and relay, when you press Enter. Without a terminal, it runs until the browser closes after 30 minutes.

Type the session's stand-ins into the payment form, as in any other session. Read them with `./awg session` output or the Control Panel.

## What is different from `./awg start`

| | `./awg start` | `./awg browserbase` |
|---|---|---|
| Browser | CloakBrowser on your machine | Browserbase's cloud, viewed through a link |
| Needs | CloakBrowser license key | Browserbase API key, on the Developer plan or higher |
| Also installed | CloakBrowser | Nothing |
| Control Panel | Loaded, with the local helper | Loaded and opened in a tab, with the local helper reached through the kit's relay. Not verified in a Browserbase browser |
| Route switching | In the panel | Not available. Browserbase sets the browser's route, so the browser stays on the session it started with |
| Recording | In the panel | Not verified in a Browserbase browser. Browserbase keeps its own session replay |

## In your own code

The same thing is two calls to Browserbase's API. Upload the session's `ca_bundle` with `POST /v1/certificates`, then create the browser with `POST /v1/sessions`:

```python
import json
from urllib.parse import unquote, urlsplit

proxy = json.load(open("RS….json"))["data"]["attributes"]["proxy"]   # the reveal session you created
url = urlsplit(proxy["url"])

browser = {
    "proxies": [{"type": "external", "server": f"{url.scheme}://{url.hostname}:{url.port}",
                 "username": unquote(url.username), "password": unquote(url.password)}],
    "proxySettings": {"caCertificates": ["<id of the uploaded certificate>"]},
}
```

[`examples/browserbase/payment_flow.py`](../examples/browserbase/payment_flow.py) is the full version: it starts the browser, opens a vendor's payment page with Playwright, types the session's stand-ins, and submits only when asked to.

Send the certificate rather than `browserSettings.ignoreCertificateErrors`: the browser then trusts only the session's certificate authority in addition to the public ones. Each reveal session has its own certificate authority and proxy password, so a new session needs a new upload and a new browser.

## What Browserbase receives

The session's proxy address, proxy username and password, and certificate authority are sent to Browserbase's API, and the proxy details are also inside the uploaded panel. The browser's traffic runs in Browserbase's cloud, where its session replay records what the pages show, including the stand-ins typed into them. The live view link and the connect address each control the browser, so keep them private. Use Sandbox and the public test card only. Browserbase never receives the card: the browser holds session stand-ins, and VGS replaces them after the request has left the browser. Your VGS client secret is never sent to Browserbase: the helper that holds it runs on your machine.

## If it fails

| Output | Meaning |
|---|---|
| `BROWSERBASE_API_KEY is not set` | Export the key or put it in front of the command. |
| `Browserbase answered HTTP 401` | Browserbase did not accept the key. |
| `Browserbase answered HTTP 402` or `403` | The project's plan lacks custom proxies or keep-alive browsers. |
| `Browserbase did not store the session's certificate authority` | The certificate upload was refused; the line above it has Browserbase's reason. |
| `Browserbase did not start the browser` | Browserbase checks the proxy when it creates the browser. The line above has its reason; the session may have expired, or Browserbase cannot reach the session's proxy host and port. |
| `Browserbase did not accept the Control Panel` | The browser still starts on the session, without the panel. |
| `Control Panel: not loaded in this browser` | The panel was not found among the browser's extensions. Read the stand-ins from the session file. |
| Pages fail with a certificate error | The browser is not trusting the session's certificate authority. Report it with the Browserbase session ID. |
