# Download, build and distribute the control panel

This repository includes **Agent Web Gateway Control Panel 1.8.0**: the extension
source, local helper, optional MCP companion, tests and illustrated setup guide. The **Build control panel**
workflow produces a versioned source/helper ZIP and a SHA-256 checksum.

## Download or build the kit

Open **Actions → Build control panel**, choose a successful run for the branch you
want, then download **agent-web-gateway-control-panel** under **Artifacts**.
During draft review, choose the PR branch; after merge, choose `main`.
Artifacts require repository access and a GitHub sign-in and are retained for 30 days.
They are build downloads, not a Chrome Web Store installation or a GitHub Release.

With the GitHub CLI:

```bash
gh run list --repo shawnmadadha7/awg \
  --workflow control-panel-package.yml --status success --limit 5

# Set this to the successful run ID you chose from the list.
AWG_RUN_ID="YOUR_RUN_ID"
gh run download "$AWG_RUN_ID" --repo shawnmadadha7/awg \
  --name agent-web-gateway-control-panel \
  --dir "$HOME/Downloads/awg-control-panel"
```

Verify and extract the kit on macOS:

```bash
cd "$HOME/Downloads/awg-control-panel"
shasum -a 256 -c vgs-agent-web-gateway-control-panel-1.8.0.zip.sha256
unzip vgs-agent-web-gateway-control-panel-1.8.0.zip
cd vgs-agent-web-gateway-control-panel-1.8.0
shasum -a 256 -c SHA256SUMS
```

On Linux, use `sha256sum -c` for each checksum check. Windows PowerShell's
`Get-FileHash -Algorithm SHA256` can calculate the archive checksum to compare
with the accompanying file. Use a new destination directory when extracting.

To build from a checkout with Python 3.10 or newer:

```bash
cd tools/vgs-proxy-controls
python3 build-package.py
```

The ZIP is written to `dist/`. The builder includes only an explicit list of
source files, bundled assets, screenshots and checksums. It does not recurse into
private configuration or generated extension directories. The workflow verifies
the source checksums, runs the helper, worker and isolated MCP browser tests, builds the ZIP and checks
its integrity before attaching it to the run. See the
[workflow](../../.github/workflows/control-panel-package.yml).

## Install the downloaded kit

Follow the included [tool README](../../tools/vgs-proxy-controls/README.md) or
[illustrated browser walkthrough](10-proxy-controls-extension.md).

1. Prepare your own Sandbox service-account credentials and an active session's
   original creation response. Keep the matching request for authenticated egress.
2. Start the helper. It generates your private `.private-extension` directory.
3. Launch Chrome for Testing with that directory, or use **Load unpacked** in the
   browser's extensions page. The source directory itself is not an installable extension.
4. Confirm your tenant, select a session and route, and inspect the PAC file.
5. Choose **No Proxy** when finished. Close the test browser and stop the helper.

The helper still needs an initial active saved session. Once installed, the panel
can create subsequent sessions using VGS Collect or existing aliases. A fresh
installation starts in PAC mode. CA trust remains a separate prerequisite.

## Distribution choices

| Channel | Trainee experience | Fit |
|---|---|---|
| Versioned source/helper ZIP | Download, start helper, load unpacked extension; update manually | First training cohort and local development |
| Unlisted Chrome Web Store | Install from a direct link; store-delivered extension updates | Recommended next step for invited training groups that do not require access restriction |
| Public Chrome Web Store | Searchable listing; store installation and updates | Broader release after onboarding is ready |
| Private Chrome Web Store | Installation limited to configured testers, groups or eligible organization users | Restricted pilots |
| Microsoft Edge Add-ons | Separate Edge listing and review | Native Edge distribution if trainees need it |
| Enterprise deployment | Organization deploys the extension through browser policy | Managed employee browsers |

Chrome's public, unlisted and private listings all go through review. Its
[distribution settings](https://developer.chrome.com/docs/webstore/cws-dashboard-distribution)
define who can install each one. A locally generated directory is not a store-ready
ZIP; a store package needs a reusable manifest and extension files at its root.

[Brave supports Chrome Web Store extensions](https://support.brave.app/hc/en-us/articles/360017909112-How-can-I-add-extensions-to-Brave),
so a separate Brave store release is not the starting point. Still validate this
extension's proxy APIs and authentication in Brave. Microsoft documents both
[Edge Add-ons and alternative deployment](https://learn.microsoft.com/en-us/microsoft-edge/extensions/publish/hosting-and-updating).
Firefox and Safari would require separate compatibility work and are outside this
Chromium training sample.

Hosting a `.crx` file on a download page is not a universal install method:
Chrome on Windows and macOS limits self-hosted installation to enterprise policy.
See [Chrome's distribution guide](https://developer.chrome.com/docs/extensions/how-to/distribute).
Use the unpacked training instructions or a store listing for individual learners.

## Package contents and private data

Each learner generates their own extension locally. Share the reviewed source/helper
ZIP, never an archive of an installed extension. The generated worker contains
session proxy credentials, a signed PAC URL and helper connection details.
Service-account credentials stay in the helper.

Generated extension directories, browser profiles, credentials, session responses,
egress requests and HAR recordings are excluded from the build. Screenshots use
synthetic account/session data and local network fixtures. The download contains
no Git history; the repository's commit history retains author metadata.

This repository remains private and its reference material is marked internal.
A public package or store release needs its own release decision, license review
and public-facing documentation. Publishing this branch does not change repository
visibility. For persistent versioned downloads, a future release workflow can
attach the same allowlisted ZIP to GitHub Releases.

CloakBrowser's wrapper source is MIT-licensed, but its distributed browser binary
uses a separate proprietary license. The
[vendor's binary license](https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md)
restricts redistribution and bundling. An optional CloakBrowser setup should send
learners to the vendor's distribution instead of including that binary in the
extension kit. Do not describe the whole CloakBrowser distribution as open source.

## Work needed for the store experience

| Current behavior | Change for a store release |
|---|---|
| Helper generates a per-user manifest and worker containing session configuration | Ship one reusable extension; deliver user configuration at runtime after local pairing |
| Helper address and token change on restart | Reconnect without editing or reloading store-installed code; choose authenticated loopback pairing or a registered native-messaging host |
| Launcher requires an active session | Start with no session, show account setup, and enable creating the first session in the panel |
| New installation immediately selects PAC | Start in **No Proxy** until the user explicitly selects a session and route |
| Browser and CA setup are separate manual prerequisites | Provide browser-specific launch help and an explicit CA-trust step without disabling TLS verification |
| Broad proxy/network permissions are required | Explain why each permission is needed and document what stays local in the listing and privacy disclosure |

Native messaging is one possible helper transport, not a feature implemented by
the current kit. Chrome describes the separate host installation and registration
in its [native messaging guide](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).
Store review and browser compatibility still need validation; code reuse alone
does not establish approval or support.

## Where this fits in the course

Keep lab 3 for the API concepts and first-session prerequisites. Offer page 10 as
the browser setup route before lab 4, so learners can choose a route and see the
PAC file without editing browser flags during checkout. Link the versioned kit
and its browser support notes from page 10.

The **Agent Web Gateway dev kit** README puts the control-panel download and
walkthrough after the product introduction. It links the reviewed source/helper
artifact rather than a generated private extension directory.

For the introductory extension lab, use one pinned Chrome for Testing build.
When reproducing an existing CloakBrowser test, keep its original browser and
configuration as the reference instead. Brave and other Chromium builds do not
inherit CloakBrowser's fingerprint behavior by using the same extension; see
[the browser comparison](10-proxy-controls-extension.md#is-brave-equivalent-to-cloakbrowser).
Treat the alternative browsers as additional validation targets. Check helper
connection and restart, session selection, all four routes, proxy authentication,
PAC host selection, CA trust and an expired session on each supported build.
The package does not start a merchant test or submit a payment.


## Verified scope

The source began with the clean 1.7.6 package and is updated to 1.10.0 in this
repository. Local verification passed 118 helper/privacy tests, 31 extension-worker
tests and 24 session-kit tests. GitHub Actions also passed isolated Chromium
fixtures for MCP capture, panel recording, gateway views, session aliases and CA
downloads. The five walkthrough screenshots come from synthetic Sandbox fixtures.
No real VGS account, card tokenization or merchant payment was used.

Browser launch examples and distribution choices reference the official vendor
documentation linked in this guide and the browser walkthrough. They do not
establish compatibility with every browser/version or provide anonymity.
