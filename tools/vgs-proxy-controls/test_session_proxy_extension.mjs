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

async function fixture(previous, noEgress = false, saved = {}) {
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
        action: {setBadgeText: d => badge.text = d.text, setBadgeBackgroundColor: d => badge.color = d.color,
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
        return {ok: true, json: async () => url.endsWith('/config') ? structuredClone(next)
            : url.endsWith('/pac') ? {pacScript: 'function FindProxyForURL() {}', fetchedAt: '2026-01-01T00:00:00Z'}
            : {sessions: [{sessionId: 'RSSECOND', available: true}], checkedAt: '2026-01-01T00:00:00Z'}};
    }});
    vm.runInContext(noEgress ? source.replace(JSON.stringify(proxies), JSON.stringify({...proxies, egress: null})) : source, context);
    await context.pacReady;
    const sender = {id: 'fixture', url: 'chrome-extension://fixture/popup.html'};
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
