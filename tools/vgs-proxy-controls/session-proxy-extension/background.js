// Account API credentials remain in the local companion, never in this extension.
let current = INITIAL_SESSION;
let switching = false;
let initialized = false;
let generation = 0;
let sessionList = [];
let checkedAt = null;
let catalogError = null;
const blockedProxy = {mode: "fixed_servers", rules: {singleProxy: {scheme: "http", host: "127.0.0.1", port: 9}, bypassList: []}};
const modes = () => ["pac", "session", ...(current.proxies.egress ? ["egress"] : []), "direct"];
const publicSession = () => ({sessionId: current.sessionId, expiresAt: current.expiresAt, pacSource: current.pacSource});
const attempted = new Map();
const requestFilter = {urls: ["<all_urls>"]};
globalThis.proxyErrors = [];

function readSettings() {
    return new Promise((resolve, reject) => {
        chrome.proxy.settings.get({incognito: false}, config => {
            if (chrome.runtime.lastError) reject(new Error("Could not read proxy settings."));
            else resolve(config);
        });
    });
}

function matchesProxy(value, proxy) {
    if (!proxy || value.mode !== "fixed_servers") return false;
    const rules = value.rules || {};
    const actual = rules.singleProxy;
    return actual && actual.scheme === proxy.scheme && actual.host === proxy.host && actual.port === proxy.port &&
        !rules.proxyForHttp && !rules.proxyForHttps && !rules.proxyForFtp && !rules.fallbackProxy &&
        (!rules.bypassList || rules.bypassList.length === 0);
}

function describe(config) {
    const value = config.value || {};
    const owned = config.levelOfControl === "controlled_by_this_extension";
    let mode = "unavailable";
    if (owned) {
        if (value.mode === "pac_script" && value.pacScript?.url === current.pacUrl && value.pacScript?.mandatory === true) mode = "pac";
        else if (matchesProxy(value, current.proxies.session)) mode = "session";
        else if (matchesProxy(value, current.proxies.egress)) mode = "egress";
        else if (value.mode === "direct") mode = "direct";
    }
    return {mode, canControl: owned || config.levelOfControl === "controllable_by_this_extension", availableModes: modes(), session: publicSession(), sessions: sessionList, checkedAt, catalogError, catalogAvailable: !!CATALOG};
}

function showBadge(state) {
    const labels = {pac: "PAC", session: "VGS", egress: "EGR", direct: "OFF", unavailable: "!"};
    const titles = {pac: "Reveal Session PAC", session: "Reveal Session Proxy", egress: "Egress Proxy", direct: "No Proxy", unavailable: "Unavailable"};
    chrome.action.setBadgeText({text: labels[state.mode]});
    chrome.action.setBadgeBackgroundColor({color: state.mode === "direct" ? "#a34b10" : state.mode === "unavailable" ? "#a12b35" : "#156b50"});
    chrome.action.setTitle({title: titles[state.mode] + " — click for proxy controls"});
    return state;
}

async function getState() {
    return showBadge(describe(await readSettings()));
}

async function setMode(mode) {
    if (!modes().includes(mode)) throw new Error("Proxy mode is not available.");
    // Never clear(): that would restore the launcher's blocking bootstrap proxy.
    const value = mode === "pac" ? {mode: "pac_script", pacScript: {url: current.pacUrl, mandatory: true}}
        : mode === "direct" ? {mode: "direct"}
        : {mode: "fixed_servers", rules: {singleProxy: current.proxies[mode], bypassList: []}};
    await new Promise((resolve, reject) => {
        chrome.proxy.settings.set({value, scope: "regular"}, () => {
            if (chrome.runtime.lastError) reject(new Error("Could not change proxy routing."));
            else resolve();
        });
    });
    const state = await getState();
    if (state.mode !== mode) throw new Error("Another browser setting controls proxy routing.");
    return state;
}

chrome.proxy.settings.onChange.addListener(config => showBadge(describe(config)));
chrome.proxy.onProxyError.addListener(error => {
    globalThis.proxyErrors.push(error);
    if (globalThis.proxyErrors.length > 20) globalThis.proxyErrors.shift();
});

chrome.webRequest.onAuthRequired.addListener((details, callback) => {
    if (!initialized || switching) return callback({cancel: true});
    const authGeneration = generation;
    if (!details.isProxy) return callback({});
    const challenger = details.challenger || {};
    const key = String(challenger.host || "").toLowerCase() + ":" + challenger.port;
    if (!Object.hasOwn(current.credentials, key)) return callback({cancel: true});
    readSettings().then(config => {
        const mode = describe(config).mode;
        const endpoint = current.proxies[mode];
        const matches = proxy => proxy && key === proxy.host + ":" + proxy.port;
        const permitted = mode === "pac" ? Object.values(current.proxies).some(matches) : matches(endpoint);
        const tried = attempted.get(details.requestId) || new Set();
        if (switching || authGeneration !== generation || !permitted || tried.has(key)) return callback({cancel: true});
        tried.add(key);
        attempted.set(details.requestId, tried);
        callback({authCredentials: current.credentials[key]});
    }, () => callback({cancel: true}));
}, requestFilter, ["asyncBlocking"]);
chrome.webRequest.onCompleted.addListener(d => attempted.delete(d.requestId), requestFilter);
chrome.webRequest.onErrorOccurred.addListener(d => attempted.delete(d.requestId), requestFilter);

async function companion(path) {
    if (!CATALOG) throw new Error("Session catalog is not connected.");
    const response = await fetch(CATALOG.url + path, {
        headers: {Authorization: "Bearer " + CATALOG.token}, cache: "no-store",
        credentials: "omit", redirect: "error", signal: AbortSignal.timeout(25000)
    });
    if (!response.ok) throw new Error("Session catalog unavailable.");
    return response.json();
}

async function refreshSessions() {
    try {
        const result = await companion("/sessions");
        sessionList = result.sessions;
        checkedAt = result.checkedAt;
        catalogError = null;
    } catch (_) {
        // Never present an old list as currently usable after a failed refresh.
        sessionList = [];
        catalogError = "Could not refresh sessions. Check the local session helper and try again.";
    }
    return getState();
}

function applySettings(value) {
    return new Promise((resolve, reject) => chrome.proxy.settings.set({value, scope: "regular"}, () =>
        chrome.runtime.lastError ? reject(new Error("Could not apply routing.")) : resolve()));
}

async function clearProxyAuth(configs) {
    const origins = [...new Set(configs.flatMap(c => Object.values(c.proxies).filter(Boolean)
        .map(p => `${p.scheme}://${p.host}:${p.port}`)))];
    // Chromium clears HTTP authentication when removing cookies for these proxy
    // origins. Merchant cookies, history, passwords and other origins are untouched.
    await new Promise((resolve, reject) => chrome.browsingData.remove({since: 0, origins}, {cookies: true}, () =>
        chrome.runtime.lastError ? reject(new Error("Could not reset proxy authentication.")) : resolve()));
}

async function selectSession(id) {
    if (!/^RS[A-Za-z0-9]+$/.test(id)) throw new Error("Invalid session.");
    if (id === current.sessionId) return getState();
    const next = await companion("/sessions/" + id + "/config");
    if (next.sessionId !== id || !(Date.parse(next.expiresAt) > Date.now())) throw new Error("Session expired.");
    const previous = current;
    const mode = (await getState()).mode;
    if (!modes().includes(mode) || (mode === "egress" && !next.proxies.egress)) throw new Error("Route unavailable for this session.");
    switching = true;
    generation++;
    try {
        await chrome.storage.local.set({switchInProgress: true, resumeMode: mode});
        await applySettings(blockedProxy);
        await clearProxyAuth([previous, next]);
        attempted.clear();
        current = next;
        await chrome.storage.local.set({selectedSession: next});
        await setMode(mode);
        await chrome.storage.local.remove(["switchInProgress", "resumeMode"]);
    } catch (_) {
        // Remain blocked on an incomplete switch, including worker interruption.
        // Explicitly choosing a route can recover; never fall back to direct.
        await applySettings(blockedProxy).catch(() => {});
        throw new Error("Session switch did not finish. Choose a route to recover.");
    } finally {
        switching = false;
    }
    return getState();
}

globalThis.pacReady = (async () => {
    await chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
    const saved = await chrome.storage.local.get(["selectedSession", "switchInProgress"]);
    if (saved.selectedSession) current = saved.selectedSession;
    if (saved.switchInProgress) await applySettings(blockedProxy);
    const state = await getState();
    // Normal worker restarts retain the selected session and route. Interrupted
    // changes stay blocked until the user explicitly chooses a route.
    if (!saved.switchInProgress && state.mode === "unavailable" && state.canControl) await setMode("pac");
    initialized = true;
    return true;
})();
let pending = globalThis.pacReady.catch(() => showBadge({mode: "unavailable"}));
chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL("popup.html")) return;
    if (!["getState", "setMode", "refreshSessions", "selectSession", "getPac"].includes(message?.type)) return;
    const operation = pending.then(async () => {
        if (message.type === "refreshSessions") return refreshSessions();
        if (message.type === "selectSession") return selectSession(message.sessionId);
        if (message.type === "getPac") return {...await getState(), ...await companion("/sessions/" + current.sessionId + "/pac")};
        if (message.type === "setMode") {
            const state = await setMode(message.mode);
            await chrome.storage.local.remove(["switchInProgress", "resumeMode"]);
            return state;
        }
        return getState();
    });
    pending = operation.catch(() => {});
    operation.then(state => respond({ok: true, ...state}), async () => {
        const state = await getState().catch(() => ({mode: "unavailable", canControl: false, availableModes: modes()}));
        respond({ok: false, ...state, error: "Could not complete that change. Refresh the session list and check the current route."});
    });
    return true;
});
