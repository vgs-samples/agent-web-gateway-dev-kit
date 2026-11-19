"""Synthetic evidence + fake DEV API; never sends merchant traffic."""
import copy
import base64
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from capture_repair import CaptureRepair
from session_operations import private_json


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cid = 'CAP' + 'a'*32
        self.policy = {'version': 1, 'environment': 'dev', 'tenantId': 'tntFixture', 'automatic': True,
            'merchants': [{'host': 'shop.invalid', 'paymentHosts': [{'host': 'pay.invalid',
                'pathPrefix': '/hpp/', 'destinationTrust': True,
                'cardFields': {'card_number': 'cardNumber', 'card_cvc': 'securityCode'}}]}]}
        private_json(self.root/'policy.json', self.policy)
        private_json(self.root/'RSFIXTURE.json', {'data': {'id': 'RSFIXTURE', 'attributes': {'session_aliases': [
            {'format': 'card_number', 'value': 'synthetic-pan'}, {'format': 'card_cvc', 'value': 'synthetic-cvc'}]}}})
        self.har = {'log': {'_capture': {'stoppedAt': '2026-11-18T23:49:00Z', 'testUrl': 'https://shop.invalid/checkout',
            'testContext': {'environment': 'dev', 'sessionId': 'RSFIXTURE'}}, 'entries': [{
            'request': {'method': 'POST', 'url': 'https://pay.invalid/hpp/process', 'postData': {
                'mimeType': 'application/x-www-form-urlencoded; charset=UTF-8',
                'text': 'cardNumber=synthetic-pan&securityCode=synthetic-cvc&name=PRIVATE'}},
            'response': {'status': 403, 'content': {'text': json.dumps({'error': 'reveal_refused',
                'reason': 'guard_refused', 'host': 'pay.invalid', 'session_id': 'RSFIXTURE'})}}}]}}
        self.destinations, self.writes = [], []
        self.timeout = False
        self.session = {'allowed_hosts': [], 'unlisted_host_mode': 'guarded'}
        catalog = SimpleNamespace(tenant='tntFixture', environment='dev', saved=lambda sid: self.root/(sid+'.json'), client=self)
        self.registry = SimpleNamespace(get=lambda env: catalog if env == 'dev' else None)
        self.engine = CaptureRepair(self.registry, self.root, self.root/'policy.json')
    def tearDown(self): self.temp.cleanup()
    def api(self, method, path, attributes=None, **kwargs):
        if method == 'GET':
            if path.startswith('/reveal-sessions/'): return {'data': {'attributes': copy.deepcopy(self.session)}}
            if path == '/agent-gateway-destinations': return {'data': copy.deepcopy(self.destinations)}
            return {'data': copy.deepcopy(next(r for r in self.destinations if path.endswith('/'+r['id'])))}
        self.writes.append((method, path, attributes))
        if self.timeout: raise TimeoutError('PRIVATE')
        if method == 'POST':
            row = {'id': 'AGDFIXTURE', 'attributes': attributes}
            self.destinations.append(row)
        else:
            row = next(r for r in self.destinations if path.endswith('/'+r['id']))
            row['attributes'].update(attributes)
        return {'data': copy.deepcopy(row)}
    def run_repair(self, apply=True):
        private_json(self.root/(self.cid+'.har'), self.har)
        result = self.engine.run(self.cid, apply=apply)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('synthetic-pan', json.dumps(result))
        return result
    def test_create_readback_and_restart_are_idempotent(self):
        self.assertEqual(self.run_repair(False)['status'], 'planned')
        self.assertFalse(self.writes)
        result = self.run_repair()
        self.assertEqual(result['status'], 'repaired')
        self.assertTrue(result['readbackVerified'])
        self.assertFalse(result['paymentRetried'])
        self.engine = CaptureRepair(self.registry, self.root, self.root/'policy.json')
        self.assertEqual(self.run_repair()['status'], 'configured')
        self.assertEqual(len(self.writes), 1)
    def test_guarded_exact_rule_is_patched(self):
        self.destinations = [{'id': 'AGDFIXTURE', 'attributes': {'host_pattern': 'pay.invalid', 'action': 'guarded'}}]
        self.assertEqual(self.run_repair()['status'], 'repaired')
        self.assertEqual(self.writes[0][0], 'PATCH')
    def test_timeout_never_retries_even_for_a_new_capture(self):
        self.timeout = True
        self.assertEqual(self.run_repair()['status'], 'unconfirmed')
        self.cid = 'CAP'+'b'*32
        self.assertEqual(self.run_repair()['status'], 'unconfirmed')
        self.assertEqual(len(self.writes), 1)
    def test_block_and_wildcard_are_never_overridden(self):
        for host, action in [('pay.invalid','block'), ('*.invalid','block'), ('*.invalid','guarded')]:
            self.destinations = [{'id': 'AGDFIXTURE', 'attributes': {'host_pattern': host, 'action': action}}]
            self.assertEqual(self.run_repair()['status'], 'needs-review')
        self.assertFalse(self.writes)
    def test_incomplete_wrong_environment_merchant_session_and_card_never_write(self):
        original = copy.deepcopy(self.har)
        variants = []
        for key, value in [('stoppedAt',None), ('testUrl','https://evil.invalid/')]:
            row = copy.deepcopy(original); row['log']['_capture'][key] = value; variants.append(row)
        row = copy.deepcopy(original); row['log']['_capture']['testContext']['environment'] = 'live'; variants.append(row)
        row = copy.deepcopy(original); row['log']['entries'][0]['request']['postData']['text'] = 'cardNumber=synthetic-pan'; variants.append(row)
        row = copy.deepcopy(original); row['log']['entries'][0]['response']['content']['text'] = '{}'; variants.append(row)
        for row in variants:
            self.har = row
            self.assertEqual(self.run_repair()['status'], 'needs-review')
        self.assertFalse(self.writes)
    def test_session_host_allowlist_is_not_silently_relaxed(self):
        self.session['allowed_hosts'] = ['shop.invalid']
        self.assertEqual(self.run_repair()['status'], 'needs-review')
        self.assertFalse(self.writes)
    def test_proxy_failure_is_identified_without_a_destination_change(self):
        entry = self.har['log']['entries'][0]
        entry['response'] = {'status': 0, 'content': {}}
        entry['_error'] = 'net::ERR_TUNNEL_CONNECTION_FAILED'
        result = self.run_repair()
        self.assertEqual(result['findings'][0]['category'], 'proxy-connection')
        self.assertEqual(result['status'], 'needs-review')
        self.assertFalse(self.writes)
    def test_authenticated_decline_takes_priority_over_later_unrelated_proxy_error(self):
        cres = base64.urlsafe_b64encode(json.dumps({'messageType':'CRes', 'transStatus':'Y',
                                                  'acsTransID':'PRIVATE'}).encode()).decode().rstrip('=')
        self.har['log']['entries'] = [
            {'request':{'url':'https://authentication.invalid/complete','method':'POST'},
             'response':{'status':200,'content':{'mimeType':'application/json',
                 'text':json.dumps({'Payload':{'CRes':cres}})}}},
            {'request':{'url':'https://pay.invalid/hpp/result','method':'GET'},
             'response':{'status':200,'content':{'mimeType':'text/html',
                 'text':'<h2>Declined</h2><p>PRIVATE</p>'}}},
            {'request':{'url':'https://unrelated.invalid/script','method':'GET'},
             'response':{'status':0,'content':{}},'_error':'net::ERR_TUNNEL_CONNECTION_FAILED'}]
        result = self.run_repair()
        self.assertEqual(result['status'], 'payment-declined')
        self.assertTrue(result['threeDSAuthenticated'])
        self.assertFalse(result['requiresConfigurationChange'])
        self.assertFalse(self.writes)
        saved = json.loads((self.root/'repairs'/(self.cid+'.json')).read_text())
        self.assertEqual(saved, result)
    def test_processor_json_refusal_is_diagnosed_without_an_automatic_repair(self):
        entry = self.har['log']['entries'][0]
        entry['response'] = {'status':200, 'content': {'mimeType':'application/json',
            'text':json.dumps({'payment_status':'REFUSED','card':'PRIVATE'})}}
        result = self.run_repair()
        self.assertEqual(result['status'], 'payment-declined')
        self.assertFalse(result['threeDSAuthenticated'])
        self.assertFalse(self.writes)
    def test_unrelated_hosts_and_hidden_error_templates_do_not_establish_a_decline(self):
        entry = self.har['log']['entries'][0]
        for url, body in [
                ('https://unrelated.invalid/hpp/result','<h2>Declined</h2>'),
                ('https://pay.invalid/unapproved/result','<h2>Declined</h2>'),
                ('https://pay.invalid/hpp/result','<script>const error = "<h2>Declined</h2>";</script>'),
                ('https://pay.invalid/hpp/result','<div hidden><h2>Declined</h2></div><h2>Processing</h2>'),
                ('https://pay.invalid/hpp/result','<template><h2>Declined</h2></template>')]:
            entry['request']['url'] = url
            entry['response'] = {'status':200,'content':{'mimeType':'text/html','text':body}}
            self.assertEqual(self.run_repair()['status'], 'needs-review')
        self.assertFalse(self.writes)
    def test_policy_tenant_change_and_public_permissions_rejected(self):
        self.policy['tenantId'] = 'tntOther'; private_json(self.root/'policy.json', self.policy)
        with self.assertRaises(ValueError): self.run_repair()
        (self.root/'policy.json').chmod(0o644)
        with self.assertRaises(ValueError): self.run_repair()
        self.assertFalse(self.writes)


if __name__ == '__main__': unittest.main()
