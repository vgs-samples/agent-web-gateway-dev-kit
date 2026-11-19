"""Gateway views and CA downloads against local synthetic API fixtures."""
import argparse
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit, parse_qs

from awg_dev_api import ApiError
from environments import domains
from session_catalog import Catalog, CatalogServer
from session_proxy_extension import write_extension
from test_session_certificates import PEM


class Client:
    environment = 'sandbox'
    tenant = 'fixtureTenant'
    def __init__(self):
        self.calls = []; self.fail = False; self.fail_functions = False; self.delay_bindings = False; self.delayed = False
        self.rows = {
            'agent-gateway-destinations': [{'id':f'DNfixture{i}', 'attributes':{'host_pattern':f'Fixture destination {i}',
                'action':['guarded','trust','block'][i%3], 'origin':'auto', 'created_by':'agent-gateway-auto-staging'}} for i in range(51)],
            'agent-gateway-adapters':[{'id':'ADfixture', 'attributes':{'name':'Fixture adapter','functions':['FNfixture'],'version':1,'published_version':1,'owner':'tenant'}}],
            'functions':[{'id':'FNfixture','attributes':{'name':'Fixture function','language':'larky','extension_point':'route.request','inputs':[{'name':'key','required':True}],
                'source':'# <script>window.untrustedSource = true</script>\ndef transform(value):\n    return value'}}],
            'agent-gateway-adapter-destinations':[
                *[{'id':f'AXother{i}','attributes':{'adapter':'ADother','enabled':True,'when':{'host':'Unrelated host'}}} for i in range(100)],
                {'id':'AXfixture','attributes':{'adapter':'ADfixture','adapter_version':1,'enabled':True,
                    'when':{'host':'Fixture host','method':'POST','path':'/payment'},'functions':[{'id':'FNfixture','inputs':{'key':{'from':'constant','value':'fixture'}}}]}},
                {'id':'AXdisabled','attributes':{'adapter':'ADfixture','adapter_version':1,'enabled':False,
                    'when':{'host':'Fixture host','method':'GET','path':'/setup'},'functions':[{'id':'FNfixture','inputs':{}}]}}
            ]
        }
    def api(self, method, path):
        self.calls.append((method,path)); assert method == 'GET'
        if self.fail: raise ApiError(403,'PRIVATE BODY')
        parsed=urlsplit(path); parts=parsed.path.strip('/').split('/'); rows=self.rows.get(parts[0],[])
        if self.fail_functions and parts[0]=='functions': raise ApiError(403,'PRIVATE FUNCTION BODY')
        if self.delay_bindings and parts[0]=='agent-gateway-adapter-destinations':
            import time
            self.delayed = True; time.sleep(0.3)
        if len(parts)>1: return {'data':next(row for row in rows if row['id']==parts[1])}
        query=parse_qs(parsed.query); offset=int(query.get('offset',['0'])[0]); limit=int(query.get('limit',['50'])[0])
        return {'data':rows[offset:offset+limit], 'meta':{'total_elements':len(rows)}}


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--browser'); parser.add_argument('--screenshot',type=Path)
    parser.add_argument('--screenshots-dir', type=Path, help='Save walkthrough images using only the synthetic Sandbox account')
    args=parser.parse_args()
    from playwright.sync_api import sync_playwright, expect
    server=context=None
    try:
        with tempfile.TemporaryDirectory(prefix='awg-gateway-') as temporary, sync_playwright() as p:
            root=Path(temporary); client=Client(); saved=root/'RSFIXTURE.json'
            attrs={'expires_at':'2099-01-01T00:00:00Z','proxy':{'url':domains('sandbox',client.tenant)['proxy'].replace('https://','https://fixture:secret@'),
                'ca_bundle':PEM,'pac_url':'https://sandbox.vgsapi.com/reveal-sessions/RSFIXTURE.pac'}}
            attrs['tokens']=[{'format':'card_number','value':'fixture-card-standin'},{'format':'card_cvc','value':'fixture-cvc-standin'}]
            saved.write_text(json.dumps({'data':{'id':'RSFIXTURE','attributes':attrs}}))
            second={**attrs,'proxy':{**attrs['proxy'],'pac_url':'https://sandbox.vgsapi.com/reveal-sessions/RSSECOND.pac'},
                    'tokens':[{'format':'card_number','value':'second-card-standin'},{'format':'card_cvc','value':'second-cvc-standin'}]}
            (root/'RSSECOND.json').write_text(json.dumps({'data':{'id':'RSSECOND','attributes':second}}))
            client.rows['reveal-sessions']=[{'id':'RSFIXTURE','attributes':attrs},{'id':'RSSECOND','attributes':second}]
            catalog=Catalog(saved,client,root,use_settings=False)
            catalog.operations.account=lambda:{'connected':True,'configured':True,'tenantId':client.tenant,'scopes':[], 'creationAvailable':True}
            server=CatalogServer(None,catalog=catalog,profiles={},captures_directory=root/'captures')
            extension=root/'extension'
            write_extension(extension,attrs['proxy']['pac_url'],{}, {'scheme':'http','host':'127.0.0.1','port':9},
                session_id='RSFIXTURE',expires_at=attrs['expires_at'],catalog=server.config,initial_mode='direct')
            context=p.chromium.launch_persistent_context(str(root/'profile'),executable_path=args.browser,channel='chromium' if not args.browser else None,
                headless=True,accept_downloads=True,args=[f'--disable-extensions-except={extension}',f'--load-extension={extension}',
                '--host-resolver-rules=EXCLUDE 127.0.0.1, MAP * ~NOTFOUND','--disable-background-networking'])
            worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page=context.new_page(); page.set_viewport_size({'width':1500,'height':1050}); errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(worker.url.rsplit('/',1)[0]+'/popup.html')
            expect(page.locator('#state')).to_have_text('No Proxy')
            expect(page.locator('[data-mode="pac"] .route-name')).to_have_text('VGS Reveal Session PAC File')
            expect(page.locator('[data-mode="session"] .route-name')).to_have_text('VGS Reveal Session Proxy')
            with page.expect_download() as event: page.locator('#download-proxy-ca').click()
            download=event.value; assert download.suggested_filename=='vgs-sandbox-RSFIXTURE-ca.pem'
            assert Path(download.path()).read_text()==PEM
            expect(page.locator('#selected-session-tokens')).to_contain_text('fixture-card-standin')
            page.evaluate("showView('create'); renderOperation({status:'complete',sessionId:'RSSECOND',environment:'sandbox',tokens:[]})")
            expect(page.locator('#view-controls')).to_be_visible()
            expect(page.locator('#session-created-notice')).to_be_visible()
            expect(page.locator('#selected-session-tokens')).to_contain_text('second-card-standin')
            expect(page.locator('#session-inspector-state')).to_have_text('Not active')
            expect(page.locator('#session-id')).to_have_text('RSFIXTURE')
            expect(page.locator('#use-session')).to_be_enabled()
            with page.expect_download() as event: page.locator('#download-selected-ca').click()
            assert event.value.suggested_filename=='vgs-sandbox-RSSECOND-ca.pem'
            page.locator('#use-session').click()
            expect(page.locator('#session-id')).to_have_text('RSSECOND')
            expect(page.locator('#session-inspector-state')).to_have_text('Active in browser')
            expect(page.locator('#state')).to_have_text('No Proxy')
            page.reload()
            expect(page.locator('#selected-session-tokens')).to_contain_text('second-card-standin')
            expect(page.locator('#session-inspector-title')).to_have_text('Session aliases')
            assert page.locator('#selected-session-id, #selected-session-summary').count() == 0
            if args.screenshots_dir:
                args.screenshots_dir.mkdir(parents=True, exist_ok=True)
                page.evaluate('document.fonts.ready')
                page.screenshot(path=str(args.screenshots_dir/'control-panel.png'), full_page=True)
                page.locator('[data-view="settings"]').click()
                page.screenshot(path=str(args.screenshots_dir/'settings.png'), full_page=True)
                page.locator('[data-view="controls"]').click()
                page.locator('#open-create').click()
                expect(page.locator('#create-title')).to_be_visible()
                page.screenshot(path=str(args.screenshots_dir/'create-session.png'), full_page=True)
                page.locator('#cancel-create').click()
                page.locator('[data-view="diagnostics"]').click()
                page.screenshot(path=str(args.screenshots_dir/'diagnostics.png'), full_page=True)
            page.get_by_role('button',name='Agent Web Gateway Config',exact=True).click()
            expect(page.locator('#gateway-range')).to_have_text('1–50 of 51')
            expect(page.locator('#gateway-table-body tr')).to_have_count(50)
            page.locator('#gateway-action-filter').select_option('review')
            expect(page.locator('#gateway-table-body tr')).to_have_count(17)
            page.locator('#gateway-action-filter').select_option('all'); page.locator('#gateway-next').click()
            expect(page.locator('#gateway-range')).to_have_text('51–51 of 51')
            page.get_by_role('button',name='View Fixture destination 50',exact=True).click()
            expect(page.locator('#gateway-detail-title')).to_have_text('Fixture destination 50')
            expect(page.locator('#gateway-detail-fields')).to_contain_text('Block')
            assert page.locator('[data-gateway-resource]').count()==2
            assert page.locator('#gateway-context').count()==0
            page.locator('[data-gateway-resource="agent-gateway-adapters"]').click()
            expect(page.get_by_role('table',name='Adapter registry',exact=True)).to_contain_text('Default')
            expect(page.locator('#gateway-table-head')).to_have_text('AdapterTypeVersionFunctionsPublication')
            page.get_by_role('button',name='View Fixture adapter',exact=True).click()
            expect(page.get_by_role('table',name='Adapter functions',exact=True)).to_contain_text('Fixture function')
            expect(page.locator('#gateway-functions-body')).to_contain_text('Request')
            expect(page.locator('#gateway-functions-body')).to_contain_text('key (required)')
            expect(page.locator('#gateway-destination-count')).to_have_text('2 of 2 destinations')
            expect(page.locator('#gateway-destinations-table')).not_to_contain_text('Unrelated host')
            expect(page.locator('#gateway-destinations-table')).to_contain_text('Disabled')
            page.locator('#gateway-destination-search').fill('POST payment')
            expect(page.locator('#gateway-destination-count')).to_have_text('1 of 2 destinations')
            page.get_by_role('button',name='View fixture host /payment',exact=True).click()
            expect(page.locator('#gateway-detail-title')).to_have_text('Fixture host')
            expect(page.locator('#gateway-bindings')).to_contain_text('constant')
            page.locator('#gateway-breadcrumbs').get_by_role('button',name='Fixture adapter',exact=True).click()
            expect(page.locator('#gateway-destination-count')).to_have_text('2 of 2 destinations')
            page.locator('#gateway-functions-body').get_by_role('button',name='Fixture function',exact=True).click()
            expect(page.locator('#gateway-source')).to_contain_text('<script>')
            assert not page.evaluate('!!window.untrustedSource')
            expect(page.locator('#gateway-breadcrumbs')).to_contain_text('Fixture adapter')
            page.locator('#gateway-breadcrumbs').get_by_role('button',name='Fixture adapter',exact=True).click()
            expect(page.locator('#gateway-functions-body')).to_contain_text('Fixture function')
            client.fail_functions=True; page.locator('#gateway-refresh').click()
            expect(page.locator('#gateway-functions-body')).to_contain_text('Could not load definition')
            expect(page.locator('#gateway-destination-count')).to_have_text('2 of 2 destinations')
            assert 'PRIVATE FUNCTION BODY' not in page.content()
            client.fail_functions=False; page.locator('#gateway-refresh').click()
            expect(page.locator('#gateway-functions-body')).to_contain_text('Fixture function')
            if args.screenshot: page.screenshot(path=str(args.screenshot),full_page=True)
            if args.screenshots_dir: page.screenshot(path=str(args.screenshots_dir/'gateway-config.png'),full_page=True)
            client.fail=True; page.locator('#gateway-refresh').click()
            expect(page.locator('#gateway-error')).to_contain_text('agent-gateway:read')
            expect(page.locator('#gateway-adapter-children')).to_be_hidden()
            assert 'PRIVATE BODY' not in page.content()
            client.fail=False; page.locator('[data-gateway-resource="agent-gateway-adapters"]').click()
            page.get_by_role('button',name='View Default',exact=True).click()
            expect(page.locator('#gateway-default')).to_be_visible()
            expect(page.locator('#gateway-table-body tr')).to_have_count(17)
            page.locator('[data-default-section="destinations"]').click()
            expect(page.locator('#gateway-table-body tr')).to_have_count(50)
            page.get_by_role('button',name='View Fixture destination 0',exact=True).click()
            expect(page.locator('#gateway-detail-title')).to_have_text('Fixture destination 0')
            page.locator('[data-gateway-resource="agent-gateway-adapters"]').click()
            client.delay_bindings=True
            page.get_by_role('button',name='View Fixture adapter',exact=True).click()
            import time
            deadline=time.monotonic()+5
            while not client.delayed and time.monotonic()<deadline: time.sleep(0.02)
            assert client.delayed
            page.evaluate("state={...state,environment:'live',account:{connected:false}};render()")
            expect(page.locator('#gateway-table-body')).not_to_contain_text('Fixture adapter')
            page.wait_for_timeout(800)
            expect(page.locator('#gateway-adapter-children')).to_be_hidden()
            expect(page.locator('#gateway-breadcrumbs')).to_be_hidden()
            assert not any(path=='/functions?limit=50&offset=0' for _,path in client.calls), 'No global function library should be loaded'
            assert page.locator('#selected-session-tokens').inner_text()==''
            assert not errors, errors
            assert all(method=='GET' for method,_ in client.calls)
            context.close(); context=None
            print('Gateway panel passed: dashboard registry, adapter children across pages, grouped destinations, function details, partial errors, default policy, stale account clearing, route labels, created-session home navigation, persistent stand-ins, explicit activation, and CA downloads.')
    finally:
        if context:
            try: context.close()
            except Exception: pass
        if server: server.close()


if __name__=='__main__': main()
