const devParameters = new URL(location.href).searchParams.getAll("allow_dev_env");
const allowDevEnv = devParameters.length === 1 && devParameters[0] === "true";
if (allowDevEnv) {
    document.getElementById("environment-select").prepend(new Option("Dev", "dev"));
    document.querySelector(".brand").href = chrome.runtime.getURL("popup.html") + "?allow_dev_env=true";
}
const stateLabel = document.getElementById("state");
const description = document.getElementById("description");
const buttons = [...document.querySelectorAll("button[data-mode]")];
const errorLabel = document.getElementById("error");
const sessionSelect = document.getElementById("session-select");
const useSession = document.getElementById("use-session");
let renderedSessions = "";
let displayedSession = null;
let busy = false;
let refreshPending = false;
const environmentLabel = value => ({dev: "Dev", sandbox: "Sandbox", live: "Live"}[value] || "Sandbox");
let state = {mode: "unavailable", canControl: false, availableModes: []};

function render() {
    globalThis.renderTestRecording?.(state, busy);
    renderAccount();
    globalThis.renderGateway?.(state);
    globalThis.renderCertificate?.(state);
    renderBrowserEgress();
    const session = state.session || {};
    document.getElementById("session-id").textContent = session.sessionId || "Not available";
    document.getElementById("pac-source").textContent = session.pacSource || "Not available";
    const expired = session.expiresAt && Date.parse(session.expiresAt) <= Date.now();
    document.getElementById("session-expiry").textContent = session.expiresAt
        ? (expired ? "Expired " : "Expires ") + new Date(session.expiresAt).toLocaleString() : "";
    const sameEnvironment = !session.environment || session.environment === state.environment;
    document.getElementById("session-environment").textContent = environmentLabel(session.environment);
    const notice = document.getElementById("environment-notice");
    notice.hidden = sameEnvironment;
    notice.textContent = `Showing ${environmentLabel(state.environment)} sessions. This browser still uses its ${environmentLabel(session.environment)} session.`;
    const key = JSON.stringify([state.sessions, session.sessionId, state.environment]);
    if (key !== renderedSessions) {
        const previous = sessionSelect.value;
        sessionSelect.replaceChildren();
        const rows = [...(state.sessions || [])];
        if (sameEnvironment && session.sessionId && !rows.some(r => r.sessionId === session.sessionId))
            rows.unshift({...session, available: false, reason: "Current; not in the active list"});
        for (const row of rows) {
            const option = document.createElement("option");
            option.value = row.sessionId;
            option.disabled = false; // Details remain inspectable even when activation is unavailable.
            option.textContent = row.sessionId + (row.available ? " · expires " + new Date(row.expiresAt).toLocaleTimeString() : " · " + row.reason);
            sessionSelect.append(option);
        }
        if (!rows.length) sessionSelect.add(new Option("No active sessions available", ""));
        sessionSelect.value = rows.some(r => r.sessionId === previous && r.available) ? previous : sameEnvironment ? session.sessionId || "" : "";
        renderedSessions = key;
    }
    if (displayedSession !== session.sessionId) {
        document.getElementById("pac-script").textContent = "Load the selected session’s routing script.";
        document.getElementById("pac-status").textContent = "";
        displayedSession = session.sessionId;
    }
    sessionSelect.disabled = busy || !state.catalogAvailable || state.account?.configured === false;
    useSession.disabled = busy || !state.canControl || !state.catalogAvailable || !sessionSelect.value
        || (sameEnvironment && sessionSelect.value === session.sessionId) || !state.sessions?.some(s => s.sessionId === sessionSelect.value && s.available);
    document.getElementById("refresh-sessions").disabled = busy || !state.catalogAvailable;
    document.getElementById("load-pac").disabled = busy || !state.catalogAvailable;
    document.getElementById("catalog-status").textContent = state.catalogError || (state.checkedAt
        ? `${(state.sessions || []).filter(s => s.available).length} usable session(s). Updated ${new Date(state.checkedAt).toLocaleTimeString()}.`
        : "Refresh to check active sessions and locally saved credentials.");
    renderSessionInspector();
    stateLabel.dataset.mode = state.mode;
    stateLabel.textContent = {pac: "VGS Reveal Session PAC File", session: "VGS Reveal Session Proxy", egress: "Egress Proxy", direct: "No Proxy", unavailable: "Unavailable"}[state.mode];
    description.textContent = {
        pac: "The PAC file chooses the route for each destination. View its exact rules in Diagnostics.",
        session: "VGS handles browser traffic directly and applies the session’s reveal rules, then its configured egress.",
        egress: "Traffic goes directly to the configured egress proxy. VGS token replacement is off.",
        direct: "Direct connection from this computer. VGS token replacement is off.",
        unavailable: "The session’s routing is not active. Another browser setting may control the proxy."
    }[state.mode];
    for (const button of buttons) {
        button.setAttribute("aria-pressed", String(button.dataset.mode === state.mode));
        button.disabled = busy || !state.canControl || !state.availableModes.includes(button.dataset.mode);
    }
    document.getElementById("egress-note").textContent = state.availableModes.includes("egress")
        ? "Use the session’s egress directly." : "No egress proxy is configured for this session.";
}

async function request(message) {
    if (busy) {
        if (message.type === "getState") refreshPending = true;
        if (["creationStatus", "cardStatus", "accountFileSelectionStatus"].includes(message.type)) setTimeout(() => request(message), 1000);
        return;
    }
    busy = true;
    render();
    if (message.type !== "getState") errorLabel.hidden = true;
    try {
        const response = await chrome.runtime.sendMessage(message);
        if (!response) throw new Error("No response");
        if (response.accountConnected) globalThis.resetGateway?.();
        state = response;
        if (response.fileSelection) renderFileSelection(response.fileSelection);
        else if (["browseAccountFile", "accountFileSelectionStatus"].includes(message.type)) { accountPicker=null; document.getElementById('account-file-status').textContent=''; }
        if (response.operation) renderOperation(response.operation);
        if (response.accountError) { document.getElementById("account-file-error").textContent = response.accountError; document.getElementById("account-file-error").hidden = false; }
        if (response.cardOperation) renderCardOperation(response.cardOperation);
        render();
        if (response.pacScript !== undefined) {
            document.getElementById("pac-script").textContent = response.pacScript;
            document.getElementById("pac-status").textContent = "Fetched " + new Date(response.fetchedAt).toLocaleString();
        }
        if (!state.ok && !response.accountError) {
            errorLabel.textContent = state.error;
            errorLabel.hidden = false;
        }
        return response;
    } catch (_) {
        if (["browseAccountFile", "accountFileSelectionStatus"].includes(message.type)) { accountPicker=null; document.getElementById('account-file-status').textContent=''; }
        state = {...state, mode: "unavailable", canControl: false, availableModes: []};
        handleCreationTransportFailure(message);
        errorLabel.textContent = "Could not reach the proxy controls. Reload this tab to try again.";
        errorLabel.hidden = false;
    } finally {
        busy = false;
        render();
        if (refreshPending) {
            refreshPending = false;
            request({type: "getState"});
        }
    }
}
buttons.forEach(button => button.addEventListener("click", () => request({type: "setMode", mode: button.dataset.mode})));
chrome.proxy.settings.onChange.addListener(() => request({type: "getState"}));
window.addEventListener("focus", () => request({type: "getState"}));
sessionSelect.addEventListener("change", render);
useSession.addEventListener("click", () => request({type: "selectSession", sessionId: sessionSelect.value, environment: state.environment}));
document.getElementById("refresh-sessions").addEventListener("click", () => request({type: "refreshSessions"}));
document.getElementById("load-pac").addEventListener("click", () => request({type: "getPac"}));
document.addEventListener("DOMContentLoaded", () => request({type: "refreshSessions"}));

function renderAccount() {
    const account = state.account;
    const mcp = account?.mcp;
    document.getElementById('mcp-status').textContent = mcp?.enabled
        ? `MCP enabled for ${environmentLabel(mcp.environment)}. Gateway writes ${mcp.writesEnabled ? 'enabled' : 'disabled'}.`
        : 'Start the helper with --enable-mcp to connect an assistant. See docs/mcp.md in the downloaded kit.';
    const mcpConfig = document.getElementById('mcp-client-config');
    mcpConfig.hidden = !mcp?.enabled;
    mcpConfig.textContent = mcp?.enabled ? JSON.stringify(mcp.clientConfig, null, 2) : '';
    const env = state.environment || "sandbox";
    document.getElementById("environment-select").value = env;
    document.getElementById("environment-select").disabled = busy || creationRunning() || !!accountPicker;
    document.getElementById("environment-shortcut").textContent = environmentLabel(env);
    document.getElementById("creation-environment").textContent = environmentLabel(env);
    document.getElementById("environment-status").textContent = account?.configured === false
        ? "Not connected. Choose a local service-account file for this environment."
        : account?.connected ? "Connected to " + environmentLabel(env) + "." : "Check the local helper and credentials for this environment.";
    document.getElementById("open-create").disabled = busy || creationRunning();
    document.getElementById("creation-availability").textContent = account?.creationAvailable ? '' : account?.configured === false
        ? `Connect a service account for ${environmentLabel(env)} to create a session.`
        : !account?.connected ? 'Connect your service account in Settings to create a session.'
        : 'Session creation requires reveal-sessions:write permission.';
    renderAccountFile();
    renderAccountSetup(env, account?.tenantId);
    document.getElementById("tenant-id").textContent = account?.tenantId || "Not configured";
    document.getElementById("account-status").textContent = account?.configured === false ? "Not configured" : account?.connected ? "Connected locally" : "Helper unavailable";
    const scopeList = document.getElementById("account-scopes");
    scopeList.replaceChildren();
    for (const scope of account?.scopes || []) {
        const row = document.createElement("div"); row.className = "scope";
        const name = document.createElement("code"); name.textContent = scope.name;
        const status = document.createElement("span"); status.textContent = scope.granted ? "Granted" : "Not in token";
        if (!scope.granted) status.className = "missing";
        row.append(name, status); scopeList.append(row);
    }
    document.getElementById("account-note").textContent = account?.cardsWriteGranted
        ? "This account also grants cards:write. Scope names above are read from its token; the API still checks tenant access."
        : "Scope names come from the account token. API authorization is checked on each operation.";
    renderCreation();
    document.getElementById("capture-status").textContent = account?.sensitiveHarEnabled === true
        ? "Sensitive HAR export enabled" : account?.sensitiveHarEnabled === false
        ? "Sensitive HAR export needs enabling" : "Sensitive HAR enabled on new Cloak launches";
    document.getElementById("capture-description").textContent = account?.sensitiveHarEnabled === true
        ? "This browser profile allows HAR exports with sensitive headers."
        : "For an existing browser, enable DevTools → Settings → Network → Allow to generate HAR with sensitive data.";
}

let accountSetupKey = '';
function renderAccountSetup(environment, tenantId) {
    const env = ['dev', 'sandbox', 'live'].includes(environment) ? environment : 'sandbox';
    // Only an identifier may be interpolated into the copyable shell commands.
    const tenant = /^[A-Za-z0-9_-]{1,255}$/.test(tenantId || '') ? tenantId : 'YOUR_TENANT_ID';
    const key = env + ':' + tenant;
    if (accountSetupKey === key) return;
    accountSetupKey = key;
    const cli = env === 'dev' ? 'vgs -e dev' : 'vgs';
    document.getElementById('account-setup-context').textContent = env === 'dev'
        ? 'These commands target Dev.'
        : `Use your ${environmentLabel(env)} tenant. Sandbox and Live share the same CLI login.`;
    document.getElementById('account-login-command').textContent = `${cli} login`;
    document.getElementById('account-generate-command').textContent = `AWG_ORGANIZATION_ID="YOUR_ORGANIZATION_ID"
AWG_TENANT_ID="${tenant}"
AWG_ACCOUNT_DIR="$HOME/.vgs/agent-web-gateway/${env}"
mkdir -p "$AWG_ACCOUNT_DIR"
chmod 700 "$AWG_ACCOUNT_DIR"
(
  umask 077
  set -o noclobber
  ${cli} generate service-account \\
    -t agent-web-gateway-admin \\
    -T "$AWG_TENANT_ID" \\
    > "$AWG_ACCOUNT_DIR/service-account.yaml"
)`;
    document.getElementById('account-apply-command').textContent = `(
  umask 077
  set -o noclobber
  ${cli} apply service-account \\
    -O "$AWG_ORGANIZATION_ID" \\
    -f "$AWG_ACCOUNT_DIR/service-account.yaml" \\
    > "$AWG_ACCOUNT_DIR/service-account-credentials.yaml"
)`;
    document.getElementById('account-created-file').textContent = `~/.vgs/agent-web-gateway/${env}/service-account-credentials.yaml`;
    document.getElementById('account-copy-status').textContent = '';
}
for (const button of document.querySelectorAll('[data-copy-command]')) {
    button.addEventListener('click', async () => {
        const code = document.getElementById(button.dataset.copyCommand);
        const status = document.getElementById('account-copy-status');
        try {
            await navigator.clipboard.writeText(code.textContent);
            status.textContent = 'Copied. Paste into your Terminal.';
        } catch (_) {
            const range = document.createRange(); range.selectNodeContents(code);
            const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
            status.textContent = 'Commands selected. Press Cmd+C or Ctrl+C to copy.';
        }
    });
}

function showView(view) {
    if (creationRunning() && view !== "create") return;
    document.getElementById("view-create").hidden = view !== "create";
    for (const button of document.querySelectorAll("button[data-view]")) {
        const selected = button.dataset.view === view;
        button.setAttribute("aria-pressed", String(selected));
        document.getElementById("view-" + button.dataset.view).hidden = !selected;
    }
    if (view === "gateway") globalThis.openGateway?.();
}
for (const button of document.querySelectorAll("button[data-view]")) button.addEventListener("click", () => showView(button.dataset.view));
document.getElementById("environment-shortcut").addEventListener("click", () => { showView("settings"); document.getElementById("environment-select").focus(); });
document.getElementById("environment-select").addEventListener("change", async event => {
    const selected = event.target.value;
    resetCreation();
    await request({type: "setEnvironment", environment: selected});
});

let egressDraftDirty = false;
function renderBrowserEgress() {
    const details = state.egress || {};
    const endpoint = details.proxy;
    document.getElementById('browser-egress-summary').textContent = endpoint ? `${endpoint.host}:${endpoint.port}` : 'Not configured';
    if (!egressDraftDirty) {
        document.getElementById('browser-egress-source').value = details.source || 'session';
        document.getElementById('browser-egress-scheme').value = endpoint?.scheme || 'http';
        document.getElementById('browser-egress-host').value = endpoint?.host || '';
        document.getElementById('browser-egress-port').value = endpoint?.port || '';
        document.getElementById('browser-egress-auth').checked = !!details.hasCredentials;
    }
    const custom = document.getElementById('browser-egress-source').value === 'custom';
    document.getElementById('browser-egress-fields').hidden = !custom;
    document.getElementById('browser-egress-credentials').hidden = !document.getElementById('browser-egress-auth').checked;
    document.getElementById('browser-egress-auth-help').textContent = details.hasCredentials ? 'Credentials saved in this browser. Leave both fields blank to keep them for the same endpoint.' : 'Credentials are saved locally in this browser.';
    for (const input of document.getElementById('browser-egress-form').elements) input.disabled = busy || !state.canControl;
}
document.getElementById('browser-egress-form').addEventListener('input', () => {egressDraftDirty = true; renderBrowserEgress(); document.getElementById('browser-egress-status').textContent = '';});
document.getElementById('browser-egress-form').addEventListener('submit', async event => {
    event.preventDefault();
    const value = id => document.getElementById('browser-egress-' + id).value;
    const localError = document.getElementById('browser-egress-error'); localError.hidden = true;
    const settings = {source: value('source')};
    if (settings.source === 'custom') {
        const host = value('host').trim(), port = value('port').trim();
        if (!/^(?=.{1,253}$)[a-zA-Z0-9]+(?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?$/.test(host) || !/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
            localError.textContent = 'Enter a proxy hostname and a port from 1 to 65535.'; localError.hidden = false; return;
        }
        Object.assign(settings, {scheme:value('scheme'), host, port:Number(port)});
        if (document.getElementById('browser-egress-auth').checked) {
            const username=value('user'), password=value('password');
            const sameEndpoint = state.egress?.proxy?.host === host.toLowerCase() && state.egress?.proxy?.scheme === settings.scheme && state.egress?.proxy?.port === settings.port;
            if (!username && !password && state.egress?.hasCredentials && sameEndpoint) settings.keepCredentials = true;
            else if (!username || !password) { localError.textContent = 'Enter both username and password for this proxy.'; localError.hidden = false; return; }
            else Object.assign(settings,{username,password});
        }
    }
    const result = await request({type:'configureEgress',settings});
    if (result?.ok) {
        egressDraftDirty=false;
        document.getElementById('browser-egress-user').value=''; document.getElementById('browser-egress-password').value='';
        document.getElementById('browser-egress-status').textContent=result.mode === 'egress' ? 'Saved and applied.' : 'Saved. Select Egress Proxy to use it.';
        renderBrowserEgress();
    }
});

let accountDraftDirty=false, accountDraftEnvironment=null, accountTenantChoices=[], accountPicker=null;
function renderAccountFile() {
    if (accountDraftEnvironment !== state.environment) {
        accountDraftDirty=false; accountDraftEnvironment=state.environment; accountTenantChoices=[]; accountPicker=null;
        document.getElementById('account-file-error').hidden=true;
        document.getElementById('account-file-status').textContent='';
    }
    if (!accountDraftDirty) {
        document.getElementById('account-file').value=state.account?.credentialsFile || '';
    }
    const selector=document.getElementById('account-tenant-select');
    const previous=selector.value; selector.replaceChildren();
    for(const row of accountTenantChoices) selector.add(new Option(row.name === row.tenantId ? row.tenantId : row.name + ' · ' + row.tenantId,row.tenantId));
    if(accountTenantChoices.some(row=>row.tenantId===previous))selector.value=previous;
    document.getElementById('account-tenant-choice').hidden=accountTenantChoices.length<2;
    document.getElementById('connect-account').textContent=accountTenantChoices.length>1?'Use selected tenant':'Connect account';
    for (const field of document.getElementById('account-file-form').elements) field.disabled=busy || !!accountPicker || creationRunning() || !state.catalogAvailable;
    document.getElementById('browse-account-file').textContent=accountPicker?'Choosing…':'Browse…';
}
function renderFileSelection(selection) {
    accountPicker=null;
    if(selection.environment!==state.environment)return;
    const status=document.getElementById('account-file-status');
    if(selection.status==='pending') {
        accountPicker=selection;
        status.textContent='Choose a file in the file explorer, or cancel to keep the current path.';
        setTimeout(()=>{if(accountPicker?.requestId===selection.requestId)request({type:'accountFileSelectionStatus',environment:selection.environment,requestId:selection.requestId});},500);
    } else if(selection.status==='selected') {
        accountDraftDirty=true; accountTenantChoices=[];
        document.getElementById('account-file').value=selection.credentialsFile;
        status.textContent='File selected. Click Connect account to load it.';
    } else if(selection.status==='cancelled') status.textContent='File selection cancelled.';
    else {
        status.textContent='';
        const error=document.getElementById('account-file-error');
        error.textContent=selection.error || 'File explorer is unavailable. Enter the local file path instead.';
        error.hidden=false;
    }
}
document.getElementById('browse-account-file').addEventListener('click',()=>{
    accountPicker={status:'pending',environment:state.environment};
    document.getElementById('account-file-error').hidden=true;
    document.getElementById('account-file-status').textContent='Opening file explorer…';
    request({type:'browseAccountFile',environment:state.environment});
});
document.getElementById('account-file').addEventListener('input',()=>{accountDraftDirty=true;accountTenantChoices=[];renderAccountFile();document.getElementById('account-file-status').textContent='';});
document.getElementById('account-file-form').addEventListener('submit',async event=>{
    event.preventDefault();
    const credentialsFile=document.getElementById('account-file').value.trim(),tenantId=accountTenantChoices.length>1?document.getElementById('account-tenant-select').value:'';
    document.getElementById('account-file-error').hidden=true;
    document.getElementById('account-file-status').textContent='Connecting…';
    const result=await request({type:'connectAccount',environment:state.environment,credentialsFile,tenantId});
    if(result?.ok && result.accountSelection){accountTenantChoices=result.accountSelection.tenants || [];renderAccountFile();document.getElementById('account-file-status').textContent='Choose which tenant to use.';return;}
    if(result?.ok && result.accountConnected){accountDraftDirty=false;accountTenantChoices=[];resetCreation();renderAccountFile();document.getElementById('account-file-status').textContent='Connected. Sessions refreshed.';}
    else document.getElementById('account-file-status').textContent='';
});

let inspectorKey = '', inspectorSequence = 0, inspectorDetails = null, inspectorError = '', inspectorLoading = false;
let inspectorCheckedAt = null, createdSessionNotice = null;
function inspectorSelection() {
    const sessionId = sessionSelect.value;
    return /^RS[A-Za-z0-9]+$/.test(sessionId || '') && state.account?.tenantId
        ? {sessionId,environment:state.environment,tenantId:state.account.tenantId} : null;
}
function renderSessionInspector() {
    const selected = inspectorSelection(), key = JSON.stringify(selected);
    if (key !== inspectorKey) {
        inspectorKey = key; inspectorSequence++; inspectorDetails = null; inspectorError = ''; inspectorLoading = false;
        document.getElementById('token-copy-status').textContent = '';
        document.getElementById('selected-session-tokens').replaceChildren();
        document.getElementById('selected-session-settings').replaceChildren();
        globalThis.renderSelectedCertificate?.(selected);
        if (selected) loadSessionInspector(selected,key);
    } else if (selected && state.checkedAt !== inspectorCheckedAt && !inspectorLoading) loadSessionInspector(selected,key);
    inspectorCheckedAt = state.checkedAt;
    const container = document.getElementById('session-inspector'); container.hidden = !selected;
    if (!selected) return;
    const active = state.session?.sessionId === selected.sessionId && state.session?.environment === selected.environment;
    const badge = document.getElementById('session-inspector-state'); badge.textContent = active ? 'Active in browser' : 'Not active'; badge.dataset.active = String(active);
    document.getElementById('session-inspector-title').textContent = 'Session aliases';
    document.getElementById('session-created-notice').hidden = JSON.stringify(createdSessionNotice) !== key;
    document.getElementById('session-inspector-status').textContent = inspectorError || (inspectorLoading ? 'Loading session details…' : '');
    document.getElementById('session-inspector-content').hidden = !inspectorDetails;
    const available = state.sessions?.find(session => session.sessionId === selected.sessionId);
    document.getElementById('selected-session-availability').textContent = !active && available?.available === false ? available.reason
        : active ? '' : 'Choose “Use selected session” to activate this session. The current proxy mode stays selected.';
    if (!inspectorDetails) return;
    const settings = inspectorDetails.settings || {};
    const expiry = settings.expires_at && Number.isFinite(Date.parse(settings.expires_at)) ? new Date(settings.expires_at).toLocaleString() : 'Unknown expiry';
    document.getElementById('standin-guidance').textContent = !active ? 'Activate this session before using these session aliases.'
        : ['pac','session'].includes(state.mode) ? 'Use these values in the checkout fields. Reveal depends on the session’s destination rules.'
        : 'Select VGS Reveal Session Proxy or its PAC file before using these values at checkout.';
    const tokens = document.getElementById('selected-session-tokens'); tokens.replaceChildren();
    for (const [index,token] of (inspectorDetails.tokens || []).entries()) {
        const row = document.createElement('div'); row.className = 'standin-row';
        const heading = document.createElement('div'), label = document.createElement('span'), copy = document.createElement('button'), value = document.createElement('code');
        const name = {card_number:'Card number',card_cvc:'Security code',text:'Text'}[token.format] || token.format;
        label.className = 'small-label'; label.textContent = name; copy.type = 'button'; copy.className = 'quiet'; copy.textContent = 'Copy'; copy.setAttribute('aria-label',`Copy ${name.toLowerCase()} session alias ${index+1}`);
        value.textContent = token.value;
        copy.addEventListener('click',async () => {
            try { await navigator.clipboard.writeText(token.value); if (key !== inspectorKey) return; document.getElementById('token-copy-status').textContent = name + ' session alias copied.'; }
            catch (_) { document.getElementById('token-copy-status').textContent = 'Select the value and copy it manually.'; }
        });
        heading.append(label,copy); row.append(heading,value); tokens.append(row);
    }
    if (!tokens.children.length) { const note=document.createElement('p');note.className='private-note';note.textContent='No session aliases were saved for this session.';tokens.append(note); }
    const fields = document.getElementById('selected-session-settings'); fields.replaceChildren();
    const endpoint = proxy => proxy?.hostname ? `${proxy.scheme}://${proxy.hostname}${proxy.port ? ':'+proxy.port : ''}` : 'None';
    const rows = [['Environment',environmentLabel(selected.environment)],['Tenant',selected.tenantId],['Session ID',selected.sessionId],['State',settings.state || 'active'],['Expires',expiry],
        ['Adapter',settings.adapter || 'Automatic'],['Adapter version',settings.adapter_version],['Allowed hosts',settings.allowed_hosts?.join('\n') || 'Tenant destination policy'],
        ['Allowed client addresses',settings.allowed_client_cidrs?.join('\n') || 'No session restriction'],['Reveal proxy',endpoint(settings.proxy)],['Egress proxy',endpoint(settings.egress)],
        ['PAC source (signature omitted)',settings.pacUrl],['Reveal limit',settings.reveal_limit ?? settings.max_reveals],['Reveals used',settings.reveal_count]];
    for (const [label,value] of rows) { if (value === undefined || value === null) continue; const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=String(value);fields.append(dt,dd); }
}
async function loadSessionInspector(selected,key) {
    const sequence = ++inspectorSequence; inspectorLoading = true; inspectorError = '';
    try {
        const result = await chrome.runtime.sendMessage({type:'getSessionDetails',environment:selected.environment,sessionId:selected.sessionId});
        if (sequence !== inspectorSequence || key !== inspectorKey) return;
        const details = result?.sessionDetails;
        if (!result?.ok || !details) throw new Error(result?.error || 'Could not load session details. Refresh the session list.');
        if (details.environment !== selected.environment || details.tenantId !== selected.tenantId || details.sessionId !== selected.sessionId) throw new Error('The selected account changed. Refresh the session list.');
        inspectorDetails = details;
    } catch (error) {
        if (sequence !== inspectorSequence || key !== inspectorKey) return;
        inspectorDetails = null; inspectorError = error.message;
    } finally {
        if (sequence === inspectorSequence && key === inspectorKey) { inspectorLoading = false; renderSessionInspector(); }
    }
}
