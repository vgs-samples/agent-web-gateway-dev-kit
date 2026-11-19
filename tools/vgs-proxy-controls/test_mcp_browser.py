#!/usr/bin/env python3
"""Opt-in end-to-end MCP/CDP check using only isolated browser and loopback fixtures."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from session_operations import private_json


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def reply(self, body, content_type='text/plain'):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Set-Cookie', 'first=fixture; Path=/; HttpOnly')
        self.send_header('Set-Cookie', 'second=fixture; Path=/')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.reply(body, self.headers.get('Content-Type', 'text/plain'))

    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/final')
            self.send_header('Content-Length', '0')
            self.end_headers()
        elif self.path == '/exercise':
            self.reply(b'''<html><title>Running</title><body><iframe src="/frame"></iframe><script>
            (async () => {
              await fetch('/echo', {method:'POST',headers:{Authorization:'Bearer synthetic-capture-fixture','Content-Type':'application/json'},body:'{"fixture":"request-body"}'}).then(r=>r.text());
              await fetch('/binary', {method:'POST',headers:{'Content-Type':'application/octet-stream'},body:new Uint8Array([255,0,128])}).then(r=>r.arrayBuffer());
              await fetch('/redirect').then(r=>r.text());
              await fetch('/oversize').then(r=>r.text());
              document.title='Finished';
            })();</script></body></html>''', 'text/html')
        elif self.path == '/oversize': self.reply(b'x' * 2048)
        elif self.path == '/frame': self.reply(b'<html>frame fixture</html>', 'text/html')
        else: self.reply(b'<html><title>Fixture</title>local fixture</html>', 'text/html')


async def run(browser_path=None):
    from playwright.async_api import async_playwright
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
    http = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    http.daemon_threads = True
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{http.server_port}'
    try:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(str(root / 'profile'), executable_path=browser_path,
                    channel='chromium' if not browser_path else None,
                    headless=True, args=['--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
                        '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1', '--disable-background-networking'])
                try:
                    page = context.pages[0]
                    await page.goto(origin + '/start')
                    other = await context.new_page()
                    await other.goto(origin + '/other')
                    port = (root / 'profile' / 'DevToolsActivePort').read_text().splitlines()[0]
                    config = root / 'connection.json'
                    private_json(config, {'url': 'http://127.0.0.1:1', 'token': 'synthetic',
                        'browserUrl': f'http://127.0.0.1:{port}', 'capturesDirectory': str(root / 'captures')})
                    params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name('awg_mcp.py')), '--connection', str(config)])
                    async with stdio_client(params) as (reader, writer):
                        async with ClientSession(reader, writer) as client:
                            await client.initialize()
                            async def call(name, **kwargs):
                                result = await client.call_tool(name, kwargs)
                                assert not result.is_error, f'{name} failed: {result.content}'
                                return json.loads(result.content[0].text)
                            tabs = (await call('browser_list_tabs'))['tabs']
                            tab = next(t for t in tabs if t['url'] == origin + '/start')
                            await call('browser_select_tab', tab_id=tab['tabId'])
                            first = await call('capture_start', max_body_bytes=1500)
                            await other.goto(origin + '/not-selected')
                            await call('browser_navigate', url=origin + '/exercise')
                            await page.wait_for_function("document.title === 'Finished'")
                            # Ensure the iframe and body reads have finished before stopping.
                            await page.wait_for_load_state('networkidle')
                            stopped = await call('capture_stop')
                            assert first['captureId'] == stopped['captureId']
                            entries = (await call('capture_read', capture_id=stopped['captureId'], include_bodies=True, limit=100))['entries']
                            assert not any('/not-selected' in e['request']['url'] for e in entries)
                            assert any('/frame' in e['request']['url'] for e in entries)
                            echo = next(e for e in entries if e['request']['url'].endswith('/echo'))
                            headers = {h['name'].lower(): h['value'] for h in echo['request']['headers']}
                            assert headers['authorization'] == 'Bearer synthetic-capture-fixture'
                            assert 'first=fixture' in headers['cookie']
                            assert echo['request']['postData']['text'] == '{"fixture":"request-body"}'
                            assert echo['response']['content']['text'] == echo['request']['postData']['text']
                            assert len([h for h in echo['response']['headers'] if h['name'].lower() == 'set-cookie']) == 2
                            binary = next(e for e in entries if e['request']['url'].endswith('/binary'))
                            assert binary['response']['content']['encoding'] == 'base64'
                            assert binary['request']['postData']['_encoding'] == 'base64'
                            assert any(e['response']['status'] == 302 for e in entries)
                            oversize = next(e for e in entries if e['request']['url'].endswith('/oversize'))
                            assert '_error' in oversize['response']['content']
                            assert stopped['bodyErrors'] >= 1
                            assert Path(stopped['path']).stat().st_mode & 0o777 == 0o600
                            full = await call('capture_entry', capture_id=stopped['captureId'], request_id=echo['_requestId'])
                            assert full['request']['postData']['text'] == echo['request']['postData']['text']
                            # Recorder remains reusable after stopping; no browser tabs are closed.
                            await call('capture_start', max_entries=1)
                            await call('browser_reload')
                            await page.wait_for_function("document.title === 'Finished'")
                            await page.wait_for_load_state('networkidle')
                            bounded = await call('capture_stop')
                            assert bounded['entries'] == 1 and bounded['omittedRequests'] > 0
                    assert not page.is_closed() and not other.is_closed()
                    assert await page.title() == 'Finished'
                    print('MCP/CDP browser check passed: selected tab, iframe, auth/cookies, bodies, binary, redirects, limits, private files, disconnect.')
                finally: await context.close()
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-path')
    parser.add_argument('--slot-file', type=Path, help='Optional existing browser-work lock (macOS/Linux)')
    args = parser.parse_args()
    lock = None
    try:
        if args.slot_file:
            import fcntl
            lock = args.slot_file.open('r')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(run(args.browser_path))
    finally:
        if lock: lock.close()


if __name__ == '__main__': main()
