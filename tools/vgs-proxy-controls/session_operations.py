"""Bounded environment-scoped account operations. No raw card fields cross the browser boundary."""
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat
import threading
from datetime import datetime, timezone

from awg_dev_api import TENANT, ApiError
from environments import domains
from session_form import validate_dashboard_options, valid_alias

REQUIRED_SCOPES = ('cards:create', 'aliases:write', 'reveal-sessions:write', 'reveal-sessions:read')


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def load_egress(path):
    if not path:
        return None
    a = json.loads(Path(path).read_text())
    if (a.get('scheme') not in ('http', 'https') or not re.fullmatch(r'[A-Za-z0-9.-]+', a.get('hostname', ''))
            or type(a.get('port')) is not int or not 1 <= a['port'] <= 65535
            or not a.get('username') or not a.get('password')):
        raise ValueError('Invalid egress profile')
    return {k: a[k] for k in ('scheme', 'hostname', 'port', 'username', 'password')} | {'type': 'custom'}


def validated_options(value, environment="dev"):
    if isinstance(value, dict) and "source" not in value:
        return validate_dashboard_options(value, environment)
    if not isinstance(value, dict) or set(value) - {'requestId', 'source', 'allowedHosts', 'adapter', 'card'}:
        raise ValueError('Unsupported session fields')
    if not isinstance(value.get('requestId'), str) or not re.fullmatch(r'[a-f0-9-]{36}', value['requestId']):
        raise ValueError('Invalid request ID')
    if value.get('source') not in ('tokenizer', 'aliases'):
        raise ValueError('Choose a card source')
    hosts = value.get('allowedHosts', [])
    if not isinstance(hosts, list) or len(hosts) > 20:
        raise ValueError('Use up to 20 exact hostnames')
    result = []
    for host in hosts:
        if not isinstance(host, str): raise ValueError('Invalid hostname')
        host = host.lower().rstrip('.')
        if len(host) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]*', host):
            raise ValueError('Use exact hostnames without a scheme, port or wildcard')
        try: ipaddress.ip_address(host)
        except ValueError: pass
        else: raise ValueError('Use hostnames, not IP addresses')
        if host not in result: result.append(host)
    adapter = value.get('adapter', '')
    if not isinstance(adapter, str) or adapter and not re.fullmatch(r'AD[A-Za-z0-9]+', adapter):
        raise ValueError('Use an adapter ID beginning AD, or leave it blank')
    card = None
    if value['source'] == 'aliases':
        card = validate_card(value.get('card'), environment)
    elif value.get('card') is not None:
        raise ValueError('Private tokenizer does not accept browser card data')
    return {'requestId': value['requestId'], 'source': value['source'], 'allowedHosts': result, 'adapter': adapter, 'card': card}


def validate_card(card, environment="dev"):
    if not isinstance(card, dict) or set(card) != {'number', 'cvc'}:
        raise ValueError('Both PAN and CVC aliases are required')
    out = {}
    for key, storage in [('number', 'PERSISTENT'), ('cvc', 'VOLATILE')]:
        a = card[key]
        if not isinstance(a, dict) or set(a) - {'alias', 'bin', 'length', 'storage'}:
            raise ValueError('Unsupported alias fields')
        # Browser form accepts unmistakable aliases for this environment, never raw/FPE cards.
        if not valid_alias(a.get('alias'), environment):
            raise ValueError('Use an alias for the selected environment, never a card number or CVC')
        if a.get('storage') != storage:
            raise ValueError('PAN must use PERSISTENT and CVC VOLATILE storage')
        if type(a.get('length')) is not int or a['length'] not in (range(13, 20) if key == 'number' else (3, 4)):
            raise ValueError('Invalid card or CVC length')
        out[key] = {'alias': a['alias'], 'storage': storage, 'length': a['length'],
                    'format': 'card_number' if key == 'number' else 'card_cvc'}
        if key == 'number':
            if not isinstance(a.get('bin'), str) or not re.fullmatch(r'\d{6}(?:\d{2})?', a['bin']): raise ValueError('BIN must contain 6 or 8 digits')
            out[key]['bin'] = a['bin']
    if out['number']['alias'] == out['cvc']['alias']: raise ValueError('PAN and CVC aliases must differ')
    return out


class Operations:
    def __init__(self, client, directory, *, egress_file=None, tokenizer_socket=None, capture_profile=None, slot_file=None):
        self.client, self.directory = client, Path(directory)
        self.environment = getattr(client, "environment", "dev")
        self.tenant = getattr(client, "tenant", TENANT)
        self.egress_file, self.tokenizer_socket = egress_file, tokenizer_socket
        self.capture_profile, self.slot_file = capture_profile, slot_file
        self.jobs = {}
        self.lock = threading.Lock()

    def account(self):
        granted, connected = set(), False
        try:
            token = self.client.token()
            claims = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))
            granted.update(claims.get('scope', '').split())
            for resource in claims.get('resource_access', {}).values():
                granted.update(resource.get('roles', []))
            connected = True
        except Exception: pass
        egress = load_egress(self.egress_file)
        sensitive = None
        if self.capture_profile:
            try:
                pref = json.loads((Path(self.capture_profile) / 'Default/Preferences').read_text())
                sensitive = pref.get('devtools', {}).get('synced_preferences_sync_disabled', {}).get('network.show-options-to-generate-har-with-sensitive-data') == 'true' or pref.get('devtools', {}).get('synced_preferences', {}).get('network.show-options-to-generate-har-with-sensitive-data') == 'true'
            except (OSError, ValueError): pass
        return {'tenantId': self.tenant, 'environment': self.environment, 'configured': True, 'domains': domains(self.environment, self.tenant), 'connected': connected,
                'scopes': [{'name': name, 'granted': name in granted} for name in REQUIRED_SCOPES],
                'cardsWriteGranted': 'cards:write' in granted,
                'tokenizerReady': bool(self.tokenizer_socket and Path(self.tokenizer_socket).exists()),
                'egress': f"{egress['scheme']}://{egress['hostname']}:{egress['port']}" if egress else None,
                'creationAvailable': bool(connected and 'reveal-sessions:write' in granted),
                'egressConfig': {k: egress[k] for k in ('scheme', 'hostname', 'port')} if egress else None,
                'egressLocked': bool(egress),
                'sensitiveHarEnabled': sensitive}

    def session_egress(self, options):
        saved = load_egress(self.egress_file)
        mode = options.get('egressMode', 'profile')
        if saved:
            if mode != 'profile': raise ValueError('Use the egress profile loaded by this app')
            return saved
        if mode == 'profile': raise ValueError('Configure an egress profile or choose an egress type')
        return options.get('egress') if mode == 'custom' else None

    def collect_token(self, value):
        # A transient token for Collect, never a credential-file export or journal entry.
        if not isinstance(value, dict) or set(value) != {'tenantId','method'} or value['tenantId'] != self.tenant or value['method'] not in ('aliases','card'):
            raise ValueError('The selected account changed')
        account = self.account()
        granted = {s['name'] for s in account['scopes'] if s['granted']}
        permitted = 'aliases:write' in granted if value['method'] == 'aliases' else account['cardsWriteGranted'] or 'cards:create' in granted
        if not account['connected'] or not permitted:
            raise ValueError('Collect requires alias or card creation permission')
        return {'accessToken': self.client.token(), 'tenantId': self.tenant, 'environment': self.environment, 'method':value['method']}

    def adapters(self):
        response = self.client.api('GET', '/agent-gateway-adapters')
        rows = response.get('data')
        if not isinstance(rows, list): raise ValueError('Invalid adapter list')
        result = []
        for row in rows:
            attrs, sid = row.get('attributes', {}), row.get('id', '')
            if attrs.get('owner') != 'tenant' and not (attrs.get('owner') == 'vgs' and attrs.get('published_version')): continue
            if not re.fullmatch(r'AD[A-Za-z0-9]+', sid): continue
            result.append({'id':sid, 'name':str(attrs.get('name', sid)), 'owner':attrs['owner']})
        return {'adapters': sorted(result, key=lambda a:(a['name'].casefold(),a['id']))}

    def create_card(self, value):
        if not isinstance(value, dict) or set(value) != {'requestId'}: raise ValueError('Card input stays in the private tokenizer')
        rid = value['requestId']
        path = self.job_path(rid)
        fingerprint = hashlib.sha256(b'private-tokenizer-card').hexdigest()
        with self.lock:
            if path.exists():
                if json.loads(path.read_text()).get('fingerprint') != fingerprint: raise ValueError('Request ID already used')
                return self.status(rid)
            record = {'requestId':rid, 'status':'running', 'fingerprint':fingerprint}
            private_json(path,record); self.jobs[rid]=record
            threading.Thread(target=self._create_card,args=(record,),daemon=True).start()
            return {'requestId':rid,'status':'running'}

    def _create_card(self, record):
        slot = None
        started = False
        try:
            if self.slot_file:
                import fcntl
                slot=open(self.slot_file)
                try: fcntl.flock(slot,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError: raise ValueError('Another test owns the browser/session slot') from None
            started = True
            card=self.fresh_card()
            record.update(status='complete', aliases=list(card.values()))
        except Exception:
            record.update(status='unknown' if started else 'failed', error='Card aliases were not confirmed. Check the private tokenizer before trying again.')
        finally:
            if slot: slot.close()
            private_json(self.job_path(record['requestId']),record)

    def fresh_card(self):
        if not self.tokenizer_socket: raise ValueError('Start the private card tokenizer first')
        path = Path(self.tokenizer_socket)
        mode = path.stat().st_mode
        if not stat.S_ISSOCK(mode) or mode & 0o077 or path.stat().st_uid != os.getuid():
            raise ValueError('Private tokenizer socket is unavailable')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(90)
            client.connect(str(path))
            client.sendall(json.dumps({'operation': 'tokenize', 'environment': self.environment, 'tenant': self.tenant}).encode() + b'\n')
            with client.makefile('rb') as stream: result = json.loads(stream.readline(65536))
        if not result.get('ok'): raise ValueError('Private card tokenization failed; no session was created')
        fixture = result['fixture']
        if fixture.get('tenant') != self.tenant or fixture.get('environment') != self.environment:
            raise ValueError('Card tokenizer tenant mismatch')
        return validate_card({k: fixture['card'][k] for k in ('number', 'cvc')}, self.environment)

    def job_path(self, rid):
        if not re.fullmatch(r'[a-f0-9-]{36}', rid): raise ValueError('Invalid request ID')
        return self.directory / '.proxy-control-operations' / (rid + '.json')

    def create(self, options):
        # Validate before recording a job or making any remote mutation.
        options = validated_options(options, self.environment)
        self.session_egress(options)  # Validate the selected route before accepting a job.
        rid, fingerprint = options['requestId'], hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()
        with self.lock:
            path = self.job_path(rid)
            if path.exists():
                old = json.loads(path.read_text())
                if old['fingerprint'] != fingerprint: raise ValueError('Request ID was already used with different inputs')
                return self.status(rid)
            record = {'requestId': rid, 'status': 'running', 'fingerprint': fingerprint}
            private_json(path, record)
            self.jobs[rid] = record
            threading.Thread(target=self._create, args=(options, record), daemon=True).start()
            return {'requestId': rid, 'status': 'running'}

    def _create(self, options, record):
        submitted, slot = False, None
        try:
            if self.slot_file:
                import fcntl
                slot = open(self.slot_file)
                try: fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: raise ValueError('Another test owns the browser/session slot; try again after it finishes') from None
            egress = self.session_egress(options)
            attrs = {'egress_proxy_settings': egress} if egress else {}
            if options['allowedHosts']: attrs['allowed_hosts'] = options['allowedHosts']
            if options['source'] == 'dashboard':
                attrs['aliases'] = options['aliases']
                if options['allowedClientCidrs']: attrs['allowed_client_cidrs'] = options['allowedClientCidrs']
                if options['adapter']:
                    if not any(row['id'] == options['adapter'] for row in self.adapters()['adapters']):
                        raise ValueError('The selected adapter is no longer available; choose another or Automatic')
                    attrs['adapter'] = options['adapter']
            else:
                card = self.fresh_card() if options['source'] == 'tokenizer' else validate_card({k: {p: v for p, v in a.items() if p != 'format'} for k, a in options['card'].items()}, self.environment)
                if options['adapter']: attrs.update(adapter=options['adapter'], cards=[card])
                else: attrs['aliases'] = list(card.values())
            # Journal before POST: retrying an interrupted request never duplicates it.
            submitted = True
            response = self.client.api('POST', '/reveal-sessions', attrs, 'reveal-sessions', accepted=(201,))
            sid = response['data']['id']
            if not re.fullmatch(r'RS[A-Za-z0-9]+', sid): raise RuntimeError('Invalid session response')
            private_json(self.directory / (sid + '.request.json'), {'data': {'type': 'reveal-sessions', 'attributes': attrs}})
            private_json(self.directory / (sid + '.json'), response)
            tokens = [{k: token[k] for k in ('format', 'value')} for token in response['data']['attributes'].get('tokens', [])]
            record.update(status='complete', sessionId=sid, tokens=tokens)
        except ApiError as error:
            if 400 <= error.status < 500:
                record.update(status='failed', error=f'VGS rejected session creation (HTTP {error.status}). Check account permissions and fresh aliases. No session was created.')
            else:
                record.update(status='unknown', error='VGS did not confirm creation. Refresh sessions before trying again; this request will not be resubmitted.')
        except ValueError as error:
            record.update(status='failed' if not submitted else 'unknown', error=str(error) if not submitted else 'Creation result is uncertain. Refresh sessions before trying again; this request will not be resubmitted.')
        except Exception:
            record.update(status='unknown' if submitted else 'failed', error='Creation result is uncertain. Refresh sessions before trying again; this request will not be resubmitted.' if submitted else 'Tokenization or configuration unavailable. No reveal session was created.')
        finally:
            if slot: slot.close()
            private_json(self.job_path(record['requestId']), record)

    def status(self, rid):
        record = json.loads(self.job_path(rid).read_text())
        if record['status'] == 'running' and rid not in self.jobs:
            record.update(status='unknown', error='The helper stopped during creation. Refresh sessions before trying again; this request will not be resubmitted.')
        return {k: v for k, v in record.items() if k != 'fingerprint'}
