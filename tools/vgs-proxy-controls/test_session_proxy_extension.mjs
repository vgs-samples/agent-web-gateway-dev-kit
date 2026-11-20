// Offline regression tests: no browser, network, session, or real credentials.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const pac = 'https://pac.invalid/session.pac?test-only';
const credentials = {
    'vgs.invalid:3443': {username: 'fixture-vgs', password: 'fixture-vgs-secret'},
    'egress.invalid:3128': {username: 'fixture-egress', password: 'fixture-egress-secret'}
};
const proxies = {session: {scheme: 'https', host: 'vgs.invalid', port: 3443}, egress: {scheme: 'http', host: 'egress.invalid', port: 3128}};
const initial = {sessionId: 'RSFIRST', expiresAt: '2099-01-01T00:00:00Z', pacUrl: pac, pacSource: 'https://pac.invalid/session.pac', proxies, credentials};
const next = {...initial, sessionId: 'RSSECOND', pacUrl: pac + '-second', credentials: {...credentials,
    'vgs.invalid:3443': {username: 'second-vgs', password: 'second-secret'}}};
const source = `const INITIAL_SESSION = ${JSON.stringify(initial)};\nconst CATALOG = {url: 'http://127.0.0.1:1234', token: 'catalog-secret'};\n` +
    readFileSync(new URL('./session-proxy-extension/background.js', import.meta.url), 'utf8');

function event() {
    const listeners = [];
    return {listeners, addListener: listener => listeners.push(listener),
        fire: (...args) => listeners.forEach(listener => listener(...args))};
}

async function fixture(previous, noEgress = false, saved = {}, environmentSupport = false) {
    const storage = structuredClone(saved);
    const cleared = [];
    let fetched = [];
    let failFetch = false;
    let config = structuredClone(previous || {
        value: {mode: 'fixed_servers'}, levelOfControl: 'controllable_by_this_extension'
    });
    const sets = [];
    const badge = {};
    let failSet = false;
    const chrome = {
        storage: {local: {
            setAccessLevel: async () => {}, get: async () => structuredClone(storage),
            set: async values => Object.assign(storage, structuredClone(values)),
            remove: async keys => keys.forEach(k => delete storage[k])
        }},
        browsingData: {remove: (options, types, callback) => {cleared.push({options, types}); callback();}},
        runtime: {id: 'fixture', getURL: path => `chrome-extension://fixture/${path}`, onMessage: event()},
        action: {onClicked: event(), setBadgeText: d => badge.text = d.text, setBadgeBackgroundColor: d => badge.color = d.color,
            setTitle: d => badge.title = d.title},
        proxy: {onProxyError: event(), settings: {
            onChange: event(),
            get: (_, done) => done(structuredClone(config)),
            set: (setting, done) => {
                if (failSet) {
                    chrome.runtime.lastError = {message: 'SECRET must not reach popup'};
                    done();
                    delete chrome.runtime.lastError;
                    return;
                }
                sets.push(structuredClone(setting));
                config = {value: structuredClone(setting.value), levelOfControl: 'controlled_by_this_extension'};
                chrome.proxy.settings.onChange.fire(config);
                done();
            },
            clear: () => { throw new Error('clear() would restore the blocking bootstrap proxy'); }
        }},
        webRequest: {onAuthRequired: event(), onCompleted: event(), onErrorOccurred: event()}
    };
    const context = vm.createContext({chrome, URL, Date, AbortSignal, fetch: async (url, options) => {
        fetched.push({url, options});
        if (failFetch) throw new Error('SECRET fetch error');
        if (url.endsWith('/collect-token')) return {ok:true,json:async()=>({accessToken:'fixture-transient',environment:'dev',tenantId:'fixture-tenant',method:'aliases'})};
        if (url.endsWith('/account')) return {ok: true, json: async () => ({configured: !url.includes('/sandbox/') && !url.includes('/live/'), connected: true})};
        return {ok: true, json: async () => url.endsWith('/config') ? structuredClone(next)
            : url.endsWith('/pac') ? {pacScript: 'function FindProxyForURL() {}', fetchedAt: '2026-01-01T00:00:00Z'}
            : {sessions: [{sessionId: 'RSSECOND', available: true}], checkedAt: '2026-01-01T00:00:00Z'}};
    }});
    let selectedSource = environmentSupport ? source.replace("token: 'catalog-secret'", "token: 'catalog-secret', environments: true, environment: 'dev'") : source;
    vm.runInContext(noEgress ? selectedSource.replace(JSON.stringify(proxies), JSON.stringify({...proxies, egress: null})) : selectedSource, context);
    await context.pacReady;
    const sender = {id: 'fixture', url: 'chrome-extension://fixture/popup.html?allow_dev_env=true'};
    return {
        chrome, context, sets, badge, storage, cleared, fetched, failFetch: () => failFetch = true,
        config: () => structuredClone(config),
        fail: () => failSet = true,
        message: (message, from = sender) => new Promise(resolve => {
            const result = chrome.runtime.onMessage.listeners[0](message, from, resolve);
            if (result !== true) resolve(undefined);
        }),
        auth: (host = 'vgs.invalid', port = 3443, requestId = 'a', isProxy = true) =>
            new Promise(resolve => chrome.webRequest.onAuthRequired.listeners[0](
                {challenger: {host, port}, requestId, isProxy}, resolve))
    };
}
const plain = value => JSON.parse(JSON.stringify(value));
const controlsSender = suffix => ({id: 'fixture', url: 'chrome-extension://fixture/popup.html' + suffix});

test('normal controls fall back from saved Dev without changing the active session or route', async () => {
    const f = await fixture(undefined, false, {selectedEnvironment: 'dev'}, true);
    const before = f.config();
    const result = await f.message({type: 'refreshSessions'}, controlsSender(''));
    assert.equal(result.environment, 'sandbox');
    assert.equal(result.session.environment, 'dev');
    assert.equal(result.session.sessionId, 'RSFIRST');
    assert.deepEqual(f.config(), before);
    assert.equal(f.storage.selectedEnvironment, 'sandbox');
    assert.deepEqual(f.fetched.map(r => r.url), ['http://127.0.0.1:1234/environments/sandbox/account']);
    assert.ok(!JSON.stringify(f.storage).includes('allow_dev_env'));
});

test('only one exact true query value enables Dev, and removing it removes access', async () => {
    const f = await fixture(undefined, false, {}, true);
    for (const suffix of ['', '?allow_dev_env=false', '?allow_dev_env=TRUE', '?allow_dev_env=1',
        '?allow_dev_env=', '#allow_dev_env=true', '?allow_dev_env=true&allow_dev_env=true', '?allow_dev_env=true&allow_dev_env=false']) {
        const before = f.fetched.length;
        const result = await f.message({type: 'setEnvironment', environment: 'dev'}, controlsSender(suffix));
        assert.equal(result.ok, false, suffix);
        assert.equal(result.environment, 'sandbox', suffix);
        assert.match(result.error, /allow_dev_env=true/);
        assert.equal(f.fetched.length, before);
    }
    for (const suffix of ['?allow_dev_env=true', '?other=ok&allow_dev_env=true#settings']) {
        assert.equal((await f.message({type: 'setEnvironment', environment: 'dev'}, controlsSender(suffix))).environment, 'dev');
        assert.equal((await f.message({type: 'getState'}, controlsSender(''))).environment, 'sandbox');
    }
});

test('Dev account, token, and job requests cannot bypass the URL gate', async () => {
    const f = await fixture(undefined, false, {}, true);
    for (const type of ['connectAccount', 'getCollectToken', 'createSession', 'createCard', 'creationStatus', 'cardStatus', 'selectSession', 'getAdapters']) {
        const result = await f.message({type, environment: 'dev', requestId: '12345678-1234-1234-1234-123456789abc'}, controlsSender(''));
        assert.equal(result.ok, false, type);
        assert.match(result.error, /allow_dev_env=true/);
    }
    assert.equal(f.fetched.length, 0);
});

test('a legacy Dev-only helper is never used as Sandbox after fallback', async () => {
    const f = await fixture();
    const result = await f.message({type: 'refreshSessions'}, controlsSender(''));
    assert.equal(result.environment, 'sandbox');
    assert.ok(result.catalogError);
    assert.equal(f.fetched.length, 0);
});

test('a Dev flag on a different extension page or origin is rejected', async () => {
    const f = await fixture();
    for (const url of ['chrome-extension://fixture/other.html?allow_dev_env=true',
        'chrome-extension://other/popup.html?allow_dev_env=true',
        'https://fixture/popup.html?allow_dev_env=true']) {
        assert.equal(await f.message({type: 'setMode', mode: 'direct'}, {id: 'fixture', url}), undefined);
    }
    assert.equal(f.config().value.mode, 'pac_script');
});

test('fresh profile starts with the exact mandatory PAC', async () => {
    const f = await fixture();
    assert.deepEqual(f.sets, [{scope: 'regular', value: {mode: 'pac_script', pacScript: {url: pac, mandatory: true}}}]);
    assert.equal(f.badge.text, 'PAC');
});

for (const [mode, badge] of Object.entries({session: 'VGS', egress: 'EGR', direct: 'OFF', pac: 'PAC'})) {
    test(`${mode} applies the correct route and persists after worker restart`, async () => {
        const f = await fixture();
        assert.equal((await f.message({type: 'setMode', mode})).mode, mode);
        const expected = mode === 'pac' ? {mode: 'pac_script', pacScript: {url: pac, mandatory: true}}
            : mode === 'direct' ? {mode: 'direct'}
            : {mode: 'fixed_servers', rules: {singleProxy: proxies[mode], bypassList: []}};
        assert.deepEqual(f.config().value, expected);
        const restarted = await fixture(f.config());
        assert.equal(restarted.sets.length, 0);
        assert.equal(restarted.badge.text, badge);
    });
    test(`${mode} authenticates only the permitted proxy endpoints`, async () => {
        const f = await fixture();
        await f.message({type: 'setMode', mode});
        for (const [role, endpoint] of Object.entries(proxies)) {
            const expected = mode === 'pac' || mode === role
                ? {authCredentials: credentials[endpoint.host + ':' + endpoint.port]} : {cancel: true};
            assert.deepEqual(plain(await f.auth(endpoint.host.toUpperCase(), endpoint.port, role)), expected);
        }
        assert.deepEqual(plain(await f.auth('other.invalid')), {cancel: true});
        assert.deepEqual(plain(await f.auth('vgs.invalid', 8443)), {cancel: true});
        assert.deepEqual(plain(await f.auth('vgs.invalid', 3443, 'origin', false)), {});
    });
}

test('missing egress is disabled and never silently becomes direct', async () => {
    const f = await fixture(undefined, true);
    assert.equal((await f.message({type: 'setMode', mode: 'egress'})).ok, false);
    assert.deepEqual(plain((await f.message({type: 'getState'})).availableModes), ['pac', 'session', 'direct']);
    assert.equal(f.config().value.mode, 'pac_script');
    assert.deepEqual(plain(await f.auth('egress.invalid', 3128)), {cancel: true});
});

test('auth retries are bounded per request and endpoint, then cleaned up', async () => {
    const f = await fixture();
    assert.ok((await f.auth()).authCredentials);
    assert.deepEqual(plain(await f.auth()), {cancel: true});
    f.chrome.webRequest.onCompleted.fire({requestId: 'a'});
    assert.ok((await f.auth()).authCredentials);
    f.chrome.webRequest.onErrorOccurred.fire({requestId: 'a'});
    assert.ok((await f.auth()).authCredentials);
});

test('rapid mode selections finish in the last selected mode', async () => {
    const f = await fixture();
    const modes = ['direct', 'session', 'egress', 'pac'];
    const results = await Promise.all(modes.map(mode => f.message({type: 'setMode', mode})));
    assert.deepEqual(results.map(r => r.mode), modes);
    assert.equal(f.config().value.mode, 'pac_script');
});

test('rejected change reports actual state without leaking the error', async () => {
    const f = await fixture();
    f.fail();
    const result = await f.message({type: 'setMode', mode: 'direct'});
    assert.equal(result.ok, false);
    assert.equal(result.mode, 'pac');
    assert.ok(!JSON.stringify(result).includes('SECRET'));
});

test('only controls may change routing; responses contain no endpoints or credentials', async () => {
    const f = await fixture();
    assert.equal(await f.message({type: 'setMode', mode: 'direct'}, {id: 'other', url: 'https://example.invalid'}), undefined);
    assert.equal(await f.message({type: 'setMode', mode: 'direct'}, {id: 'fixture', url: 'https://example.invalid'}), undefined);
    const result = await f.message({type: 'getState'});
    for (const secret of ['fixture-vgs-secret', 'fixture-egress-secret', 'catalog-secret', '?test-only']) assert.ok(!JSON.stringify(result).includes(secret));
    assert.equal((await f.message({type: 'setMode', mode: 'bad'})).ok, false);
});

test('foreign settings are reported unavailable and do not supply auth', async () => {
    const f = await fixture({value: {mode: 'direct'}, levelOfControl: 'controlled_by_other_extensions'});
    assert.equal(f.sets.length, 0);
    assert.equal((await f.message({type: 'getState'})).mode, 'unavailable');
    assert.deepEqual(plain(await f.auth()), {cancel: true});
});

test('session selection preserves mode, clears scoped auth, and survives restart', async () => {
    for (const mode of ['pac', 'session', 'egress', 'direct']) {
        const f = await fixture();
        await f.message({type: 'setMode', mode});
        const result = await f.message({type: 'selectSession', sessionId: 'RSSECOND'});
        assert.equal(result.ok, true);
        assert.equal(result.mode, mode);
        assert.equal(result.session.sessionId, 'RSSECOND');
        assert.deepEqual(plain(f.cleared), [{options: {since: 0, origins: ['https://vgs.invalid:3443', 'http://egress.invalid:3128']}, types: {cookies: true}}]);
        assert.equal(f.storage.selectedSession.sessionId, 'RSSECOND');
        const restarted = await fixture(f.config(), false, f.storage);
        assert.equal((await restarted.message({type: 'getState'})).session.sessionId, 'RSSECOND');
        assert.equal((await restarted.message({type: 'getState'})).mode, mode);
        if (['pac', 'session'].includes(mode)) assert.equal((await restarted.auth()).authCredentials.username, 'second-vgs');
    }
});
test('failed refresh disables stale choices; failed selection keeps route and auth', async () => {
    const f = await fixture();
    assert.equal((await f.message({type: 'refreshSessions'})).sessions.length, 1);
    f.failFetch();
    const refreshed = await f.message({type: 'refreshSessions'});
    assert.equal(refreshed.sessions.length, 0);
    assert.ok(refreshed.catalogError);
    const result = await f.message({type: 'selectSession', sessionId: 'RSSECOND'});
    assert.equal(result.ok, false);
    assert.equal(result.session.sessionId, 'RSFIRST');
    assert.equal(result.mode, 'pac');
    assert.ok(!JSON.stringify(result).includes('SECRET'));
});
test('interrupted session switch stays blocked across restart', async () => {
    const f = await fixture({value: {mode: 'fixed_servers', rules: {singleProxy: {scheme: 'http', host: '127.0.0.1', port: 9}}}, levelOfControl: 'controlled_by_this_extension'}, false, {selectedSession: next, switchInProgress: true});
    assert.equal(f.sets.length, 1);
    assert.equal((await f.message({type: 'getState'})).mode, 'unavailable');
    assert.deepEqual(plain(await f.auth()), {cancel: true});
});


test('extension reload restores the saved route instead of reverting to PAC', async () => {
    const f = await fixture();
    await f.message({type: 'setMode', mode: 'direct'});
    const reloaded = await fixture(undefined, false, f.storage);
    assert.equal((await reloaded.message({type:'getState'})).mode, 'direct');
});


test('environment selection persists without changing browser route or requesting unconfigured lists', async () => {
    const f = await fixture(undefined, false, {}, true);
    await f.message({type: 'setMode', mode: 'session'});
    const before = f.config();
    const selected = await f.message({type: 'setEnvironment', environment: 'live'});
    assert.equal(selected.environment, 'live'); assert.equal(selected.account.configured, false);
    assert.deepEqual(f.config(), before); assert.equal(selected.session.environment, 'dev');
    assert.deepEqual(plain(selected.sessions), []);
    assert.equal(f.fetched.at(-1).url, 'http://127.0.0.1:1234/environments/live/account');
    assert.ok(!f.fetched.some(v => v.url.endsWith('/live/sessions')));
    const restarted = await fixture(before, false, f.storage, true);
    assert.equal((await restarted.message({type: 'getState'})).environment, 'live');
    const pac = await f.message({type: 'getPac'}); assert.equal(pac.ok, true);
    assert.ok(f.fetched.at(-1).url.includes('/environments/dev/sessions/RSFIRST/pac'));
    assert.equal((await f.message({type: 'setEnvironment', environment: 'production'})).ok, false);
    assert.equal((await f.message({type: 'createSession', environment: 'dev', options: {}})).ok, false);
    assert.deepEqual(f.config(), before);
});

test('manual egress is saved without changing the route, scoped by mode, and survives restart', async () => {
    const f = await fixture();
    const settings = {source:'custom', scheme:'http', host:'custom.invalid', port:8080, username:'custom-user', password:'manual-secret'};
    const saved = await f.message({type:'configureEgress',settings});
    assert.equal(saved.ok,true); assert.equal(saved.mode,'pac');
    assert.equal(saved.egress.source,'custom'); assert.equal(saved.egress.hasCredentials,true);
    assert.ok(!JSON.stringify(saved).includes('manual-secret')); assert.ok(!JSON.stringify(saved).includes('custom-user'));
    assert.deepEqual(plain(await f.auth('custom.invalid',8080,'custom-pac')),{cancel:true});
    await f.message({type:'setMode',mode:'egress'});
    assert.deepEqual(f.config().value.rules.singleProxy,{scheme:'http',host:'custom.invalid',port:8080});
    assert.equal((await f.auth('custom.invalid',8080,'custom')).authCredentials.password,'manual-secret');
    assert.deepEqual(plain(await f.auth('egress.invalid',3128,'old')),{cancel:true});
    const restarted = await fixture(f.config(),false,f.storage);
    assert.equal((await restarted.message({type:'getState'})).mode,'egress');
    assert.equal((await restarted.auth('custom.invalid',8080,'after-restart')).authCredentials.username,'custom-user');
    assert.equal((await restarted.message({type:'configureEgress',settings:{...settings,username:undefined,password:undefined,keepCredentials:true}})).ok,true);
    const switched = await restarted.message({type:'selectSession',sessionId:'RSSECOND'});
    assert.equal(switched.mode,'egress'); assert.equal(switched.egress.source,'custom');
    assert.equal((await restarted.message({type:'configureEgress',settings:{source:'session'}})).egress.source,'session');
    assert.deepEqual(restarted.config().value.rules.singleProxy,proxies.egress);
});
test('manual credentials on a shared endpoint never replace the session PAC credentials', async () => {
    const f = await fixture();
    await f.message({type:'configureEgress',settings:{source:'custom',...proxies.egress,username:'alternate',password:'alternate-secret'}});
    assert.equal((await f.auth('egress.invalid',3128,'pac')).authCredentials.username,'fixture-egress');
    await f.message({type:'setMode',mode:'egress'});
    assert.equal((await f.auth('egress.invalid',3128,'manual')).authCredentials.username,'alternate');
    const before = f.cleared.length;
    await f.message({type:'setMode',mode:'pac'});
    assert.ok(f.cleared.length > before);
    assert.equal((await f.auth('egress.invalid',3128,'pac-again')).authCredentials.username,'fixture-egress');
});
test('manual egress validates endpoints and credentials before touching routing', async () => {
    const f = await fixture(undefined,true);
    const base = {source:'custom',scheme:'http',host:'custom.invalid',port:8080};
    for (const settings of [{...base,host:'https://bad.invalid'},{...base,port:0},{...base,port:2.5},{...base,username:'user'},{...base,keepCredentials:true},{...base,host:'vgs.invalid',port:3443}]) {
        const before = f.sets.length;
        assert.equal((await f.message({type:'configureEgress',settings})).ok,false);
        assert.equal(f.sets.length,before);
    }
    assert.equal((await f.message({type:'configureEgress',settings:base})).ok,true);
    assert.equal((await f.message({type:'setMode',mode:'egress'})).mode,'egress');
    assert.deepEqual(plain(await f.auth('custom.invalid',8080)),{cancel:true});
    assert.equal((await f.message({type:'configureEgress',settings:{source:'session'}})).ok,false);
    assert.equal((await f.message({type:'getState'})).mode,'egress');
});

 test('Collect authorization is transient, sender-scoped and rejects stale environments', async () => {
    const f = await fixture(undefined,false,{},true);
    const result = await f.message({type:'getCollectToken',environment:'dev',tenantId:'fixture-tenant',method:'aliases'});
    assert.equal(result.accessToken,'fixture-transient');
    assert.equal(result.mode,undefined);
    assert.equal(JSON.stringify(f.storage).includes('fixture-transient'),false);
    assert.equal(JSON.stringify(await f.message({type:'getState'})).includes('fixture-transient'),false);
    const count=f.fetched.length;
    assert.equal(await f.message({type:'getCollectToken',environment:'dev',tenantId:'fixture-tenant',method:'aliases'},{id:'fixture',url:'https://merchant.invalid'}),undefined);
    assert.equal((await f.message({type:'getCollectToken',environment:'sandbox',tenantId:'fixture-tenant',method:'aliases'})).ok,false);
    assert.equal(f.fetched.length,count);
    const call=f.fetched.find(r=>r.url.endsWith('/collect-token'));
    assert.equal(call.url,'http://127.0.0.1:1234/environments/dev/collect-token');
    assert.equal(call.options.body,JSON.stringify({tenantId:'fixture-tenant',method:'aliases'}));
 });

test('gateway reads use the selected environment without changing the route', async () => {
    const f = await fixture(undefined, false, {}, true);
    const before = f.config();
    const options = {tenantId:'fixtureTenant',resource:'functions',limit:50,offset:0};
    const response = await f.message({type:'readGateway',environment:'dev',options});
    assert.equal(response.ok, true);
    const call = f.fetched.find(row => row.url.endsWith('/gateway/read'));
    assert.equal(call.url, 'http://127.0.0.1:1234/environments/dev/gateway/read');
    assert.deepEqual(JSON.parse(call.options.body), options);
    assert.deepEqual(f.config(), before);
    const count = f.fetched.length;
    const stale = await f.message({type:'readGateway',environment:'sandbox',options});
    assert.equal(stale.ok, false);
    assert.equal(f.fetched.length, count);
    assert.deepEqual(f.config(), before);
});

test('session detail reads are sender-scoped, environment-scoped and preserve routing', async () => {
    const f = await fixture(undefined,false,{},true);
    const before = f.config();
    const result = await f.message({type:'getSessionDetails',environment:'dev',sessionId:'RSSECOND'});
    assert.equal(result.ok,true);
    assert.ok(f.fetched.some(row => row.url === 'http://127.0.0.1:1234/environments/dev/sessions/RSSECOND/details'));
    assert.deepEqual(f.config(),before);
    const count = f.fetched.length;
    assert.equal((await f.message({type:'getSessionDetails',environment:'live',sessionId:'RSSECOND'})).ok,false);
    assert.equal((await f.message({type:'getSessionDetails',environment:'dev',sessionId:'../RSSECOND'})).ok,false);
    assert.equal(await f.message({type:'getSessionDetails',environment:'dev',sessionId:'RSSECOND'},{id:'fixture',url:'https://merchant.invalid'}),undefined);
    assert.equal(f.fetched.length,count);
    assert.deepEqual(f.config(),before);
});
