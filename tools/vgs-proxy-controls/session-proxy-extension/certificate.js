/* Download public certificates only; certificate trust is configured by the user. */
(() => {
    const $ = id => document.getElementById(id);
    let active = null, created = null, selected = null, activeKey = '', createdKey = '', selectedKey = '';
    const pending = new Set();
    const key = session => JSON.stringify([session?.sessionId, session?.environment]);
    const valid = session => /^RS[A-Za-z0-9]+$/.test(session?.sessionId || '') && ['dev', 'sandbox', 'live'].includes(session?.environment);
    function renderButtons() {
        for (const id of ['download-proxy-ca', 'download-session-ca']) $(id).disabled = !valid(active) || pending.has(key(active));
        $('download-created-ca').disabled = !valid(created) || pending.has(key(created));
        $('download-selected-ca').disabled = !valid(selected) || pending.has(key(selected));
    }
    globalThis.renderCertificate = current => {
        active = current.session || null;
        const nextKey = key(active);
        if (nextKey !== activeKey) {
            activeKey = nextKey;
            $('proxy-ca-status').textContent = '';
            $('certificate-status').textContent = '';
        }
        $('certificate-context').textContent = valid(active)
            ? `${environmentLabel(active.environment)} · Active reveal session ${active.sessionId}`
            : 'Choose a reveal session to download its CA certificate.';
        $('download-proxy-ca').title = valid(active) ? `Download the CA for the active ${environmentLabel(active.environment)} reveal session` : 'Choose a reveal session first';
        renderButtons();
    };
    globalThis.renderCreatedCertificate = value => {
        created = value.status === 'complete' ? {sessionId:value.sessionId, environment:value.environment || creationEnvironment} : null;
        if (key(created) !== createdKey) { createdKey = key(created); $('created-ca-status').textContent = ''; }
        renderButtons();
    };
    globalThis.renderSelectedCertificate = value => {
        selected = value;
        if (key(selected) !== selectedKey) { selectedKey = key(selected); $('selected-ca-status').textContent = ''; }
        renderButtons();
    };
    async function download(session, statusIds) {
        if (!valid(session) || pending.has(key(session))) return;
        const selected = {...session}, requestKey = key(selected);
        const stillSelected = () => statusIds.includes('created-ca-status') ? key(created) === requestKey : statusIds.includes('selected-ca-status') ? selectedKey === requestKey : key(active) === requestKey;
        const status = message => { if (stillSelected()) for (const id of statusIds) $(id).textContent = message; };
        pending.add(requestKey); renderButtons(); status('Preparing certificate…');
        try {
            const response = await chrome.runtime.sendMessage({type:'getSessionCa', sessionId:selected.sessionId, environment:selected.environment});
            if (!response?.ok) throw new Error(response?.error || 'Could not reach the local helper.');
            const certificate = response.certificate;
            if (certificate?.sessionId !== selected.sessionId || certificate.environment !== selected.environment || typeof certificate.caBundle !== 'string')
                throw new Error('The certificate response did not match this session. Refresh and try again.');
            const url = URL.createObjectURL(new Blob([certificate.caBundle], {type:'application/x-pem-file'}));
            const link = document.createElement('a'); link.href = url;
            link.download = `vgs-${selected.environment}-${selected.sessionId}-ca.pem`;
            document.body.append(link); link.click(); link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 60000);
            status(`${environmentLabel(selected.environment)} CA download started. See Diagnostics for installation instructions.`);
        } catch (error) { status(error.message || 'Could not download the certificate. Try again.'); }
        finally { pending.delete(requestKey); renderButtons(); }
    }
    for (const id of ['download-proxy-ca', 'download-session-ca']) $(id).addEventListener('click', () => download(active, ['proxy-ca-status', 'certificate-status']));
    $('download-selected-ca').addEventListener('click', () => download(selected, ['selected-ca-status']));
    $('download-created-ca').addEventListener('click', () => download(created, ['created-ca-status']));
    $('created-ca-help').addEventListener('click', () => { showView('diagnostics'); $('certificate-installation').open = true; $('certificate-installation').focus(); });
})();
