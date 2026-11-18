import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from awg_dev_api import ApiError
from mcp_gateway import GatewayBridge, McpGatewayServer, loopback_url, runtime_lock
from mcp_capture import CaptureStore, encoded_body, body_allowed


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = Mock()
        self.client.api.return_value = {'data': {'id': 'FNfixture', 'attributes': {'extension_point': 'route.request'}}}
        self.catalog = SimpleNamespace(tenant='tntFixture', client=self.client, operations=Mock())
        self.catalog.operations.account.return_value = {'tenantId': 'tntFixture', 'connected': True, 'scopes': ['agent-gateway:read'], 'secret': 'must-stay-local'}
        registry = SimpleNamespace(get=lambda env: self.catalog if env == 'sandbox' else None)
        self.bridge = GatewayBridge(registry, 'sandbox', self.temp.name, True)
        self.value = {'operation': 'create', 'tenantId': 'tntFixture', 'resource': 'functions', 'requestId': 'a' * 32,
                      'attributes': {'name': 'fixture', 'source': 'pass', 'extension_point': 'route.request'}}

    def tearDown(self): self.temp.cleanup()

    def test_account_excludes_secret(self):
        self.assertNotIn('secret', self.bridge.execute({'operation': 'account'}))

    def test_mutation_scope_and_paths(self):
        for change in ({'tenantId': 'tntOther'}, {'resource': '../preferences'}, {'id': 'FNx?query=1'},
                       {'operation': 'delete'}, {'attributes': {'name': 'bad'}}, {'requestId': '../file'}):
            with self.assertRaises(ValueError): self.bridge.execute({**self.value, **change})
        self.client.api.assert_not_called()
        self.bridge.allow_writes = False
        with self.assertRaises(ValueError): self.bridge.execute(self.value)
        self.client.api.assert_not_called()

    def test_repeated_write_and_restart_do_not_duplicate(self):
        result = self.bridge.execute(self.value)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.bridge.execute(self.value), result)
        self.bridge = GatewayBridge(self.bridge.registry, 'sandbox', self.temp.name, True)
        self.assertEqual(self.bridge.execute(self.value), result)
        self.client.api.assert_called_once()
        with self.assertRaises(ValueError): self.bridge.execute({**self.value, 'attributes': {**self.value['attributes'], 'name': 'changed'}})

    def test_timeout_is_not_retried(self):
        self.client.api.side_effect = TimeoutError('sensitive API data')
        result = self.bridge.execute(self.value)
        self.assertEqual(result['status'], 'unconfirmed')
        self.assertNotIn('sensitive', json.dumps(result))
        self.assertEqual(self.bridge.execute(self.value), result)
        self.client.api.assert_called_once()

    def test_gateway_errors_do_not_echo_response_bodies(self):
        self.client.api.side_effect = ApiError(403, 'secret body')
        result = self.bridge.execute(self.value)
        self.assertEqual((result['status'], result['httpStatus']), ('rejected', 403))
        self.assertNotIn('secret', json.dumps(result))

    def test_new_binding_disabled_unless_explicit(self):
        self.bridge.execute({**self.value, 'resource': 'agent-gateway-adapter-destinations',
            'attributes': {'adapter': 'ADfixture', 'when': {'host': 'fixture.invalid'}, 'functions': [{'id': 'FNfixture'}]}})
        self.assertFalse(self.client.api.call_args.args[2]['enabled'])

    def test_dry_run_rejects_invoke_functions(self):
        self.client.api.return_value['data']['attributes']['extension_point'] = 'invoke'
        value = {**self.value, 'operation': 'dry_run', 'id': 'FNfixture', 'attributes': {'request': {'method': 'POST'}}}
        with self.assertRaises(ValueError): self.bridge.execute(value)
        self.assertEqual(self.client.api.call_count, 1)
        self.client.api.return_value['data']['attributes']['extension_point'] = 'route.request'
        self.bridge.execute(value)
        self.assertEqual(self.client.api.call_args.args[:2], ('POST', '/functions/FNfixture/invocations'))
        self.assertEqual(self.client.api.call_args.kwargs['kind'], 'function-invocations')

    def test_read_pagination_and_id(self):
        self.bridge.execute({'operation': 'read', 'tenantId': 'tntFixture', 'resource': 'agent-gateway-adapters', 'offset': 100})
        self.client.api.assert_called_once_with('GET', '/agent-gateway-adapters?limit=50&offset=100')

    def test_loopback_http_authorization(self):
        server = McpGatewayServer(self.bridge)
        try:
            headers = {'Authorization': 'Bearer ' + server.config['token'], 'Content-Type': 'application/json'}
            for extra in ({'Authorization': 'Bearer wrong'}, {'Origin': 'https://fixture.invalid'}, {'Origin': 'chrome-extension://' + 'a' * 32}, {'Host': 'localhost'}):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(server.config['url'] + '/gateway', data=b'{"operation":"account"}', headers={**headers, **extra}))
                self.assertEqual(error.exception.code, 403)
            with urlopen(Request(server.config['url'] + '/gateway', data=b'{"operation":"account"}', headers=headers)) as response:
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertNotIn('secret', json.load(response))
        finally: server.close()

    def test_loopback_only(self):
        self.assertEqual(loopback_url('http://127.0.0.1:9222/'), 'http://127.0.0.1:9222')
        for value in ['http://localhost:9222', 'http://127.0.0.1:9222/path', 'http://user@127.0.0.1:9222', 'https://fixture.invalid:443', 'http://127.0.0.1:9222?token=secret']:
            with self.assertRaises(ValueError): loopback_url(value)

    def test_helper_runtime_lock(self):
        first = runtime_lock(self.temp.name)
        try:
            with self.assertRaises(ValueError): runtime_lock(self.temp.name)
        finally: first.close()
        runtime_lock(self.temp.name).close()

    def test_body_limits_report_omissions(self):
        meta = {'maxBodyBytes': 10, 'maxTotalBodyBytes': 12, 'capturedBodyBytes': 0, 'bodyErrors': 0}
        self.assertTrue(body_allowed(b'12345678', meta))
        self.assertFalse(body_allowed(b'123456', meta))
        self.assertFalse(body_allowed(b'1' * 11, meta))
        self.assertEqual((meta['capturedBodyBytes'], meta['bodyErrors']), (8, 2))

    def test_private_har_store_retains_sensitive_fields(self):
        store = CaptureStore(Path(self.temp.name) / 'captures')
        cid = 'CAP' + 'b' * 32
        har = {'log': {'_capture': {'unredacted': True}, 'entries': [{'request': {'headers': [{'name': 'Authorization', 'value': 'synthetic-fixture'}]}}]}}
        store.write(cid, har)
        self.assertEqual(store.read(cid), har)
        self.assertEqual(store.path(cid).stat().st_mode & 0o777, 0o600)
        self.assertEqual(store.listing()[0]['entries'], 1)
        with self.assertRaises(ValueError): store.read('../../account')
        self.assertEqual(encoded_body(b'\xff')['encoding'], 'base64')


if __name__ == '__main__': unittest.main()
