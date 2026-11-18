"""Environment-scoped session companion. Account credentials remain in this local process."""
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
from session_operations import Operations, private_json
from account_files import AccountFileError, discover_tenants
from credential_picker import CredentialFilePicker
from environments import ENVIRONMENTS, EnvironmentClient, domains


def alive(attrs):
    return attrs.get('state', 'active') == 'active' and datetime.fromisoformat(attrs['expires_at'].replace('Z', '+00:00')) > datetime.now(timezone.utc)


def session_config(path, ca_bundle, environment="dev", tenant=TENANT):
    endpoints = domains(environment, tenant)
    document = json.loads(path.read_text())
    sid, a = document['data']['id'], document['data']['attributes']
    if not re.fullmatch(r'RS[A-Za-z0-9]+', sid):
        raise ValueError('Invalid session ID')
    if a['proxy']['ca_bundle'].strip() != ca_bundle.strip():
        raise ValueError('Requires a new browser: different session CA')
    pac = urlsplit(a['proxy']['pac_url'])
    vgs = urlsplit(a['proxy']['url'])
    if (pac.scheme != 'https' or pac.netloc != urlsplit(endpoints['api']).netloc
            or pac.path != f'/reveal-sessions/{sid}.pac'
            or vgs.scheme != 'https' or vgs.hostname != urlsplit(endpoints['proxy']).hostname
            or vgs.port != urlsplit(endpoints['proxy']).port or not vgs.username or not vgs.password):
        raise ValueError('Session does not match this environment and tenant')
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
            saved = next((c for c in candidates if all(c.get(k) == egress.get(k) for k in ('scheme', 'hostname', 'port', 'username'))
                          and isinstance(c.get('password'), str) and c['password'] and c['password'] != '********'), None)
            if saved is None:
                raise ValueError('Missing saved egress credentials')
            credentials[f"{egress['hostname']}:{egress['port']}"] = {'username': saved['username'], 'password': saved['password']}
    return {'sessionId': sid, 'environment': environment, 'tenantId': tenant, 'expiresAt': a['expires_at'], 'pacUrl': a['proxy']['pac_url'],
            'pacSource': urlunsplit((pac.scheme, pac.netloc, pac.path, '', '')),
            'proxies': proxies, 'credentials': credentials}


class Catalog:
    def __init__(self, session_path, client=None, sessions_directory=None, *, ca_bundle=None, use_settings=True, **operation_options):
        self.path = Path(session_path) if session_path else None
        self.sessions_directory = Path(sessions_directory or KIT / ".state-dev/sessions")
        self.initial = json.loads(self.path.read_text()) if self.path else None
        self.ca = ca_bundle if ca_bundle is not None else self.initial['data']['attributes']['proxy']['ca_bundle']
        self.client = client or Client()
        self.environment = getattr(self.client, "environment", "dev")
        self.tenant = getattr(self.client, "tenant", TENANT)
        self.lock = threading.Lock()
        settings = KIT / '.proxy-controls.json'
        configured = json.loads(settings.read_text()) if use_settings and settings.exists() else {}
        configured = {k: v for k, v in configured.items() if k in ('egress_file', 'tokenizer_socket', 'capture_profile', 'slot_file')}
        configured.update({k: v for k, v in operation_options.items() if v is not None})
        self.operations = Operations(self.client, self.sessions_directory, **configured)

    def saved(self, sid):
        if self.initial and self.initial['data']['id'] == sid:
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
                    session_config(self.saved(sid), self.ca, self.environment, self.tenant)
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
        config = session_config(self.saved(sid), self.ca, self.environment, self.tenant)
        config['expiresAt'] = a['expires_at']
        return config

    def pac(self, sid):
        config = session_config(self.saved(sid), self.ca, self.environment, self.tenant)
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


class CatalogRegistry:
    def __init__(self, initial, profiles=None):
        self.initial = initial
        self.profile_file = Path(initial.sessions_directory).parent / ".proxy-controls-accounts.json" if hasattr(initial, "sessions_directory") else None
        self.saved_profiles = {}
        self.default = getattr(initial, 'environment', 'dev')
        self.catalogs = {self.default: initial}
        self.profiles = profiles or {}
        self.lock = threading.Lock()
        directories = {str(Path(initial.sessions_directory).resolve())} if hasattr(initial, 'sessions_directory') else set()
        for environment, profile in self.profiles.items():
            if environment not in ENVIRONMENTS or environment == self.default:
                raise ValueError('Profiles must describe other environments')
            if set(profile) - {'credentials_file', 'sessions_directory', 'tokenizer_socket', 'egress_file'}:
                raise ValueError('Unknown profile fields')
            directory = str(Path(profile['sessions_directory']).resolve())
            if directory in directories: raise ValueError('Environments require separate session directories')
            directories.add(directory)

        if self.profile_file and self.profile_file.exists():
            stored = json.loads(self.profile_file.read_text())
            for environment, profile in stored.items():
                if environment not in ENVIRONMENTS or not isinstance(profile, dict) or set(profile) - {'credentials_file','tenant_id','sessions_directory','tokenizer_socket','egress_file'}:
                    raise ValueError('Invalid saved account profile')
            self.saved_profiles = stored
            self.profiles = {**self.profiles, **stored}
            for environment in stored: self.catalogs.pop(environment, None)

    def get(self, environment):
        if environment not in ENVIRONMENTS: raise ValueError('Unknown environment')
        with self.lock:
            if environment not in self.catalogs and environment in self.profiles:
                profile = self.profiles[environment]
                initial = self.initial
                self.catalogs[environment] = Catalog(None, EnvironmentClient(profile['credentials_file'], environment, profile.get('tenant_id')),
                    profile['sessions_directory'], ca_bundle=initial.ca, use_settings=False,
                    egress_file=profile.get('egress_file'), tokenizer_socket=profile.get('tokenizer_socket'),
                    capture_profile=initial.operations.capture_profile, slot_file=initial.operations.slot_file)
            return self.catalogs.get(environment)

    def account(self, environment):
        try:
            catalog = self.get(environment)
        except (OSError, ValueError, KeyError):
            catalog = None
        if catalog:
            result = catalog.operations.account()
            return {'configured': True, 'environment': environment, 'domains': domains(environment, result.get('tenantId')), 'credentialsFile': getattr(getattr(catalog, 'client', None), 'credentials_file', None), **result}
        return {'environment': environment, 'tenantId': None, 'configured': False, 'connected': False,
                'domains': domains(environment), 'scopes': [], 'creationAvailable': False, 'tokenizerReady': False}

    def connect(self, environment, options):
        if environment not in ENVIRONMENTS or not isinstance(options, dict) or set(options) - {'credentialsFile', 'tenantId'}:
            raise AccountFileError('Choose an environment and a local credentials file.')
        client = EnvironmentClient(options.get('credentialsFile'), environment, allow_unresolved=True)
        choices = discover_tenants(client)
        selected = options.get('tenantId')
        if selected:
            if selected not in [row['tenantId'] for row in choices]:
                raise AccountFileError('Choose a tenant returned for this service account.')
        elif len(choices) == 1:
            selected = choices[0]['tenantId']
        else:
            return {'selectionRequired':True, 'tenants':choices}
        client.tenant = client.env['VGS_TENANT'] = selected
        with self.lock:
            old = self.catalogs.get(environment)
            if old and any(job.get('status') == 'running' for job in old.operations.jobs.values()):
                raise AccountFileError('Wait for the current session or card operation to finish.')
            if old and old.tenant == client.tenant:
                directory, session_path = old.sessions_directory, old.path
                egress_file, tokenizer_socket = old.operations.egress_file, old.operations.tokenizer_socket
            else:
                if not self.profile_file: raise AccountFileError('The helper needs a local sessions directory before connecting an account.')
                directory = self.profile_file.parent / 'control-panel-sessions' / environment / client.tenant
                session_path, egress_file, tokenizer_socket = None, None, None
            candidate = Catalog(session_path, client, directory, ca_bundle=self.initial.ca, use_settings=False,
                egress_file=egress_file, tokenizer_socket=tokenizer_socket,
                capture_profile=self.initial.operations.capture_profile, slot_file=self.initial.operations.slot_file)
            account = candidate.operations.account()
            if not account.get('connected'):
                raise AccountFileError('Authentication failed. Check the file and selected environment.')
            try:
                client.api('GET', '/reveal-sessions?state=active&limit=1')
            except Exception:
                raise AccountFileError('This account cannot read sessions for that tenant. Check the tenant ID and reveal-sessions:read permission.') from None
            profile = {'credentials_file':client.credentials_file, 'tenant_id':client.tenant, 'sessions_directory':str(directory),
                       **({'egress_file':str(egress_file)} if egress_file else {}),
                       **({'tokenizer_socket':str(tokenizer_socket)} if tokenizer_socket else {})}
            saved = {**self.saved_profiles, environment:profile}
            if self.profile_file: private_json(self.profile_file, saved)
            self.saved_profiles, self.profiles = saved, {**self.profiles, environment:profile}
            self.catalogs[environment] = candidate
        return self.account(environment)


class CatalogServer:
    def __init__(self, session_path, catalog=None, profiles=None, file_picker=None):
        initial = catalog or Catalog(session_path)
        if profiles is None:
            settings = KIT / ".proxy-controls.json"
            profiles = json.loads(settings.read_text()).get("environments", {}) if settings.exists() else {}
        registry = CatalogRegistry(initial, profiles)
        self.file_picker = picker = file_picker or CredentialFilePicker()
        token = secrets.token_urlsafe(32)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.handle_request(False)

            def do_POST(self):
                self.handle_request(True)

            def handle_request(self, write):
                if (self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}'
                        or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)
                        or (self.headers.get('Origin') and not re.fullmatch(r'chrome-extension://[a-p]{32}', self.headers['Origin']))):
                    self.send_error(403)
                    return
                try:
                    route, environment = self.path, registry.default
                    if route.startswith('/environments/'):
                        match = re.fullmatch(r'/environments/(dev|sandbox|live)(/.*)', route)
                        if not match: raise ValueError('Unknown environment')
                        environment, route = match.groups()
                    catalog = registry.get(environment) if route not in ('/account', '/credentials') and not route.startswith('/credentials/picker') else None
                    if route == '/account' and not write:
                        data = registry.account(environment)
                    elif route == '/credentials' and write:
                        length = int(self.headers.get('Content-Length', '0'))
                        if not 0 < length <= 8192 or self.headers.get('Content-Type') != 'application/json':
                            raise AccountFileError('Choose a local credentials file.')
                        data = registry.connect(environment, json.loads(self.rfile.read(length)))
                    elif route == '/credentials/picker' and write:
                        length = int(self.headers.get('Content-Length', '0'))
                        if not 0 < length <= 32 or self.headers.get('Content-Type') != 'application/json' or json.loads(self.rfile.read(length)) != {}:
                            raise AccountFileError('Choose the file with the Browse button.')
                        data = picker.start(environment)
                    elif not write and (match := re.fullmatch(r'/credentials/picker/([a-f0-9-]{36})', route)):
                        data = picker.status(environment, match[1])
                    elif not catalog:
                        raise ValueError('Configure this environment in the local helper first')
                    elif write:
                        length = int(self.headers.get('Content-Length', '0'))
                        if route not in ('/sessions', '/cards', '/collect-token') or not 0 < length <= 24576 or self.headers.get('Content-Type') != 'application/json':
                            self.send_error(400)
                            return
                        value = json.loads(self.rfile.read(length))
                        if route == '/collect-token': data = catalog.operations.collect_token(value)
                        else: data = catalog.operations.create_card(value) if route == '/cards' else catalog.operations.create(value)
                    elif route == '/adapters':
                        data = catalog.operations.adapters()
                    elif match := re.fullmatch(r'/operations/([a-f0-9-]{36})', route):
                        data = catalog.operations.status(match[1])
                    else:
                        with catalog.lock:
                            if route == '/sessions':
                                data = catalog.listing()
                            elif match := re.fullmatch(r'/sessions/(RS[A-Za-z0-9]+)/(config|pac)', route):
                                data = catalog.configuration(match[1]) if match[2] == 'config' else catalog.pac(match[1])
                            else:
                                self.send_error(404)
                                return
                    status = 200
                except AccountFileError as error:
                    status, data = 400, {'accountError': str(error)}
                except ValueError:
                    status, data = 400, {'error': 'Invalid session input. Check aliases, hostnames and local configuration.'}
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
        self.config = {'url': f'http://127.0.0.1:{self.server.server_port}', 'token': token, 'environments': True, 'environment': registry.default}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.file_picker.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--owner-pid', type=int, required=True)
    parser.add_argument('--egress-profile', type=Path)
    parser.add_argument('--tokenizer-socket', type=Path)
    parser.add_argument('--capture-profile', type=Path)
    parser.add_argument('--slot-file', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    server = CatalogServer(args.session, Catalog(args.session, egress_file=args.egress_profile, tokenizer_socket=args.tokenizer_socket, capture_profile=args.capture_profile, slot_file=args.slot_file))
    args.output.write_text(json.dumps(server.config))
    args.output.chmod(0o600)
    print('Local session catalog ready', flush=True)
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
