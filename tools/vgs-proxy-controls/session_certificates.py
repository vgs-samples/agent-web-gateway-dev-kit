"""Export only the public CA bundle from a saved, environment-matched session."""
import base64
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from environments import domains, matches_session_proxy, matches_session_pac


class CertificateError(ValueError):
    pass


def session_certificate(catalog, session_id):
    try:
        if not re.fullmatch(r'RS[A-Za-z0-9]+', session_id):
            raise ValueError()
        saved = json.loads(catalog.saved(session_id).read_text())
        proxy = saved['data']['attributes']['proxy']
        actual = urlsplit(proxy['url'])
        if saved['data']['id'] != session_id or not matches_session_proxy(proxy['url'], catalog.environment, catalog.tenant):
            raise ValueError()
        pem = proxy['ca_bundle']
        if not isinstance(pem, str) or not 0 < len(pem) <= 131072:
            raise ValueError()
        pattern = r'-----BEGIN CERTIFICATE-----\s*([A-Za-z0-9+/=\s]+?)\s*-----END CERTIFICATE-----'
        matches = list(re.finditer(pattern, pem))
        if not matches or re.sub(pattern, '', pem).strip():
            raise ValueError()
        fingerprints = []
        for match in matches:
            der = base64.b64decode(re.sub(r'\s', '', match[1]), validate=True)
            if not der: raise ValueError()
            fingerprints.append(':'.join(re.findall('..', hashlib.sha256(der).hexdigest().upper())))
        return {'sessionId': session_id, 'environment': catalog.environment, 'tenantId': catalog.tenant,
                'filename': f'vgs-{catalog.environment}-{session_id}-ca.pem',
                'caBundle': pem.strip() + '\n', 'sha256Fingerprints': fingerprints}
    except Exception:
        raise CertificateError('The saved CA certificate is unavailable or does not match this environment and tenant.') from None


class SessionDetailsError(ValueError):
    pass


def session_details(catalog, session_id):
    """Expose stand-ins and session settings, never proxy credentials or signed URLs."""
    try:
        if not re.fullmatch(r'RS[A-Za-z0-9]+', session_id):
            raise ValueError()
        saved = json.loads(catalog.saved(session_id).read_text())
        attrs = saved['data']['attributes']
        actual = urlsplit(attrs['proxy']['url'])
        if saved['data']['id'] != session_id or not matches_session_proxy(attrs['proxy']['url'], catalog.environment, catalog.tenant):
            raise ValueError()
        # Refresh mutable status/settings; the one-time stand-ins remain in the local creation response.
        try:
            latest = catalog.client.api('GET', '/reveal-sessions/' + session_id)
            if latest['data']['id'] != session_id:
                raise ValueError()
            current = {**attrs, **latest['data']['attributes']}
        except Exception as error:
            expired = datetime.fromisoformat(attrs['expires_at'].replace('Z', '+00:00')) <= datetime.now(timezone.utc)
            # Expired sessions disappear from the API; keep their saved details
            # inspectable, explicitly expired and never eligible for activation.
            if getattr(error, 'status', None) != 404 or not expired:
                raise
            current = {**attrs, 'state': 'expired'}
        tokens = []
        for token in attrs.get('tokens', []):
            if not isinstance(token.get('value'), str) or not isinstance(token.get('format'), str):
                raise ValueError()
            tokens.append({k: token[k] for k in ('format', 'value')})
        fields = ('state', 'created_at', 'expires_at', 'allowed_hosts', 'allowed_client_cidrs',
                  'adapter', 'adapter_version', 'reveal_limit', 'max_reveals', 'reveal_count')
        settings = {k: current[k] for k in fields if k in current}
        egress = current.get('egress_proxy_settings') or {}
        settings['egress'] = {k: egress[k] for k in ('type','scheme','hostname','port') if k in egress}
        settings['proxy'] = {'scheme': actual.scheme, 'hostname': actual.hostname, 'port': actual.port}
        settings['pacUrl'] = domains(catalog.environment,catalog.tenant)['api'] + '/reveal-sessions/' + session_id + '.pac'
        saved_pac = attrs['proxy'].get('pac_url', '')
        if matches_session_pac(saved_pac, session_id, catalog.environment):
            pac = urlsplit(saved_pac)
            settings['pacUrl'] = urlunsplit((pac.scheme, pac.netloc, pac.path, '', ''))
        return {'sessionId':session_id,'environment':catalog.environment,'tenantId':catalog.tenant,
                'tokens':tokens,'settings':settings}
    except Exception:
        raise SessionDetailsError('Session details are unavailable. Refresh the list and check the saved session for this account.') from None


def ca_trusted_locally(pem):
    """Read macOS SSL trust without installing a CA or adding a trust anchor.

    Other platforms keep the launch-time CA requirement until an equivalent
    browser-compatible trust check is implemented. Recheck on every selection
    so removing trust takes effect without restarting the helper.
    """
    if sys.platform != 'darwin' or not isinstance(pem, str) or not 0 < len(pem) <= 131072:
        return False
    pattern = r'-----BEGIN CERTIFICATE-----\s*[A-Za-z0-9+/=\s]+?\s*-----END CERTIFICATE-----'
    certificates = re.findall(pattern, pem)
    if not certificates or re.sub(pattern, '', pem).strip():
        return False
    try:
        for certificate in certificates:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pem') as file:
                file.write(certificate + '\n')
                file.flush()
                # Never pass -r: that would supply an anchor rather than test trust.
                result = subprocess.run(
                    ['/usr/bin/security', 'verify-cert', '-c', file.name,
                     '-p', 'ssl', '-l', '-L', '-q'],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=5, check=False)
            if result.returncode != 0:
                return False
        return True
    except (OSError, subprocess.SubprocessError):
        return False
