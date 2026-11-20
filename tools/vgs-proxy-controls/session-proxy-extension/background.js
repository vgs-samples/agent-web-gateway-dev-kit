// Account API credentials remain in the local companion, never in this extension.
const environments = ["dev", "sandbox", "live"];
function sessionEnvironment(session) {
    if (environments.includes(session.environment)) return session.environment;
    const host = new URL(session.pacSource || session.pacUrl).hostname;
    return (host === "vgsapi.com" || host === "live.vgsapi.com") ? "live" : host === "sandbox.vgsapi.com" ? "sandbox" : "dev";
}
let current = {...INITIAL_SESSION, environment: sessionEnvironment(INITIAL_SESSION)};
let environment = CATALOG?.environment || current.environment;
let switching = false;
let initialized = false;
let generation = 0;
let sessionList = [];
let checkedAt = null;
let catalogError = null;
let account = null;
let recording = null;
let manualEgress = null;
const egressProxy = () => manualEgress?.proxy || current.proxies.egress;
const publicEgress = () => ({source: manualEgress ? "custom" : "session", proxy: egressProxy(), hasCredentials: !!manualEgress?.credentials});
const blockedProxy = {mode: "fixed_servers", rules: {singleProxy: {scheme: "http", host: "127.0.0.1", port: 9}, bypassList: []}};
const modes = () => ["pac", "session", ...(egressProxy() ? ["egress"] : []), "direct"];
const publicSession = () => ({sessionId: current.sessionId, expiresAt: current.expiresAt, pacSource: current.pacSource, environment: current.environment, tenantId: current.tenantId});
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
        else if (matchesProxy(value, egressProxy())) mode = "egress";
        else if (value.mode === "direct") mode = "direct";
    }
    return {mode, canControl: owned || config.levelOfControl === "controllable_by_this_extension", availableModes: modes(), session: publicSession(), sessions: sessionList, checkedAt, catalogError, catalogAvailable: !!CATALOG, environment, account, recording, egress: publicEgress()};
}

function showBadge(state) {
    const labels = {pac: "PAC", session: "VGS", egress: "EGR", direct: "OFF", unavailable: "!"};
    const titles = {pac: "VGS Reveal Session PAC File", session: "VGS Reveal Session Proxy", egress: "Egress Proxy", direct: "No Proxy", unavailable: "Unavailable"};
    chrome.action.setBadgeText({text: labels[state.mode]});
    chrome.action.setBadgeBackgroundColor({color: state.mode === "direct" ? "#a34b10" : state.mode === "unavailable" ? "#a12b35" : "#156b50"});
    chrome.action.setTitle({title: titles[state.mode] + " — Agent Web Gateway Control Panel"});
    return state;
}

async function getState() {
    return showBadge(describe(await readSettings()));
}

async function setMode(mode) {
    const oldMode = (await getState()).mode;
    if (!modes().includes(mode)) throw new Error("Proxy mode is not available.");
    // Never clear(): that would restore the launcher's blocking bootstrap proxy.
    const value = mode === "pac" ? {mode: "pac_script", pacScript: {url: current.pacUrl, mandatory: true}}
        : mode === "direct" ? {mode: "direct"}
        : {mode: "fixed_servers", rules: {singleProxy: mode === "egress" ? egressProxy() : current.proxies[mode], bypassList: []}};
    const resetAuth = !switching && manualEgress && ((oldMode === "egress") !== (mode === "egress"));
    if (resetAuth) { switching = true; generation++; }
    try {
        if (resetAuth) {
            await chrome.storage.local.set({switchInProgress: true});
            await applySettings(blockedProxy);
            await clearProxyAuth([current, {proxies: {custom: manualEgress.proxy}}]);
            attempted.clear();
        }
        await applySettings(value);
        const state = await getState();
        if (state.mode !== mode) throw new Error("Another browser setting controls proxy routing.");
        await chrome.storage.local.set({selectedMode: mode});
        if (resetAuth) await chrome.storage.local.remove(["switchInProgress", "resumeMode"]);
        return state;
    } catch (error) {
        if (resetAuth) await applySettings(blockedProxy).catch(() => {});
        throw error;
    } finally { if (resetAuth) switching = false; }
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
    readSettings().then(config => {
        const mode = describe(config).mode;
        const endpoint = mode === "egress" ? egressProxy() : current.proxies[mode];
        const credential = mode === "egress" && manualEgress ? manualEgress.credentials : current.credentials[key];
        const matches = proxy => proxy && key === proxy.host + ":" + proxy.port;
        const permitted = mode === "pac" ? Object.values(current.proxies).some(matches) : matches(endpoint);
        const tried = attempted.get(details.requestId) || new Set();
        if (!credential || switching || authGeneration !== generation || !permitted || tried.has(key)) return callback({cancel: true});
        tried.add(key);
        attempted.set(details.requestId, tried);
        callback({authCredentials: credential});
    }, () => callback({cancel: true}));
}, requestFilter, ["asyncBlocking"]);
chrome.webRequest.onCompleted.addListener(d => attempted.delete(d.requestId), requestFilter);
chrome.webRequest.onErrorOccurred.addListener(d => attempted.delete(d.requestId), requestFilter);

async function companion(path, body, selected = environment) {
    if (!environments.includes(selected)) throw new Error("Invalid environment.");
    if (!CATALOG) throw new Error("Session catalog is not connected.");
    if (!CATALOG.environments && selected !== (CATALOG.environment || sessionEnvironment(INITIAL_SESSION)))
        throw new Error("This helper does not support that environment.");
    const response = await fetch(CATALOG.url + (CATALOG.environments ? "/environments/" + selected : "") + path, {
        method: body ? "POST" : "GET", body: body ? JSON.stringify(body) : undefined,
        headers: {Authorization: "Bearer " + CATALOG.token, ...(body ? {"Content-Type": "application/json"} : {})}, cache: "no-store",
        credentials: "omit", redirect: "error", signal: AbortSignal.timeout(path === "/credentials" ? 90000 : 25000)
    });
    if (!response.ok) {
        const error = new Error("Session catalog unavailable."); error.status = response.status;
        if (path === "/credentials" || path.startsWith("/credentials/picker")) { const body = await response.json().catch(() => ({})); if (typeof body.accountError === "string" && body.accountError.length < 300) error.accountError = body.accountError; }
        if (path === "/egress-profiles") { const body = await response.json().catch(() => ({})); if (typeof body.egressError === "string" && body.egressError.length < 300) error.egressError = body.egressError; }
        if (path.startsWith("/recording")) { const body = await response.json().catch(() => ({})); if (typeof body.recordingError === "string" && body.recordingError.length < 400) error.recordingError = body.recordingError; }
        if (path === "/gateway/read") { const body = await response.json().catch(() => ({})); if (typeof body.gatewayError === "string" && body.gatewayError.length < 400) error.gatewayError = body.gatewayError; }
        if (path.endsWith("/ca")) { const body = await response.json().catch(() => ({})); if (typeof body.certificateError === "string" && body.certificateError.length < 400) error.certificateError = body.certificateError; }
        throw error;
    }
    return response.json();
}

async function refreshSessions() {
    try {
        account = null;
        checkedAt = null;
        account = await companion("/account");
        if (account.configured === false) {
            sessionList = [];
            catalogError = "Connect a service-account file in Settings to load sessions in this environment.";
            return getState();
        }
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
    if (id === current.sessionId && environment === current.environment) return getState();
    const next = await companion("/sessions/" + id + "/config");
    if ((next.environment || "dev") !== environment || next.sessionId !== id || !(Date.parse(next.expiresAt) > Date.now())) throw new Error("Session expired.");
    const previous = current;
    const mode = (await getState()).mode;
    if (!modes().includes(mode) || (mode === "egress" && !manualEgress && !next.proxies.egress)) throw new Error("Route unavailable for this session.");
    switching = true;
    generation++;
    try {
        await chrome.storage.local.set({switchInProgress: true, resumeMode: mode});
        await applySettings(blockedProxy);
        await clearProxyAuth([previous, next, {proxies: {custom: manualEgress?.proxy}}]);
        attempted.clear();
        current = {...next, environment};
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

function validateManualEgress(settings) {
    if (!settings || !["session", "custom"].includes(settings.source)) throw new Error("Invalid egress source.");
    if (settings.source === "session") return null;
    const {scheme, host, port} = settings;
    if (!["http", "https"].includes(scheme) || typeof host !== "string" || !/^(?=.{1,253}$)[a-zA-Z0-9]+(?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?$/.test(host)
        || !Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid proxy endpoint.");
    const proxy = {scheme, host: host.toLowerCase(), port};
    if (proxy.host === current.proxies.session.host && proxy.port === current.proxies.session.port) throw new Error("Use a separate egress endpoint.");
    let credentials = null;
    if (settings.keepCredentials) {
        if (!manualEgress?.credentials || JSON.stringify(proxy) !== JSON.stringify(manualEgress.proxy)) throw new Error("Re-enter credentials for this endpoint.");
        credentials = manualEgress.credentials;
    } else if (settings.username || settings.password) {
        if (typeof settings.username !== "string" || typeof settings.password !== "string" || !settings.username || !settings.password
            || settings.username.length > 1024 || settings.password.length > 4096 || /[\r\n:]/.test(settings.username) || /[\r\n]/.test(settings.password)) throw new Error("Invalid proxy credentials.");
        credentials = {username: settings.username, password: settings.password};
    }
    return {proxy, credentials};
}
async function configureEgress(settings) {
    const next = validateManualEgress(settings);
    const mode = (await getState()).mode;
    if (!modes().includes(mode) || (mode === "egress" && !next && !current.proxies.egress)) throw new Error("Choose another route first.");
    switching = true; generation++;
    try {
        await chrome.storage.local.set({switchInProgress: true});
        await applySettings(blockedProxy);
        await clearProxyAuth([current, {proxies: {old: manualEgress?.proxy, next: next?.proxy}}]);
        attempted.clear();
        manualEgress = next;
        await chrome.storage.local.set({manualEgress: next});
        await setMode(mode);
        await chrome.storage.local.remove(["switchInProgress", "resumeMode"]);
        return getState();
    } catch (error) {
        await applySettings(blockedProxy).catch(() => {});
        throw error;
    } finally { switching = false; }
}

globalThis.pacReady = (async () => {
    await chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
    const saved = await chrome.storage.local.get(["selectedSession", "switchInProgress", "selectedMode", "selectedEnvironment", "manualEgress"]);
    if (saved.selectedSession) current = {...saved.selectedSession, environment: sessionEnvironment(saved.selectedSession)};
    manualEgress = saved.manualEgress || null;
    environment = environments.includes(saved.selectedEnvironment) ? saved.selectedEnvironment : current.environment;
    if (saved.switchInProgress) await applySettings(blockedProxy);
    const state = await getState();
    // Normal worker restarts retain the selected session and route. Interrupted
    // changes stay blocked until the user explicitly chooses a route.
    if (!saved.switchInProgress && state.mode === "unavailable" && state.canControl) await setMode(modes().includes(saved.selectedMode) ? saved.selectedMode : typeof INITIAL_MODE !== "undefined" ? INITIAL_MODE : "pac");
    initialized = true;
    return true;
})();
let pending = globalThis.pacReady.catch(() => showBadge({mode: "unavailable"}));
function controlsPage(url) {
    try {
        const parsed = new URL(url), expected = new URL(chrome.runtime.getURL("popup.html"));
        return parsed.protocol === expected.protocol && parsed.host === expected.host && parsed.pathname === expected.pathname
            && !parsed.username && !parsed.password ? parsed : null;
    } catch (_) { return null; }
}
function allowDevForPage(page) {
    const values = page.searchParams.getAll("allow_dev_env");
    return values.length === 1 && values[0] === "true";
}
async function changeEnvironment(selected) {
    environment = selected;
    account = null; sessionList = []; checkedAt = null; catalogError = null;
    await chrome.storage.local.set({selectedEnvironment: environment});
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
    const page = controlsPage(sender.url);
    if (sender.id !== chrome.runtime.id || !page) return;
    const allowDev = allowDevForPage(page);
    if (!["getState", "setMode", "refreshSessions", "selectSession", "getPac", "createSession", "creationStatus", "setEnvironment", "getAdapters", "createCard", "cardStatus", "configureEgress", "connectAccount", "browseAccountFile", "accountFileSelectionStatus", "getCollectToken", "getEgressProfiles", "saveEgressProfile", "saveBrowserEgressProfile", "recordingStatus", "recordingTabs", "startRecording", "stopRecording", "readGateway", "getSessionCa", "getSessionDetails"].includes(message?.type)) return;
    const operation = pending.then(async () => {
        // Gate environment management per controls URL, never by a saved opt-in.
        // Existing routing remains visible and controllable independently.
        if (!allowDev && environment === "dev") await changeEnvironment("sandbox");
        if (!allowDev && message.environment === "dev") {
            const error = new Error("Dev requires allow_dev_env=true in the control-panel URL.");
            error.status = 403; error.devEnvironmentDisabled = true; throw error;
        }
        if (message.type === "getSessionDetails") {
            if (!/^RS[A-Za-z0-9]+$/.test(message.sessionId) || !environments.includes(message.environment) || message.environment !== environment) throw new Error("Invalid session.");
            return {...await getState(), sessionDetails: await companion("/sessions/" + message.sessionId + "/details", undefined, message.environment)};
        }
        if (message.type === "getSessionCa") {
            if (!/^RS[A-Za-z0-9]+$/.test(message.sessionId) || !environments.includes(message.environment)) throw new Error("Invalid session.");
            return {...await getState(), certificate: await companion("/sessions/" + message.sessionId + "/ca", undefined, message.environment)};
        }
        if (message.type === "readGateway") {
            if (message.environment !== environment) throw new Error("Environment changed.");
            return {...await getState(), gateway: await companion("/gateway/read", message.options)};
        }
        if (message.type === "recordingStatus") {
            recording = await companion("/recording");
            return getState();
        }
        if (message.type === "recordingTabs") return {...await getState(), recordingTabs: (await companion("/recording/tabs")).tabs};
        if (message.type === "startRecording") {
            const state = await getState();
            if (state.mode === "unavailable" || ((state.mode === "pac" || state.mode === "session") && !(Date.parse(current.expiresAt) > Date.now())))
                throw Object.assign(new Error("Choose an available route and active session first."), {recordingError: "Choose an available route and active session before starting the test."});
            recording = await companion("/recording/start", {...message.options, sessionId: current.sessionId}, current.environment);
            return getState();
        }
        if (message.type === "stopRecording") {
            recording = await companion("/recording/stop", {});
            return getState();
        }
        if (message.type === "configureEgress") return configureEgress(message.settings);
        if (message.type === "setEnvironment") {
            if (!environments.includes(message.environment) || !CATALOG?.environments) throw new Error("Environment unavailable.");
            await changeEnvironment(message.environment);
            return refreshSessions();
        }
        if (["createSession", "selectSession", "createCard", "getAdapters", "connectAccount", "browseAccountFile", "accountFileSelectionStatus", "getCollectToken", "getEgressProfiles", "saveEgressProfile", "saveBrowserEgressProfile"].includes(message.type) && message.environment && message.environment !== environment)
            throw new Error("Environment changed; refresh the panel.");
        if (message.type === "getEgressProfiles") return {...await getState(), ...await companion("/egress-profiles")};
        if (message.type === "saveBrowserEgressProfile") {
            const selected = egressProxy();
            if (!selected) throw new Error("Configure a browser egress proxy first.");
            const {scheme, host, port} = selected;
            const credentials = manualEgress ? manualEgress.credentials : current.credentials[`${host}:${port}`];
            return {...await getState(), ...await companion("/egress-profiles", {name:message.name,
                proxy:{type:"custom",scheme,hostname:host,port,...(credentials || {})}})};
        }
        if (message.type === "saveEgressProfile") return {...await getState(), ...await companion("/egress-profiles", message.profile)};
        if (message.type === "getCollectToken") return companion("/collect-token", {tenantId: message.tenantId, method: message.method});
        if (message.type === "browseAccountFile") return {...await getState(), fileSelection: await companion("/credentials/picker", {})};
        if (message.type === "accountFileSelectionStatus") {
            if (!/^[a-f0-9-]{36}$/.test(message.requestId)) throw new Error("Invalid file selection");
            return {...await getState(), fileSelection: await companion("/credentials/picker/" + message.requestId)};
        }
        if (message.type === "connectAccount") {
            const result = await companion("/credentials", {credentialsFile:message.credentialsFile, tenantId:message.tenantId || ""});
            if (result.selectionRequired) return {...await getState(), accountSelection:{tenants:result.tenants}};
            return {...await refreshSessions(), accountConnected:true};
        }
        if (message.type === "getAdapters") {
            try { return {...await getState(), ...await companion("/adapters"), adaptersLoaded: true}; }
            catch (_) { return {...await getState(), adapters: [], adaptersLoaded: false}; }
        }
        if (message.type === "createCard") return {...await getState(), cardOperation: {...await companion("/cards", {requestId: message.requestId}), environment}};
        if (message.type === "cardStatus") {
            if (!/^[a-f0-9-]{36}$/.test(message.requestId)) throw new Error("Invalid operation");
            return {...await getState(), cardOperation: {...await companion("/operations/" + message.requestId, undefined, message.environment || environment), environment: message.environment || environment}};
        }
        if (message.type === "createSession") return {...await getState(), operation: {...await companion("/sessions", message.options), environment}};
        if (message.type === "creationStatus") {
            if (!/^[a-f0-9-]{36}$/.test(message.requestId)) throw new Error("Invalid operation");
            return {...await getState(), operation: {...await companion("/operations/" + message.requestId, undefined, message.environment || environment), environment: message.environment || environment}};
        }
        if (message.type === "refreshSessions") return refreshSessions();
        if (message.type === "selectSession") return selectSession(message.sessionId);
        if (message.type === "getPac") return {...await getState(), ...await companion("/sessions/" + current.sessionId + "/pac", undefined, current.environment)};
        if (message.type === "setMode") {
            const state = await setMode(message.mode);
            await chrome.storage.local.remove(["switchInProgress", "resumeMode"]);
            return state;
        }
        return getState();
    });
    pending = operation.catch(() => {});
    operation.then(state => respond({ok: true, ...state}), async failure => {
        const state = await getState().catch(() => ({mode: "unavailable", canControl: false, availableModes: modes()}));
        const result = {ok: false, ...state, error: "Could not complete that change. Refresh the session list and check the current route."};
        if (message.type === "getSessionDetails") result.error = failure.sessionDetailsError || "Could not load session details. Refresh the list and try again.";
        if (message.type === "getSessionCa") result.error = failure.certificateError || "Could not download the session CA. Check the helper and saved session.";
        if (message.type === "readGateway") result.error = failure.gatewayError || "Could not load gateway configuration. Refresh the panel and check the local helper.";
        if (failure.devEnvironmentDisabled) result.error = "Dev requires allow_dev_env=true in the control-panel URL.";
        if (["recordingStatus", "recordingTabs", "startRecording", "stopRecording"].includes(message.type)) {
            result.error = failure.recordingError || "Recording status is unconfirmed. Check the local helper and refresh recording status before starting another test.";
            if (message.type !== "recordingTabs") result.recording = recording = {...recording, state:"unknown", error:result.error};
        }
        if (["createSession", "creationStatus", "createCard", "cardStatus"].includes(message.type)) {
            const rejected = [400,403,404].includes(failure.status);
            const job = {requestId: message.requestId || message.options?.requestId, environment: message.environment || environment,
                status: rejected ? "failed" : "unknown", error: rejected ? "Check the form and local configuration. The helper rejected this request." : "The helper did not confirm the result. Check its status before starting another request."};
            result[["createCard", "cardStatus"].includes(message.type) ? "cardOperation" : "operation"] = job;
        }
        if (["getEgressProfiles", "saveEgressProfile", "saveBrowserEgressProfile"].includes(message.type)) result.egressError = failure.egressError || "Saved proxies are unavailable. Check the local helper and retry.";
        if (message.type === "connectAccount") result.accountError = failure.accountError || "Connection was not confirmed. Check the file and helper, then refresh before trying again.";
        if (["browseAccountFile", "accountFileSelectionStatus"].includes(message.type)) result.accountError = failure.accountError || "File explorer is unavailable. Enter the local file path instead.";
        respond(result);
    });
    return true;
});

async function openControls() {
    const url = chrome.runtime.getURL("popup.html");
    const tabs = (await chrome.tabs.query({url: url + "*"})).filter(tab => controlsPage(tab.url));
    if (tabs.length) {
        await chrome.tabs.update(tabs[0].id, {active: true});
        await chrome.windows.update(tabs[0].windowId, {focused: true});
    } else await chrome.tabs.create({url});
}
chrome.action.onClicked.addListener(() => openControls());
