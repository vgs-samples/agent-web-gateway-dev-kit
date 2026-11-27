"""Offline tests of the read-only binding readback. curl is replaced; nothing reaches a network."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

KIT = Path(__file__).resolve().parent
SECRET = 'DO_NOT_PRINT'

MOCK_CURL = r'''#!/usr/bin/env bash
set -eu
args="$*"
printf '%s\n' "$args" >> "$MOCK_CALLS"
if [[ "$args" = *openid-connect/token* ]]; then
  printf '%s' '{"access_token":"offline-token"}'
elif [[ "$args" = *agent-gateway-adapter-destinations* ]]; then
  cat "$MOCK_DATA/bindings.json"; printf '\n%s' "${MOCK_BINDINGS_CODE:-200}"
elif [[ "$args" = *agent-gateway-adapters* ]]; then
  cat "$MOCK_DATA/adapters.json"; printf '\n200'
elif [[ "$args" = */functions* ]]; then
  cat "$MOCK_DATA/functions.json"; printf '\n200'
elif [[ "$args" = */reveal-sessions/* ]]; then
  cat "$MOCK_DATA/session.json"; printf '\n200'
else
  exit 94
fi
'''


def binding(adapter, function, point, host, method, path, enabled=True):
    return {'id': 'AX' + function, 'attributes': {
        'adapter': adapter, 'adapter_version': 2, 'enabled': enabled,
        'when': {'host': host, 'method': method, 'path': path},
        'functions': [{'id': function, 'extension_point': point,
                       'inputs': {'private': {'from': 'constant', 'value': SECRET}}}]}}


class ReadBindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='awg-read-bindings-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ['lib.sh', 'read-bindings.sh']:
            shutil.copy2(KIT / name, self.root / name)
        (self.root / '.env').write_text('VGS_CLIENT_ID=offline\nVGS_CLIENT_SECRET=offline-secret\nVGS_TENANT=tntoffline\n')
        (self.root / 'bin').mkdir()
        mock = self.root / 'bin/curl'
        mock.write_text(MOCK_CURL)
        mock.chmod(0o700)
        self.data = self.root / 'data'
        self.data.mkdir()
        adapter = lambda sid, name: {'id': sid, 'attributes': {'name': name, 'status': 'ACTIVE',
                                                               'latest_version': 2, 'published_version': 2}}
        self.write('adapters', [adapter('ADone', 'cybersource'), adapter('ADtwo', 'stripe')])
        self.write('functions', [{'id': i, 'attributes': {'name': n, 'source': SECRET}} for i, n in [
            ('FNcapture', 'CyberSource capture-context'), ('FNbridge', 'CyberSource bridge-sdk'),
            ('FNencrypt', 'CyberSource encrypt-token'), ('FNother', 'Reveal card')]])
        self.write('bindings', [
            binding('ADone', 'FNcapture', 'route.response', 'shop.invalid', 'GET', '/checkout'),
            binding('ADone', 'FNbridge', 'route.response', 'flex.cybersource.com', 'GET', '/bundle/iframe.min.js', enabled=False),
            binding('ADone', 'FNencrypt', 'route.request', 'flex.cybersource.com', 'POST', '/flex/v2/tokens'),
            binding('ADone', 'FNother', 'route.request', 'shop.invalid', 'POST', '/pay/*'),
            binding('ADtwo', 'FNother', 'route.request', 'api.stripe.com', 'POST', '/v1/tokens')])
        self.write('session', {'attributes': {'state': 'active', 'expires_at': '2099-01-01T00:00:00Z', 'adapter': 'ADone',
                                              'reveal_count': 3, 'refusal_count': 0, 'aliases': [{'value': SECRET}]}})
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('VGS_', 'KIT_', 'MOCK_'))}
        self.env.update(PATH=str(self.root / 'bin') + ':' + self.env['PATH'], MOCK_DATA=str(self.data),
                        MOCK_CALLS=str(self.root / 'calls'))

    def write(self, name, data):
        (self.data / (name + '.json')).write_text(json.dumps({'data': data}))

    def run_script(self, *args, **env):
        return subprocess.run(['/bin/bash', str(self.root / 'read-bindings.sh'), *args], env={**self.env, **env},
                              capture_output=True, text=True, timeout=20)

    def test_reports_stages_routes_and_enabled_flags_without_private_values(self):
        result = self.run_script('CyberSource')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['adapter'], {'id': 'ADone', 'name': 'cybersource', 'status': 'ACTIVE',
                                             'latestVersion': 2, 'publishedVersion': 2})
        self.assertEqual([(b['key'], b['when']['path'], b['enabled']) for b in report['bindings']],
                         [('capture', '/checkout', True), ('bridge-sdk', '/bundle/iframe.min.js', False),
                          ('encrypt', '/flex/v2/tokens', True)])
        # A wildcard route cannot be compared with a HAR, so it is counted, not listed.
        self.assertEqual((report['bindingsNotExactRoutes'], report['disabledBindings']), (1, 1))
        self.assertEqual(report['notChecked'], ['vault route content-type policy'])
        self.assertNotIn('session', report)
        calls = (self.root / 'calls').read_text()
        for private in (SECRET, 'offline-secret', 'offline-token'):
            self.assertNotIn(private, result.stdout + result.stderr)
        # Read-only: the token request is the only POST.
        self.assertEqual(calls.count('-X POST'), 1)
        self.assertNotIn('stripe', result.stdout)

    def test_session_selection_and_output_file_feed_the_har_report(self):
        output = self.root / 'routes.json'
        result = self.run_script('ADone', '--session', 'RSoffline', '--output', str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['session'],
                         {'state': 'active', 'expiresAt': '2099-01-01T00:00:00Z', 'revealCount': 3,
                          'refusalCount': 0, 'adapterSelection': 'this-adapter'})
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(set(json.loads(output.read_text())), {'bindings'})
        fixture = KIT.parents[3] / 'examples/adapters/cybersource/fixtures/encrypt.synthetic.har'
        report = subprocess.run(['python3', str(KIT.parent / 'har-index.py'), '--cybersource-bindings', str(output),
                                 str(fixture)], capture_output=True, text=True, check=True)
        row, = json.loads(report.stdout)['stages']['encrypt']
        self.assertEqual((row['mismatchedFields'], row['bindingEnabled']), ([], True))
        # An existing file is never overwritten.
        self.assertNotEqual(self.run_script('ADone', '--output', str(output)).returncode, 0)

    def test_stops_on_an_unknown_adapter_or_a_refused_request(self):
        unknown = self.run_script('adyen')
        self.assertNotEqual(unknown.returncode, 0)
        self.assertEqual(unknown.stdout, '')
        self.assertIn('no single adapter', unknown.stderr)
        refused = self.run_script('cybersource', MOCK_BINDINGS_CODE='403')
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(refused.stdout, '')
        self.assertIn('agent-gateway-adapter-destinations answered HTTP 403', refused.stderr)
        self.assertNotEqual(self.run_script('cybersource', '--session', 'not-a-session').returncode, 0)


if __name__ == '__main__':
    unittest.main()
