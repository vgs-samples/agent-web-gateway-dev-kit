"""Gateway view isolation and read-only contracts, with synthetic API responses."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from awg_dev_api import ApiError
from gateway_view import GatewayViewError, RESOURCES, read_configuration
from test_session_catalog import CatalogTests
from session_catalog import CatalogServer


class GatewayViewTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.api.return_value = {'data': [], 'meta': {'total_elements': 0}}
        self.catalog = SimpleNamespace(tenant='fixtureTenant', client=self.client)
        self.registry = SimpleNamespace(get=lambda environment: self.catalog if environment == 'sandbox' else None)

    def read(self, **options):
        return read_configuration(self.registry, 'sandbox', {'tenantId':'fixtureTenant', 'resource':'functions', **options})

    def test_lists_and_details_are_get_only_and_preserve_context(self):
        for resource in RESOURCES:
            result = self.read(resource=resource, limit=25, offset=50)
            self.client.api.assert_called_with('GET', '/' + resource + '?limit=25&offset=50')
            self.assertEqual(result['tenantId'], 'fixtureTenant')
            self.assertEqual(result['environment'], 'sandbox')
        self.read(id='FNfixture')
        self.client.api.assert_called_with('GET', '/functions/FNfixture')
        self.assertEqual({call.args[0] for call in self.client.api.call_args_list}, {'GET'})

    def test_rejects_other_tenants_mutations_paths_and_unbounded_pagination(self):
        invalid = [{'tenantId':'other'}, {'resource':'reveal-sessions'}, {'operation':'update'}, {'attributes':{}},
                   {'id':'FNfixture/../other'}, {'id':'FNfixture?secret'}, {'limit':101}, {'offset':-1}, {'limit':True}]
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(GatewayViewError): self.read(**options)
        self.client.api.assert_not_called()
        with self.assertRaises(GatewayViewError):
            read_configuration(self.registry, 'live', {'tenantId':'fixtureTenant', 'resource':'functions'})
        self.client.api.assert_not_called()

    def test_api_failures_are_actionable_without_exposing_response_bodies(self):
        for status in (401,403,404,500):
            self.client.api.side_effect = ApiError(status, 'PRIVATE BODY')
            with self.assertRaises(GatewayViewError) as error: self.read()
            self.assertNotIn('PRIVATE', str(error.exception))
            if status in (401,403): self.assertIn('agent-gateway:read', str(error.exception))


class GatewayEndpointTests(CatalogTests):
    def test_gateway_endpoint_requires_auth_and_routes_reads_to_selected_tenant(self):
        self.catalog.tenant = 'fixtureTenant'
        self.catalog.client.api = Mock(return_value={'data':[]})
        server = CatalogServer(None, catalog=self.catalog, profiles={})
        try:
            url = server.config['url'] + '/environments/dev/gateway/read'
            options = {'tenantId':'fixtureTenant','resource':'functions','limit':50,'offset':0}
            headers = {'Authorization':'Bearer '+server.config['token'], 'Content-Type':'application/json'}
            for extra in ({'Authorization':'Bearer wrong'},{'Origin':'https://untrusted.invalid'}):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(url,data=json.dumps(options).encode(),headers={**headers,**extra}))
                self.assertEqual(error.exception.code,403)
            self.catalog.client.api.assert_not_called()
            with urlopen(Request(url,data=json.dumps(options).encode(),headers=headers)) as response:
                self.assertEqual(response.headers['Cache-Control'],'no-store')
                self.assertEqual(json.load(response)['document'], {'data':[]})
            self.catalog.client.api.assert_called_once_with('GET','/functions?limit=50&offset=0')
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url,data=json.dumps({**options,'operation':'delete'}).encode(),headers=headers))
            self.assertEqual(error.exception.code,400)
            self.assertEqual(self.catalog.client.api.call_count,1)
        finally: server.close()


if __name__ == '__main__': unittest.main()
