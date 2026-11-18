# VGS Proxy Controls — DEV edition

A shareable Chromium extension with a local helper for choosing an existing reveal
session, viewing its actual PAC script, and selecting one of four browser routes:

1. Reveal Session PAC — the session's host-based routing rules.
2. Reveal Session Proxy — VGS proxy followed by that session's configured egress.
3. Egress Proxy — the session's egress directly, without VGS replacement.
4. No Proxy — direct connection from this computer.

Version 1.3.0. Supports the DEV environment `sandbox.vgsapi.io`, vault
`tntmdki2teh`. Production is deliberately unsupported. Each user supplies their
own authorized DEV service-account credentials and session creation files.

## Install

Requires Python 3.10+ and a Chromium browser that supports unpacked Manifest V3
extensions (for example, your existing CloakBrowser or Chrome for Testing).
The helper uses Python's standard library; no Python packages are needed.
Use a dedicated DEV test browser already configured with the reveal session's
VGS CA through your team's approved browser setup. This extension does not install
certificates or disable TLS verification.

1. Unzip this package into a folder you will keep. Keep the source folder intact.
2. Copy `dev.env.example` to a private file outside the shareable package, and fill
   in your own DEV service-account ID and secret. It needs `reveal-sessions:read`
   access to this DEV vault. Use plain `KEY=value` lines, without shell `export`
   prefixes or quotes. On macOS/Linux, restrict it with `chmod 600 /path/dev.env`.
3. Keep the original reveal-session creation responses in a private directory,
   named `RS….json`. The API list cannot retrieve their one-time proxy credentials.
   For a session with authenticated custom egress, keep its original creation
   request beside it as `RS….request.json`; the response masks the egress password.
   Create sessions using your existing approved DEV workflow.
4. From the unzipped folder, run:

   ```sh
   python3 start-proxy-controls.py \
     --session /path/to/sessions/RS_EXAMPLE.json \
     --credentials-file /path/to/dev.env \
     --sessions-dir /path/to/sessions
   ```

   Replace `RS_EXAMPLE.json` with your actual session file. Keep this Terminal open.
   Use `--check` to validate these inputs locally without contacting VGS.
5. In the test browser, open `chrome://extensions`, enable Developer mode, choose
   **Load unpacked**, and select the `.private-extension` directory printed by the
   command. Pin **VGS Proxy Controls** from the extensions menu and open it.

After restarting the helper, click **Reload** for this extension on
`chrome://extensions` to reconnect to the new local helper. The browser's selected
session survives worker restarts. A newly installed extension starts in PAC mode.
Stop the helper with Ctrl-C when finished. An already selected route continues to
use its session; Refresh and changing sessions need the helper running.

## Use

**Available DEV sessions** lists active sessions from the account. Click **Refresh**
to include sessions created after opening the browser. Entries without locally
saved credentials or a compatible CA are disabled and explain why. Expired or
revoked sessions cannot be selected; a current expired session remains visible.

Choose an entry, then click **Use selected session**. The current PAC / VGS /
egress / direct mode is kept. Switching briefly blocks routing and resets cached
authentication for the proxy endpoints so Chrome uses the new session's credentials.
Merchant cookies, tabs and history are preserved. Switching to a session without
custom egress is refused while Egress Proxy mode is selected. An interrupted
switch stays blocked until you explicitly choose a route.

Session stand-ins are specific to the session: re-enter the newly selected session's
stand-ins in existing checkout forms. The extension does not fill forms, create
sessions, tokenize cards, or submit orders/payments. Reload pages after switching;
requests already running may finish on their previous route.

**View actual PAC file → Load PAC script** retrieves and displays the actual routing
script, with a fetch timestamp. The displayed PAC source omits its private signature.
PAC means Proxy Auto-Configuration; it chooses routes by host and does not detect
checkout. For checkout-only VGS routing, choose Egress Proxy while browsing, then
Reveal Session Proxy before opening checkout.

## Share this package

Share the original `vgs-proxy-controls-1.3.0.zip`, or rebuild it using the included
`build-package.py`. The builder uses a fixed allowlist and produces a clean ZIP.

**Never share `.private-extension`, a loaded browser profile, your DEV environment
file, or saved session/request JSON files.** The generated extension contains your
session's proxy credentials and signed PAC URL. Do not export the installed
extension with Chrome's “Pack extension” button. Each recipient generates their
own private extension using the steps above.

The account API credentials remain in the local helper. Its HTTP interface binds
only to `127.0.0.1`, requires a random access token, rejects website origins, and
supports read-only session/PAC operations. It does not expose a general-purpose
API proxy. Public UI messages omit credentials and signed PAC URLs.

## Troubleshooting

- **No usable sessions:** create a fresh session through your approved DEV workflow,
  save its creation response and matching request in `--sessions-dir`, then Refresh.
- **Proxy credentials not saved:** GET/list API responses are insufficient; use the
  original creation response. Credentials are returned only at creation.
- **Missing saved egress credentials:** put the matching `.request.json` beside the
  response. Do not substitute a different proxy's credentials.
- **Could not refresh:** keep the helper running, confirm the service account's DEV
  access, then Refresh. After a helper restart, reload the extension first.
- **Different session CA:** use a fresh browser configured for that session's CA.
- **Session expired:** select a fresh available session. Expiry does not prove that
  a backing CVC alias is still available; use fresh aliases for new checkout tests.

## Developer checks

`node --test test_session_proxy_extension.mjs` runs offline worker tests.
`python3 -m unittest test_session_catalog.py` tests catalog filtering and localhost
authentication with synthetic fixtures. `test_session_proxy_browser.py` additionally
needs Playwright and a Chrome for Testing executable; it verifies real proxy routing,
session changes at the same endpoint, merchant-cookie preservation, worker restarts,
and exact PAC display using local fixtures only.
