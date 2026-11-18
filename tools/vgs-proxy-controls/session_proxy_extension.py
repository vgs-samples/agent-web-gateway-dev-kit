"""Build the private, per-session proxy controls extension used by CloakBrowser."""

import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def write_extension(directory: Path, pac_url: str, credentials: dict,
                    session_proxy: dict, egress_proxy: dict | None = None, *,
                    session_id: str | None = None, expires_at: str | None = None,
                    catalog: dict | None = None) -> None:
    pac = urlsplit(pac_url)
    if pac.scheme not in ('http', 'https') or not pac.hostname or pac.username or pac.password:
        raise ValueError('Invalid PAC source URL')
    if session_id is not None and (not session_id.startswith('RS') or not session_id.isascii() or not session_id.isalnum()):
        raise ValueError('Invalid reveal session ID')
    # Only non-secret display metadata belongs in the page; never the signed query.
    session_info = {'sessionId': session_id, 'pacSource': urlunsplit((pac.scheme, pac.netloc, pac.path, '', ''))}
    def endpoint(proxy):
        if proxy is None:
            return None
        scheme, host, port = proxy.get('scheme'), proxy.get('host'), proxy.get('port')
        if (scheme not in ('http', 'https') or not isinstance(host, str) or not host
                or any(c in host for c in '/@?#: ') or not isinstance(port, int)
                or isinstance(port, bool) or not 1 <= port <= 65535):
            raise ValueError('Invalid proxy endpoint')
        return {'scheme': scheme, 'host': host.lower(), 'port': port}

    proxies = {'session': endpoint(session_proxy), 'egress': endpoint(egress_proxy)}
    if proxies['session'] is None:
        raise ValueError('Reveal session proxy is required')
    if proxies['session'] == proxies['egress']:
        raise ValueError('Reveal session and egress proxies must be distinct')
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    source = Path(__file__).resolve().parent / "session-proxy-extension"
    manifest = {
        "manifest_version": 3,
        "name": "VGS Proxy Controls",
        "version": "1.3.0",
        "permissions": ["proxy", "webRequest", "webRequestAuthProvider", "storage", "browsingData"],
        "host_permissions": ["<all_urls>"],
        "background": {"service_worker": "background.js"},
        "action": {"default_title": "VGS Proxy Controls", "default_popup": "popup.html"},
    }
    files = {"manifest.json": json.dumps(manifest, indent=2) + "\n"}
    files['session-info.js'] = 'globalThis.SESSION_INFO = Object.freeze(' + json.dumps(session_info) + ');\n'
    initial = {**session_info, 'expiresAt': expires_at, 'pacUrl': pac_url,
               'proxies': proxies, 'credentials': {key.lower(): value for key, value in credentials.items()}}
    files['background.js'] = ('const INITIAL_SESSION = ' + json.dumps(initial) + ';\n'
                              + 'const CATALOG = ' + json.dumps(catalog) + ';\n'
                              + (source / 'background.js').read_text())
    for name in ("popup.html", "popup.css", "popup.js"):
        files[name] = (source / name).read_text()
    for name, text in files.items():
        path = directory / name
        path.write_text(text)
        path.chmod(0o600)
