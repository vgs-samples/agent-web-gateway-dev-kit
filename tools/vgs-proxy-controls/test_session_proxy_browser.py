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
from capture_preferences import prepare_profile, har_recording_filter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', required=True)
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--walkthrough', action='store_true', help='Capture the Sandbox walkthrough using local fixtures')
    args = parser.parse_args()
    if args.walkthrough and not args.screenshot:
        parser.error('--walkthrough requires --screenshot')
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
                environment = 'sandbox' if args.walkthrough else 'dev'
                cards_only = False
                @property
                def operations(self): return self
                def account(self):
                    return {'tenantId': 'tntTrainingDemo', 'connected': True, 'creationAvailable': True,
                            'egressConfig': {'scheme':'http','hostname':'egress.fixture','port':3128}, 'egressLocked': True, 'tokenizerReady': True, 'egress': 'http://egress.fixture:3128', 'sensitiveHarEnabled': True,
                            'cardsWriteGranted': self.cards_only,
                            'scopes': [{'name': s, 'granted': True} for s in ['cards:create', 'aliases:write', 'reveal-sessions:write', 'reveal-sessions:read'] if not self.cards_only or s != 'aliases:write']}
                def adapters(self):
                    return {'adapters':[{'id':'ADGLOBAL','name':'Global-e','owner':'vgs'},{'id':'ADLOCAL','name':'Fixture custom','owner':'tenant'}]}
                def collect_token(self, options):
                    assert options["tenantId"] == "tntTrainingDemo" and options["method"] in ("aliases","card")
                    return {"tenantId":"tntTrainingDemo","environment":self.environment,"accessToken":"fixture-transient-token","method":options["method"]}
                def create_card(self, options):
                    return {'requestId':options['requestId'],'status':'complete','aliases':[
                        {'alias':'tok_sandbox_panfixture123','format':'card_number','bin':'411111','length':16,'storage':'PERSISTENT'},
                        {'alias':'tok_sandbox_cvcfixture123','format':'card_cvc','length':3,'storage':'VOLATILE'}]}
                def create(self, options):
                    from session_operations import validated_options
                    validated_options(options)
                    return {'requestId': options['requestId'], 'status': 'complete', 'sessionId': 'RSSECOND',
                            'tokens': [{'format': 'card_number', 'value': 'fixture-standin'}]}
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
            class FixturePicker:
                count = 0
                def start(self, environment):
                    self.count += 1
                    self.job = {'requestId':'12345678-1234-1234-1234-123456789abc', 'environment':environment, 'status':'pending'}
                    return self.job
                def status(self, environment, request_id):
                    assert environment == self.job['environment'] and request_id == self.job['requestId']
                    return {**self.job, **({ 'status':'selected', 'credentialsFile':'/tmp/Service account ü.json'} if self.count == 1
                        else {'status':'cancelled'} if self.count == 2 else {'status':'failed', 'error':'File explorer is unavailable. Enter the local file path instead.'})}
                def close(self): pass
            fixture_catalog = FixtureCatalog()
            fixture_catalog.sessions_directory = root / "sessions"
            fixture_catalog.ca = "fixture-ca"
            catalog = CatalogServer(None, catalog=fixture_catalog, file_picker=FixturePicker())
            if args.walkthrough:
                catalog.mcp_status = {'enabled': True, 'environment': 'sandbox', 'writesEnabled': False,
                    'clientConfig': {'mcpServers': {'awg-testing': {'command': '/path/to/.venv-mcp/bin/python',
                        'args': ['/path/to/awg_mcp.py', '--connection', '/path/to/.private-mcp/connection.json']}}}}
            write_extension(extension, pac_url, credentials,
                            {'scheme': 'http', 'host': '127.0.0.1', 'port': vgs.server_port},
                            {'scheme': 'http', 'host': '127.0.0.1', 'port': egress.server_port},
                            session_id='RSLOCALFIXTURE', expires_at='2099-01-01T00:00:00Z', catalog=catalog.config)
            # Loopback PAC URLs have no environment suffix; set the fixture metadata explicitly.
            worker_path = extension / 'background.js'
            bootstrap, worker_source = worker_path.read_text().split('\n', 1)
            initial = json.loads(bootstrap.removeprefix('const INITIAL_SESSION = ').removesuffix(';'))
            initial.update(environment=fixture_catalog.environment, tenantId='tntTrainingDemo')
            worker_path.write_text('const INITIAL_SESSION = ' + json.dumps(initial) + ';\n' + worker_source)
            assert all(path.stat().st_mode & 0o777 == 0o600 for path in extension.rglob("*") if path.is_file())
            # Replace only this temporary fixture extension's SDK with a local mock.
            # No raw inputs, external network, or real tokenization are involved.
            mock_sdk = r'''globalThis.VGSCollect = {logLevel(){},create(tenant,env,callback){
                if(tenant!=='tntTrainingDemo'||!['sandbox','live'].includes(env))throw Error('wrong Collect environment');
                let nodes=[];let options=[];
                globalThis.collectFixtureFields=options;
                function update(){callback({card_number:{isValid:true,isTouched:true,bin:'411111',cardType:'visa'},card_cvc:{isValid:true,isTouched:true},'exp-date':{isValid:true,isTouched:true}});}
                return {field(selector,opts){
                    options.push(opts);const iframe=document.createElement('iframe');iframe.title=opts.iframeTitle;
                    document.querySelector(selector).append(iframe);nodes.push(iframe);setTimeout(update,10);
                    return {promise:Promise.resolve(),update(){setTimeout(update,0);}};
                },createAliases(auth,success,error){
                    if(auth.access_token!=='fixture-transient-token')throw Error('wrong transient token');
                    if(options[0].tokenization.storage!=='PERSISTENT'||options[1].tokenization.storage!=='VOLATILE'||options.some(o=>o.tokenization.format!=='UUID'))throw Error('wrong alias policy');
                    if(globalThis.collectFixtureMode==='error')error({secret:'DO_NOT_REFLECT_THIS'});
                    else if(globalThis.collectFixtureMode==='invalid')success(201,{card_number:'4111111111111111',card_cvc:'123'});
                    else if(globalThis.collectFixtureMode==='wrong-environment')success(201,{card_number:'tok_live_panfixture123',card_cvc:'tok_live_cvcfixture123'});
                    else success(201,{card_number:'tok_dev_panfixture123',card_cvc:'tok_dev_cvcfixture123'});
                },createCard(auth,success,error){
                    if(auth.auth!=='fixture-transient-token'||JSON.stringify(auth.data)!=='{"cardholder":{}}')throw Error('wrong card authorization');
                    if(options.map(o=>o.name).join(',')!=='pan,cvc,exp-date')throw Error('wrong card field names');
                    const attributes={pan_alias:'tok_dev_panfixture123',cvc_alias:globalThis.collectFixtureMode==='missing-cvc'?null:'tok_dev_cvcfixture123'};
                    success(201,{metadata:{observability:{vault_id:'tntTrainingDemo'}},data:{attributes}});
                },unmount(){nodes.forEach(n=>n.remove());callback({});}};
            }};'''
            for name in ('vgs-collect-dev-4.0.1.js','vgs-collect-4.0.1.js'):
                (extension/'vendor'/name).write_text(mock_sdk)
            prepare_profile(root / "profile")
            context = p.chromium.launch_persistent_context(
                str(root / 'profile'), executable_path=args.browser, headless=True,
                record_har_path=str(root / 'capture.har'), record_har_mode='full', record_har_content='embed', record_har_url_filter=har_recording_filter(),
                record_video_dir=str(root / 'video'), record_video_size={'width': 1280, 'height': 800},
                args=[f'--disable-extensions-except={extension}', f'--load-extension={extension}',
                      '--proxy-server=http://127.0.0.1:9', '--disable-quic',
                      '--host-resolver-rules=MAP awg-toggle.test 127.0.0.1, EXCLUDE 127.0.0.1, EXCLUDE localhost, MAP * ~NOTFOUND'],
            )
            try:
                worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                worker.evaluate('() => globalThis.pacReady')
                controls = context.new_page()
                panel_url = worker.url.rsplit('/', 1)[0] + '/popup.html'
                if args.walkthrough:
                    controls.set_viewport_size({'width':1440,'height':1000})
                    controls.goto(panel_url)
                    controls.locator('#environment-shortcut').filter(has_text='Sandbox').wait_for()
                    controls.locator('#tenant-id').filter(has_text='tntTrainingDemo').wait_for()
                    controls.evaluate('document.fonts.ready')
                    assert controls.locator('#environment-select option').all_text_contents() == ['Sandbox', 'Live']
                    controls.screenshot(path=str(args.screenshot), full_page=True)
                    controls.locator('button[data-view=settings]').click()
                    controls.locator('#environment-status').filter(has_text='Connected').wait_for()
                    controls.screenshot(path=str(args.screenshot.with_name('settings.png')), full_page=True)
                    controls.locator('button[data-view=controls]').click()
                    controls.locator('#open-create').click()
                    controls.locator('#add-alias').click()
                    controls.fill('#alias-0-alias', 'tok_sandbox_panfixture123')
                    controls.fill('#alias-0-bin', '411111')
                    controls.locator('#add-alias').click()
                    controls.fill('#alias-1-alias', 'tok_sandbox_cvcfixture123')
                    controls.screenshot(path=str(args.screenshot.with_name('create-session.png')), full_page=True)
                    controls.locator('#cancel-create').click()
                    controls.locator('button[data-view=diagnostics]').click()
                    controls.locator('summary').filter(has_text='Connect an assistant with MCP').click()
                    assert controls.locator('#mcp-status').inner_text() == 'MCP enabled for Sandbox. Gateway writes disabled.'
                    assert 'token' not in controls.locator('#mcp-client-config').inner_text()
                    controls.locator('#pac-script-details summary').click()
                    controls.locator('#load-pac').click()
                    controls.locator('#pac-script').filter(has_text='FindProxyForURL').wait_for()
                    assert controls.locator('#pac-script').inner_text() == pac_script
                    controls.screenshot(path=str(args.screenshot.with_name('diagnostics.png')), full_page=True)
                    print(json.dumps({'walkthrough':'passed','environment':'Sandbox','screenshots':4,'data':'synthetic local fixtures only'}))
                    return
                for suffix in ('', '?allow_dev_env=false', '?allow_dev_env=TRUE', '#allow_dev_env=true', '?allow_dev_env=true&allow_dev_env=false'):
                    controls.goto(panel_url + suffix)
                    controls.locator('#environment-shortcut').filter(has_text='Sandbox').wait_for()
                    assert controls.locator('#environment-select option').all_text_contents() == ['Sandbox', 'Live']
                    assert controls.locator('#session-id').inner_text() == 'RSLOCALFIXTURE'
                    assert controls.locator('button[data-mode=pac]').get_attribute('aria-pressed') == 'true'
                controls.goto(panel_url + '?allow_dev_env=true')
                controls.locator('#environment-shortcut').click()
                assert controls.locator('#environment-select option').all_text_contents() == ['Dev', 'Sandbox', 'Live']
                assert controls.locator('.brand').get_attribute('href') == panel_url + '?allow_dev_env=true'
                controls.select_option('#environment-select', 'dev')
                controls.locator('#environment-status').filter(has_text='Connected').wait_for()
                controls.locator('.brand').click()
                controls.locator('#environment-shortcut').filter(has_text='Dev').wait_for()
                assert controls.url == panel_url + '?allow_dev_env=true'
                controls.locator('#session-id').filter(has_text='RSLOCALFIXTURE').wait_for()
                assert controls.locator('#session-id').inner_text() == 'RSLOCALFIXTURE'
                assert controls.locator('#pac-source').text_content() == pac_url
                assert controls.locator('#tenant-id').inner_text() == 'tntTrainingDemo'
                assert controls.title() == 'Agent Web Gateway Control Panel'
                assert controls.locator('.flow-routes > button').count() == 4
                assert controls.locator('.pac-flow .flow-branch').count() == 2
                assert controls.locator('.pac-flow .flow-branch').nth(0).inner_text().replace('\n',' ').find('Matching destinations') > 0
                assert controls.locator('button[data-mode=direct] .flow-node').all_text_contents() == ['Browser','Destination']
                if args.screenshot:
                    controls.set_viewport_size({'width':1440,'height':1000})
                    controls.evaluate('document.fonts.ready')
                    controls.screenshot(path=str(args.screenshot.with_name('controls-pac.png')),full_page=True)
                controls.locator('button[data-view=settings]').click()
                assert not controls.locator('#account-setup').evaluate('(el)=>el.open')
                controls.locator('#account-setup summary').click()
                assert controls.locator('#account-login-command').inner_text() == 'vgs -e dev login'
                generated = controls.locator('#account-generate-command').inner_text()
                assert '-t agent-web-gateway-admin' in generated and '-T "$AWG_TENANT_ID"' in generated
                assert 'vgs -e dev generate service-account' in generated
                assert 'AWG_TENANT_ID="tntTrainingDemo"' in generated
                applied = controls.locator('#account-apply-command').inner_text()
                assert 'vgs -e dev apply service-account' in applied and '-O "$AWG_ORGANIZATION_ID"' in applied
                assert 'umask 077' in applied and 'set -o noclobber' in applied
                assert '> "$AWG_ACCOUNT_DIR/service-account-credentials.yaml"' in applied
                controls.evaluate('''() => Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{writeText:async text=>{window.fixtureClipboard=text;}}})''')
                controls.get_by_role('button',name='Copy create account commands',exact=True).click()
                controls.locator('#account-copy-status').filter(has_text='Copied.').wait_for()
                assert controls.evaluate('window.fixtureClipboard') == applied
                controls.evaluate('''() => renderAccountSetup('dev', '$(touch unsafe)')''')
                assert 'AWG_TENANT_ID="YOUR_TENANT_ID"' in controls.locator('#account-generate-command').inner_text()
                assert 'touch unsafe' not in controls.locator('#account-generate-command').inner_text()
                controls.evaluate('()=>renderAccountSetup(state.environment,state.account.tenantId)')
                if args.screenshot:
                    controls.screenshot(path=str(args.screenshot.with_name('account-setup.png')),full_page=True)
                    controls.set_viewport_size({'width':390,'height':844})
                    assert controls.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    controls.screenshot(path=str(args.screenshot.with_name('account-setup-mobile.png')),full_page=True)
                    controls.set_viewport_size({'width':1440,'height':1000})
                controls.locator('#account-setup summary').click()
                controls.locator('button[data-view=controls]').click()
                assert not controls.locator('#create-form').is_visible()
                controls.locator('#open-create').click()
                controls.locator('#create-title').filter(has_text='Create reveal session').wait_for()
                docs = controls.locator('a.doc-link').evaluate_all('(links)=>links.map(a=>({url:a.href,target:a.target,rel:a.rel,label:a.getAttribute("aria-label")}))')
                assert len(docs)==7
                assert all(d['url'].startswith('https://docs.verygoodsecurity.com/') and d['target']=='_blank' and 'noopener' in d['rel'] and 'noreferrer' in d['rel'] and 'new tab' in d['label'] for d in docs)
                assert any(d['url'].endswith('/reveal-sessions#post-reveal-sessions') for d in docs)
                assert any(d['url'].endswith('/reveal-sessions#get-reveal-sessions-id-.pac') for d in docs)
                context.route('https://docs.verygoodsecurity.com/**', lambda route: route.fulfill(status=200,content_type='text/html',body='<h1>Local documentation fixture</h1>'))
                with context.expect_page() as docs_opened:
                    controls.get_by_role('link', name='Create reveal session API (opens in a new tab)', exact=True).click()
                doc_page = docs_opened.value
                doc_page.locator('h1').filter(has_text='Local documentation fixture').wait_for()
                assert doc_page.evaluate('window.opener===null')
                assert controls.locator('#create-title').is_visible()
                doc_page.close()
                assert controls.locator('#alias-rows').inner_text() == ''
                controls.locator('#add-alias').click()
                controls.fill('#alias-0-alias', 'tok_sandbox_panfixture123')
                controls.fill('#alias-0-bin', '411111')
                controls.locator('#add-alias').click()
                controls.fill('#alias-1-alias', 'tok_sandbox_cvcfixture123')
                controls.fill('#allowed-client-cidrs', '203.0.113.0/24')
                controls.locator('#adapter-search').click()
                controls.fill('#adapter-search', 'Global')
                controls.get_by_role('option', name='Global-e · Registered').click()
                assert controls.locator('#egress-type').is_disabled()
                assert controls.locator('#egress-type option:checked').inner_text() == 'Saved proxy'
                assert controls.locator('#egress-fields').is_hidden()
                assert controls.locator('#egress-hostname').input_value() == ''
                controls.locator('#create-session').click()
                controls.locator('#created-session-id').filter(has_text='RSSECOND').wait_for()
                assert controls.locator('#session-id').text_content() == 'RSLOCALFIXTURE'
                assert controls.locator('#session-tokens').inner_text().endswith('fixture-standin')
                controls.locator('#back-create').click()
                controls.locator('#open-create').click()
                assert controls.locator('#alias-rows').inner_text() == ''
                assert controls.locator('#adapter-select').input_value() == ''
                assert controls.locator('#adapter-search').input_value() == 'Automatic'
                for mode, message in [('invalid','did not return both expected aliases'),('wrong-environment','did not return both expected aliases'),('error','could not create aliases')]:
                    controls.evaluate('(mode)=>globalThis.collectFixtureMode=mode',mode)
                    controls.locator('#add-card').click()
                    controls.locator('#create-aliases').click()
                    controls.locator('#card-notice').filter(has_text=message).wait_for()
                    assert controls.locator('.alias-row').count()==0
                    assert 'DO_NOT_REFLECT_THIS' not in controls.locator('body').inner_text()
                    assert '4111111111111111' not in controls.locator('body').inner_text()
                controls.evaluate('globalThis.collectFixtureMode="success"')
                controls.locator('#add-card').click()
                controls.locator('#cancel-card').click()
                assert controls.locator('.collect-field iframe').count()==0
                controls.locator('#add-card').click()
                controls.locator('#collect-status').filter(has_text='Ready to create aliases').wait_for()
                assert controls.locator('#add-card-panel input').count()==0
                assert controls.locator('.collect-field iframe').count()==2
                assert controls.locator('#collect-test-cards button').all_text_contents()==['Visa · 4242','Visa · 4111','Mastercard · 5454']
                for preset,pan in [('visa4242','4242424242424242'),('visa4111','4111111111111111'),('mastercard5454','5454545454545454')]:
                    controls.locator(f'[data-test-card={preset}]').click()
                    controls.locator('#collect-status').filter(has_text='Ready to create aliases').wait_for()
                    assert controls.evaluate('collectFixtureFields.map(f=>f.defaultValue)')==[pan,'123']
                    assert controls.locator('.collect-field iframe').count()==2
                    assert controls.locator('.alias-row').count()==0
                    assert pan not in controls.evaluate('JSON.stringify({state,localStorage,sessionStorage})')
                controls.locator('#create-aliases').click()
                controls.locator('#card-notice').filter(has_text='Aliases ready').wait_for()
                assert controls.locator('.alias-row').count()==2
                assert controls.input_value('#alias-0-alias')=='tok_dev_panfixture123'
                assert controls.input_value('#alias-1-alias')=='tok_dev_cvcfixture123'
                assert controls.input_value('#alias-0-length')=='16'
                assert controls.input_value('#alias-1-length')=='3'
                assert controls.locator('.collect-field iframe').count()==0
                assert 'fixture-transient-token' not in controls.evaluate('JSON.stringify({state,localStorage,sessionStorage})')
                assert 'fixture-transient-token' not in worker.evaluate('()=>chrome.storage.local.get(null).then(JSON.stringify)')
                controls.locator('#cancel-create').click()
                controls.locator('#open-create').click()
                # Exercise the Cards API branch for an account without aliases:write.
                fixture_catalog.cards_only = True
                controls.wait_for_function('() => !busy')
                controls.evaluate("()=>request({type:'refreshSessions'})")
                assert controls.evaluate('state.account.cardsWriteGranted && !state.account.scopes.some(s=>s.name==="aliases:write")')
                for mode,expected in [('missing-cvc','without a fresh security-code alias'),('card-success','Aliases ready')]:
                    controls.evaluate('(mode)=>globalThis.collectFixtureMode=mode',mode)
                    controls.locator('#add-card').click()
                    controls.locator('#collect-status').filter(has_text='Ready to create aliases').wait_for()
                    assert controls.locator('.collect-field iframe').count()==3
                    assert controls.evaluate('collectFixtureFields.every(f=>f.defaultValue===undefined)')
                    controls.locator('[data-test-card=visa4242]').click()
                    controls.locator('#collect-status').filter(has_text='Ready to create aliases').wait_for()
                    assert controls.evaluate('collectFixtureFields.map(f=>f.defaultValue)')==['4242424242424242','123',controls.evaluate('`12/${String((new Date().getFullYear()+3)%100).padStart(2,"0")}`')]
                    controls.locator('#create-aliases').click()
                    controls.locator('#card-notice').filter(has_text=expected).wait_for()
                    assert controls.locator('.alias-row').count()==(0 if mode=='missing-cvc' else 2)
                # Exercise visibility and the runtime guard without any external API.
                for env,visible in [('sandbox',True),('live',False)]:
                    controls.evaluate('(env)=>collectCard.open(env,state.account,()=>{})',env)
                    assert controls.locator('#collect-test-cards').evaluate('(n)=>!n.hidden')==visible
                    assert controls.evaluate('collectFixtureFields.every(f=>f.defaultValue===undefined)')
                    if env=='live':
                        controls.locator('[data-test-card=visa4242]').dispatch_event('click')
                        controls.evaluate('()=>collectCard.open("live",state.account,()=>{},"visa4242")')
                        assert controls.evaluate('collectFixtureFields.every(f=>f.defaultValue===undefined)')
                controls.evaluate('collectCard.reset()')
                if args.screenshot:
                    controls.set_viewport_size({'width':1440,'height':1100})
                    controls.screenshot(path=str(args.screenshot.with_name('create-session.png')),full_page=True)
                    controls.set_viewport_size({'width':390,'height':844})
                    assert controls.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    controls.screenshot(path=str(args.screenshot.with_name('create-mobile.png')),full_page=True)
                    controls.set_viewport_size({'width':1440,'height':1000})
                controls.locator('#cancel-create').click()
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
                    controls.set_viewport_size({'width': 1440, 'height': 1000})
                    controls.screenshot(path=str(args.screenshot), full_page=True)
                assert controls.get_by_role('heading', name='Proxy Settings').is_visible()
                controls.locator('#browser-egress-settings summary').click()
                controls.select_option('#browser-egress-source', 'custom')
                controls.fill('#browser-egress-host', '127.0.0.1')
                controls.fill('#browser-egress-port', str(egress.server_port))
                controls.locator('#browser-egress-auth').check()
                controls.fill('#browser-egress-user', 'fixture-egress')
                controls.fill('#browser-egress-password', 'dummy-egress')
                controls.locator('#save-browser-egress').click()
                controls.locator('#browser-egress-status').filter(has_text='Saved. Select').wait_for()
                assert controls.locator('#browser-egress-password').input_value() == ''
                assert controls.locator('button[data-mode=direct][aria-pressed=true]').is_visible()
                select('egress')
                route('/manual-egress', 'egress')
                controls.reload()
                controls.locator('button[data-mode=egress][aria-pressed=true]').wait_for()
                controls.locator('#browser-egress-settings summary').click()
                assert controls.locator('#browser-egress-source').input_value() == 'custom'
                assert controls.locator('#browser-egress-auth').is_checked()
                assert controls.locator('#browser-egress-password').input_value() == ''
                if args.screenshot:
                    controls.screenshot(path=str(args.screenshot.with_name('egress-settings.png')), full_page=True)
                controls.select_option('#browser-egress-source', 'session')
                controls.locator('#save-browser-egress').click()
                controls.locator('#browser-egress-status').filter(has_text='Saved and applied').wait_for()
                controls.locator('#browser-egress-settings summary').click()
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
                controls.locator('button[data-view=diagnostics]').click()
                controls.locator('#pac-script-details summary').click()
                controls.locator('#load-pac').click()
                controls.locator('#pac-script').filter(has_text='FindProxyForURL').wait_for()
                assert controls.locator('#pac-script').inner_text() == pac_script
                assert controls.locator('option[value=RSMISSING]').is_disabled()
                if args.screenshot:
                    controls.screenshot(path=str(args.screenshot.with_name('diagnostics.png')),full_page=True)
                controls.locator('button[data-view=settings]').click()
                for env, expected in [('sandbox', 'https://sandbox.vgsapi.com'), ('live', 'https://vgsapi.com')]:
                    controls.select_option('#environment-select', env)
                    controls.locator('#environment-status').filter(has_text='Not connected').wait_for()
                    assert controls.locator('#account-login-command').text_content() == 'vgs login'
                    assert 'vgs -e dev' not in controls.locator('#account-apply-command').text_content()
                    assert f'/agent-web-gateway/{env}/' in controls.locator('#account-created-file').text_content()
                    assert controls.locator('#environment-domains').count() == 0
                    assert not controls.locator('#environment-notice').get_attribute('hidden')
                    assert controls.locator('#open-create').is_enabled()
                    controls.locator('button[data-view=controls]').click()
                    controls.locator('#open-create').click()
                    assert controls.locator('#account-file').is_visible()
                    assert controls.locator('input#account-tenant').count() == 0
                    assert not controls.locator('#account-tenant-choice').is_visible()
                    assert 'service account' in controls.locator('#creation-availability').text_content()
                    route('/unchanged-' + env, 'vgs-second')
                controls.fill('#account-file','/tmp/previous.json')
                controls.locator('#browse-account-file').click()
                controls.locator('#account-file-status').filter(has_text='Click Connect account').wait_for()
                assert controls.input_value('#account-file') == '/tmp/Service account ü.json'
                assert controls.locator('#environment-status').filter(has_text='Not connected').is_visible()
                controls.locator('#browse-account-file').click()
                controls.locator('#account-file-status').filter(has_text='cancelled').wait_for()
                assert controls.input_value('#account-file') == '/tmp/Service account ü.json'
                controls.locator('#browse-account-file').click()
                controls.locator('#account-file-error').filter(has_text='File explorer is unavailable').wait_for()
                assert controls.locator('#account-file').is_enabled()
                controls.fill('#account-file','/missing/fixture-account.txt')
                controls.locator('#connect-account').click()
                controls.locator('#account-file-error').filter(has_text='could not read').wait_for()
                controls.reload()
                controls.locator('#environment-shortcut').filter(has_text='Live').wait_for()
                controls.locator('button[data-view=settings]').click()
                controls.select_option('#environment-select', 'dev')
                controls.locator('#environment-status').filter(has_text='Connected').wait_for()
                if args.screenshot: controls.screenshot(path=str(args.screenshot.with_name('settings.png')),full_page=True)
                controls.locator('button[data-view=controls]').click()
                cdp.send('ServiceWorker.stopAllWorkers')
                controls.reload()
                controls.locator('#session-id').filter(has_text='RSSECOND').wait_for()
                route('/second-after-restart', 'vgs-second')
                if args.screenshot:
                    controls.screenshot(path=str(args.screenshot), full_page=True)
                if args.screenshot:
                    controls.set_viewport_size({'width': 390, 'height': 844})
                    assert controls.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    controls.screenshot(path=str(args.screenshot.with_name('mobile.png')), full_page=True)
                    controls.set_viewport_size({'width': 1440, 'height': 1000})
                    await_fonts = controls.evaluate('document.fonts.ready.then(() => document.fonts.check(\'14px Averta\'))')
                    assert await_fonts
                    assert controls.locator('.brand img').evaluate('(img) => img.complete && img.naturalWidth > 0')
                    worker = context.service_workers[0]
                    tabs = worker.evaluate('() => openControls().then(() => chrome.tabs.query({url:chrome.runtime.getURL("popup.html")+"*"})).then(t => t.map(tab => tab.url))')
                    assert tabs == [panel_url + '?allow_dev_env=true']
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
