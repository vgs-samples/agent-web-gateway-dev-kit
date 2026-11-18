# Packaging and publishing the Agent Web Gateway Control Panel

**Proposal for review.** Start training with a versioned source/helper download and
Chrome for Testing. For easier ongoing installation, prepare a reusable extension
for an **unlisted Chrome Web Store listing**, with a separately installed local
helper. Unlisted means anyone with the link can install it; it is not private.

The [current lab](10-proxy-controls-extension.md) works from the 1.3.0 tool already
in this repository. This proposal describes the desired experience for the newer
Agent Web Gateway Control Panel. It does not publish an extension, add a download
URL, or replace the bundled tool.

## What the trainee would see

### Available now: downloadable training kit

1. Get the versioned kit supplied for the training cohort and unpack it.
2. Use your own DEV service account and an active session created in the preceding
   lab. Save the original creation response and any authenticated egress request.
3. Start the helper in one terminal; it generates your private extension directory.
4. Launch Chrome for Testing in another terminal using the
   [copyable browser command](10-proxy-controls-extension.md#chrome-for-testing-cli-first-path).
5. Open the controls, choose the session and route, and inspect the actual PAC file.
   Choose **No Proxy** when finished, then end the session through its creation
   workflow.

This is an example for the **current bundled kit**, after the lab's copy/setup steps:

```bash
# Terminal 1: use your actual saved session and private credentials paths.
cd "$HOME/vgs-proxy-controls"
python3 start-proxy-controls.py \
  --session /absolute/private/sessions/RS_EXAMPLE.json \
  --credentials-file /absolute/private/dev.env \
  --sessions-dir /absolute/private/sessions
```

```bash
# Terminal 2: Chrome for Testing installed in /Applications on macOS.
AWG_EXTENSION_DIR="$HOME/vgs-proxy-controls/.private-extension"
"/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" \
  --user-data-dir="$HOME/Library/Application Support/AWG Training/chrome-for-testing" \
  --load-extension="$AWG_EXTENSION_DIR" \
  --no-first-run
```

Keep the helper terminal open. CA trust remains a separate setup requirement.
The bundled tool starts in PAC mode and needs an existing active session; it is
not yet an install-first, create-your-first-session experience.

### Proposed next: install and connect

```text
Install the extension + local helper
                ↓
Open Agent Web Gateway Control Panel — No Proxy
                ↓
Settings → environment → Browse for service-account file → Connect
                ↓
Tenant and granted permissions appear
                ↓
Select an existing session, or open New session
                ↓
Choose a route → inspect PAC and traffic → No Proxy when finished
```

The helper would support starting without a saved session. The installed extension
would discover and pair with the helper without rewriting its shipped files.
The newer panel's session-creation and account-file UI would be brought into the
versioned release. The DEV lab would retain explicit DEV opt-in; enabling an
environment in the UI would not grant account permissions.

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

## What belongs in a downloadable release

The existing `build-package.py` uses a fixed list of source files and includes
checksums. Each learner generates their own extension locally. Publish a reviewed
release artifact built from that source list; never ZIP the installed extension.

The generated worker contains session proxy credentials, a signed PAC URL and
helper connection details. Service-account credentials remain in the helper.
Keep generated extension directories, browser profiles, credentials, session
responses, egress requests and HAR recordings out of the downloadable artifact.

This training repository is marked internal. A public tool release would use a
separate package and public-facing setup guide, without copying the internal
reference documents, slides or training archive. Select a version, license and
release owner for that package before publishing it. No public download or store
listing is created by this proposal.

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
this proposal. Chrome describes the separate host installation and registration
in its [native messaging guide](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).
Store review and browser compatibility still need validation; code reuse alone
does not establish approval or support.

## Where this fits in the course

Keep lab 3 for the API concepts and first-session prerequisites. Offer page 10 as
the browser setup route before lab 4, so learners can choose a route and see the
PAC file without editing browser flags during checkout. Link the versioned kit
and its browser support notes from page 10 once a release exists.

Place this under **Testing** in the proposed Agent Web Gateway Quick Start
navigation, after the product introduction and first-session setup. The download
entry should point to the reviewed tool release once it exists, not to the
generated private extension directory.

For the introductory extension lab, use one pinned Chrome for Testing build.
When reproducing an existing CloakBrowser test, keep its original browser and
configuration as the reference instead. Brave and other Chromium builds do not
inherit CloakBrowser's fingerprint behavior by using the same extension; see
[the browser comparison](10-proxy-controls-extension.md#is-brave-equivalent-to-cloakbrowser).
Treat the alternative browsers as additional validation targets. Check helper
connection and restart, session selection, all four routes, proxy authentication,
PAC host selection, CA trust and an expired session on each supported build.
This proposal does not start a merchant test or submit a payment.

## Evidence and limits

Prepared 2026-11-18 from the bundled 1.3.0 launcher, generator, package builder and
README, plus the vendor documentation linked above. Browser commands are examples
checked against source and documentation; they have not been executed against
real accounts or merchant sites for this change. The newer panel is a release
candidate to integrate separately, not functionality supplied by this docs PR.
