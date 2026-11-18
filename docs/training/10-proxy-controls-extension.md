# 10. Switching routes with the VGS Proxy Controls extension

**When you finish this page you can** pick a reveal session in your test browser and switch between four routes with one click, instead of relaunching the browser.

> **Status: source-checked, not run.** These steps follow the extension's own README (version 1.3.0) and its code. Nobody has run them as part of writing this page.

> **DEV only.** The extension works with the DEV environment (`sandbox.vgsapi.io`) and the DEV tenant `tntmdki2teh`. Production is deliberately unsupported.

For the CLI-first training path, start the helper below, then use **Chrome for
Testing** from the [browser launch examples](#browser-launch-examples). Regular
Chrome, Edge and Brave have a one-time manual installation step. These examples
target the **1.3.0 tool bundled in this repository**, not the newer Agent Web
Gateway Control Panel. The [distribution proposal](extension-distribution.md)
describes how the newer panel could become an installable training tool.

## What it does

VGS Proxy Controls is a Chromium extension with a small helper program that runs on your computer. It lets you choose one of your existing reveal sessions and one of four routes for the browser's traffic:

| Route | Where traffic goes | Use it to |
|---|---|---|
| **Reveal Session PAC** | Only the session's payment hosts go through VGS, by the session's PAC file | Run a checkout the way an agent would |
| **Reveal Session Proxy** | Everything goes through VGS, then out through the session's egress proxy | Force every request through VGS |
| **Egress Proxy** | Everything goes straight out through the session's egress proxy. VGS swaps nothing | Check how the site behaves without VGS |
| **No Proxy** | Direct from your computer | Compare against a plain connection |

It also shows the session's actual PAC file, so you can see which hosts go through VGS.

It does **not** fill forms, create sessions, store cards or submit payments. You still type the session tokens yourself.

## What you need

1. Python 3.10 or later. No extra Python packages.
2. A Chromium test browser that can load unpacked extensions and already trusts the session's VGS CA. The extension does not install certificates.
3. Your own DEV service account with the `reveal-sessions:read` scope on the DEV tenant.
4. At least one reveal session you created, with its **original create response saved** as a file named `RS….json`. The proxy login is returned only when a session is created, so a session without that file cannot be used.
5. If the session uses an egress proxy with a password, the **original create request** saved beside it as `RS….request.json`. The response hides the egress password.

The session kit from lab 4 saves both files for you, under `.state-dev/sessions/` when you run it with `KIT_ENV=dev`.

## Steps

### 1. Copy the tool to a private folder

```bash
cp -R tools/vgs-proxy-controls ~/vgs-proxy-controls
cd ~/vgs-proxy-controls
```

### 2. Create your credentials file

```bash
cp dev.env.example ~/vgs-proxy-controls-dev.env
chmod 600 ~/vgs-proxy-controls-dev.env
```

Open that file and replace the two placeholders with your DEV service account's id and secret. Use plain `KEY=value` lines, with no quotes and no `export`. Leave the other three lines as they are.

### 3. Check your inputs

```bash
python3 start-proxy-controls.py \
  --session /path/to/sessions/RS_EXAMPLE.json \
  --credentials-file ~/vgs-proxy-controls-dev.env \
  --sessions-dir /path/to/sessions \
  --check
```

Replace `/path/to/sessions` with your sessions folder and `RS_EXAMPLE.json` with one of your session files. `--check` validates the inputs on your computer without contacting VGS.

### 4. Start the helper

Run the same command without `--check`, and leave that terminal open.

**Success:** it prints the path of a `.private-extension` folder.

### 5. Load the extension

For Chrome for Testing or Chromium, you can use the CLI examples below instead.
For a manual install, open a **dedicated training profile**, not your everyday
browser profile, then:

1. In the test browser, open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Click **Load unpacked** and choose the `.private-extension` folder from step 4.
4. Pin **VGS Proxy Controls** from the extensions menu, and open it.

**Success:** the extension opens in **Reveal Session PAC** mode and lists your sessions under **Available DEV sessions**.

The current helper needs an **active session before it can generate the
extension**. Installation is not a way to create your first session. Stopping the
helper does not turn off proxying; choose **No Proxy** when you want to turn it off.

### 6. Pick a session and a route

1. Choose a session in the list and click **Use selected session**.
2. Choose a route.
3. Reload the page you are testing. Requests already running may finish on the old route.

After you switch sessions, type the **new** session's tokens into any checkout form that is open. Session tokens work only in their own session.

### 7. Stop

Choose **No Proxy**, close the training browser, then press Ctrl-C in the helper's
terminal. Stopping the helper alone keeps the selected route working; refreshing
the list and changing sessions need the helper running. End the reveal session
through the workflow that created it when the lab is finished.

## Browser launch examples

**Recommended for the introductory lab: Chrome for Testing.**
[Chromium](https://www.chromium.org/chromium-projects/) is the open-source browser
project underlying Chrome. [Chrome for Testing](https://developer.chrome.com/docs/automation-and-testing/chrome-for-testing)
is Google's Chrome build for testing, with versioned downloads aligned to Chrome
releases and no automatic browser updates. It can open an ordinary visible window;
it is not an anonymity mode. Pin a maintained build for each cohort and update it
deliberately. Regular Chrome is the everyday, auto-updating product.

Chromium also works as a launch target, but choosing a specific Chrome for Testing
release gives the course a clearer reproducible baseline. Brave remains an
optional privacy-oriented browser compatibility target. For an existing merchant
test, preserve the browser originally used, as explained below.

Run the helper from step 4 first and leave it running. Use a second terminal for
the browser. The examples assume macOS applications installed in `/Applications`;
change the executable path if yours is elsewhere. They launch the browser, but do
not install a browser or configure its CA trust.

Use a separate profile for each browser. Close that training browser before
launching again: an existing process may ignore new command-line flags. Keep the
same profile and generated extension directory for subsequent launches. Proxy
settings affect every tab in that profile.

| Browser | First installation | Later launches |
|---|---|---|
| Chrome for Testing | Load the generated directory with `--load-extension` | Repeat the command with the same profile |
| Chromium | Load the generated directory with `--load-extension` | Repeat the command with the same profile |
| Google Chrome | Developer mode → **Load unpacked** | Launch the same profile |
| Microsoft Edge | Developer mode → **Load unpacked** at `edge://extensions` | Launch the same profile |
| Brave | Developer mode → **Load unpacked** at `brave://extensions` | Launch the same profile |

**These are source-checked launch recipes, not a tested browser compatibility
matrix.** The four routing modes, proxy authentication and helper connection
still need a smoke test on each browser/version selected for a training cohort.

### Is Brave equivalent to CloakBrowser?

No. Both modify fingerprinting signals.
[Brave's graphics protections](https://brave.com/privacy-updates/38-webgl-webgpu-fingerprinting-protections/)
use generic values, remove identifying details and randomize some signals to
reduce tracking. [CloakBrowser documents](https://github.com/CloakHQ/CloakBrowser)
coordinated, repeatable browser-fingerprint profiles, Playwright/Puppeteer
integration and automation-specific Chromium modifications. Those vendor
capabilities are not effectiveness guarantees verified by this lab.
Installing the same VGS extension does not make
their browser behavior or fingerprints identical, and neither establishes
complete anonymity.

A separate profile isolates local cookies and browsing data. The selected proxy
route determines the network path for traffic it carries. Those are different
from the browser characteristics a website can observe. Even with the same
egress, two browsers can produce different site behavior. Browser protections
may also change which page resources load.

Use the same browser build and configuration to reproduce an existing test. If
that test used CloakBrowser, keep it as the reference environment. Use the examples
here for extension setup and additional browser compatibility checks; they are
not a replacement for that environment. Record the browser/version alongside the
session and route when comparing results.

### What about Kitesurf?

[Kitesurf](https://developers.cloudflare.com/browser-run/kitesurf/) is a different,
experimental engine running on Cloudflare Workers. Cloudflare explicitly leaves
out extensions and lists long-running authenticated sessions with persistent
state as a current limitation. Its Chrome DevTools Protocol support does not make
it a Chromium extension host. It cannot run this control-panel extension; treat a
future AWG integration as separate work, not another launch option in this lab.

### Chrome for Testing: CLI-first path

With the tool copied to the location used in step 1:

```bash
AWG_EXTENSION_DIR="$HOME/vgs-proxy-controls/.private-extension"
"/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" \
  --user-data-dir="$HOME/Library/Application Support/AWG Training/chrome-for-testing" \
  --load-extension="$AWG_EXTENSION_DIR" \
  --no-first-run
```

Open **VGS Proxy Controls** from the extensions menu. The bundled version opens
as a toolbar popup; it does not open a full control-panel tab automatically.

### Chromium

```bash
AWG_EXTENSION_DIR="$HOME/vgs-proxy-controls/.private-extension"
"/Applications/Chromium.app/Contents/MacOS/Chromium" \
  --user-data-dir="$HOME/Library/Application Support/AWG Training/chromium" \
  --load-extension="$AWG_EXTENSION_DIR" \
  --no-first-run
```

### Google Chrome, Edge and Brave

Run **one** command for your chosen browser. In the extensions page it opens,
enable Developer mode, choose **Load unpacked**, and select
`~/vgs-proxy-controls/.private-extension`. On macOS, **Cmd+Shift+G** in the folder
chooser lets you enter the hidden folder's full path. Keep the folder in place.

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --user-data-dir="$HOME/Library/Application Support/AWG Training/chrome" \
  --no-first-run "chrome://extensions"
```

```bash
"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
  --user-data-dir="$HOME/Library/Application Support/AWG Training/edge" \
  --no-first-run "edge://extensions"
```

```bash
"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
  --user-data-dir="$HOME/Library/Application Support/AWG Training/brave" \
  --no-first-run "brave://extensions"
```

Regular Google Chrome removed `--load-extension` in version 137. Chromium and
Chrome for Testing retain it, according to the
[Chrome team's announcement](https://groups.google.com/a/chromium.org/g/chromium-extensions/c/1-g8EFx2BBY/m/S0ET5wPjCAAJ).
Do not assume every Chromium-derived browser accepts the same extension-loading
flags. The Edge example follows Microsoft's
[documented sideloading path](https://learn.microsoft.com/en-us/microsoft-edge/extensions/getting-started/extension-sideloading).
Managed browser policy may disable developer-mode installation.

### Linux and Windows

For Chromium or Chrome for Testing on Linux, use the executable you installed:

```bash
AWG_BROWSER_BIN="/absolute/path/to/browser-executable"
AWG_EXTENSION_DIR="$HOME/vgs-proxy-controls/.private-extension"
"$AWG_BROWSER_BIN" \
  --user-data-dir="$HOME/.local/share/awg-training/chromium" \
  --load-extension="$AWG_EXTENSION_DIR" \
  --no-first-run
```

For Chrome for Testing on Windows, after preparing the helper and extension with
your own Windows paths, the corresponding PowerShell launch is:

```powershell
$AwgBrowser = 'C:\path\to\chrome-win64\chrome.exe'
$AwgExtension = Join-Path $HOME 'vgs-proxy-controls\.private-extension'
$AwgProfile = Join-Path $env:LOCALAPPDATA 'AWG Training\chrome-for-testing'
& $AwgBrowser "--user-data-dir=$AwgProfile" "--load-extension=$AwgExtension" --no-first-run
```

Use the extension-management UI for regular Chrome on these platforms too.
The macOS/Linux copy and permission commands earlier in this page are not a
Windows setup walkthrough. Windows launch syntax is provided as a sample and
has not been executed here.

### Check the installation and restart it

1. The extension-management page shows **VGS Proxy Controls** enabled.
2. The panel shows the intended session. **Refresh** works while the helper runs.
3. Choose **No Proxy** to confirm the off control is available. Before selecting a
   VGS route, configure the dedicated browser to trust the session's CA through
   the approved setup from your team. A fresh profile does not establish trust.
4. For the route check, follow [lab 4's verification steps](04-lab-browser-checkout.md#5-check-it-worked)
   on an authorized test destination. An installed extension alone does not prove
   traffic passed through VGS.

After restarting the helper, click **Reload** on the extension-management page
before using it. Its local connection details change on restart. This step is
needed even when the browser profile and generated extension path stayed the same.

## A useful pattern

The PAC file routes by host, so it cannot send only the checkout step through VGS. To do that by hand: browse the site on **Egress Proxy**, then switch to **Reveal Session Proxy** just before you open the checkout.

## If something goes wrong

| What you see | What to do |
|---|---|
| No usable sessions | Create a fresh session, save its create response (and request) in your sessions folder, then click **Refresh** |
| "Proxy credentials not saved" | You need the original create response. Reading or listing a session later does not return its proxy login |
| "Missing saved egress credentials" | Put the matching `RS….request.json` beside the response. Do not use a different proxy's credentials |
| Could not refresh | Check the helper is still running and your service account has DEV access. If you restarted the helper, click **Reload** for the extension on `chrome://extensions` first |
| Different session CA | Use a fresh browser set up for that session's CA |
| Session expired | Pick another session. Expired and revoked sessions cannot be selected |

## Keep these private

**Never share** the `.private-extension` folder, a browser profile it was loaded into, your credentials file, or your saved session files. The generated extension contains your session's proxy login and signed PAC link. Do not use Chrome's "Pack extension" button on it.

To give the tool to a teammate, point them at `tools/vgs-proxy-controls/` in this repository. Each person generates their own private extension with the steps above.

For a versioned training download or a future store listing, see
[Packaging and publishing the control panel](extension-distribution.md). The
repository is marked internal; a public release should contain the separately
reviewed tool package, not an archive of this training repository.

---

## Details and sources

- **What the helper exposes.** It listens only on `127.0.0.1`, requires a random access token, rejects website origins, and offers read-only session and PAC operations. Your service-account credentials stay in the helper.
- **Switching sessions.** The current route is kept. Switching briefly blocks routing and resets cached proxy authentication so the browser uses the new session's login. Merchant cookies, tabs and history are kept. An interrupted switch stays blocked until you choose a route. Switching to a session without an egress proxy is refused while **Egress Proxy** is selected.
- **The PAC view** omits the link's private signature.
- **Expiry and CVC.** A session that has not expired can still have a CVC alias that is no longer available. Use fresh aliases for new checkout tests.
- **The files are unchanged** from the `vgs-proxy-controls-1.3.0.zip` package; `SHA256SUMS` in that folder verifies them.
- **Lab 4's file locations** come from the session kit's code (`lib.sh`, `create-session.sh`), not from the extension's README.
- **Browser examples added 2026-11-18.** Arguments were checked against the bundled
  helper and the browser sources linked above. No browser, account or merchant
  session was started to validate this documentation change.

Sources: `tools/vgs-proxy-controls/README.md`, `dev.env.example`, `start-proxy-controls.py`, `session_catalog.py` and `session-proxy-extension/background.js` in the same folder; `skills/vgs-checkout-adapter/scripts/session-kit/lib.sh` and `create-session.sh`.
