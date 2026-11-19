"""Evidence-based DEV repairs. Never submits merchant traffic or changes vault preferences."""
import base64
import fnmatch
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
import threading
from urllib.parse import parse_qs, urlsplit

from mcp_gateway import GatewayBridge, runtime_lock
from session_operations import private_json


def digest(value):
    return hashlib.sha256(value).hexdigest()


def response_text(content):
    try:
        text = content.get('text', '')
        if content.get('encoding') == 'base64':
            text = base64.b64decode(text, validate=True).decode()
        return text if isinstance(text, str) else ''
    except (ValueError, UnicodeError):
        return ''


def json_leaves(value, depth=0):
    if depth > 12:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                yield from json_leaves(child, depth + 1)
            else:
                yield key, child
    elif isinstance(value, list):
        for child in value:
            yield from json_leaves(child, depth + 1)


class PaymentHeadings(HTMLParser):
    """Read visible result headings; script strings and telemetry are not outcomes."""
    def __init__(self):
        super().__init__()
        self.heading = None
        self.parts = []
        self.declined = False
        self.frames = []
        self.hidden = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        hidden = (self.hidden or tag in ('script', 'style', 'template') or 'hidden' in attrs
                  or attrs.get('aria-hidden') == 'true'
                  or re.search(r'(display\s*:\s*none|visibility\s*:\s*hidden)', attrs.get('style', ''), re.I))
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.frames.append((tag, bool(hidden)))
            self.hidden = bool(hidden)
        if not self.hidden and tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.heading, self.parts = tag, []

    def handle_endtag(self, tag):
        if tag == self.heading:
            label = ' '.join(''.join(self.parts).split()).casefold()
            if not self.hidden and label in ('declined', 'payment declined', 'transaction declined', 'payment refused', 'transaction refused'):
                self.declined = True
            self.heading = None
        for index in range(len(self.frames) - 1, -1, -1):
            if self.frames[index][0] == tag:
                self.frames = self.frames[:index]
                break
        self.hidden = self.frames[-1][1] if self.frames else False

    def handle_data(self, text):
        if self.heading and not self.hidden:
            self.parts.append(text)


def payment_outcomes(entry, index, payment_hosts):
    """Diagnosis only. Never converts processor declines or 3DS results into repairs."""
    response = entry.get('response', {})
    if not 200 <= response.get('status', 0) < 300:
        return []
    url = urlsplit(entry.get('request', {}).get('url', ''))
    body = response_text(response.get('content', {}))
    try:
        document = json.loads(body)
    except ValueError:
        document = None
    findings = []
    for key, value in json_leaves(document):
        if key.casefold() != 'cres' or not isinstance(value, str) or len(value) > 65536:
            continue
        try:
            decoded = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
            status = decoded.get('transStatus')
            if decoded.get('messageType') == 'CRes' and status in ('Y', 'N', 'U', 'A', 'R'):
                findings.append({'entry': index, 'host': url.hostname, 'category': 'three-d-secure', 'transStatus': status})
        except (ValueError, UnicodeError, AttributeError):
            pass
    # Require an approved processor host/path. A tracking response containing
    # "declined", or a script with an unused error template, is not a payment result.
    approved = any(rule.get('host') == url.hostname and rule.get('pathPrefix', '').startswith('/')
                   and url.path.startswith(rule['pathPrefix']) for rule in payment_hosts)
    if not approved:
        return findings
    declined = any(key.replace('_', '').casefold() in ('paymentstatus', 'authorizationstatus')
                   and isinstance(value, str) and value.casefold() in ('refused', 'declined')
                   for key, value in json_leaves(document))
    if 'html' in response.get('content', {}).get('mimeType', '').casefold():
        headings = PaymentHeadings()
        headings.feed(body)
        declined = declined or headings.declined
    if declined:
        findings.append({'entry': index, 'host': url.hostname, 'category': 'payment-declined', 'reason': 'processor-refused'})
    return findings


def private_policy(path):
    path = Path(path)
    info = path.stat()
    if path.is_symlink() or (os.name != 'nt' and
            (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077)):
        raise ValueError('Repair policy must be an owner-only local file (chmod 600).')
    value = json.loads(path.read_text())
    if value.get('version') != 1 or value.get('environment') != 'dev' or not value.get('tenantId'):
        raise ValueError('Repair policy must specify version 1 and a DEV tenant.')
    return value


class CaptureRepair:
    """Known repair recipes, with an explicit merchant/host policy and durable write journal.

    HAR content is evidence, never a source of permissions or executable instructions.
    Only a local policy may authorize an exact host. An unknown failure stays unresolved.
    """
    def __init__(self, registry, captures_directory, policy_path=None):
        self.registry = registry
        self.directory = Path(captures_directory)
        self.policy_path = Path(policy_path) if policy_path else None
        self.lock = threading.Lock()

    def saved(self, capture_id):
        if not re.fullmatch(r'CAP[a-f0-9]{32}', capture_id):
            raise ValueError('Invalid capture ID.')
        path = self.directory / (capture_id + '.har')
        if path.is_symlink():
            raise ValueError('Capture must be a local recording.')
        return path

    def automatic(self, capture_id):
        if not self.policy_path:
            return {'status': 'disabled', 'message': 'Automatic repair has no local DEV policy.'}
        return self.run(capture_id, apply=private_policy(self.policy_path).get('automatic') is True)

    def run(self, capture_id, *, apply=False):
        self.saved(capture_id)  # Validate before using the ID in a diagnosis filename.
        with self.lock:
            # The cross-process lock also covers diagnosis, preventing simultaneous helpers
            # from planning duplicate creates before either journals the operation.
            directory = self.directory / 'repairs'
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            lock = runtime_lock(directory)
            try:
                result = self._run(capture_id, apply)
                private_json(directory / (capture_id + '.json'), result)
                return result
            finally:
                lock.close()

    def _run(self, capture_id, apply):
        if not self.policy_path:
            return {'status': 'disabled', 'message': 'No local repair policy configured.'}
        policy = private_policy(self.policy_path)
        raw = self.saved(capture_id).read_bytes()
        log = json.loads(raw)['log']
        meta = log.get('_capture', {})
        context = meta.get('testContext', {})
        result = {'captureId': capture_id, 'harSha256': digest(raw), 'status': 'needs-review',
                  'message': 'No supported repair identified.', 'findings': [],
                  'merchantRequestsSent': 0, 'paymentRetried': False}
        if not meta.get('stoppedAt') or context.get('environment') != 'dev':
            result['message'] = 'A finalized DEV recording with session context is required.'
            return result
        sid = context.get('sessionId', '')
        if not isinstance(sid, str) or not re.fullmatch(r'RS[A-Za-z0-9]+', sid):
            return result
        catalog = self.registry.get('dev')
        if not catalog or catalog.tenant != policy['tenantId'] or catalog.environment != 'dev':
            raise ValueError('Repair policy does not match the connected DEV account.')
        merchant = urlsplit(meta.get('testUrl', '')).hostname
        rules = [r for r in policy.get('merchants', []) if r.get('host') == merchant]
        if len(rules) != 1:
            result['message'] = 'This merchant has no approved local repair policy.'
            return result
        saved = json.loads(catalog.saved(sid).read_text())
        if saved['data']['id'] != sid:
            raise ValueError('Saved session does not match the capture.')
        tokens = {row.get('format'): row.get('value') for row in saved['data']['attributes'].get('session_aliases', [])}
        candidates = []
        for index, entry in enumerate(log.get('entries', [])):
            response, request = entry.get('response', {}), entry.get('request', {})
            result['findings'].extend(payment_outcomes(entry, index, rules[0].get('paymentHosts', [])))
            if entry.get('_error') in ('net::ERR_TUNNEL_CONNECTION_FAILED', 'net::ERR_PROXY_CONNECTION_FAILED',
                                        'net::ERR_PROXY_AUTH_REQUESTED'):
                result['findings'].append({'entry': index, 'host': urlsplit(request.get('url', '')).hostname,
                    'category': 'proxy-connection', 'reason': entry['_error']})
            if response.get('status', 0) < 400:
                continue
            content = response.get('content', {})
            try:
                body = content['text']
                if content.get('encoding') == 'base64':
                    body = base64.b64decode(body, validate=True).decode()
                failure = json.loads(body)
                if not isinstance(failure, dict) or failure.get('error') != 'reveal_refused':
                    continue
            except (KeyError, ValueError, UnicodeError):
                continue
            url = urlsplit(request.get('url', ''))
            reason = failure.get('reason')
            finding = {'entry': index, 'host': url.hostname, 'category': 'vgs-refusal',
                       'reason': reason if reason in ('guard_refused', 'alias_unavailable', 'session_expired',
                                                    'adapter_failed', 'transform_failed') else 'other'}
            result['findings'].append(finding)
            matches = [r for r in rules[0].get('paymentHosts', []) if r.get('host') == url.hostname]
            if (len(matches) != 1 or reason != 'guard_refused' or failure.get('host') != url.hostname
                    or failure.get('session_id') != sid or response['status'] != 403
                    or url.scheme != 'https' or url.username or url.password or url.port not in (None, 443)
                    or request.get('method') != 'POST'):
                continue
            rule = matches[0]
            prefix = rule.get('pathPrefix', '')
            if not prefix.startswith('/') or not url.path.startswith(prefix):
                continue
            post = request.get('postData', {})
            if post.get('mimeType', '').split(';')[0].strip() != 'application/x-www-form-urlencoded':
                continue
            fields = parse_qs(post.get('text', ''), keep_blank_values=True)
            # Match BOTH saved stand-ins in the explicitly approved fields; never expose them.
            mapping = rule.get('cardFields', {})
            if any(not tokens.get(role) or fields.get(mapping.get(role)) != [tokens[role]]
                   for role in ('card_number', 'card_cvc')):
                continue
            if rule.get('destinationTrust') is True:
                candidates.append((finding, rule))
        declines = [row for row in result['findings'] if row['category'] == 'payment-declined']
        if declines:
            last_decline = declines[-1]
            auth = [row for row in result['findings'] if row['category'] == 'three-d-secure'
                    and row['entry'] < last_decline['entry']]
            authenticated = bool(auth and auth[-1]['transStatus'] == 'Y')
            result.update(status='payment-declined', diagnosis='processor-decline',
                          threeDSAuthenticated=authenticated, requiresConfigurationChange=False,
                          message=('3DS authentication succeeded, then the processor declined the payment. '
                                   if authenticated else 'The processor declined the payment. ') +
                                  'No destination change or payment retry was made. The specific decline reason requires processor or issuer confirmation.')
            return result
        if not candidates:
            categories = {row['category'] for row in result['findings']}
            result['message'] = ('VGS refused a request; the evidence does not match an authorized repair recipe.' if 'vgs-refusal' in categories else
                'The capture contains proxy connection failures. Check the current route before another checkout attempt.' if 'proxy-connection' in categories else
                'No supported VGS refusal found; inspect the captured payment exchange.')
            return result
        hosts = {rule['host'] for _, rule in candidates}
        if len(hosts) != 1:
            result['message'] = 'Multiple repair targets require review.'
            return result
        host = next(iter(hosts))
        client = catalog.client
        session = client.api('GET', '/reveal-sessions/' + sid)['data']['attributes']
        if session.get('allowed_hosts') or session.get('unlisted_host_mode') != 'guarded':
            result['message'] = 'Session host restrictions or guard mode need separate diagnosis.'
            return result
        destinations = client.api('GET', '/agent-gateway-destinations')['data']
        matches = [row for row in destinations if fnmatch.fnmatchcase(host, row['attributes']['host_pattern'])]
        exact = [row for row in matches if row['attributes']['host_pattern'] == host]
        if any(row['attributes']['action'] == 'block' for row in matches) or len(exact) > 1:
            result['message'] = 'An explicit block or ambiguous destination must be reviewed.'
            return result
        if any(row['attributes']['host_pattern'] != host for row in matches):
            result['message'] = 'A wildcard destination matches this host; review precedence before changing it.'
            return result
        if exact and exact[0]['attributes']['action'] == 'trust':
            result.update(status='configured', message='Exact destination is trusted. A fresh checkout is needed to verify merchant behavior.',
                          host=host, destinationId=exact[0]['id'], readbackVerified=True)
            return result
        if exact and exact[0]['attributes']['action'] != 'guarded':
            return result
        before = exact[0] if exact else None
        attrs = {'action': 'trust'} | ({} if before else {'host_pattern': host})
        operation = {'operation': 'update' if before else 'create', 'tenantId': catalog.tenant,
                     'resource': 'agent-gateway-destinations', 'id': before['id'] if before else None,
                     'attributes': attrs}
        # Deterministic across captures/restarts: an uncertain mutation is never replayed.
        identity = json.dumps([catalog.tenant, host, before], sort_keys=True).encode()
        operation['requestId'] = digest(identity)[:32]
        result.update(status='planned', host=host, diagnosis='destination-guard',
                      message='The payment host is guarded. Set its exact DEV destination to trust.',
                      operation=operation, beforeAction='guarded' if before else 'unlisted')
        if not apply:
            return result
        journal = self.directory / 'repairs'
        backup = journal / (operation['requestId'] + '.before.json')
        if not backup.exists():
            private_json(backup, {'evidence': result, 'destination': before})
        bridge = GatewayBridge(self.registry, 'dev', journal, allow_writes=True)
        mutation = bridge.execute(operation)
        if mutation['status'] != 'completed':
            result.update(status=mutation['status'], message='Destination write was not confirmed. Inspect remote state before retrying.')
        else:
            rid = mutation['result']['data']['id']
            after = client.api('GET', '/agent-gateway-destinations/' + rid)
            a = after['data']['attributes']
            verified = a.get('host_pattern') == host and a.get('action') == 'trust'
            result.update(status='repaired' if verified else 'needs-review', destinationId=rid,
                          readbackVerified=verified,
                          message='DEV destination repaired and read back. Payment has not been retried.' if verified else
                                  'Destination readback did not match the requested change.',
                          rollback={'method': 'PATCH' if before else 'DELETE',
                                    'path': '/agent-gateway-destinations/' + rid,
                                    'attributes': {'action': 'guarded'} if before else None})
            private_json(journal / (operation['requestId'] + '.after.json'), after)
        private_json(journal / (capture_id + '.json'), result)
        return result
