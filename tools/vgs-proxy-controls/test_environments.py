"""Environment isolation checks; synthetic files and fake outbound transport only."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from awg_dev_api import Client, TENANT
from environments import EnvironmentClient, domains
from session_catalog import Catalog, CatalogRegistry, CatalogServer, session_config
from session_operations import validate_card

class EnvironmentsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def credentials(self, environment, tenant=TENANT):
        values = {'VGS_API': domains(environment)['api'], 'VGS_AUTH_URL': domains(environment)['auth'],
                  'VGS_TENANT': tenant, 'VGS_CLIENT_ID': environment + '-fixture', 'VGS_CLIENT_SECRET': environment + '-dummy-secret'}
        path = self.root / (environment + '.env')
        path.write_text('\n'.join(k + '=' + v for k, v in values.items())); return path
    def session(self, environment, tenant=TENANT, sid='RSFIXTURE'):
        directory = self.root / environment; directory.mkdir(exist_ok=True)
        path = directory / (sid + '.json'); urls = domains(environment, tenant)
        attrs = {'state': 'active', 'expires_at': '2099-01-01T00:00:00Z', 'proxy': {'ca_bundle': 'fixture-ca',
                 'pac_url': urls['api'] + '/reveal-sessions/' + sid + '.pac?private=fixture',
                 'url': urls['proxy'].replace('https://', 'https://dummy:secret@')}}
        path.write_text(json.dumps({'data': {'id': sid, 'attributes': attrs}})); return path
    def test_exact_domains_and_no_cross_environment_credentials(self):
        for env in ('dev', 'sandbox', 'live'):
            path = self.credentials(env)
            client = EnvironmentClient(path, env)
            seen = []
            class Opener:
                def open(_, request, **kwargs):
                    seen.append(request)
                    data = {'access_token': 'fixture-token', 'expires_in': 300} if request.full_url == domains(env)['auth'] else {'data': []}
                    response = io.BytesIO(json.dumps(data).encode()); response.status = 200; return response
            client.opener = Opener(); client.api('GET', '/reveal-sessions')
            self.assertEqual([r.full_url for r in seen], [domains(env)['auth'], domains(env)['api'] + '/reveal-sessions'])
            self.assertEqual(seen[-1].get_header('Vgs-tenant'), TENANT)
            for other in set(('dev','sandbox','live')) - {env}:
                with self.assertRaises(ValueError): EnvironmentClient(path, other)
        self.assertEqual(domains('live')['api'], 'https://vgsapi.com')
        with self.assertRaises(AssertionError): Client(self.credentials('live'))
        legacy = Client(self.credentials('dev', 'tntOwnAccount'))
        self.assertEqual(legacy.tenant, 'tntOwnAccount')
    def test_session_files_match_environment_tenant_and_ca(self):
        for env in ('dev', 'sandbox', 'live'):
            path = self.session(env)
            config = session_config(path, 'fixture-ca', env, TENANT)
            self.assertEqual(config['environment'], env)
            self.assertNotIn('?', config['pacSource'])
            for other in set(('dev','sandbox','live')) - {env}:
                with self.assertRaises(ValueError): session_config(path, 'fixture-ca', other, TENANT)
            with self.assertRaises(ValueError): session_config(path, 'fixture-ca', env, 'tntother')
            with self.assertRaises(ValueError): session_config(path, 'different-ca', env, TENANT)
    def test_live_session_port_is_preserved_but_wrong_accounts_and_ports_are_rejected(self):
        path = self.session('live')
        doc = json.loads(path.read_text())
        original = doc['data']['attributes']['proxy']['url']
        doc['data']['attributes']['proxy']['pac_url'] = doc['data']['attributes']['proxy']['pac_url'].replace('https://vgsapi.com', 'https://live.vgsapi.com')
        for port in (3443, 8443):
            doc['data']['attributes']['proxy']['url'] = original.replace(':8443', ':' + str(port))
            path.write_text(json.dumps(doc))
            config = session_config(path, 'fixture-ca', 'live', TENANT)
            self.assertEqual(config['proxies']['session']['port'], port)
            with self.assertRaises(ValueError):session_config(path, 'fixture-ca', 'sandbox', TENANT)
        doc['data']['attributes']['proxy']['url'] = original.replace(':8443', ':443')
        path.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):session_config(path, 'fixture-ca', 'live', TENANT)

    def test_registry_isolates_profiles_and_requires_configuration(self):
        dev = Catalog(self.session('dev'), EnvironmentClient(self.credentials('dev'), 'dev'), self.root/'dev', use_settings=False)
        profile = {'credentials_file': str(self.credentials('sandbox', 'tntsandbox')), 'sessions_directory': str(self.root/'sandbox')}
        registry = CatalogRegistry(dev, {'sandbox': profile})
        sandbox = registry.get('sandbox')
        self.assertEqual(sandbox.tenant, 'tntsandbox'); self.assertEqual(sandbox.environment, 'sandbox')
        self.assertIsNone(sandbox.operations.tokenizer_socket)
        self.assertNotEqual(sandbox.operations.job_path('a'*36), dev.operations.job_path('a'*36))
        self.assertIsNone(registry.get('live'))
        with self.assertRaises(ValueError): CatalogRegistry(dev, {'sandbox': {**profile, 'sessions_directory': str(self.root/'dev')}})
        with patch.object(dev.client, 'api', side_effect=AssertionError('Must not call DEV')):
            server = CatalogServer(None, catalog=dev, profiles={})
            try:
                headers = {'Authorization': 'Bearer ' + server.config['token']}
                def get(path): return urlopen(Request(server.config['url'] + path, headers=headers))
                for env in ('sandbox', 'live'):
                    with get('/environments/' + env + '/account') as response: account = json.load(response)
                    self.assertFalse(account['configured']); self.assertFalse(account['creationAvailable'])
                    self.assertEqual(account['domains']['api'], domains(env)['api'])
                    for route in ('/sessions', '/sessions/RSFIXTURE/config', '/sessions/RSFIXTURE/pac'):
                        with self.assertRaises(HTTPError) as error: get('/environments/' + env + route)
                        self.assertEqual(error.exception.code, 400)
                    with self.assertRaises(HTTPError):
                        urlopen(Request(server.config['url']+'/environments/'+env+'/sessions', data=b'{}', headers={**headers, 'Content-Type':'application/json'}))
            finally: server.close()
    def test_alias_prefix_is_environment_specific(self):
        card = {'number': {'alias':'tok_sandbox_panfixture123', 'storage':'PERSISTENT', 'bin':'411111', 'length':16},
                'cvc': {'alias':'tok_sandbox_cvcfixture123', 'storage':'VOLATILE', 'length':3}}
        validate_card(card, 'dev'); validate_card(card, 'sandbox')
        with self.assertRaises(ValueError): validate_card(card, 'live')
        live = copy.deepcopy(card)
        for a in live.values(): a['alias'] = a['alias'].replace('tok_sandbox_', 'tok_live_')
        validate_card(live, 'live')
        with self.assertRaises(ValueError): validate_card(live, 'dev')

if __name__ == '__main__': unittest.main()
