"""Local synthetic proxy fixtures only; no external routes or accounts."""
import concurrent.futures
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import uuid

from egress_profiles import EgressProfiles, EgressProfileError
from session_form import validate_dashboard_options
from session_operations import Operations


class EgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'private/proxies.json'
        self.store = EgressProfiles(self.path)
        self.value = {'name': 'Office', 'proxy': {'scheme': 'https', 'hostname': 'proxy.invalid', 'port': 8443,
                      'username': 'fixture-user', 'password': 'fixture-secret'}}

    def tearDown(self): self.tmp.cleanup()

    def test_multiple_profiles_survive_restart_without_exposing_auth(self):
        first = self.store.save(self.value)
        self.store.save({'name': 'Other', 'proxy': {'scheme': 'http', 'hostname': 'other.invalid', 'port': 3128}})
        restored = EgressProfiles(self.path)
        listed = restored.listing()
        self.assertEqual(len(listed['egressProfiles']), 2)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        for secret in ('fixture-user', 'fixture-secret', 'password', 'username'):
            self.assertNotIn(secret, json.dumps([first, listed]))
        self.assertEqual(restored.resolve(first['savedEgressProfileId'])['password'], 'fixture-secret')
        self.assertFalse(listed['egressProfiles'][1]['hasAuthentication'])

    def test_validation_duplicate_names_missing_ids_and_failed_write(self):
        self.store.save(self.value)
        original = self.path.read_bytes()
        for bad in [{**self.value, 'name': ' office '}, {**self.value, 'name': ''},
                    {**self.value, 'file': '/tmp/elsewhere'},
                    {'name':'Other','proxy':{**self.value['proxy'],'port':True}},
                    {'name':'Other','proxy':{**self.value['proxy'],'password':''}}]:
            with self.assertRaises(EgressProfileError): self.store.save(bad)
        for id in ['../elsewhere', '0' * 32]:
            with self.assertRaises(EgressProfileError): self.store.resolve(id)
        with patch('egress_profiles.os.replace', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError): self.store.save({**self.value, 'name':'Other'})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ['proxies.json','proxies.json.lock'])

    def test_concurrent_saves_do_not_lose_profiles(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: EgressProfiles(self.path).save({**self.value,'name':str(i)}), range(12)))
        self.assertEqual(len(self.store.listing()['egressProfiles']), 12)

    def test_rejects_insecure_or_corrupt_file_without_overwriting(self):
        self.store.save(self.value)
        self.path.chmod(0o644)
        with self.assertRaises(EgressProfileError): self.store.listing()
        self.path.chmod(0o600); self.path.write_text('broken')
        with self.assertRaises(EgressProfileError): self.store.save(self.value)
        self.assertEqual(self.path.read_text(), 'broken')
        self.path.unlink(); self.path.symlink_to(self.path.parent/'elsewhere')
        with self.assertRaises(OSError): self.store.save(self.value)

    def test_session_resolves_credentials_locally_and_respects_locked_profile(self):
        saved = self.store.save(self.value)
        options = {'requestId':str(uuid.uuid4()),'aliases':[{'alias':'tok_dev_fixture_alias','format':'text','storage':'PERSISTENT'}],
                   'egressMode':'saved','egressProfileId':saved['savedEgressProfileId']}
        parsed = validate_dashboard_options(options, 'dev')
        ops = Operations(object(), self.path.parent/'sessions'); ops.egress_profiles = self.store
        self.assertEqual(ops.session_egress(parsed)['password'], 'fixture-secret')
        for changes in [{'egressProfileId':'../file'}, {'egressMode':'none'}, {'egress':self.value['proxy']}]:
            with self.assertRaises(ValueError): validate_dashboard_options({**options, **changes}, 'dev')
        with patch('session_operations.load_egress', return_value=self.value['proxy']):
            with self.assertRaises(ValueError): ops.session_egress(parsed)

    def test_saved_profile_reaches_session_request_but_not_job_status(self):
        from unittest.mock import Mock
        client = Mock(environment='dev', tenant='fixture')
        client.api.return_value = {'data': {'id':'RSFIXTURE', 'attributes':{'tokens':[]}}}
        ops = Operations(client, self.path.parent/'sessions'); ops.egress_profiles = self.store
        selected = self.store.save(self.value)['savedEgressProfileId']
        rid = str(uuid.uuid4())
        options = {'requestId':rid, 'aliases':[{'alias':'tok_dev_fixture_alias','format':'text','storage':'PERSISTENT'}],
                   'egressMode':'saved','egressProfileId':selected}
        ops.create(options)
        for _ in range(200):
            status = ops.status(rid)
            if status['status'] != 'running': break
            time.sleep(.01)
        self.assertEqual(status['status'], 'complete')
        self.assertEqual(client.api.call_args.args[2]['egress_proxy_settings']['password'], 'fixture-secret')
        self.assertNotIn('fixture-secret', json.dumps(status))
        ops.create(options); self.assertEqual(client.api.call_count, 1)

    def test_api_auth_safe_responses_and_local_only(self):
        from session_catalog import Catalog, CatalogServer
        from unittest.mock import Mock
        client = Mock(environment='dev', tenant='fixture')
        catalog = Catalog(None, client, self.path.parent/'sessions', ca_bundle='fixture-ca', use_settings=False)
        server = CatalogServer(None, catalog=catalog, profiles={})
        try:
            url = server.config['url'] + '/environments/dev/egress-profiles'
            headers = {'Authorization':'Bearer ' + server.config['token'], 'Content-Type':'application/json'}
            for extra in [{'Authorization':'Bearer wrong'}, {'Origin':'https://merchant.invalid'}]:
                with self.assertRaises(HTTPError) as result:
                    urlopen(Request(url, data=json.dumps(self.value).encode(), headers={**headers,**extra}))
                self.assertEqual(result.exception.code,403)
            with urlopen(Request(url, data=json.dumps(self.value).encode(), headers=headers)) as response:
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                saved = json.load(response)
                self.assertNotIn('fixture-secret', json.dumps(saved))
            with urlopen(Request(url,headers=headers)) as response:
                self.assertEqual(json.load(response)['egressProfiles'], saved['egressProfiles'])
            with self.assertRaises(HTTPError) as result:
                urlopen(Request(url, data=json.dumps(self.value).encode(), headers=headers))
            self.assertIn('already saved', json.load(result.exception)['egressError'])
            client.api.assert_not_called(); client.token.assert_not_called()
        finally: server.close()


if __name__ == '__main__': unittest.main()
