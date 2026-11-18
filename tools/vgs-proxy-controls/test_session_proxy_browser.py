"""Local-only Chromium smoke test; no AWG session or merchant traffic.

Run with a Python environment containing Playwright and --browser /path/to/chromium.
Only loopback fixtures are contacted. Uses a new temporary profile and dummy auth.
"""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading

from session_proxy_extension import write_extension
from session_catalog import CatalogServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', required=True)
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright

    counts = {'direct': 0, 'vgs': 0, 'egress': 0, 'pac': 0}
    secrets = {name: {'username': 'fixture-' + name, 'password': 'dummy-' + name}
               for name in ('vgs', 'egress')}
    servers = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, body, content_type='text/plain', headers=None):
            body = body.encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            role = self.server.role
            if role == 'pac':
                counts['pac'] += 1
                self.reply(200, pac_script, 'application/x-ns-proxy-autoconfig')
                return
            if role in secrets:
                auth = secrets[role]
                encoded = base64.b64encode((auth['username'] + ':' + auth['password']).encode()).decode()
                second_encoded = base64.b64encode(b'fixture-second:dummy-second').decode()
                is_second = role == 'vgs' and self.headers.get('Proxy-Authorization') == 'Basic ' + second_encoded
                if self.headers.get('Proxy-Authorization') != 'Basic ' + encoded and not is_second:
                    self.reply(407, '', headers={'Proxy-Authenticate': 'Basic realm="local-fixture"'})
                    return
                # Reject browser background requests; never forward anything externally.
                if not self.path.startswith('http://awg-toggle.test:'):
                    self.reply(502, 'Fixture only')
                    return
            else:
                assert self.headers.get('Proxy-Authorization') is None
            counts[role] += 1
            self.reply(200, 'vgs-second' if role == 'vgs' and is_second else role)

        def do_CONNECT(self):
            self.reply(502, 'Fixture only')

    try:
        for role in ('direct', 'vgs', 'egress', 'pac'):
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.daemon_threads = True
            server.role = role
            servers.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
        origin, vgs, egress, pac_server = servers
        pac_script = (
            'function FindProxyForURL(url, host) { return url.indexOf("/egress") >= 0 ? '
            f'"PROXY 127.0.0.1:{egress.server_port}" : "PROXY 127.0.0.1:{vgs.server_port}"; }}'
        )
        pac_url = f'http://127.0.0.1:{pac_server.server_port}/fixture.pac'
        credentials = {f'127.0.0.1:{server.server_port}': secrets[server.role] for server in (vgs, egress)}
        with tempfile.TemporaryDirectory(prefix='awg-toggle-browser-') as root, sync_playwright() as p:
            root = Path(root)
            extension = root / 'extension'
            class FixtureCatalog:
                lock = threading.Lock()
                def listing(self):
                    return {'sessions': [
                        {'sessionId': 'RSLOCALFIXTURE', 'expiresAt': '2099-01-01T00:00:00Z', 'available': True},
                        {'sessionId': 'RSSECOND', 'expiresAt': '2099-01-01T00:00:00Z', 'available': True},
                        {'sessionId': 'RSMISSING', 'expiresAt': '2099-01-01T00:00:00Z', 'available': False, 'reason': 'Proxy credentials not saved on this computer'}], 'checkedAt': '2026-11-18T00:00:00Z'}
                def configuration(self, sid):
                    assert sid == 'RSSECOND'
                    return {'sessionId': sid, 'expiresAt': '2099-01-01T00:00:00Z', 'pacUrl': pac_url + '?second', 'pacSource': pac_url,
                            'proxies': {'session': {'scheme': 'http', 'host': '127.0.0.1', 'port': vgs.server_port},
                                        'egress': {'scheme': 'http', 'host': '127.0.0.1', 'port': egress.server_port}},
                            'credentials': {**credentials, f'127.0.0.1:{vgs.server_port}': {'username': 'fixture-second', 'password': 'dummy-second'}}}
                def pac(self, sid):
                    return {'pacScript': pac_script, 'fetchedAt': '2026-11-18T00:00:00Z'}
            catalog = CatalogServer(None, catalog=FixtureCatalog())
            write_extension(extension, pac_url, credentials,
                            {'scheme': 'http', 'host': '127.0.0.1', 'port': vgs.server_port},
                            {'scheme': 'http', 'host': '127.0.0.1', 'port': egress.server_port},
                            session_id='RSLOCALFIXTURE', expires_at='2099-01-01T00:00:00Z', catalog=catalog.config)
            assert all(path.stat().st_mode & 0o777 == 0o600 for path in extension.iterdir())
            context = p.chromium.launch_persistent_context(
                str(root / 'profile'), executable_path=args.browser, headless=True,
                record_har_path=str(root / 'capture.har'), record_har_mode='full', record_har_content='embed',
                record_video_dir=str(root / 'video'), record_video_size={'width': 1280, 'height': 800},
                args=[f'--disable-extensions-except={extension}', f'--load-extension={extension}',
                      '--proxy-server=http://127.0.0.1:9', '--disable-quic',
                      '--host-resolver-rules=MAP awg-toggle.test 127.0.0.1, EXCLUDE 127.0.0.1, EXCLUDE localhost, MAP * ~NOTFOUND'],
            )
            try:
                worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                worker.evaluate('() => globalThis.pacReady')
                controls = context.new_page()
                controls.goto(worker.url.rsplit('/', 1)[0] + '/popup.html')
                controls.locator('#session-id').filter(has_text='RSLOCALFIXTURE').wait_for()
                assert controls.locator('#session-id').inner_text() == 'RSLOCALFIXTURE'
                assert controls.locator('#pac-source').text_content() == pac_url
                controls.locator('button[data-mode=pac][aria-pressed=true]').wait_for(state='visible')
                page = context.new_page()
                url = f'http://awg-toggle.test:{origin.server_port}'

                def route(path, expected):
                    response = page.goto(url + path, wait_until='domcontentloaded', timeout=15000)
                    assert response.status == 200
                    assert page.locator('body').inner_text() == expected

                # The recording workflow must start on egress before its first page.
                assert worker.evaluate("() => setMode('egress')")['mode'] == 'egress'
                route('/initial-page', 'egress')
                assert counts['vgs'] == 0
                assert worker.evaluate("() => setMode('pac')")['mode'] == 'pac'
                route('/vgs', 'vgs')
                route('/egress', 'egress')
                def select(mode):
                    controls.locator('button[data-mode=' + mode + ']').click()
                    controls.locator('button[data-mode=' + mode + '][aria-pressed=true]').wait_for(state='visible')

                for mode, expected in [('session', 'vgs'), ('egress', 'egress'), ('direct', 'direct')]:
                    select(mode)
                    route('/vgs?' + mode, expected)
                    route('/egress?' + mode, expected)
                if args.screenshot:
                    controls.set_viewport_size({'width': 720, 'height': 800})
                    controls.screenshot(path=str(args.screenshot), full_page=True)
                cdp = context.new_cdp_session(controls)
                cdp.send('ServiceWorker.enable')
                for mode, expected in [('direct', 'direct'), ('session', 'vgs'), ('egress', 'egress')]:
                    select(mode)
                    cdp.send('ServiceWorker.stopAllWorkers')
                    controls.reload()
                    controls.locator('button[data-mode=' + mode + '][aria-pressed=true]').wait_for(state='visible')
                    route('/vgs?restart-' + mode, expected)
                select('pac')
                route('/vgs?pac-again', 'vgs')
                route('/egress?pac-again', 'egress')
                worker = context.service_workers[0]
                config = worker.evaluate('() => new Promise(r => chrome.proxy.settings.get({incognito:false}, r))')
                assert config['value'] == {'mode': 'pac_script', 'pacScript': {'url': pac_url, 'mandatory': True}}
                assert worker.evaluate('() => new Promise(r => chrome.action.getBadgeText({}, r))') == 'PAC'
                # Both sessions' credentials remain valid at the same proxy endpoint.
                # Without clearing HTTP auth, Chrome silently keeps using the first.
                select('session')
                route('/before-session-switch', 'vgs')
                context.add_cookies([{'name': 'cart', 'value': 'keep-me', 'domain': 'awg-toggle.test', 'path': '/'}])
                controls.select_option('#session-select', 'RSSECOND')
                controls.locator('#use-session').click()
                controls.locator('#session-id').filter(has_text='RSSECOND').wait_for()
                controls.locator('button[data-mode=session][aria-pressed=true]').wait_for()
                route('/after-session-switch', 'vgs-second')
                assert any(c['name'] == 'cart' for c in context.cookies())
                controls.locator('#pac-script-details').click()
                controls.locator('#load-pac').click()
                controls.locator('#pac-script').filter(has_text='FindProxyForURL').wait_for()
                assert controls.locator('#pac-script').inner_text() == pac_script
                assert controls.locator('option[value=RSMISSING]').is_disabled()
                cdp.send('ServiceWorker.stopAllWorkers')
                controls.reload()
                controls.locator('#session-id').filter(has_text='RSSECOND').wait_for()
                route('/second-after-restart', 'vgs-second')
                if args.screenshot:
                    controls.screenshot(path=str(args.screenshot), full_page=True)
                print(json.dumps({'sessionSwitch': 'passed', 'sameEndpoint': 'new authentication used', 'merchantCookie': 'preserved', 'pacViewer': 'exact script', 'restart': 'selected session preserved'}))
                print(json.dumps({'result': 'passed', 'routes': counts, 'workerRestart': 'all fixed/direct modes preserved',
                                  'bootstrapOverride': 'direct verified', 'credentials': 'dummy localhost only'}))
            finally:
                context.close()
                catalog.close()
            har = json.loads((root / 'capture.har').read_text())
            captured = [e for e in har['log']['entries'] if e['request']['url'].endswith('/initial-page')]
            assert len(captured) == 1 and captured[0]['response']['content']['text'] == 'egress'
            assert any(p.stat().st_size > 0 for p in (root / 'video').glob('*.webm'))
            print(json.dumps({'recording': 'passed', 'firstPage': 'egress', 'harBodies': 'embedded', 'video': 'finalized'}))
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
