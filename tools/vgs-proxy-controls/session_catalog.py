"""Read-only DEV session catalog. Account credentials never enter the extension."""
import argparse
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import Request

from awg_dev_api import API, KIT, TENANT, Client


def alive(attrs):
    return attrs.get('state', 'active') == 'active' and datetime.fromisoformat(attrs['expires_at'].replace('Z', '+00:00')) > datetime.now(timezone.utc)


def session_config(path, ca_bundle):
    document = json.loads(path.read_text())
    sid, a = document['data']['id'], document['data']['attributes']
    if not re.fullmatch(r'RS[A-Za-z0-9]+', sid):
        raise ValueError('Invalid session ID')
    if a['proxy']['ca_bundle'].strip() != ca_bundle.strip():
        raise ValueError('Requires a new browser: different session CA')
    pac = urlsplit(a['proxy']['pac_url'])
    vgs = urlsplit(a['proxy']['url'])
    if (pac.scheme != 'https' or pac.netloc != 'sandbox.vgsapi.io'
            or pac.path != f'/reveal-sessions/{sid}.pac'
            or vgs.scheme != 'https' or vgs.hostname != TENANT + '.sandbox.verygoodproxy.io'
            or vgs.port != 3443 or not vgs.username or not vgs.password):
        raise ValueError('Not a supported DEV session')
    credentials = {f'{vgs.hostname}:{vgs.port}': {'username': unquote(vgs.username), 'password': unquote(vgs.password)}}
    proxies = {'session': {'scheme': vgs.scheme, 'host': vgs.hostname, 'port': vgs.port}, 'egress': None}
    egress = a.get('egress_proxy_settings') or {}
    if egress.get('type') == 'custom':
        if egress.get('scheme') not in ('http', 'https') or not egress.get('hostname') or not isinstance(egress.get('port'), int):
            raise ValueError('Unsupported egress endpoint')
        proxies['egress'] = {'scheme': egress['scheme'], 'host': egress['hostname'], 'port': egress['port']}
        if egress.get('has_password') or egress.get('username'):
            candidates = []
            request = path.with_suffix('.request.json')
            if request.is_file():
                candidates.append(json.loads(request.read_text())['data']['attributes'].get('egress_proxy_settings') or {})
            profile = KIT / '.state-dev/amazingfriends/custom-domain/proxy.json'
            if profile.is_file():
                candidates.append(json.loads(profile.read_text()))
            saved = next((c for c in candidates if all(c.get(k) == egress.get(k) for k in ('scheme', 'hostname', 'port', 'username'))
                          and isinstance(c.get('password'), str) and c['password'] and c['password'] != '********'), None)
            if saved is None:
                raise ValueError('Missing saved egress credentials')
            credentials[f"{egress['hostname']}:{egress['port']}"] = {'username': saved['username'], 'password': saved['password']}
    return {'sessionId': sid, 'expiresAt': a['expires_at'], 'pacUrl': a['proxy']['pac_url'],
            'pacSource': urlunsplit((pac.scheme, pac.netloc, pac.path, '', '')),
            'proxies': proxies, 'credentials': credentials}


class Catalog:
    def __init__(self, session_path, client=None, sessions_directory=None):
        self.path = Path(session_path)
        self.sessions_directory = Path(sessions_directory or KIT / ".state-dev/sessions")
        self.initial = json.loads(self.path.read_text())
        self.ca = self.initial['data']['attributes']['proxy']['ca_bundle']
        self.client = client or Client()
        self.lock = threading.Lock()

    def saved(self, sid):
        if self.initial['data']['id'] == sid:
            return self.path
        return self.sessions_directory / (sid + '.json')

    def listing(self):
        rows, offset = [], 0
        while True:
            result = self.client.api('GET', f'/reveal-sessions?state=active&limit=100&offset={offset}')
            data = result['data']
            for item in data:
                a, sid = item['attributes'], item['id']
                reason = None
                try:
                    if not alive(a):
                        raise ValueError('Expired or revoked')
                    session_config(self.saved(sid), self.ca)
                except FileNotFoundError:
                    reason = 'Proxy credentials not saved on this computer'
                except ValueError as e:
                    reason = str(e) if str(e) in ('Requires a new browser: different session CA', 'Missing saved egress credentials', 'Expired or revoked') else 'Saved session configuration unavailable'
                except (KeyError, TypeError):
                    reason = 'Saved session configuration unavailable'
                rows.append({'sessionId': sid, 'expiresAt': a.get('expires_at'), 'available': reason is None,
                             'reason': reason, 'hosts': a.get('allowed_hosts', [])})
            offset += len(data)
            if not data or offset >= result.get('meta', {}).get('total_elements', offset):
                break
            if offset >= 10000:
                raise ValueError('Session list limit exceeded')
        return {'sessions': rows, 'checkedAt': datetime.now(timezone.utc).isoformat()}

    def configuration(self, sid):
        a = self.client.api('GET', '/reveal-sessions/' + sid)['data']['attributes']
        if not alive(a):
            raise ValueError('Session expired or revoked')
        config = session_config(self.saved(sid), self.ca)
        config['expiresAt'] = a['expires_at']
        return config

    def pac(self, sid):
        config = session_config(self.saved(sid), self.ca)
        with self.client.opener.open(Request(config['pacUrl']), timeout=15) as response:
            body = response.read(65537).decode('utf-8')
        if len(body.encode()) > 65536 or 'FindProxyForURL' not in body:
            raise ValueError('Invalid PAC response')
        # PAC scripts have routes, not proxy secrets. Do not return an error body.
        for credentials in config['credentials'].values():
            for value in credentials.values():
                if value and value in body:
                    raise ValueError('PAC contains authentication data')
        return {'pacScript': body, 'fetchedAt': datetime.now(timezone.utc).isoformat()}


class CatalogServer:
    def __init__(self, session_path, catalog=None):
        catalog = catalog or Catalog(session_path)
        token = secrets.token_urlsafe(32)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if (self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}'
                        or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)
                        or (self.headers.get('Origin') and not re.fullmatch(r'chrome-extension://[a-p]{32}', self.headers['Origin']))):
                    self.send_error(403)
                    return
                try:
                    with catalog.lock:
                        if self.path == '/sessions':
                            data = catalog.listing()
                        elif match := re.fullmatch(r'/sessions/(RS[A-Za-z0-9]+)/(config|pac)', self.path):
                            data = catalog.configuration(match[1]) if match[2] == 'config' else catalog.pac(match[1])
                        else:
                            self.send_error(404)
                            return
                    status = 200
                except Exception:
                    status, data = 503, {'error': 'Session data unavailable. Refresh or check the local session files.'}
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.config = {'url': f'http://127.0.0.1:{self.server.server_port}', 'token': token}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--owner-pid', type=int, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    server = CatalogServer(args.session)
    args.output.write_text(json.dumps(server.config))
    args.output.chmod(0o600)
    print('Local DEV session catalog ready', flush=True)
    try:
        while True:
            time.sleep(5)
            try:
                os.kill(args.owner_pid, 0)
            except ProcessLookupError:
                break
    finally:
        server.close()
        args.output.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
