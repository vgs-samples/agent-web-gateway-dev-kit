"""Dashboard form contracts using synthetic aliases and no external services."""
import copy
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from session_operations import Operations, private_json, validated_options
from session_form import validate_dashboard_options

class DashboardFormTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.aliases=[{'alias':'tok_sandbox_panfixture123','format':'card_number','bin':'411111','storage':'PERSISTENT','length':16},
                      {'alias':'tok_sandbox_cvcfixture123','format':'card_cvc','storage':'VOLATILE','length':3}]
        self.value={'requestId':str(uuid.uuid4()),'aliases':self.aliases,'allowedHosts':['PAY.EXAMPLE.com'],
                    'allowedClientCidrs':['203.0.113.4/24','2001:db8::1'], 'adapter':'ADGLOBAL', 'egressMode':'profile'}
        self.egress=self.root/'egress.json'; private_json(self.egress,{'scheme':'http','hostname':'fixture.proxy','port':3128,'username':'fixture','password':'fixture-secret'})
        self.calls=[]; outer=self
        class Client:
            def api(self, method, path, attrs=None, *args, **kwargs):
                outer.calls.append((method,path,attrs))
                if path=='/agent-gateway-adapters': return {'data':[
                    {'id':'ADGLOBAL','attributes':{'name':'Global-e','owner':'vgs','published_version':1}},
                    {'id':'ADPRIVATE','attributes':{'name':'Private','owner':'vgs'}},
                    {'id':'ADCUSTOM','attributes':{'name':'Custom','owner':'tenant'}}]}
                return {'data':{'id':'RSCREATED','attributes':{'tokens':[]}}}
        self.operations=Operations(Client(),self.root/'sessions',egress_file=self.egress)
    def tearDown(self):self.tmp.cleanup()
    def finish(self,rid):
        for _ in range(200):
            result=self.operations.status(rid)
            if result['status']!='running':return result
            time.sleep(.01)
        self.fail('Job timed out')
    def test_dashboard_payload_and_adapter_verification(self):
        self.operations.create(self.value); self.assertEqual(self.finish(self.value['requestId'])['status'],'complete')
        self.assertEqual(self.calls[0][:2],('GET','/agent-gateway-adapters'))
        attrs=self.calls[-1][2]
        self.assertEqual(attrs['aliases'],self.aliases);self.assertNotIn('cards',attrs)
        self.assertEqual(attrs['adapter'],'ADGLOBAL')
        self.assertEqual(attrs['allowed_client_cidrs'],['203.0.113.0/24','2001:db8::1/128'])
        self.assertEqual(attrs['egress_proxy_settings']['password'],'fixture-secret')
        self.operations.create(self.value);self.assertEqual(len([c for c in self.calls if c[0]=='POST']),1)
    def test_unpublished_adapter_never_submits(self):
        self.value['adapter']='ADPRIVATE';self.operations.create(self.value)
        self.assertEqual(self.finish(self.value['requestId'])['status'],'failed')
        self.assertFalse(any(c[0]=='POST' for c in self.calls))
    def test_validation_and_configured_egress_cannot_be_bypassed(self):
        for change in [lambda x:x.update(allowedClientCidrs=['not-an-ip']),lambda x:x.update(aliases=x['aliases'][:1]),
                       lambda x:x['aliases'][0].update(alias='4111111111111111'),lambda x:x['aliases'][1].update(storage='PERSISTENT'),
                       lambda x:x.update(egressMode='none'),lambda x:x.update(allowedHosts=['*.example.com'])]:
            value=copy.deepcopy(self.value);change(value)
            with self.assertRaises(ValueError):self.operations.create(value)
        self.assertEqual(self.calls,[])
    def test_generic_text_alias_and_optional_custom_egress(self):
        value={**self.value,'aliases':[{'alias':'tok_sandbox_textfixture','format':'text','storage':'PERSISTENT'}],
               'adapter':'','egressMode':'custom','egress':{'scheme':'https','hostname':'proxy.fixture','port':8443}}
        parsed=validated_options(value)
        other=Operations(self.operations.client,self.root/'other')
        self.assertEqual(other.session_egress(parsed)['hostname'],'proxy.fixture')
        parsed=validated_options({**value,'egressMode':'none','egress':None});self.assertIsNone(other.session_egress(parsed))
    def test_private_card_aliases_are_returned_once_without_creating_session(self):
        rid=str(uuid.uuid4())
        card={'number':self.aliases[0],'cvc':self.aliases[1]}
        with patch.object(self.operations,'fresh_card',return_value=card) as tokenizer:
            self.operations.create_card({'requestId':rid});result=self.finish(rid)
            self.operations.create_card({'requestId':rid})
            self.assertEqual(tokenizer.call_count,1)
        self.assertEqual(result['aliases'],self.aliases);self.assertEqual(self.calls,[])
        self.assertEqual(self.operations.job_path(rid).stat().st_mode & 0o777,0o600)
        with self.assertRaises(ValueError):self.operations.create_card({'requestId':rid,'pan':'raw'})
    def test_tokenizer_failure_never_retries_automatically(self):
        rid=str(uuid.uuid4())
        with patch.object(self.operations,'fresh_card',side_effect=TimeoutError('private-body')) as tokenizer:
            self.operations.create_card({'requestId':rid});result=self.finish(rid)
            self.operations.create_card({'requestId':rid});self.assertEqual(tokenizer.call_count,1)
        self.assertEqual(result['status'],'unknown');self.assertNotIn('private-body',json.dumps(result))

if __name__=='__main__':unittest.main()
