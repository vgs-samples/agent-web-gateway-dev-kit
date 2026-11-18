"""Mutations use synthetic local fixtures; never account or card credentials."""
import base64
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid
from session_operations import Operations, private_json, validated_options
from capture_preferences import HAR_PREFERENCE, prepare_profile, har_recording_filter

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name)
        self.egress = self.path / 'egress.json'
        private_json(self.egress, {'scheme': 'http', 'hostname': 'egress.fixture', 'port': 3128, 'username': 'fixture', 'password': 'not-real'})
        self.calls = []
        outer = self
        class Client:
            def token(self):
                return 'header.' + base64.urlsafe_b64encode(json.dumps({'scope': 'cards:write reveal-sessions:read reveal-sessions:write'}).encode()).decode() + '.sig'
            def api(self, method, path, attrs, kind, **kw):
                outer.calls.append((method, path, attrs, kind))
                return {'data': {'id': 'RSCREATED', 'attributes': {'tokens': [{'format': 'card_number', 'value': 'standin-only', 'alias': 'hidden-alias'}]}}}
        self.client = Client()
        self.operations = Operations(self.client, self.path / 'sessions', egress_file=self.egress)
        self.options = {'requestId': str(uuid.uuid4()), 'source': 'aliases', 'allowedHosts': ['PAY.EXAMPLE.com'], 'adapter': '',
            'card': {'number': {'alias': 'tok_sandbox_panfixture123', 'bin': '411111', 'length': 16, 'storage': 'PERSISTENT'},
                     'cvc': {'alias': 'tok_sandbox_cvcfixture123', 'length': 3, 'storage': 'VOLATILE'}}}
    def tearDown(self): self.temp.cleanup()
    def finished(self):
        for _ in range(200):
            r = self.operations.status(self.options['requestId'])
            if r['status'] != 'running': return r
            time.sleep(.01)
        self.fail('Job did not finish')
    def test_private_idempotent_creation(self):
        self.operations.create(self.options); r = self.finished()
        self.assertEqual(r['status'], 'complete'); self.assertEqual(len(self.calls), 1)
        attrs = self.calls[0][2]
        self.assertEqual(attrs['allowed_hosts'], ['pay.example.com'])
        self.assertEqual([a['storage'] for a in attrs['aliases']], ['PERSISTENT', 'VOLATILE'])
        self.assertEqual(attrs['egress_proxy_settings']['hostname'], 'egress.fixture')
        self.operations.create(self.options)
        restarted = Operations(self.client, self.path / 'sessions', egress_file=self.egress)
        restarted.create(self.options); self.assertEqual(len(self.calls), 1)
        for p in (self.path / 'sessions').rglob('*.json'): self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        for secret in ('hidden-alias', 'not-real', 'fingerprint'): self.assertNotIn(secret, json.dumps(r))
    def test_invalid_inputs_never_send(self):
        for mutate in [lambda o: o.update(pan='raw'), lambda o: o.update(allowedHosts=['*.example.com']),
                lambda o: o['card']['number'].update(alias='4111111111111111'),
                lambda o: o['card']['cvc'].update(storage='PERSISTENT'), lambda o: o['card']['cvc'].update(alias='123')]:
            v=copy.deepcopy(self.options); mutate(v)
            with self.assertRaises(ValueError): self.operations.create(v)
        self.assertEqual(self.calls, []); self.assertFalse((self.path / 'sessions').exists())
    def test_timeout_does_not_retry_or_guess_success(self):
        with patch.object(self.client, 'api', side_effect=TimeoutError('SECRET error')) as api:
            self.operations.create(self.options); r = self.finished()
            self.assertEqual(r['status'], 'unknown'); self.assertNotIn('SECRET', json.dumps(r))
            self.operations.create(self.options); self.assertEqual(api.call_count, 1)
        v=copy.deepcopy(self.options); v['allowedHosts']=['other.example.com']
        with self.assertRaises(ValueError): self.operations.create(v)
    def test_fresh_tokenizer_is_used(self):
        v=copy.deepcopy(self.options); v['source']='tokenizer'; del v['card']
        with patch.object(self.operations, 'fresh_card', return_value=validated_options(self.options)['card']) as tokenize:
            self.operations.create(v); self.finished(); self.assertEqual(tokenize.call_count,1)
        self.assertEqual(len(self.calls),1)
    def test_claims_distinguish_missing_scopes(self):
        v=self.operations.account(); self.assertTrue(v['connected']); self.assertTrue(v['cardsWriteGranted'])
        scopes={s['name']:s['granted'] for s in v['scopes']}
        self.assertFalse(scopes['cards:create']); self.assertFalse(scopes['aliases:write']); self.assertTrue(scopes['reveal-sessions:write'])
        self.assertNotIn('not-real',json.dumps(v))
    def test_collect_token_is_tenant_bound_scope_checked_and_never_persisted(self):
        with self.assertRaises(ValueError): self.operations.collect_token({'tenantId':self.operations.tenant,'method':'aliases'})
        claims = base64.urlsafe_b64encode(json.dumps({'scope':'aliases:write'}).encode()).decode()
        token = 'fixture.' + claims + '.sig'
        with patch.object(self.client,'token',return_value=token):
            for value in [{}, {'tenantId':'other'}, {'tenantId':self.operations.tenant,'method':'aliases','pan':'rejected'}]:
                with self.assertRaises(ValueError): self.operations.collect_token(value)
            result = self.operations.collect_token({'tenantId':self.operations.tenant,'method':'aliases'})
            self.assertEqual(result,{'accessToken':token,'tenantId':self.operations.tenant,'environment':'dev','method':'aliases'})
            self.assertNotIn(token,json.dumps(self.operations.account()))
        card=self.operations.collect_token({'tenantId':self.operations.tenant,'method':'card'})
        self.assertEqual(card['method'],'card')
        self.assertFalse((self.path/'sessions').exists())
        self.assertEqual(self.calls,[])

    def test_interrupted_journal_is_uncertain(self):
        rid=self.options['requestId']; private_json(self.operations.job_path(rid),{'requestId':rid,'status':'running'})
        self.assertEqual(self.operations.status(rid)['status'],'unknown')
    def test_har_filter_excludes_collect_and_local_authorization(self):
        pattern=har_recording_filter()
        for url in ['http://127.0.0.1:1234/environments/dev/collect-token','http://localhost:1234/account','http://[::1]:1234/collect-token','https://tntFixture.sandbox.vault-api.verygoodvault.io/aliases','https://tntFixture.live.vault-api.verygoodvault.com/aliases','https://sandbox.vgsapi.io/cards','https://vgsapi.com/cards']:
            self.assertIsNone(pattern.search(url))
        for url in ['https://securev2.global-e.com/1/Payments/example','http://awg-toggle.test:1234/egress','https://shop.example/verygoodvault.com']:
            self.assertIsNotNone(pattern.search(url))

    def test_har_pref_seed_never_overwrites(self):
        p=self.path/'profile'; prepare_profile(p)
        pref=json.loads((p/'Default/Preferences').read_text())
        self.assertEqual(pref['devtools']['synced_preferences_sync_disabled'][HAR_PREFERENCE],'true')
        with self.assertRaises(ValueError):prepare_profile(p)
        self.operations.capture_profile=p;self.assertTrue(self.operations.account()['sensitiveHarEnabled'])

class TokenizerTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('private_tokenizer', Path(__file__).with_name('private-card-tokenizer.py'))
        self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        self.supplied = {'pan': '4' + '1' * 15, 'cvc': '123', 'exp_month': 10, 'exp_year': 30}
    def test_cards_requires_both_aliases_and_matching_tenant(self):
        from types import SimpleNamespace
        response = {'metadata': {'observability': {'vault_id': 'tntFixture'}}, 'data': {'attributes': {
            'last4': '1111', 'pan_alias': 'tok_sandbox_panfixture123', 'cvc_alias': 'tok_sandbox_cvcfixture123'}}}
        calls = []
        client = SimpleNamespace(api=lambda *a, **kw: (calls.append((a, kw)), copy.deepcopy(response))[1])
        result = self.module.tokenize(client, self.supplied, 'cards')
        self.assertEqual(calls[0][0][:2], ('POST', '/cards'))
        self.assertEqual(result['card']['cvc']['storage'], 'VOLATILE')
        self.assertNotIn(self.supplied['pan'], json.dumps(result))
        response['data']['attributes']['cvc_alias'] = None
        with self.assertRaises(ValueError): self.module.tokenize(client, self.supplied, 'cards')
        response['metadata']['observability']['vault_id'] = 'other'
        with self.assertRaises(ValueError): self.module.tokenize(client, self.supplied, 'cards')
    def test_alias_method_uses_only_tenant_sandbox_api_and_correct_storage(self):
        import io
        from types import SimpleNamespace
        supplied = self.supplied
        outer = self
        class Opener:
            def open(self, request, **kw):
                outer.assertEqual(request.full_url, 'https://tntFixture.sandbox.vault-api.verygoodvault.io/aliases')
                data = json.loads(request.data)['data']
                outer.assertEqual([d['storage'] for d in data], ['PERSISTENT', 'VOLATILE'])
                rows = [dict(d, aliases=[{'alias': 'tok_sandbox_fixture' + str(i) * 8, 'format': 'UUID'}]) for i, d in enumerate(data)]
                r = io.BytesIO(json.dumps({'data': rows}).encode()); r.status = 201; return r
        result = self.module.tokenize(SimpleNamespace(token=lambda:'fixture', opener=Opener()), supplied, 'aliases')
        self.assertNotIn(supplied['pan'], json.dumps(result))
        self.assertEqual(result['card']['number']['storage'], 'PERSISTENT')

if __name__=='__main__':unittest.main()
