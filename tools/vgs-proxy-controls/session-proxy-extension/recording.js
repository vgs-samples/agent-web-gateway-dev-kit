// Recording is owned by the local helper, so closing this panel does not stop it.
(() => {
    const get = id => document.getElementById(id);
    let knownTabs = '';
    globalThis.renderTestRecording = (state, busy) => {
        const capture = state.recording || {};
        const active = ['starting', 'recording', 'stopping'].includes(capture.state);
        const status = get('test-recording-state');
        status.textContent = {idle:'Ready', starting:'Starting…', recording:'Recording', stopping:'Saving…', saved:'HAR saved', failed:'Recording failed', unknown:'Status unavailable'}[capture.state] || 'Checking…';
        if (capture.setupRequired && !active) status.textContent = 'Browser relaunch needed';
        status.dataset.recording = String(capture.state === 'recording');
        get('start-test').disabled = busy || active || !state.catalogAvailable || !['idle','saved','failed'].includes(capture.state) || !!capture.setupRequired;
        get('stop-test').disabled = busy || capture.state !== 'recording';
        get('refresh-test-tabs').disabled = busy || active;
        get('refresh-recording').disabled = busy;
        get('test-tab').disabled = busy || active;
        get('test-address').disabled = busy || active;
        if (state.recordingTabs && JSON.stringify(state.recordingTabs) !== knownTabs) {
            knownTabs = JSON.stringify(state.recordingTabs);
            const selected = get('test-tab').value;
            get('test-tab').replaceChildren(new Option('New test tab', ''));
            for (const tab of state.recordingTabs) get('test-tab').add(new Option(`${tab.title || 'Untitled'} · ${tab.url}`, tab.tabId));
            if (state.recordingTabs.some(tab => tab.tabId === selected)) get('test-tab').value = selected;
        }
        const detail = [];
        if (capture.captureId) detail.push(`${capture.entries || 0} requests recorded`);
        if (capture.omittedRequests) detail.push(`${capture.omittedRequests} requests omitted at the capture limit`);
        if (capture.bodyErrors) detail.push(`${capture.bodyErrors} ${capture.bodyErrors === 1 ? "body" : "bodies"} unavailable or above the size limit`);
        if (capture.incompleteEntries) detail.push(`${capture.incompleteEntries} incomplete requests`);
        if (capture.checkpointError) detail.push('Local checkpoint save failed');
        get('test-recording-detail').textContent = detail.join(' · ');
        get('test-recording-error').hidden = !(capture.error || capture.setupRequired);
        get('test-recording-error').textContent = capture.error || capture.setupRequired || '';
        get('test-recording-path').hidden = !capture.path;
        get('test-recording-path').textContent = capture.path || '';
        if (get('test-repair-status')) {
            get('test-repair-status').hidden = !capture.repair;
            get('test-repair-status').textContent = capture.repair?.message || '';
        }
    };
    get('test-recording-form').addEventListener('submit', event => {
        event.preventDefault();
        const tabId = get('test-tab').value, url = get('test-address').value.trim();
        if (!tabId && !url) { get('test-address').required = true; get('test-address').reportValidity(); return; }
        get('test-address').required = false;
        request({type:'startRecording', options:{requestId:crypto.randomUUID(), tabId:tabId || null, url}});
    });
    get('test-tab').addEventListener('change', () => { get('test-address').required = !get('test-tab').value; });
    get('refresh-test-tabs').addEventListener('click', () => request({type:'recordingTabs'}));
    get('stop-test').addEventListener('click', () => request({type:'stopRecording'}));
    get('refresh-recording').addEventListener('click', () => request({type:'recordingStatus'}));
    // Background polling must not enter request()'s global busy/render cycle.
    // That cycle disables selects and rebuilds form controls, interrupting input.
    let polling = false;
    setInterval(async () => {
        if (document.hidden || busy || polling) return;
        polling = true;
        try {
            const response = await chrome.runtime.sendMessage({type:'recordingStatus'});
            if (response?.recording) {
                state.recording = response.recording;
                globalThis.renderTestRecording(state, busy);
            }
        } catch (_) { /* Keep the form usable; explicit Refresh can report connection errors. */ }
        finally { polling = false; }
    }, 2000);
})();
