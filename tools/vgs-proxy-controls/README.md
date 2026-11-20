# Agent Web Gateway Control Panel source

This directory contains the Chromium extension, local helper, and their tests.

The user guides are in `docs/`:

- [Control Panel: install, create sessions, record traffic, and troubleshoot](../../docs/control-panel.md)
- [MCP companion: connect an assistant to captures and gateway tools](../../docs/mcp.md)
- [Browser proxying: egress, PAC routing, and checkout timing](../../docs/browser-proxying.md)

The downloadable package includes the same guides under `docs/`. The package
builder copies them from the repository and adjusts links for the archive.

## Developer checks

`node --test test_session_proxy_extension.mjs` runs offline worker tests.
`python3 -m unittest discover -p 'test_*.py'` tests catalog filtering and localhost
authentication with synthetic fixtures. `test_session_proxy_browser.py` additionally
needs Playwright and a Chrome for Testing executable; it verifies real proxy routing,
session changes at the same endpoint, merchant-cookie preservation, worker restarts,
and exact PAC display using local fixtures only.

Run these commands from this directory. To build the public source package:

```sh
python3 build-package.py
```

The builder uses a fixed file list and checks it for private artifacts. Keep
credentials, generated extensions, sessions, and captures outside the repository.
