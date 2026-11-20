"""Narrow, separately authenticated MCP access to the helper's configured account."""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from awg_dev_api import ApiError
from session_operations import private_json

# These are the bridge's supported attributes. The API validates nested values.
RESOURCES = {
    'functions': {'prefix': 'FN', 'create': ['name', 'language', 'source', 'extension_point', 'inputs', 'previous_version'],
                  'required': ['name', 'source', 'extension_point'], 'update': []},
    'agent-gateway-adapters': {'prefix': 'AD', 'create': ['name', 'functions'],
                             'required': ['name', 'functions'], 'update': ['publish_at']},
    'agent-gateway-destinations': {'prefix': 'AGD', 'create': ['host_pattern', 'action'],
                                 'required': ['host_pattern', 'action'], 'update': ['action']},
    'agent-gateway-adapter-destinations': {'prefix': 'AX',
        'create': ['adapter', 'adapter_version', 'enabled', 'when', 'functions'],
        'required': ['adapter', 'when', 'functions'], 'update': ['adapter_version', 'enabled', 'when', 'functions']},
    'function-invocations': {'prefix': 'FI', 'create': [], 'required': [], 'update': []},
    'agent-gateway-registry': {'prefix': None, 'create': [], 'required': [], 'update': []},
}


def loopback_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/')):
        raise ValueError('Use an HTTP URL with address 127.0.0.1 and an explicit port.')
    return value.rstrip('/')


def runtime_lock(directory):
    """One helper owns each connection file; a stopped helper cannot delete another's token."""
    path = Path(directory) / '.helper.lock'
    stream = path.open('a+b')
    path.chmod(0o600)
    try:
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise ValueError('Another helper is using this MCP directory.') from None
    return stream


class GatewayBridge:
    def __init__(self, registry, environment, directory, allow_writes=False, repair=None):
        self.registry, self.environment = registry, environment
        self.directory, self.allow_writes = Path(directory), allow_writes
        self.lock = threading.Lock()
        self.repair = repair

    def execute(self, value):
        if not isinstance(value, dict):
            raise ValueError('Expected a JSON object.')
        with self.lock:
            catalog = self.registry.get(self.environment)
            if not catalog:
                raise ValueError('Connect an account in the panel for this environment first.')
            op = value.get('operation')
            if op == 'account':
                account = catalog.operations.account()
                return {key: account.get(key) for key in ('tenantId', 'connected', 'scopes', 'missingScopes')} | {
                    'environment': self.environment, 'writesEnabled': self.allow_writes}
            if value.get('tenantId') != catalog.tenant:
                raise ValueError('Tenant changed or does not match. Read gateway_account and select the intended account.')
            if op in ('diagnose_capture', 'repair_capture'):
                if not self.repair or self.environment != 'dev':
                    raise ValueError('Capture repair requires a configured DEV repair policy.')
                if op == 'repair_capture' and not self.allow_writes:
                    raise ValueError('Gateway writes are disabled.')
                return self.repair.run(value.get('captureId'), apply=op == 'repair_capture')
            resource, rid = value.get('resource'), value.get('id')
            spec = RESOURCES.get(resource)
            if not spec:
                raise ValueError('Unsupported gateway resource.')
            # IDs are opaque. Never accept path separators, queries or traversal.
            if rid is not None and (not spec['prefix'] or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]{1,127}', rid)):
                raise ValueError('Invalid resource ID.')
            path = '/' + resource + ('/' + rid if rid else '')
            if op == 'read':
                limit, offset = value.get('limit', 50), value.get('offset', 0)
                if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 100000:
                    raise ValueError('Invalid pagination.')
                return catalog.client.api('GET', path + (f'?limit={limit}&offset={offset}' if not rid else ''))
            if not self.allow_writes:
                raise ValueError('Gateway writes are disabled. Restart the helper with --mcp-write to enable them.')
            attrs = value.get('attributes')
            if not isinstance(attrs, dict):
                raise ValueError('Supply resource attributes as an object.')
            kind, method = resource, 'POST'
            if op == 'create' and not rid and spec['create']:
                if set(attrs) - set(spec['create']) or set(spec['required']) - set(attrs):
                    raise ValueError('Invalid attributes. Read gateway_schema before creating this resource.')
                if resource == 'agent-gateway-adapter-destinations' and 'enabled' not in attrs:
                    attrs = {**attrs, 'enabled': False}
            elif op == 'update' and rid and spec['update']:
                if not attrs or set(attrs) - set(spec['update']):
                    raise ValueError('Invalid update attributes. Read gateway_schema first.')
                method = 'PATCH'
            elif op == 'version' and rid and resource == 'agent-gateway-adapters' and set(attrs) == {'functions'}:
                pass
            elif op == 'dry_run' and rid and resource == 'functions':
                if set(attrs) - {'request', 'response', 'inputs', 'destination', 'session'}:
                    raise ValueError('Only route-function dry-run attributes are accepted.')
                fn = catalog.client.api('GET', path)['data']['attributes']
                point = fn.get('extension_point')
                if point not in ('route.request', 'route.response'):
                    raise ValueError('Only route.request and route.response functions can be dry-run here.')
                expected = 'request' if point == 'route.request' else 'response'
                if expected not in attrs or ('response' if expected == 'request' else 'request') in attrs:
                    raise ValueError('The fixture must match the function extension point.')
                kind, path = 'function-invocations', path + '/invocations'
            else:
                raise ValueError('Unsupported gateway operation.')
            request_id = value.get('requestId', '')
            if not re.fullmatch(r'[a-f0-9]{32}', request_id):
                raise ValueError('Use a unique 32-character lowercase hex request ID for each write.')
            fingerprint = hashlib.sha256(json.dumps([self.environment, catalog.tenant, method, path, attrs], sort_keys=True).encode()).hexdigest()
            journal = self.directory / 'operations' / (request_id + '.json')
            if journal.exists():
                prior = json.loads(journal.read_text())
                if prior['fingerprint'] != fingerprint:
                    raise ValueError('Request ID already belongs to a different operation.')
                return prior
            result = {'requestId': request_id, 'fingerprint': fingerprint, 'status': 'unconfirmed'}
            # Persist before sending. A timeout/restart must never repeat an uncertain write.
            private_json(journal, result)
            try:
                result['result'] = catalog.client.api(method, path, attrs, kind=kind)
                result['status'] = 'completed'
            except ApiError as error:
                result.update(status='rejected' if 400 <= error.status < 500 else 'unconfirmed', httpStatus=error.status)
            except Exception:
                pass
            private_json(journal, result)
            return result


class McpGatewayServer:
    def __init__(self, bridge):
        self.bridge = bridge
        token = secrets.token_urlsafe(32)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass

            def do_POST(self):
                if (self.path != '/gateway' or self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}'
                        or self.headers.get('Origin') is not None
                        or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)):
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 2500000 or self.headers.get('Content-Type') != 'application/json':
                        raise ValueError('Invalid request size or content type.')
                    data = bridge.execute(json.loads(self.rfile.read(length)))
                    status = 200
                except ValueError as error:
                    status, data = 400, {'error': str(error)}
                except ApiError as error:
                    status, data = 502, {'error': 'Gateway request rejected.', 'httpStatus': error.status}
                except Exception:
                    status, data = 503, {'error': 'Gateway unavailable. Check the helper and account.'}
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-store')
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
