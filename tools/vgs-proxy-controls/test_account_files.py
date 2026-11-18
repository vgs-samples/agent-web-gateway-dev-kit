"""Local account-file setup with mocked VGS transport; never contacts VGS."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from account_files import AccountFileError, read_account_file
from environments import EnvironmentClient, domains
from session_catalog import Catalog, CatalogRegistry, CatalogServer

TOKEN = 'fixture.' + base64.urlsafe_b64encode(json.dumps({'scope':'reveal-sessions:read reveal-sessions:write aliases:write','clientAnnotations':{'vgs.io/vault-id':'tntfixture'}}).encode()).decode().rstrip('=') + '.fixture'

class AccountFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.path=self.root/'account.txt'; self.path.write_text('clientId="fixture-account"\nclientSecret="fixture-secret"')
    def tearDown(self): self.temp.cleanup()
    def initial(self):
        env=self.root/'dev.env';env.write_text('VGS_TENANT=tntfixture\nVGS_CLIENT_ID=fixture\nVGS_CLIENT_SECRET=dummy\nVGS_ENVIRONMENT=dev')
        return Catalog(None,EnvironmentClient(env,'dev'),self.root/'sessions',ca_bundle='fixture-ca',use_settings=False)
    def test_dashboard_download_and_json_and_env_are_data_only(self):
        values=read_account_file(str(self.path),'dev','tntfixture')
        self.assertEqual(values['VGS_CLIENT_ID'],'fixture-account')
        self.assertEqual(values['VGS_API'],domains('dev')['api'])
        with self.assertRaisesRegex(AccountFileError,'tenant ID'):read_account_file(str(self.path),'dev')
        self.path.write_text(json.dumps({'tenant_id':'tntfixture','client_id':'fixture-account','client_secret':'$(touch should-never-run)'}))
        self.assertEqual(read_account_file(str(self.path),'dev')['VGS_CLIENT_SECRET'],'$(touch should-never-run)')
        self.path.write_text('export VGS_TENANT="tntfixture"\nVGS_CLIENT_ID=fixture\nVGS_CLIENT_SECRET=dummy\nVGS_API=https://sandbox.vgsapi.io')
        self.assertEqual(read_account_file(str(self.path),'dev')['VGS_TENANT'],'tntfixture')
        with self.assertRaisesRegex(AccountFileError,'different environment'):read_account_file(str(self.path),'sandbox')
    def test_cli_service_account_yaml_and_json_use_exported_vaults(self):
        self.path.write_text('apiVersion: 1.0.0\nkind: ServiceAccount\ndata:\n  clientId: fixture-id\n  clientSecret: fixture-secret\n  name: Example\n  scopes:\n  - name: reveal-sessions:write\n  vaults:\n  - tntfixture\n')
        self.assertEqual(read_account_file(str(self.path),'dev')['VGS_TENANT'],'tntfixture')
        self.path.write_text(self.path.read_text().replace('  - tntfixture', '  - tntfixture\n  - tntsecond'))
        with self.assertRaisesRegex(AccountFileError,'tenant ID'):read_account_file(str(self.path),'dev')
        self.assertEqual(read_account_file(str(self.path),'dev','tntsecond')['VGS_TENANT'],'tntsecond')
        with self.assertRaisesRegex(AccountFileError,'listed'):read_account_file(str(self.path),'dev','tntother')
        self.path.write_text(json.dumps({'apiVersion':'1.0.0','kind':'ServiceAccount','data':{'clientId':'fixture-id','clientSecret':'fixture-secret','vaults':['tntfixture']}}))
        self.assertEqual(read_account_file(str(self.path),'dev')['VGS_CLIENT_SECRET'],'fixture-secret')
        self.path.write_text(json.dumps({'data':{'attributes':{'client_id':'fixture-id','client_secret':'fixture-secret'}}}))
        self.assertEqual(read_account_file(str(self.path),'dev','tntfixture')['VGS_CLIENT_ID'],'fixture-id')
    def test_bad_files_do_not_echo_contents(self):
        for content in ['not parseable fixture-secret', '{"client_secret": "fixture-secret"}', 'clientId=a\nclientId=b\nclientSecret=fixture-secret']:
            self.path.write_text(content)
            with self.assertRaises(AccountFileError) as caught:read_account_file(str(self.path),'dev','tntfixture')
            self.assertNotIn('fixture-secret',str(caught.exception))
        for filename in ['relative.txt',str(self.root),str(self.root/'missing')]:
            with self.assertRaises(AccountFileError):read_account_file(filename,'dev','tntfixture')
        self.path.write_text('x'*65537)
        with self.assertRaises(AccountFileError):read_account_file(str(self.path),'dev','tntfixture')
    @patch.object(EnvironmentClient,'api',return_value={'data':[]})
    @patch.object(EnvironmentClient,'token',return_value=TOKEN)
    def test_connect_persists_only_paths_and_separates_tenants(self,token,api):
        self.path.write_text(json.dumps({'clientId':'fixture','clientSecret':'dummy','vaults':['tntsandbox','tntother']}))
        initial=self.initial();registry=CatalogRegistry(initial)
        account=registry.connect('sandbox',{'credentialsFile':str(self.path),'tenantId':'tntsandbox'})
        self.assertTrue(account['creationAvailable']);self.assertEqual(account['tenantId'],'tntsandbox')
        self.assertNotIn('fixture-secret',json.dumps(account))
        persisted=registry.profile_file.read_text();self.assertNotIn('fixture-secret',persisted)
        self.assertEqual(registry.profile_file.stat().st_mode&0o777,0o600)
        self.assertIs(registry.get('dev'),initial)
        restored=CatalogRegistry(initial);self.assertEqual(restored.get('sandbox').tenant,'tntsandbox')
        self.assertIsNone(restored.get('sandbox').operations.tokenizer_socket)
        first=restored.get('sandbox').sessions_directory
        restored.connect('sandbox',{'credentialsFile':str(self.path),'tenantId':'tntother'})
        self.assertNotEqual(first,restored.get('sandbox').sessions_directory)
        self.assertTrue(all(call.args[0]=='GET' for call in api.call_args_list))
    @patch.object(EnvironmentClient,'api',side_effect=RuntimeError('fixture-secret'))
    @patch.object(EnvironmentClient,'token',return_value=TOKEN)
    def test_failed_connect_keeps_previous_account(self,token,api):
        initial=self.initial();registry=CatalogRegistry(initial)
        with self.assertRaisesRegex(AccountFileError,'cannot read sessions'):
            registry.connect('dev',{'credentialsFile':str(self.path)})
        self.assertIs(registry.get('dev'),initial);self.assertFalse(registry.profile_file.exists())
    @patch.object(EnvironmentClient,'api',return_value={'data':[]})
    @patch.object(EnvironmentClient,'token',return_value=TOKEN)
    def test_authenticated_local_endpoint_loads_file_and_returns_safe_errors(self,token,api):
        server=CatalogServer(None,catalog=self.initial(),profiles={})
        try:
            headers={'Authorization':'Bearer '+server.config['token'],'Content-Type':'application/json'}
            url=server.config['url']+'/environments/dev/credentials'
            body=json.dumps({'credentialsFile':str(self.path),'tenantId':'tntfixture'}).encode()
            with self.assertRaises(HTTPError) as error:urlopen(Request(url,data=body,headers={**headers,'Origin':'https://merchant.invalid'}))
            self.assertEqual(error.exception.code,403);error.exception.close()
            with urlopen(Request(url,data=body,headers=headers)) as response:result=json.load(response)
            self.assertTrue(result['creationAvailable']);self.assertNotIn('fixture-secret',json.dumps(result))
            with self.assertRaises(HTTPError) as error:urlopen(Request(url,data=b'{"credentialsFile":"/missing/account"}',headers=headers))
            safe=json.load(error.exception);error.exception.close()
            self.assertIn('local file',safe['accountError'])
        finally:server.close()

    @patch.object(EnvironmentClient,'api',return_value={'data':[]})
    @patch.object(EnvironmentClient,'token',return_value=TOKEN)
    def test_dashboard_export_connects_without_tenant_input(self,token,api):
        registry=CatalogRegistry(self.initial())
        account=registry.connect('dev',{'credentialsFile':str(self.path)})
        self.assertEqual(account['tenantId'],'tntfixture');self.assertTrue(account['creationAvailable'])
        self.assertEqual(registry.get('dev').client.env['VGS_TENANT'],'tntfixture')
        self.assertNotIn('fixture-secret',json.dumps(account))
    @patch.object(EnvironmentClient,'api',return_value={'data':[]})
    @patch.object(EnvironmentClient,'token',return_value=TOKEN)
    def test_multiple_tenants_require_selection_before_saving(self,token,api):
        self.path.write_text(json.dumps({'clientId':'fixture','clientSecret':'dummy','vaults':['tntsecond','tntfixture']}))
        initial=self.initial();registry=CatalogRegistry(initial)
        result=registry.connect('dev',{'credentialsFile':str(self.path)})
        self.assertTrue(result['selectionRequired']);self.assertEqual(len(result['tenants']),2)
        self.assertFalse(registry.profile_file.exists());self.assertIs(registry.get('dev'),initial);api.assert_not_called()
        with self.assertRaisesRegex(AccountFileError,'returned'):
            registry.connect('dev',{'credentialsFile':str(self.path),'tenantId':'tntunexpected'})
        api.assert_not_called()
        selected=registry.connect('dev',{'credentialsFile':str(self.path),'tenantId':'tntsecond'})
        self.assertEqual(selected['tenantId'],'tntsecond')
    def test_token_tenant_metadata_needs_no_tenant_list_permission(self):
        from account_files import discover_tenants
        client=EnvironmentClient(self.path,'dev',allow_unresolved=True)
        client.token=Mock(return_value=TOKEN)
        client.opener=Mock()
        self.assertEqual(discover_tenants(client),[{'tenantId':'tntfixture','name':'tntfixture'}])
        client.opener.open.assert_not_called()

    def test_missing_or_invalid_tenant_metadata_never_queries_account_api(self):
        from account_files import discover_tenants
        claims_cases=[{}, [], {'scope':'reveal-sessions:read'},
                      {'clientAnnotations':None}, {'clientAnnotations':[]},
                      {'clientAnnotations':{'vgs.io/vault-id':['tntfixture']}},
                      {'clientAnnotations':{'vgs.io/vault-id':'invalid/private-claim'}}]
        tokens=['malformed-token']+['fixture.'+base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')+'.fixture' for claims in claims_cases]
        for token in tokens:
            with self.subTest(token_shape=token.split('.')[0]):
                client=EnvironmentClient(self.path,'dev',allow_unresolved=True)
                client.token=Mock(return_value=token)
                client.opener=Mock()
                client.opener.open.side_effect=AssertionError('Tenant-list lookup is forbidden')
                with self.assertRaisesRegex(AccountFileError,'No tenant ID') as caught:
                    discover_tenants(client)
                client.opener.open.assert_not_called()
                self.assertNotIn('vaults:read',str(caught.exception))
                self.assertNotIn('private-claim',str(caught.exception))
                self.assertNotIn(token,str(caught.exception))

    @patch.object(EnvironmentClient,'api')
    @patch.object(EnvironmentClient,'token',return_value='fixture.e30.fixture')
    @patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Tenant-list lookup is forbidden'))
    def test_missing_tenant_metadata_keeps_current_account(self,opener,token,api):
        initial=self.initial();registry=CatalogRegistry(initial)
        with self.assertRaisesRegex(AccountFileError,'No tenant ID'):
            registry.connect('dev',{'credentialsFile':str(self.path)})
        self.assertIs(registry.get('dev'),initial)
        self.assertFalse(registry.profile_file.exists())
        api.assert_not_called();opener.assert_not_called()

if __name__=='__main__':unittest.main()
