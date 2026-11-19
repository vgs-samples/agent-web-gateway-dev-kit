"""Offline lifecycle regressions. All HTTP and browser calls use local test doubles."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

KIT = Path(__file__).resolve().parent

MOCK_CURL = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
url = next(a for a in args if a.startswith('https://'))
kind = 'card' if url.endswith('/cards') else 'session' if url.endswith('/reveal-sessions') else 'auth'
with open(os.environ['MOCK_CALLS'], 'a') as log:
    log.write(kind + '\n')
with open(pathlib.Path(os.environ['MOCK_REQUESTS'], 'http-calls.jsonl'), 'a') as log:
    log.write(json.dumps({'kind': kind, 'url': url,
        'headers': [args[i + 1] for i, arg in enumerate(args) if arg == '-H'],
        'form': [args[i + 1] for i, arg in enumerate(args) if arg == '-d']}) + '\n')
if kind == 'auth':
    print(json.dumps({'access_token': 'offline-token'}))
    sys.exit(0)
data = args[args.index('--data-binary') + 1]
request = json.loads(sys.stdin.read() if data == '@-' else pathlib.Path(data[1:]).read_text())
pathlib.Path(os.environ['MOCK_REQUESTS'], kind + '.json').write_text(json.dumps(request))
if kind == 'card':
    code = os.environ.get('MOCK_CARD_CODE', '201')
    response = {'data': {'id': 'CRDoffline', 'attributes': {
        'pan_alias': 'fresh-pan-alias', 'cvc_alias': None if os.environ.get('MOCK_NULL_CVC') else 'fresh-cvc-alias',
        'card_brand': 'VISA', 'last4': '1111', 'bin': '411111'}}}
else:
    code = os.environ.get('MOCK_SESSION_CODE', '201')
    attrs = request['data']['attributes']
    response = {'data': {'id': 'RSoffline', 'attributes': {
        'expires_at': '2030-01-01T00:00:00Z', 'allowed_hosts': attrs.get('allowed_hosts', []),
        'egress_proxy_settings': attrs['egress_proxy_settings'],
        'proxy': {'url': 'https://RSoffline:offline-password@proxy.invalid:8443',
                  'pac_url': 'https://api.invalid/offline.pac'},
        'tokens': [{'format': 'card_number', 'value': '4111111111111111'},
                   {'format': 'card_cvc', 'value': '123'}]}}}
pathlib.Path(args[args.index('-o') + 1]).write_text(json.dumps(response))
sys.stdout.write(code)
'''


class FreshSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='awg-fresh-session-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ['lib.sh', 'create-card.sh', 'create-session.sh', 'create-fresh-session.sh', 'start.sh']:
            shutil.copy2(KIT / name, self.root / name)
        (self.root / '.env').write_text('VGS_CLIENT_ID=offline\nVGS_CLIENT_SECRET=offline\nVGS_TENANT=tntoffline\n')
        (self.root / '.state').mkdir()
        self.old_card = {'pan_alias': 'old-pan-alias', 'cvc_alias': 'old-cvc-alias', 'bin': '411111', 'length': 16}
        (self.root / '.state/card.json').write_text(json.dumps(self.old_card))
        (self.root / 'bin').mkdir()
        mock = self.root / 'bin/curl'
        mock.write_text(MOCK_CURL)
        mock.chmod(0o700)
        (self.root / 'launch-chromium.sh').write_text('#!/usr/bin/env bash\nprintf "browser\\n" >> "$MOCK_CALLS"\n')
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('VGS_', 'CARD_', 'KIT_', 'EGRESS_', 'MOCK_', 'CLOAK_', 'ADAPTER_'))}
        (self.root / 'cloak-launch.py').write_text("""import json, os, pathlib, sys
with open(os.environ['MOCK_CALLS'], 'a') as log:
    log.write('cloak\\n')
session = pathlib.Path(sys.argv[1])
assert session.is_file()
assert session.with_suffix('.request.json').is_file()
pathlib.Path(os.environ['MOCK_REQUESTS'], 'cloak.json').write_text(json.dumps({
    'session': str(session), 'id': json.loads(session.read_text())['data']['id'],
    'url': sys.argv[2]}))
sys.exit(int(os.environ.get('MOCK_BROWSER_CODE', '0')))
""")
        self.env['CLOAK_PYTHON'] = sys.executable
        self.env['EGRESS_ALLOWED_HOST'] = 'proxy.example.invalid'
        self.env['EGRESS_ALLOWED_PORT'] = '8080'
        self.env.update(PATH=str(self.root / 'bin') + os.pathsep + os.environ['PATH'],
                        MOCK_CALLS=str(self.root / 'calls'), MOCK_REQUESTS=str(self.root),
                        EGRESS_PROXY='http://offline:offline@proxy.example.invalid:8080',
                        CARD_PAN='4111111111111111', CARD_CVC='123', CARD_EXP='12/30')

    def run_script(self, script, *args):
        return subprocess.run(['bash', str(self.root / script), *args], env=self.env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)

    def calls(self):
        p = self.root / 'calls'
        return p.read_text().splitlines() if p.exists() else []

    def test_start_stores_card_then_uses_only_new_aliases_then_opens_browser(self):
        result = self.run_script('start.sh', 'merchant.invalid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ['auth', 'card', 'auth', 'session', 'browser'])
        request = json.loads((self.root / 'session.json').read_text())['data']['attributes']
        card = request['cards'][0]
        self.assertEqual([card[k]['alias'] for k in ('number','cvc')], ['fresh-pan-alias', 'fresh-cvc-alias'])
        self.assertNotIn('aliases', request)
        self.assertNotIn('adapter', request)
        self.assertEqual(card['number']['storage'], 'PERSISTENT')
        self.assertEqual(card['cvc']['storage'], 'VOLATILE')
        self.assertEqual(request['allowed_hosts'], ['merchant.invalid'])
        self.assertEqual(request['egress_proxy_settings']['hostname'], 'proxy.example.invalid')
        stored = json.loads((self.root / '.state/card.json').read_text())
        self.assertNotIn('pan', stored)
        self.assertNotIn('cvc', stored)

    def test_null_cvc_stops_without_using_old_aliases_or_opening_browser(self):
        for code in ['303', '201']:
            with self.subTest(code=code):
                (self.root / 'calls').unlink(missing_ok=True)
                self.env.update(MOCK_CARD_CODE=code, MOCK_NULL_CVC='1')
                result = self.run_script('start.sh', 'merchant.invalid')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('no PAN or CVC alias', result.stderr)
                self.assertEqual(self.calls(), ['auth', 'card'])
                self.assertEqual(json.loads((self.root / '.state/card.json').read_text()), self.old_card)

    def test_card_http_error_stops_before_session(self):
        self.env['MOCK_CARD_CODE'] = '500'
        result = self.run_script('start.sh', 'merchant.invalid')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), ['auth', 'card'])

    def test_missing_details_never_substitutes_a_test_card(self):
        for key in ['CARD_PAN', 'CARD_CVC', 'CARD_EXP']:
            self.env.pop(key)
        result = self.run_script('start.sh', 'merchant.invalid')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing card details', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_fresh_wrapper_rejects_alias_overrides(self):
        result = self.run_script('create-fresh-session.sh', '--cvc-alias', 'old-cvc-alias')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_missing_saved_cvc_requires_explicit_pan_only_diagnostic(self):
        self.old_card['cvc_alias'] = None
        (self.root / '.state/card.json').write_text(json.dumps(self.old_card))
        result = self.run_script('create-session.sh', '--hosts', 'merchant.invalid')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no CVC alias', result.stderr)
        self.assertEqual(self.calls(), [])
        result = self.run_script('create-session.sh', '--hosts', 'merchant.invalid', '--no-cvc')
        self.assertEqual(result.returncode, 0, result.stderr)
        request = json.loads((self.root / 'session.json').read_text())['data']['attributes']
        self.assertEqual(request['cards'][0]['number']['format'], 'card_number')
        self.assertNotIn('cvc', request['cards'][0])

    def test_session_failure_does_not_open_browser(self):
        self.env['MOCK_SESSION_CODE'] = '500'
        result = self.run_script('start.sh', 'merchant.invalid')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), ['auth', 'card', 'auth', 'session'])

    def test_fresh_wrapper_requires_201_even_when_303_has_cvc(self):
        self.env['MOCK_CARD_CODE'] = '303'
        result = self.run_script('create-fresh-session.sh', '--launch-browser')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('new card ID is required', result.stderr)
        self.assertEqual(self.calls(), ['auth', 'card'])
        self.assertEqual(json.loads((self.root / '.state/card.json').read_text()), self.old_card)

    def test_fresh_wrapper_rejects_same_card_id_even_with_201(self):
        self.old_card['card_id'] = 'CRDoffline'
        (self.root / '.state/card.json').write_text(json.dumps(self.old_card))
        result = self.run_script('create-fresh-session.sh', '--launch-browser')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('did not return a new card ID', result.stderr)
        self.assertEqual(self.calls(), ['auth', 'card'])
        self.assertEqual(json.loads((self.root / '.state/card.json').read_text()), self.old_card)

    def test_help_has_no_side_effects(self):
        result = self.run_script('create-fresh-session.sh', '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [])

    def test_revolut_profile_keeps_credentials_and_card_session_state_separate(self):
        (self.root / '.env.revolut_sandbox').write_text(
            'VGS_CLIENT_ID=revolut-offline\nVGS_CLIENT_SECRET=revolut-offline-secret\n'
            'VGS_TENANT=tntrevolut\nVGS_API=https://sandbox.vgsapi.com\n'
            'VGS_AUTH_URL=https://auth.verygoodsecurity.com/auth/realms/vgs/protocol/openid-connect/token\n')
        self.env['KIT_ENV'] = 'revolut_sandbox'
        result = self.run_script('create-fresh-session.sh', '--launch-browser')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ['auth', 'card', 'auth', 'session', 'cloak'])
        calls = [json.loads(line) for line in (self.root / 'http-calls.jsonl').read_text().splitlines()]
        for call in (c for c in calls if c['kind'] == 'auth'):
            self.assertEqual(call['url'], 'https://auth.verygoodsecurity.com/auth/realms/vgs/protocol/openid-connect/token')
            self.assertIn('client_id=revolut-offline', call['form'])
            self.assertIn('client_secret=revolut-offline-secret', call['form'])
        card_call = next(c for c in calls if c['kind'] == 'card')
        self.assertEqual(card_call['url'], 'https://sandbox.vgsapi.com/cards')
        session_call = next(c for c in calls if c['kind'] == 'session')
        self.assertEqual(session_call['url'], 'https://sandbox.vgsapi.com/reveal-sessions')
        self.assertIn('VGS-Tenant: tntrevolut', session_call['headers'])
        self.assertEqual(json.loads((self.root / '.state/card.json').read_text()), self.old_card)
        state = self.root / '.state-revolut_sandbox'
        self.assertEqual(json.loads((state / 'card.json').read_text())['pan_alias'], 'fresh-pan-alias')
        self.assertTrue((state / 'latest-session.json').is_file())
        opened = json.loads((self.root / 'cloak.json').read_text())
        self.assertEqual(opened['session'], str(state / 'sessions/RSoffline.json'))

    def write_proxy_profile(self, **changes):
        profile = {'scheme': 'http', 'hostname': 'proxy.example.invalid', 'port': 8080,
                   'username': 'offline-user', 'password': 'offline-egress-password'}
        profile.update(changes)
        path = self.root / 'proxy.json'
        path.write_text(json.dumps(profile))
        return str(path)

    def test_fresh_session_uses_explicit_proxy_and_adapter(self):
        profile = self.write_proxy_profile()
        result = self.run_script('create-fresh-session.sh', '--adapter', 'ADofflineStripe',
                                 '--hosts', 'api.stripe.com', '--egress-profile', profile)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ['auth', 'card', 'auth', 'session'])
        attrs = json.loads((self.root / 'session.json').read_text())['data']['attributes']
        self.assertEqual(attrs['adapter'], 'ADofflineStripe')
        self.assertEqual(attrs['allowed_hosts'], ['api.stripe.com'])
        self.assertEqual(attrs['cards'][0]['number']['alias'], 'fresh-pan-alias')
        self.assertEqual(attrs['cards'][0]['cvc']['alias'], 'fresh-cvc-alias')
        self.assertEqual(attrs['egress_proxy_settings'], {
            'type': 'custom', 'scheme': 'http', 'hostname': 'proxy.example.invalid',
            'port': 8080, 'username': 'offline-user', 'password': 'offline-egress-password'})
        self.assertNotIn('offline-egress-password', result.stdout)

    def test_proxy_profile_rejects_unapproved_or_incomplete_settings(self):
        for changes in [{'hostname': 'unapproved.invalid'}, {'port': 80},
                        {'password': None}, {'scheme': 'socks5'}]:
            with self.subTest(changes=changes):
                result = self.run_script('create-session.sh', '--egress-profile', self.write_proxy_profile(**changes))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('egress profile must contain', result.stderr)
                self.assertEqual(self.calls(), [])

    def test_invalid_profile_never_falls_back_to_environment_proxy(self):
        result = self.run_script('create-session.sh', '--egress-profile', str(self.root / 'missing.json'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('cannot read egress profile', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_environment_proxy_restriction_and_no_direct_fallback_remain(self):
        self.env['EGRESS_PROXY'] = 'http://offline:offline@unapproved.invalid:8080'
        result = self.run_script('create-session.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('egress must match locally configured', result.stderr)
        self.env.pop('EGRESS_PROXY')
        result = self.run_script('create-session.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('direct VGS egress is disabled', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_proxy_requires_explicit_host_and_port_configuration(self):
        profile = self.write_proxy_profile()
        for args in [(), ('--egress-profile', profile)]:
            for key in ['EGRESS_ALLOWED_HOST', 'EGRESS_ALLOWED_PORT']:
                with self.subTest(args=args, missing=key):
                    saved = self.env.pop(key)
                    result = self.run_script('create-session.sh', *args)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.calls(), [])
                    self.env[key] = saved

    def test_named_adyen_uses_selected_profile_ledger_and_role_context(self):
        self.env['KIT_ENV'] = 'team'
        (self.root / '.env.team').write_text(
            'VGS_CLIENT_ID=offline\nVGS_CLIENT_SECRET=offline\nVGS_TENANT=tntoffline\n')
        ledger = self.root / 'private-registrations'
        ledger.mkdir()
        (ledger / 'team-tntoffline-adyen.json').write_text(json.dumps({'adapterId': 'ADofflineAdyen'}))
        self.env['ADAPTER_REGISTRY_DIR'] = str(ledger)
        result = self.run_script('create-fresh-session.sh', '--adapter', 'adyen')
        self.assertEqual(result.returncode, 0, result.stderr)
        attrs = json.loads((self.root / 'session.json').read_text())['data']['attributes']
        self.assertEqual(attrs['adapter'], 'ADofflineAdyen')
        self.assertEqual(attrs['cards'][0]['cvc']['alias'], 'fresh-cvc-alias')
        self.assertEqual(attrs['context']['adyen_expiry_month'], '12')
        self.assertEqual(attrs['context']['adyen_expiry_year'], '2030')
        self.assertTrue(attrs['context']['adyen_generationtime'].endswith('Z'))
        self.assertTrue((self.root / '.state-team/latest-session.json').is_file())

    def test_invalid_profile_name_stops_before_any_api_request(self):
        self.env['KIT_ENV'] = '../../elsewhere'
        result = self.run_script('create-fresh-session.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('KIT_ENV must contain', result.stderr)
        self.assertEqual(self.calls(), [])


    def test_launch_browser_uses_the_created_session_file_and_requested_url(self):
        url = 'https://merchant.invalid/checkout?amount=100&currency=SEK'
        result = self.run_script('create-session.sh', '--launch-browser', '--url', url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ['auth', 'session', 'cloak'])
        opened = json.loads((self.root / 'cloak.json').read_text())
        self.assertEqual(opened, {'session': str(self.root / '.state/sessions/RSoffline.json'),
                                  'id': 'RSoffline', 'url': url})

    def test_fresh_wrapper_passes_browser_flag_and_defaults_to_ip_check(self):
        result = self.run_script('create-fresh-session.sh', '--launch-browser')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ['auth', 'card', 'auth', 'session', 'cloak'])
        opened = json.loads((self.root / 'cloak.json').read_text())
        self.assertEqual(opened['url'], 'https://ipinfo.io/json')

    def test_launch_flag_does_not_open_browser_when_session_creation_fails(self):
        self.env['MOCK_SESSION_CODE'] = '500'
        result = self.run_script('create-session.sh', '--launch-browser')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), ['auth', 'session'])

    def test_missing_cloak_runtime_fails_before_creating_session(self):
        self.env['CLOAK_PYTHON'] = str(self.root / 'missing-python')
        result = self.run_script('create-session.sh', '--launch-browser')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CloakBrowser Python not found', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_browser_failure_preserves_created_session_and_returns_failure(self):
        self.env['MOCK_BROWSER_CODE'] = '7'
        result = self.run_script('create-session.sh', '--launch-browser')
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertTrue((self.root / '.state/sessions/RSoffline.json').is_file())
        self.assertEqual(self.calls(), ['auth', 'session', 'cloak'])

    def test_url_needs_a_value_and_the_launch_flag(self):
        for args in [('--url',), ('--url', '--launch-browser'), ('--url', 'https://merchant.invalid')]:
            with self.subTest(args=args):
                result = self.run_script('create-session.sh', *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('--url requires', result.stderr)
                self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()
