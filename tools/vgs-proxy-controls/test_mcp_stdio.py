import importlib.util
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest

from session_operations import private_json


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'Optional MCP dependencies are not installed')
class McpProtocolTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX helper shutdown check')
    async def test_launcher_generates_separate_private_mcp_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            credentials = root / 'sandbox.env'
            credentials.write_text('VGS_TENANT=tntFixture\nVGS_CLIENT_ID=synthetic\nVGS_CLIENT_SECRET=synthetic\n'
                'VGS_API=https://sandbox.vgsapi.com\nVGS_AUTH_URL=https://auth.verygoodsecurity.com/auth/realms/vgs/protocol/openid-connect/token\n')
            session = root / 'RSFIXTURE.json'
            private_json(session, {'data': {'id': 'RSFIXTURE', 'attributes': {'state': 'active', 'expires_at': '2099-01-01T00:00:00Z',
                'proxy': {'ca_bundle': 'synthetic-ca', 'url': 'https://synthetic:fixture@tntFixture.sandbox.verygoodproxy.com:8443',
                'pac_url': 'https://sandbox.vgsapi.com/reveal-sessions/RSFIXTURE.pac?signature=synthetic'}}}})
            directory, extension = root / 'mcp', root / 'extension'
            proc = await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).with_name('start-proxy-controls.py')),
                '--environment', 'sandbox', '--credentials-file', str(credentials), '--session', str(session),
                '--output', str(extension), '--enable-mcp', '--mcp-directory', str(directory),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                async def ready():
                    while True:
                        line = await proc.stdout.readline()
                        if not line: raise AssertionError('Helper did not start with synthetic inputs')
                        if b'MCP client configuration:' in line: return
                await asyncio.wait_for(ready(), 15)
                config = json.loads((directory / 'connection.json').read_text())
                public = json.loads((directory / 'mcp-client.json').read_text())
                self.assertEqual(public['mcpServers']['awg-testing']['command'], sys.executable)
                self.assertNotIn(config['token'], json.dumps(public))
                self.assertNotIn(config['token'], (extension / 'background.js').read_text())
                self.assertEqual((directory / 'connection.json').stat().st_mode & 0o777, 0o600)
            finally:
                if proc.returncode is None: proc.send_signal(signal.SIGINT)
                await asyncio.wait_for(proc.communicate(), 10)
            self.assertEqual(proc.returncode, 0)
            self.assertFalse((directory / 'connection.json').exists())

    async def test_sdk_handshake_tools_and_capture_store(self):
        from mcp.client.session import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp_capture import CaptureStore
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / 'connection.json'
            private_json(config, {'url': 'http://127.0.0.1:1', 'token': 'synthetic',
                         'browserUrl': 'http://127.0.0.1:2', 'capturesDirectory': str(root / 'captures')})
            store = CaptureStore(root / 'captures')
            cid = 'CAP' + 'd' * 32
            store.write(cid, {'log': {'_capture': {'unredacted': True}, 'entries': [
                {'_requestId': 'REQfixture', 'request': {'headers': [{'name': 'Cookie', 'value': 'fixture=yes'}], 'postData': {'text': 'fixture-request'}},
                 'response': {'content': {'text': 'fixture-response'}}}]}})
            params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name('awg_mcp.py')), '--connection', str(config)])
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.server_info.name, 'Agent Web Gateway Testing')
                    listing = await session.list_tools()
                    names = {tool.name for tool in listing.tools}
                    self.assertTrue({'browser_select_tab', 'capture_start', 'capture_entry', 'gateway_write', 'diagnose_capture', 'repair_capture'} <= names)
                    result = await session.call_tool('gateway_schema', {'resource': 'functions'})
                    self.assertFalse(result.is_error)
                    schema = json.loads(result.content[0].text)
                    self.assertEqual(schema['spec_url'],
                        'https://openapi.gitbook.com/o/hcowjO8ckQ1K5fm3NPZH/spec/agent-web-gateway-api.yaml')
                    self.assertIn('source', schema['create'])
                    self.assertNotIn('schema', schema)
                    invalid = await session.call_tool('gateway_schema', {'resource': 'unsupported'})
                    self.assertTrue(invalid.is_error)
                    result = await session.call_tool('capture_read', {'capture_id': cid})
                    self.assertFalse(result.is_error)
                    view = json.loads(result.content[0].text)
                    self.assertNotIn('text', view['entries'][0]['request']['postData'])
                    result = await session.call_tool('capture_entry', {'capture_id': cid, 'request_id': 'REQfixture'})
                    self.assertEqual(json.loads(result.content[0].text)['response']['content']['text'], 'fixture-response')
                    invalid = await session.call_tool('capture_entry', {'capture_id': '../../secrets', 'request_id': 'x'})
                    self.assertTrue(invalid.is_error)


if __name__ == '__main__': unittest.main()
