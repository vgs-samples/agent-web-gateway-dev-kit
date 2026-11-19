#!/usr/bin/env python3
"""Build only public source files; never recurse into private runtime directories."""
from pathlib import Path
import hashlib
import zipfile

FILES = [
    'BROWSER-PROXY-BEST-PRACTICES.md',
    'MCP.md', 'requirements-mcp.txt', 'awg_mcp.py', 'mcp_capture.py', 'mcp_gateway.py', 'gateway-api-schema.json',
    'test_mcp_gateway.py', 'test_mcp_stdio.py', 'test_mcp_browser.py',
    'session-proxy-extension/collect-card.js', 'COLLECT-SDK.md',
    'session-proxy-extension/vendor/vgs-collect-dev-4.0.1.js',
    'session-proxy-extension/vendor/vgs-collect-4.0.1.js',
    'account_files.py', 'test_account_files.py', 'credential_picker.py', 'test_credential_picker.py',
    'session_form.py', 'test_session_form.py', 'session-proxy-extension/create-session.js', 'environments.py', 'environments.example.json', 'test_environments.py', 'BRAND-ASSETS.md', 'session_operations.py', 'capture_preferences.py',
    'private-card-tokenizer.py', 'test_session_operations.py',
    'session-proxy-extension/assets/vgs-logo.svg',
    'session-proxy-extension/assets/Averta-Regular.woff2',
    'session-proxy-extension/assets/Averta-Semibold.woff2',
    'session-proxy-extension/assets/Averta-Bold.woff2',
    'session-proxy-extension/assets/icon-16.png', 'session-proxy-extension/assets/icon-32.png',
    'session-proxy-extension/assets/icon-48.png',
    'README.md', 'sandbox.env.example', '.gitignore', 'build-package.py',
    'screenshots/control-panel.png', 'screenshots/settings.png',
    'screenshots/create-session.png', 'screenshots/diagnostics.png',
    'start-proxy-controls.py', 'awg_dev_api.py', 'session_catalog.py',
    'session_proxy_extension.py', 'test_session_catalog.py',
    'test_session_proxy_extension.mjs', 'test_session_proxy_browser.py',
    'session-proxy-extension/background.js', 'session-proxy-extension/popup.html',
    'session-proxy-extension/popup.js', 'session-proxy-extension/popup.css',
]


def build(root=None, output=None):
    root = Path(root or Path(__file__).resolve().parent)
    output = Path(output or root / 'dist/vgs-agent-web-gateway-control-panel-1.8.1.zip')
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = 'vgs-agent-web-gateway-control-panel-1.8.1/'
    checksums = []
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise ValueError('Missing or symlinked public source: ' + name)
            data = path.read_bytes()
            if name == 'session-proxy-extension/background.js' and b'const INITIAL_SESSION =' in data:
                raise ValueError('Use the source template, not a generated private worker')
            archive.writestr(prefix + name, data)
            checksums.append(hashlib.sha256(data).hexdigest() + '  ' + name)
        archive.writestr(prefix + 'SHA256SUMS', '\n'.join(checksums) + '\n')
    print(str(output))
    return output


if __name__ == '__main__':
    build()
