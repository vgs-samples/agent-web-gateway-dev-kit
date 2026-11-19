"""End-to-end panel recording against synthetic loopback fixtures only."""
import argparse
import json
from pathlib import Path
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from session_catalog import CatalogServer
from session_proxy_extension import write_extension


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def reply(self, body, mime='text/html'):
        self.send_response(200); self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        self.reply(self.rfile.read(int(self.headers.get('Content-Length', 0))), 'application/json')
    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302); self.send_header('Location', '/exercise'); self.send_header('Content-Length', '0'); self.end_headers()
        elif self.path == '/exercise':
            self.reply(b'''<title>Working</title><iframe src="/frame"></iframe><script>
            (async()=>{ await fetch('/echo',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"synthetic":"payload"}'});
            await fetch('https://js.verygoodvault.com/excluded-fixture').catch(()=>{}); document.title='Finished'; })();</script>''')
        else: self.reply(b'<title>Fixture</title>Local fixture')


class Catalog:
    environment = 'dev'
    lock = threading.Lock()
    @property
    def operations(self): return self
    def account(self):
        return {'connected':True,'configured':True,'tenantId':'tntFixture','scopes':[], 'creationAvailable':False}
    def listing(self): return {'sessions':[], 'checkedAt':'2026-11-18T00:00:00Z'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser')
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright, expect
    http = ThreadingHTTPServer(('127.0.0.1',0), Fixture)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    origin = f'http://awg-recording.test:{http.server_port}'
    server = context = None
    try:
        with tempfile.TemporaryDirectory(prefix='awg-recording-') as temp, sync_playwright() as p:
            root = Path(temp)
            catalog = Catalog(); catalog.sessions_directory = root/'sessions'
            server = CatalogServer(None, catalog=catalog, profiles={}, captures_directory=root/'captures')
            server.recording.repair = lambda cid: {'status':'needs-review', 'message':'Synthetic repair review completed.'}
            extension = root/'extension'
            write_extension(extension, 'https://sandbox.vgsapi.io/reveal-sessions/RSFIXTURE.pac', {},
                            {'scheme':'http','host':'127.0.0.1','port':9}, session_id='RSFIXTURE',
                            expires_at='2099-01-01T00:00:00Z', catalog=server.config, initial_mode='direct')
            context = p.chromium.launch_persistent_context(str(root/'profile'), executable_path=args.browser,
                channel='chromium' if not args.browser else None, headless=True,
                args=[f'--disable-extensions-except={extension}',f'--load-extension={extension}',
                      '--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',
                      '--host-resolver-rules=MAP awg-recording.test 127.0.0.1, EXCLUDE 127.0.0.1, MAP * ~NOTFOUND',
                      '--disable-background-networking'])
            port = (root/'profile'/'DevToolsActivePort').read_text().splitlines()[0]
            server.recording.endpoint = f'http://127.0.0.1:{port}'
            context.route('https://js.verygoodvault.com/excluded-fixture', lambda r: r.fulfill(status=200,body='excluded synthetic data',headers={'Access-Control-Allow-Origin':'*'}))
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            panel = context.new_page(); panel.set_viewport_size({'width':1400,'height':1100})
            errors=[]; panel.on('pageerror', lambda e: errors.append(str(e)))
            panel.goto(worker.url.rsplit('/',1)[0]+'/popup.html?allow_dev_env=true')
            expect(panel.locator('#view-controls')).to_be_visible()
            expect(panel.locator('#view-recording')).to_be_hidden()
            panel.get_by_role('button', name='Recording', exact=True).click()
            expect(panel.locator('#view-controls')).to_be_hidden()
            expect(panel.locator('#view-recording')).to_be_visible()
            expect(panel.locator('#test-recording-state')).to_have_text('Ready', timeout=15000)
            panel.locator('#test-address').fill(origin+'/redirect')
            panel.locator('#start-test').click()
            expect(panel.locator('#test-recording-state')).to_have_text('Recording', timeout=15000)
            merchant = next(page for page in context.pages if page.url.startswith(origin))
            expect(merchant).to_have_title('Finished', timeout=15000)
            merchant.wait_for_load_state('networkidle')
            panel.get_by_role('button', name='Browser Settings', exact=True).click()
            expect(panel.locator('#view-recording')).to_be_hidden()
            assert server.recording.status()['recording'], 'Switching views must keep recording'
            panel.get_by_role('button', name='Recording', exact=True).click()
            expect(panel.locator('#test-address')).to_have_value(origin+'/redirect')
            expect(panel.locator('#test-recording-state')).to_have_text('Recording')
            panel.locator('#stop-test').click()
            expect(panel.locator('#test-recording-state')).to_have_text('HAR saved', timeout=15000)
            expect(panel.locator('#test-repair-status')).to_have_text('Synthetic repair review completed.', timeout=15000)
            path = Path(panel.locator('#test-recording-path').inner_text())
            har = json.loads(path.read_text()); entries=har['log']['entries']
            assert any(e['response']['status']==302 for e in entries), 'Initial redirect must be recorded'
            assert any(e['request']['url'].endswith('/frame') for e in entries), 'Iframe missing'
            echo = next(e for e in entries if e['request']['url'].endswith('/echo'))
            assert echo['request']['postData']['text']=='{"synthetic":"payload"}'
            assert echo['response']['content']['text']==echo['request']['postData']['text']
            assert not any('verygoodvault' in e['request']['url'] for e in entries)
            assert har['log']['_capture']['excludedRequests']>=1
            assert path.stat().st_mode & 0o777 == 0o600
            assert path.parent.stat().st_mode & 0o777 == 0o700
            assert not errors, errors
            # Passive recording polls must leave interactive controls enabled.
            panel.evaluate("""() => {
                window.pollDisabledChanges = 0;
                new MutationObserver(rows => { window.pollDisabledChanges += rows.length; })
                    .observe(document.querySelector('#test-tab'), {attributes:true, attributeFilter:['disabled']});
            }""")
            panel.wait_for_timeout(2500)
            assert panel.evaluate('window.pollDisabledChanges') == 0, 'Polling interrupted an interactive control'
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True,exist_ok=True)
                panel.locator('#test-recording-path').evaluate("el => el.textContent = '~/AWG Testing/test-captures/example.har'")
                panel.screenshot(path=str(args.screenshot), full_page=True)
            # Panel can be closed and reopened while the helper continues recording.
            panel.locator('#test-address').fill(origin+'/exercise'); panel.locator('#start-test').click()
            expect(panel.locator('#test-recording-state')).to_have_text('Recording', timeout=15000)
            second = [page for page in context.pages if page.url.startswith(origin) and page is not merchant][-1]
            expect(second).to_have_title('Finished'); panel.close()
            assert server.recording.status()['recording']
            second.close()
            import time
            for _ in range(50):
                if server.recording.status()['state']=='saved': break
                time.sleep(.1)
            assert server.recording.status()['stoppedReason']=='tab-closed'
            print('Panel recording passed: capture before redirect, iframe, request/response bodies, tokenization excluded, private HAR, panel-close persistence, tab-close autosave.')
    finally:
        if server: server.close()
        if context:
            try: context.close()
            except Exception: pass
        http.shutdown();http.server_close()


if __name__ == '__main__': main()
