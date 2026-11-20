#!/usr/bin/env python3
"""Build only public source files; never recurse into private runtime directories."""
from pathlib import Path
import hashlib
import os
import re
from urllib.parse import unquote, urlsplit, urlunsplit
import zipfile
from check_publication import check_files

FILES = [
    'check_publication.py', 'test_publication.py',
    'egress_profiles.py', 'test_egress_profiles.py',
    'session_certificates.py', 'test_session_certificates.py', 'session-proxy-extension/certificate.js',
    'gateway_view.py', 'test_gateway_view.py', 'test_gateway_panel_browser.py', 'session-proxy-extension/gateway.js',
    'capture_repair.py', 'repair-capture.py', 'test_capture_repair.py', 'REPAIRS.md',
    'panel_recording.py', 'requirements-recording.txt', 'test_panel_recording.py', 'test_panel_recording_browser.py', 'session-proxy-extension/recording.js',
    'requirements-mcp.txt', 'awg_mcp.py', 'mcp_capture.py', 'mcp_gateway.py',
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
    'screenshots/create-session.png', 'screenshots/diagnostics.png', 'screenshots/gateway-config.png',
    'start-proxy-controls.py', 'awg_dev_api.py', 'session_catalog.py',
    'session_proxy_extension.py', 'test_session_catalog.py',
    'test_session_proxy_extension.mjs', 'test_session_proxy_browser.py',
    'session-proxy-extension/background.js', 'session-proxy-extension/popup.html',
    'session-proxy-extension/popup.js', 'session-proxy-extension/popup.css',
]


DOCS = ['docs/control-panel.md', 'docs/mcp.md', 'docs/browser-proxying.md']
REPOSITORY = 'https://github.com/mottersheadt/agent-web-gateway-dev-kit/blob/main/'


def package_markdown(name, data, sources, docs_root):
    """Keep bundled links local and point other repo links to the online docs."""
    destinations = {source.resolve(): target for target, source in sources.items()}

    def rewrite(match):
        url = urlsplit(match[2])
        if url.scheme or url.netloc or not url.path:
            return match[0]
        source = (sources[name].parent / unquote(url.path)).resolve()
        if source in destinations:
            target = os.path.relpath(destinations[source], Path(name).parent).replace(os.sep, '/')
        elif source.is_relative_to(docs_root) and source.is_file():
            target = REPOSITORY + source.relative_to(docs_root).as_posix()
        else:
            raise ValueError('Unresolved documentation link in ' + name + ': ' + url.path)
        return match[1] + urlunsplit(('', '', target, url.query, url.fragment)) + match[3]

    return re.sub(r'(\]\()([^\s)]+)(\))', rewrite, data.decode()).encode()


def build(root=None, output=None):
    root = Path(root or Path(__file__).resolve().parent).resolve()
    output = Path(output or root / 'dist/vgs-agent-web-gateway-control-panel-1.10.0.zip')
    output.parent.mkdir(parents=True, exist_ok=True)
    # A checkout stores guides in the repo's docs/. An extracted package already
    # includes them in its own docs/, so it can be rebuilt without the checkout.
    docs_root = root if all((root / name).is_file() for name in DOCS) else root.parents[1]
    check_files(root, FILES)
    check_files(docs_root, DOCS)
    sources = {name: root / name for name in FILES} | {name: docs_root / name for name in DOCS}
    prefix = 'vgs-agent-web-gateway-control-panel-1.10.0/'
    checksums = []
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, path in sources.items():
            data = path.read_bytes()
            if name.endswith('.md'):
                data = package_markdown(name, data, sources, docs_root)
            archive.writestr(prefix + name, data)
            checksums.append(hashlib.sha256(data).hexdigest() + '  ' + name)
        archive.writestr(prefix + 'SHA256SUMS', '\n'.join(checksums) + '\n')
    print(str(output))
    return output


if __name__ == '__main__':
    build()
