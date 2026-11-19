"""Read-only catalog/security checks with synthetic DEV-shaped fixtures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import session_catalog as module


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.kit = Path(self.root.name)
        self.patch = patch.object(module, 'KIT', self.kit)
        self.patch.start()
        self.saved = self.kit / '.state-dev/sessions/RSFIRST.json'
        self.saved.parent.mkdir(parents=True)
        self.attributes = {'state': 'active', 'expires_at': '2099-01-01T00:00:00Z', 'allowed_hosts': ['checkout.invalid'],
                           'proxy': {'url': 'https://fixture:dummy@tntFixture.sandbox.verygoodproxy.io:3443',
                                     'pac_url': 'https://sandbox.vgsapi.io/reveal-sessions/RSFIRST.pac?signature=private-fixture',
                                     'ca_bundle': 'fixture-ca'}}
        self.saved.write_text(json.dumps({'data': {'id': 'RSFIRST', 'attributes': self.attributes}}))
        self.calls = []
        outer = self
        class Client:
            def api(self, method, path):
                outer.calls.append((method, path))
                if '?state=' in path:
                    return {'data': [{'id': sid, 'attributes': outer.attributes} for sid in ['RSFIRST', 'RSMISSING']],
                            'meta': {'total_elements': 2}}
                return {'data': {'id': 'RSFIRST', 'attributes': outer.attributes}}
        self.catalog = module.Catalog(self.saved, Client())

    def tearDown(self):
        self.patch.stop()
        self.root.cleanup()

    def test_public_list_and_private_config(self):
        listed = self.catalog.listing()
        self.assertTrue(listed['sessions'][0]['available'])
        self.assertFalse(listed['sessions'][1]['available'])
        self.assertNotIn('dummy', json.dumps(listed))
        self.assertNotIn('signature', json.dumps(listed))
        configured = self.catalog.configuration('RSFIRST')
        self.assertEqual(configured['sessionId'], 'RSFIRST')
        self.assertNotIn('?', configured['pacSource'])
        self.assertEqual({method for method, _ in self.calls}, {'GET'})

    def test_expired_revoked_and_incompatible(self):
        for state in ['expired', 'revoked']:
            self.attributes['state'] = state
            with self.assertRaises(ValueError): self.catalog.configuration('RSFIRST')
        self.attributes['state'] = 'active'
        self.attributes['expires_at'] = '2000-01-01T00:00:00Z'
        with self.assertRaises(ValueError): self.catalog.configuration('RSFIRST')
        with self.assertRaises(ValueError): module.session_config(self.saved, 'other-ca')

    def test_different_ca_uses_existing_local_trust_and_rechecks_selection(self):
        self.catalog.ca = 'original-launch-ca'
        with patch.object(module, 'ca_trusted_locally', return_value=False) as trust:
            listed = self.catalog.listing()['sessions'][0]
            self.assertFalse(listed['available'])
            self.assertIn('trust it locally', listed['reason'])
            with self.assertRaises(ValueError): self.catalog.configuration('RSFIRST')
        with patch.object(module, 'ca_trusted_locally', return_value=True):
            self.assertTrue(self.catalog.listing()['sessions'][0]['available'])
            self.assertEqual(self.catalog.configuration('RSFIRST')['sessionId'], 'RSFIRST')
            with self.assertRaises(ValueError): module.session_config(self.saved, 'original-launch-ca', 'live')
        with patch.object(module, 'ca_trusted_locally', return_value=False):
            with self.assertRaises(ValueError): self.catalog.configuration('RSFIRST')

    def test_loopback_requires_secret_and_rejects_web_origins(self):
        server = module.CatalogServer(None, catalog=self.catalog)
        try:
            url = server.config['url'] + '/sessions'
            for headers in [{}, {'Authorization': 'Bearer wrong'},
                            {'Authorization': 'Bearer ' + server.config['token'], 'Origin': 'https://merchant.invalid'}]:
                with self.assertRaises(HTTPError) as error: urlopen(Request(url, headers=headers))
                self.assertEqual(error.exception.code, 403)
            with urlopen(Request(url, headers={'Authorization': 'Bearer ' + server.config['token']})) as response:
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertEqual(len(json.load(response)['sessions']), 2)
        finally: server.close()

    def test_collect_token_endpoint_is_authenticated_post_only_no_store(self):
        self.catalog.operations.collect_token = Mock(return_value={'accessToken':'fixture-transient','tenantId':'fixture','environment':'dev'})
        server = module.CatalogServer(None,catalog=self.catalog)
        try:
            url=server.config['url']+'/environments/dev/collect-token'
            headers={'Authorization':'Bearer '+server.config['token'],'Content-Type':'application/json'}
            for extra in [{'Authorization':'Bearer wrong'},{'Origin':'https://merchant.invalid'}]:
                with self.assertRaises(HTTPError) as error: urlopen(Request(url,data=b'{"tenantId":"fixture","method":"aliases"}',headers={**headers,**extra}))
                self.assertEqual(error.exception.code,403)
            self.catalog.operations.collect_token.assert_not_called()
            with self.assertRaises(HTTPError): urlopen(Request(url,headers=headers))
            with urlopen(Request(url,data=b'{"tenantId":"fixture","method":"aliases"}',headers=headers)) as response:
                self.assertEqual(response.headers['Cache-Control'],'no-store')
                self.assertEqual(json.load(response)['accessToken'],'fixture-transient')
            self.catalog.operations.collect_token.assert_called_once_with({'tenantId':'fixture','method':'aliases'})
        finally: server.close()

    def test_recording_endpoints_are_local_authenticated_and_do_not_require_account(self):
        recorder = Mock()
        recorder.status.return_value = {'state':'idle', 'recording':False}
        recorder.start.return_value = {'state':'starting'}
        recorder.stop.return_value = {'state':'stopping'}
        server = module.CatalogServer(None, catalog=self.catalog, recording=recorder)
        try:
            url = server.config['url'] + '/environments/sandbox/recording'
            headers = {'Authorization':'Bearer '+server.config['token'], 'Content-Type':'application/json'}
            for extra in ({'Authorization':'Bearer wrong'}, {'Origin':'https://merchant.invalid'}):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(url+'/start', data=b'{}', headers={**headers, **extra}))
                self.assertEqual(error.exception.code, 403)
            recorder.start.assert_not_called()
            with urlopen(Request(url, headers=headers)) as response:
                self.assertEqual(json.load(response)['state'], 'idle')
            with urlopen(Request(url+'/start', data=b'{"requestId":"fixture"}', headers=headers)) as response:
                self.assertEqual(json.load(response)['state'], 'starting')
            recorder.start.assert_called_once_with({'requestId':'fixture','environment':'sandbox'})
            with urlopen(Request(url+'/stop', data=b'{}', headers=headers)) as response:
                self.assertEqual(json.load(response)['state'], 'stopping')
            self.assertEqual(self.calls, [])
        finally: server.close()
        recorder.close.assert_called_once()

    def test_file_picker_requires_auth_and_works_before_account_connection(self):
        picker = Mock()
        job = {'requestId':'12345678-1234-1234-1234-123456789abc', 'environment':'sandbox', 'status':'pending'}
        picker.start.return_value = job
        picker.status.return_value = {**job, 'status':'selected', 'credentialsFile':'/tmp/account.json'}
        server = module.CatalogServer(None, catalog=self.catalog, file_picker=picker)
        try:
            url = server.config['url'] + '/environments/sandbox/credentials/picker'
            headers = {'Authorization':'Bearer '+server.config['token'], 'Content-Type':'application/json'}
            for extra in [{'Authorization':'Bearer wrong'}, {'Origin':'https://merchant.invalid'}]:
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(url, data=b'{}', headers={**headers, **extra}))
                self.assertEqual(error.exception.code, 403)
            picker.start.assert_not_called()
            with urlopen(Request(url, data=b'{}', headers=headers)) as response:
                self.assertEqual(json.load(response), job)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
            picker.start.assert_called_once_with('sandbox')
            with urlopen(Request(url+'/'+job['requestId'], headers=headers)) as response:
                self.assertEqual(json.load(response)['credentialsFile'], '/tmp/account.json')
            picker.status.assert_called_once_with('sandbox', job['requestId'])
            self.assertEqual(self.calls, [])
        finally: server.close()
        picker.close.assert_called_once()


if __name__ == '__main__': unittest.main()
