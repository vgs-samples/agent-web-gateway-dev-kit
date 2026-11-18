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
let state = {mode: "unavailable", canControl: false, availableModes: []};

function render() {
    const session = state.session || {};
    document.getElementById("session-id").textContent = session.sessionId || "Not available";
    document.getElementById("pac-source").textContent = session.pacSource || "Not available";
    const expired = session.expiresAt && Date.parse(session.expiresAt) <= Date.now();
    document.getElementById("session-expiry").textContent = session.expiresAt
        ? (expired ? "Expired " : "Expires ") + new Date(session.expiresAt).toLocaleString() : "";
    const key = JSON.stringify([state.sessions, session.sessionId]);
    if (key !== renderedSessions) {
        const previous = sessionSelect.value;
        sessionSelect.replaceChildren();
        const rows = [...(state.sessions || [])];
        if (session.sessionId && !rows.some(r => r.sessionId === session.sessionId))
            rows.unshift({...session, available: false, reason: "Current; not in the active list"});
        for (const row of rows) {
            const option = document.createElement("option");
            option.value = row.sessionId;
            option.disabled = !row.available;
            option.textContent = row.sessionId + (row.available ? " · expires " + new Date(row.expiresAt).toLocaleTimeString() : " · " + row.reason);
            sessionSelect.append(option);
        }
        if (!rows.length) sessionSelect.add(new Option("No active sessions available", ""));
        sessionSelect.value = rows.some(r => r.sessionId === previous && r.available) ? previous : session.sessionId || "";
        renderedSessions = key;
    }
    if (displayedSession !== session.sessionId) {
        document.getElementById("pac-script").textContent = "Load the selected session’s routing script.";
        document.getElementById("pac-status").textContent = "";
        displayedSession = session.sessionId;
    }
    sessionSelect.disabled = busy || !state.catalogAvailable;
    useSession.disabled = busy || !state.canControl || !state.catalogAvailable || !sessionSelect.value
        || sessionSelect.value === session.sessionId || !state.sessions?.some(s => s.sessionId === sessionSelect.value && s.available);
    document.getElementById("refresh-sessions").disabled = busy || !state.catalogAvailable;
    document.getElementById("load-pac").disabled = busy || !state.catalogAvailable;
    document.getElementById("catalog-status").textContent = state.catalogError || (state.checkedAt
        ? `${(state.sessions || []).filter(s => s.available).length} usable session(s). Updated ${new Date(state.checkedAt).toLocaleTimeString()}.`
        : "Refresh to check active sessions and locally saved credentials.");
    stateLabel.dataset.mode = state.mode;
    stateLabel.textContent = {pac: "Reveal Session PAC", session: "Reveal Session Proxy", egress: "Egress Proxy", direct: "No Proxy", unavailable: "Unavailable"}[state.mode];
    description.textContent = {
        pac: "VGS handles the hosts selected by this session’s PAC. Other traffic follows its egress route.",
        session: "VGS handles browser traffic directly and applies the session’s reveal rules, then its configured egress.",
        egress: "Traffic goes directly to the session’s egress proxy. VGS token replacement is off.",
        direct: "Direct connection from this computer. VGS token replacement is off.",
        unavailable: "The session’s routing is not active. Another browser setting may control the proxy."
    }[state.mode];
    for (const button of buttons) {
        button.setAttribute("aria-pressed", String(button.dataset.mode === state.mode));
        button.disabled = busy || !state.canControl || !state.availableModes.includes(button.dataset.mode);
    }
    document.getElementById("egress-note").textContent = state.availableModes.includes("egress")
        ? "Use the session’s egress directly, without VGS." : "No egress proxy is configured for this session.";
}

async function request(message) {
    if (busy) {
        if (message.type === "getState") refreshPending = true;
        return;
    }
    busy = true;
    render();
    if (message.type !== "getState") errorLabel.hidden = true;
    try {
        const response = await chrome.runtime.sendMessage(message);
        if (!response) throw new Error("No response");
        state = response;
        render();
        if (response.pacScript !== undefined) {
            document.getElementById("pac-script").textContent = response.pacScript;
            document.getElementById("pac-status").textContent = "Fetched " + new Date(response.fetchedAt).toLocaleString();
        }
        if (!state.ok) {
            errorLabel.textContent = state.error;
            errorLabel.hidden = false;
        }
    } catch (_) {
        state = {mode: "unavailable", canControl: false, availableModes: []};
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
useSession.addEventListener("click", () => request({type: "selectSession", sessionId: sessionSelect.value}));
document.getElementById("refresh-sessions").addEventListener("click", () => request({type: "refreshSessions"}));
document.getElementById("load-pac").addEventListener("click", () => request({type: "getPac"}));
request({type: "refreshSessions"});
