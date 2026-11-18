"""Read-only catalog/security checks with synthetic DEV-shaped fixtures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
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
                           'proxy': {'url': 'https://fixture:dummy@tntmdki2teh.sandbox.verygoodproxy.io:3443',
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


if __name__ == '__main__': unittest.main()
