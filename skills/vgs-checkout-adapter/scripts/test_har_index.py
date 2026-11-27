"""Offline tests of body availability, decoding and private extraction."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('har-index.py')
spec = importlib.util.spec_from_file_location('har_index', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HarTests(unittest.TestCase):
    def test_body_availability_and_decoding(self):
        for value, state, data in [
            ({}, 'missing', None), ({'text': ''}, 'empty', b''),
            ({'text': 'aGVsbG8=', 'encoding': 'base64'}, 'present', b'hello'),
            ({'text': '!!!', 'encoding': 'base64'}, 'invalid-base64', None),
            ({'params': [{'name': 'x', 'value': 'y'}]}, 'params-only', None),
            ({'text': 'x', 'encoding': 'gzip'}, 'unsupported-encoding', None),
        ]:
            with self.subTest(state=state):
                info, actual = module.body_info(value)
                self.assertEqual(info['availability'], state)
                self.assertEqual(actual, data)

    def test_index_omits_secrets_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = json.dumps({'log': {'entries': [{
                'request': {'method': 'POST', 'url': 'https://user:pass@merchant.invalid/pay?secret=QUERY_SECRET',
                            'headers': [{'name': 'Authorization', 'value': 'HEADER_SECRET'}],
                            'postData': {'mimeType': 'application/json', 'text': 'BODY_SECRET'}},
                'response': {'status': 200, 'content': {'mimeType': 'text/plain'}}
            }]}}).encode()
            original = root / 'capture.har'
            original.write_bytes(raw)
            output = root / 'index.json'
            extracted = root / 'entry'
            run = subprocess.run([sys.executable, str(SCRIPT), str(original), '--output', str(output),
                                  '--entry', '0', '--extract-dir', str(extracted)], capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            text = output.read_text()
            for secret in ('QUERY_SECRET', 'HEADER_SECRET', 'BODY_SECRET', 'user:pass'):
                self.assertNotIn(secret, text)
            self.assertEqual(original.read_bytes(), raw)
            self.assertEqual((extracted / 'request.body').read_bytes(), b'BODY_SECRET')
            self.assertFalse((extracted / 'response.body').exists())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            # Exclusive output refuses to replace an original capture.
            run = subprocess.run([sys.executable, str(SCRIPT), str(original), '--output', str(original)], capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(original.read_bytes(), raw)


class CyberSourceTests(unittest.TestCase):
    fixtures = SCRIPT.resolve().parents[3] / 'examples/adapters/cybersource/fixtures'

    def entry(self, stage):
        return json.loads((self.fixtures / (stage + '.synthetic.har')).read_bytes())['log']['entries'][0]

    def report(self, *entries):
        return module.cybersource_report(json.dumps({'log': {'entries': entries}}).encode())['stages']

    def test_bundled_fixtures(self):
        stages = self.report(*(self.entry(stage) for stage in ('capture', 'bridge-sdk', 'encrypt')))
        for index, stage in enumerate(('capture', 'bridge-sdk', 'encrypt')):
            row, = stages[stage]
            self.assertEqual(row['entry'], index)
            self.assertEqual(row['bindingIndex'], index)
            self.assertEqual(row['mismatchedFields'], [])
            self.assertEqual(row['bodyAvailability'], 'present')
        self.assertEqual(stages['bridge-sdk'][0]['sdkPatchMarker'], 'absent-in-recorded-body')
        self.assertEqual(stages['encrypt'][0]['requestEnvelope'], 'AWGCS1-relay-shaped')

    def test_route_predicates(self):
        entries = []
        for host, method, path in [('other.invalid', 'POST', '/flex/v2/tokens'),
                                   ('flex.cybersource.com', 'GET', '/flex/v2/tokens'),
                                   ('flex.cybersource.com', 'POST', '/another/v3/tokens')]:
            entries.append({'request': {'method': method, 'url': f'https://{host}{path}?private=value'}})
        stages = self.report(*entries, {'request': {'url': 'https://unrelated.invalid/asset.js'}})
        self.assertEqual(stages['encrypt'], [{'entry': i, 'bindingIndex': 2, 'mismatchedFields': [field]}
                                             for i, field in enumerate(('host', 'method', 'path'))])
        self.assertEqual(stages['bridge-sdk'], [])
        self.assertEqual(stages['capture'], [])

    def test_explicit_routes_and_sibling_near_misses(self):
        entries = [self.entry(stage) for stage in ('capture', 'bridge-sdk', 'encrypt')]
        routes = json.loads((self.fixtures.parent / 'adapter.json').read_bytes())['bindings']
        bindings = [{'key': b['key'], 'when': b['when']} for b in routes]
        for stage, method, path in [('capture', 'GET', '/book/checkout/__data.json'),
                                    ('encrypt', 'POST', '/book/api/bsmPayments')]:
            when = {'host': 'shop.invalid', 'method': method, 'path': path}
            bindings.append({'key': stage, 'when': when})
            entries.append({'request': {'method': method, 'url': 'https://shop.invalid' + path,
                                        'postData': {'text': 'eyJh.Yg.Yw'}}})
        raw = json.dumps({'log': {'entries': entries}}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'PRIVATE_SPEC')
            path.write_text(json.dumps({'bindings': bindings}))
            report = module.cybersource_report(raw, path)
            self.assertEqual(report['bindingsSource'], 'explicit-file')
            stages = report['stages']
            self.assertEqual([(r['entry'], r['bindingIndex']) for r in stages['capture']],
                             [(0, 0), (3, 3)])
            flex, payment = stages['encrypt']
            self.assertEqual((flex['entry'], flex['bindingIndex'], flex['routeLabel'], flex['requestEnvelope']),
                             (2, 2, 'flex-tokens', 'AWGCS1-relay-shaped'))
            self.assertEqual((payment['entry'], payment['bindingIndex'], payment['routeLabel']),
                             (4, 4, 'bsm-payments'))
            self.assertNotIn('requestEnvelope', payment)
            self.assertNotIn('shop.invalid', json.dumps(report))
            self.assertNotIn('bsmPayments', json.dumps(report))

            alternate = {**bindings[2]['when'], 'host': 'alternate.invalid'}
            bindings.append({'key': 'encrypt', 'when': alternate})
            path.write_text(json.dumps({'bindings': bindings}))
            rows = module.cybersource_report(raw, path)['stages']['encrypt']
            self.assertEqual(rows, [flex, payment])
            entries[2]['request']['method'] = 'GET'
            raw = json.dumps({'log': {'entries': entries}}).encode()
            rows = module.cybersource_report(raw, path)['stages']['encrypt']
            self.assertEqual([(r['bindingIndex'], r['mismatchedFields']) for r in rows if r['entry'] == 2],
                             [(2, ['method']), (5, ['host', 'method'])])

    def test_standalone_cli_and_private_binding_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp, SCRIPT.name)
            script.write_bytes(SCRIPT.read_bytes())
            fixture = self.fixtures / 'encrypt.synthetic.har'
            path = Path(tmp, 'PRIVATE_SPEC')
            cmd = [sys.executable, str(script), '--cybersource', str(fixture)]
            missing = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn('--cybersource-bindings PATH', missing.stderr)

            cmd = [sys.executable, str(script), '--cybersource-bindings', str(path), str(fixture)]
            when = {'host': 'flex.cybersource.com', 'method': 'POST', 'path': '/flex/v2/tokens'}
            binding = {'key': 'encrypt', 'when': when}
            path.write_text(json.dumps({'bindings': [binding]}))
            valid = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(valid.stdout)['bindingsSource'], 'explicit-file')
            self.assertNotIn('PRIVATE_SPEC', valid.stdout + valid.stderr)
            bad_routes = [{'key': 'PRIVATE_STAGE', 'when': when},
                          {'key': 'encrypt', 'when': {'path': '/PRIVATE_PATH'}}]
            for field, value in [('host', 'https://PRIVATE_HOST'), ('method', 99),
                                 ('path', '/?PRIVATE_QUERY'), ('extra', 'PRIVATE_EXTRA')]:
                bad_routes.append({'key': 'encrypt', 'when': {**when, field: value}})
            path.unlink()
            for contents in [None, 'PRIVATE_JSON', '{"bindings":"PRIVATE_LIST"}',
                             *(json.dumps({'bindings': [b]}) for b in bad_routes)]:
                with self.subTest(contents=contents):
                    if contents is not None:
                        path.write_text(contents)
                    invalid = subprocess.run(cmd, capture_output=True, text=True)
                    self.assertNotEqual(invalid.returncode, 0)
                    self.assertEqual(invalid.stdout, '')
                    self.assertNotIn('PRIVATE', invalid.stderr)
                    self.assertNotIn('Traceback', invalid.stderr)

    def test_sdk_cache_gateway_and_marker_are_independent(self):
        cached, fetched, patched = (self.entry('bridge-sdk') for _ in range(3))
        cached['_fromCache'] = 'disk'
        del cached['response']['content']['text']
        fetched['response'].update(headers=[{'name': 'VGS-Request-ID', 'value': 'synthetic'},
                                             {'name': 'Cache-Control', 'value': ' Private, NO-STORE '}],
                                   _transferSize=108000)
        patched['response']['headers'] = [{'name': 'VGS-Upstream', 'value': 'PRIVATE_HEADER'},
                                          {'name': 'Cache-Control', 'value': 'no-store, private, no-cache'}]
        marker = b'const awgCsCard=e&&e.CARD,awgCsStandins={};return Promise.resolve("AWGCS1:"+value)'
        patched['response']['content'].update(encoding='base64', text=base64.b64encode(marker).decode())
        rows = self.report(cached, fetched, patched)['bridge-sdk']
        self.assertEqual([row['sdkPatchMarker'] for row in rows],
                         ['unknown', 'absent-in-recorded-body', 'present'])
        self.assertEqual([row['vgsRequestIdPresent'] for row in rows], [False, True, False])
        self.assertEqual([row['vgsUpstreamPresent'] for row in rows], [False, False, True])
        self.assertEqual([row['cacheControlNoStorePrivate'] for row in rows], [False, True, False])
        self.assertNotIn('PRIVATE_HEADER', json.dumps(rows))
        self.assertEqual([row['cacheEvidence'] for row in rows], ['cache-flag', 'none-recorded', 'none-recorded'])
        self.assertEqual(rows[1]['transferBytes'], 108000)
        fetched['response'].update(status=304, _transferSize=0)
        self.assertEqual(self.report(fetched)['bridge-sdk'][0]['cacheEvidence'], 'revalidated-304')

    def test_request_envelope_uses_request_bytes_only(self):
        entry = self.entry('encrypt')
        entry['response']['content'] = {'mimeType': 'application/jwt', 'text': 'AWGCS1:aa'}
        for body, state, shape in [
            ({'text': 'eyJh.Yg.Yw'}, 'present', 'compact-JWS-shaped'),
            ({'text': 'eyJh.Yg.Yw.ZA.ZQ'}, 'present', 'compact-JWE-shaped'),
            ({'text': 'AWGCS1:aaa'}, 'present', 'AWGCS1-invalid-encoding'),
            ({'text': ' AWGCS1:aa'}, 'present', 'other'),
            ({}, 'missing', 'unknown'), ({'text': ''}, 'empty', 'unknown'),
            ({'encoding': 'base64', 'text': '!!!'}, 'invalid-base64', 'unknown'),
        ]:
            with self.subTest(state=state, shape=shape):
                entry['request']['postData'] = body
                row, = self.report(entry)['encrypt']
                self.assertEqual((row['bodyAvailability'], row['requestEnvelope']), (state, shape))
                self.assertEqual(row['httpStatus'], 201)

    def test_upstream_code_is_separate_from_browser_status(self):
        entry = self.entry('encrypt')
        headers = [{'name': 'VGS-Upstream-Status-Code', 'value': ' 400 '},
                   {'name': 'vgs-upstream-response-time', 'value': 'PRIVATE_TIMING'}]
        entry['response']['headers'] = headers
        row, = self.report(entry)['encrypt']
        self.assertEqual((row['httpStatus'], row['vgsUpstreamStatusCode']), (201, 400))
        self.assertTrue(row['vgsUpstreamResponseTimePresent'])
        self.assertFalse(row['vgsUpstreamPresent'])
        self.assertNotIn('PRIVATE_TIMING', json.dumps(row))
        headers.append({'name': 'vgs-upstream-status-code', 'value': '201'})
        row, = self.report(entry)['encrypt']
        self.assertIsNone(row['vgsUpstreamStatusCode'])

    def test_cli_emits_only_safe_evidence(self):
        secret = 'DO_NOT_PRINT'
        entry = self.entry('encrypt')
        req, res = entry['request'], entry['response']
        req['url'] += '?private=' + secret
        req['postData'] = {'text': secret, 'mimeType': secret, 'encoding': secret}
        req['cookies'] = [{'name': 'session', 'value': secret}]
        res['headers'] = [{'name': 'vgs-request-id', 'value': secret},
                          {'name': 'VGS-Upstream-Status-Code', 'value': secret}]
        res['content']['text'] = secret
        near_miss = {'request': {'method': secret, 'url': f'https://{secret}.invalid/{secret}/tokens'}}
        jwt = self.entry('encrypt')
        jwt['request']['postData']['text'] = f'eyJh.{secret}.signature'
        sdk = self.entry('bridge-sdk')
        sdk['response']['content']['text'] += secret
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'input.har')
            path.write_text(json.dumps({'log': {'entries': [entry, near_miss, jwt, sdk]}}))
            cmd = [sys.executable, str(SCRIPT), '--cybersource', str(path)]
            run = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.assertNotIn(secret.lower(), (run.stdout + run.stderr).lower())
            report = json.loads(run.stdout)
            self.assertEqual(report['bindingsSource'], 'bundled-example')
            row = report['stages']['encrypt'][0]
            self.assertEqual(row['bodyAvailability'], 'unsupported-encoding')
            self.assertTrue(row['vgsRequestIdPresent'])
            refused = subprocess.run(cmd + ['--entry', '0', '--extract-dir', str(Path(tmp, 'extract'))],
                                     capture_output=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertFalse(Path(tmp, 'extract').exists())
            req['url'] = f'https://[{secret}/tokens'
            path.write_text(json.dumps({'log': {'entries': [entry]}}))
            invalid = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertNotIn(secret, invalid.stdout + invalid.stderr)


if __name__ == '__main__':
    unittest.main()
