/* Read-only dashboard hierarchy: destinations, then adapters with their own functions and destinations. */
(() => {
    const $ = id => document.getElementById(id);
    const DESTINATIONS = 'agent-gateway-destinations', ADAPTERS = 'agent-gateway-adapters';
    const BINDINGS = 'agent-gateway-adapter-destinations';
    const labels = {[DESTINATIONS]:'Destinations', [ADAPTERS]:'Adapters'};
    let context = null, key = '', resource = DESTINATIONS;
    let rows = [], detail = null, adapter = null, selectedId = null, child = null, offset = 0, total = null;
    let functions = [], destinations = [], destinationError = '', defaultSection = 'review';
    let loading = false, error = '', loaded = false, updated = null, sequence = 0;
    const limit = 50;
    const visible = () => !$('view-gateway').hidden && !document.hidden;
    const isDefault = () => resource === ADAPTERS && selectedId === 'default';
    const isAdapter = () => resource === ADAPTERS && selectedId && !isDefault();
    const isList = () => !selectedId || isDefault();
    const text = value => value === undefined || value === null || value === '' ? '—'
        : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
    const date = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : text(value);
    const phase = value => ({'route.request':'Request','route.response':'Response',invoke:'Direct invocation'})[value] || text(value);
    function node(tag, value, className) {
        const element = document.createElement(tag);
        if (value !== undefined) element.textContent = value;
        if (className) element.className = className;
        return element;
    }
    function button(label, action, accessibleName) {
        const element = node('button', label, 'text-button'); element.type = 'button';
        if (accessibleName) element.setAttribute('aria-label', accessibleName);
        element.addEventListener('click', action); return element;
    }
    function badge(value, tone) {
        const normalized = String(value ?? '').toLowerCase();
        const element = node('span', ({trust:'Trust',guarded:'Guarded',block:'Block',true:'Enabled',false:'Disabled'})[normalized] || text(value), 'gateway-badge');
        element.dataset.tone = tone || ({trust:'success',guarded:'warning',block:'danger',true:'success'})[normalized] || 'neutral';
        return element;
    }
    function cell(row, value, tag = 'td') {
        const element = node(tag); element.append(value instanceof Node ? value : document.createTextNode(text(value))); row.append(element); return element;
    }
    function emptyRow(body, message, count) {
        const row = node('tr'), td = node('td', message, 'gateway-empty'); td.colSpan = count; row.append(td); body.append(row);
    }
    function approver(a) {
        const staged = a.created_by === 'agent-gateway-auto-staging';
        if (a.action === 'trust' && a.promoted_by) return a.promoted_by;
        if (a.action === 'trust' && staged && a.origin === 'manual') return 'Approved (approver not recorded)';
        return staged ? 'Auto-staged' : text(a.created_by);
    }
    function clearDetail() { detail = null; adapter = null; functions = []; destinations = []; destinationError = ''; }
    function select(id, nextChild = null) {
        selectedId = id; child = nextChild; clearDetail();
        $('gateway-destination-search').value = ''; load();
    }
    function openFunction(id) { select(selectedId, {resource:'functions', id}); }
    function breadcrumb() {
        const container = $('gateway-breadcrumbs'); container.replaceChildren(); container.hidden = !selectedId;
        if (!selectedId) return;
        container.append(button(labels[resource], () => { selectedId = null; child = null; clearDetail(); offset = 0; load(); }));
        const name = isDefault() ? 'Default' : adapter?.attributes?.name || (isAdapter() ? selectedId : detail?.attributes?.host_pattern || selectedId);
        container.append(node('span', '›', 'gateway-crumb-divider'));
        if (child) {
            container.append(button(name, () => select(selectedId)), node('span', '›', 'gateway-crumb-divider'));
            const current = node('span', detail?.attributes?.name || detail?.attributes?.when?.path || child.id);
            current.setAttribute('aria-current', 'page'); container.append(current);
        } else {
            const current = node('span', name); current.setAttribute('aria-current', 'page'); container.append(current);
        }
    }
    function registryRow(item) {
        const a = item.attributes || {}, builtIn = item.id === 'default', tr = node('tr');
        const name = node('div', undefined, 'gateway-adapter-name');
        const icon = node('span', builtIn ? '⌕' : '↔', 'gateway-adapter-icon'); icon.setAttribute('aria-hidden','true');
        if (builtIn) icon.classList.add('gateway-adapter-icon-default');
        const caption = node('div'); caption.append(button(a.name, () => { if (builtIn) {offset = 0; defaultSection = 'review';} select(item.id); }, 'View ' + a.name));
        caption.append(node(builtIn ? 'p' : 'code', builtIn ? 'Catch-all search and replace' : item.id, 'gateway-row-note'));
        name.append(icon, caption); cell(tr, name);
        cell(tr, badge(builtIn || a.owner === 'vgs' ? 'Registered' : 'Custom', builtIn || a.owner === 'vgs' ? 'brand' : 'neutral'));
        cell(tr, builtIn ? '—' : 'v' + text(a.version)); cell(tr, builtIn ? '—' : (a.functions || []).length);
        const publication = node('div'); publication.append(badge(builtIn ? 'Built in' : a.published_version ? 'Published v' + a.published_version : 'Private draft', a.published_version ? 'success' : 'neutral'));
        if (a.scheduled_version) publication.append(node('p', 'v' + a.scheduled_version + ' scheduled', 'gateway-row-note'));
        cell(tr, publication); return tr;
    }
    function table() {
        const registry = resource === ADAPTERS && !selectedId;
        const headings = registry ? ['Adapter','Type','Version','Functions','Publication'] : ['Host pattern','Action','Origin','Approved by','Created at','Details'];
        $('gateway-table-head').replaceChildren(...headings.map(label => node('th', label)));
        $('gateway-table').setAttribute('aria-label', registry ? 'Adapter registry' : 'Destination policy');
        $('gateway-registry-note').hidden = !registry;
        $('gateway-search-label').textContent = registry ? 'Search adapters' : 'Filter this page';
        $('gateway-search').placeholder = registry ? 'Search adapters' : 'Search names, IDs, or settings';
        const terms = $('gateway-search').value.toLowerCase().trim().split(/\s+/).filter(Boolean);
        const filter = isDefault() && defaultSection === 'review' ? 'review' : $('gateway-action-filter').value;
        let filtered = rows.filter(row => {
            const a = row.attributes || {};
            if (registry && a.owner === 'vgs' && !a.published_version) return false;
            const matches = filter === 'all' || a.action === filter || (filter === 'review' && a.action === 'guarded' && a.origin === 'auto');
            const searchable = registry ? `${a.name} ${row.id} ${a.owner === 'vgs' ? 'Registered' : 'Custom'}` : JSON.stringify(row);
            return (registry || matches) && terms.every(term => searchable.toLowerCase().includes(term));
        });
        if (registry) filtered.sort((a,b) => String(a.attributes?.name || a.id).localeCompare(String(b.attributes?.name || b.id)));
        const body = $('gateway-table-body'); body.replaceChildren();
        if (registry && !offset && !error && context?.connected && terms.every(term => 'default registered built in catch-all search and replace'.includes(term))) body.append(registryRow({id:'default',attributes:{name:'Default'}}));
        for (const item of filtered) {
            if (registry) { body.append(registryRow(item)); continue; }
            const a = item.attributes || {}, tr = node('tr');
            for (const value of [a.host_pattern, badge(a.action), a.origin === 'auto' ? 'Auto' : text(a.origin), approver(a), date(a.created_at)]) cell(tr, value);
            cell(tr, button('View', () => {
                if (isDefault()) select('default', {resource:DESTINATIONS, id:item.id});
                else select(item.id);
            }, 'View ' + (a.host_pattern || item.id))); body.append(tr);
        }
        if (!body.children.length) emptyRow(body, loading ? 'Loading…' : error ? 'Configuration could not be loaded.'
            : !context?.connected ? 'Connect a service account in Settings to view configuration.'
            : terms.length || filter !== 'all' ? 'No results match these filters.' : registry ? 'No adapters found for this tenant.' : 'No destinations found for this tenant.', headings.length);
        $('gateway-range').textContent = rows.length ? `${offset + 1}–${offset + rows.length}${total !== null ? ' of ' + total : ''}` : '';
        $('gateway-prev').disabled = loading || offset === 0;
        $('gateway-next').disabled = loading || !rows.length || (total === null ? rows.length < limit : offset + rows.length >= total);
    }
    function renderDestinations() {
        const table = $('gateway-destinations-table'); for (const body of [...table.tBodies]) body.remove();
        const terms = $('gateway-destination-search').value.toLowerCase().trim().split(/\s+/).filter(Boolean);
        const groups = new Map(); let count = 0;
        for (const row of destinations) {
            const a = row.attributes || {}, when = a.when || {};
            if (!terms.every(term => `${when.host} ${when.method || 'Any method'} ${when.path || 'Any path'} ${(a.functions || []).map(fn => fn.id).join(' ')}`.toLowerCase().includes(term))) continue;
            const host = String(when.host || 'Unspecified host').toLowerCase();
            if (!groups.has(host)) groups.set(host, []); groups.get(host).push(row); count++;
        }
        $('gateway-destination-count').textContent = destinationError ? '' : `${count} of ${destinations.length} destinations`;
        $('gateway-destination-error').hidden = !destinationError; $('gateway-destination-error').textContent = destinationError;
        for (const [host, items] of [...groups.entries()].sort(([a],[b]) => a.localeCompare(b))) {
            const body = node('tbody'); body.setAttribute('aria-label', host);
            const header = node('tr'), heading = cell(header, host, 'th'); heading.scope = 'rowgroup'; heading.colSpan = 4; body.append(header);
            for (const item of items) {
                const a = item.attributes || {}, when = a.when || {}, row = node('tr'), trigger = node('div');
                trigger.append(node('p', when.method || 'Any method', 'gateway-row-note'), button(when.path || 'Any path', () => select(selectedId, {resource:BINDINGS,id:item.id}), 'View ' + host + ' ' + (when.path || 'Any path')));
                cell(row, trigger); cell(row, 'v' + text(a.adapter_version));
                const links = node('div', undefined, 'gateway-function-links');
                for (const fn of a.functions || []) links.append(button(functions.find(item => item.id === fn.id)?.data?.attributes?.name || fn.id, () => openFunction(fn.id)));
                cell(row, links); cell(row, badge(a.enabled)); body.append(row);
            }
            table.append(body);
        }
        if (!groups.size) { const body = node('tbody'); emptyRow(body, destinationError ? 'Connected destinations could not be loaded.' : loading ? 'Loading destinations…' : terms.length ? 'No matching destinations' : 'No connected destinations', 4); table.append(body); }
    }
    function renderFunctions() {
        const body = $('gateway-functions-body'); body.replaceChildren();
        for (const fn of functions) {
            const a = fn.data?.attributes || {}, row = node('tr'), name = node('div');
            name.append(button(a.name || fn.id, () => openFunction(fn.id)), node('code',fn.id,'gateway-row-note'));
            if (fn.error) name.append(node('p','Could not load definition. Open the function to retry.','gateway-inline-error'));
            cell(row,name); cell(row,phase(a.extension_point)); cell(row,(a.inputs || []).map(input => `${input.name}${input.required ? ' (required)' : ''}`).join(', ') || '—'); body.append(row);
        }
        if (!functions.length) emptyRow(body, loading ? 'Loading functions…' : 'No functions in this adapter version.', 3);
    }
    const fieldLabels = {host_pattern:'Host pattern', action:'Action', origin:'Origin', created_by:'Created by',
        created_at:'Created at', updated_at:'Updated at', promoted_by:'Approved by', promoted_at:'Approved at',
        route_id:'Route ID', name:'Function name', extension_point:'Runs on', language:'Language', inputs:'Inputs',
        previous_version:'Previous version', adapter:'Adapter', adapter_version:'Adapter version', enabled:'State', when:'When to run'};
    function renderDetail() {
        const a = detail?.attributes || {}, parentView = isAdapter() && !child;
        $('gateway-detail-title').textContent = a.name || a.host_pattern || a.when?.host || (loading ? 'Loading…' : child?.id || selectedId || '');
        $('gateway-detail-subtitle').textContent = parentView && detail ? `Version ${a.version} · ${a.published_version ? 'Published v' + a.published_version : 'Unpublished'}${a.scheduled_at ? ` · v${a.scheduled_version} scheduled for ${date(a.scheduled_at)}` : ''}` : '';
        $('gateway-detail-id').textContent = detail?.id || '';
        const fields = $('gateway-detail-fields'); fields.replaceChildren(); fields.hidden = parentView || !detail;
        for (const [name,value] of Object.entries(a)) {
            if (parentView || ['source','functions','inputs'].includes(name)) continue;
            const group = node('div'), dt = node('dt',fieldLabels[name] || name.replaceAll('_',' ')), dd = node('dd');
            if (name === 'action' || name === 'enabled') dd.append(badge(value));
            else dd.textContent = name === 'extension_point' ? phase(value) : name.endsWith('_at') ? date(value) : text(value);
            group.append(dt,dd); fields.append(group);
        }
        $('gateway-adapter-children').hidden = !parentView || !detail;
        if (parentView && detail) { renderFunctions(); renderDestinations(); }
        $('gateway-source-section').hidden = typeof a.source !== 'string'; $('gateway-source').textContent = a.source || '';
        const bindings = $('gateway-bindings'); bindings.replaceChildren();
        $('gateway-bindings-section').hidden = !child || !detail || !['functions',BINDINGS].includes(child.resource);
        if (child?.resource === 'functions') {
            for (const input of a.inputs || []) bindings.append(node('p', `${input.name}${input.required ? ' (required)' : ' (optional)'}`));
            if (!(a.inputs || []).length) bindings.append(node('p','No inputs declared.','private-note'));
        } else if (child?.resource === BINDINGS) {
            for (const fn of a.functions || []) {
                const group = node('section'); group.append(button(fn.id, () => openFunction(fn.id)), node('pre',JSON.stringify(fn.inputs || {},null,2))); bindings.append(group);
            }
        }
        $('gateway-raw').hidden = !detail; $('gateway-json').textContent = detail ? JSON.stringify(detail,null,2) : '';
    }
    function render() {
        $('gateway-refresh').disabled = loading || !context?.connected;
        $('gateway-error').hidden = !error; $('gateway-error').textContent = error;
        $('gateway-updated').textContent = loading ? 'Refreshing…' : updated ? 'Updated ' + updated.toLocaleTimeString() : '';
        $('gateway-resource-title').textContent = resource === ADAPTERS ? 'Adapter registry' : 'Destinations';
        $('gateway-resource-title').hidden = !!selectedId;
        const showList = isList() && !child;
        $('gateway-list').hidden = !showList; $('gateway-detail').hidden = showList;
        $('gateway-default').hidden = !isDefault() || !!child;
        $('gateway-action-field').hidden = resource === ADAPTERS && (!isDefault() || defaultSection === 'review');
        for (const element of document.querySelectorAll('[data-gateway-resource]')) element.setAttribute('aria-pressed',String(element.dataset.gatewayResource === resource));
        for (const element of document.querySelectorAll('[data-default-section]')) element.setAttribute('aria-pressed',String(element.dataset.defaultSection === defaultSection));
        breadcrumb(); if (showList) table(); else renderDetail();
    }
    async function load() {
        if (!context?.connected || !context.tenantId) { render(); return; }
        const request = ++sequence, selectedKey = key, selectedResource = resource, id = selectedId, selectedChild = child;
        const current = () => request === sequence && key === selectedKey;
        const account = {...context};
        async function read(kind, itemId = null, pageOffset = 0, pageLimit = limit) {
            const response = await chrome.runtime.sendMessage({type:'readGateway',environment:account.environment,
                options:{tenantId:account.tenantId,resource:kind,...(itemId ? {id:itemId} : {limit:pageLimit,offset:pageOffset})}});
            if (!current()) throw new Error('Selection changed');
            if (!response?.ok || !response.gateway) throw new Error(response?.error || 'Could not reach the local helper. Reload the panel and try again.');
            const result = response.gateway;
            if (result.environment !== account.environment || result.tenantId !== account.tenantId || result.resource !== kind || (result.id || null) !== itemId)
                throw new Error('The account or selection changed. Refresh the panel.');
            if (itemId ? result.document?.data?.id !== itemId : !Array.isArray(result.document?.data)) throw new Error('The resource response was incomplete. Try refreshing.');
            return result.document;
        }
        async function adapterDestinations(adapterId) {
            const found = [], seen = new Set();
            for (let start = 0; start < 10000; start += 100) {
                const result = await read(BINDINGS,null,start,100), data = result.data;
                for (const row of data) {
                    if (seen.has(row.id)) throw new Error('The destination list changed while loading. Refresh to try again.');
                    seen.add(row.id);
                    if (row.attributes?.adapter === adapterId) found.push(row);
                }
                const count = result.meta?.total_elements;
                if (data.length < 100 || (Number.isInteger(count) && start + data.length >= count)) return found;
            }
            throw new Error('There are too many destinations to display. Use the dashboard to inspect this adapter.');
        }
        loading = true; error = ''; render();
        try {
            if (id && id !== 'default' && selectedResource === ADAPTERS) {
                const parent = (await read(ADAPTERS,id)).data;
                if (selectedChild) {
                    const result = await read(selectedChild.resource,selectedChild.id);
                    if (!current()) return;
                    adapter = parent; detail = result.data;
                } else {
                    const functionIds = [...new Set(parent.attributes?.functions || [])];
                    const [functionResults,destinationResult] = await Promise.all([
                        Promise.allSettled(functionIds.map(fn => read('functions',fn))),
                        adapterDestinations(id).then(data => ({data}),failure => ({error:failure.message}))
                    ]);
                    if (!current()) return;
                    adapter = parent; detail = parent;
                    functions = functionResults.map((result,index) => ({id:functionIds[index],data:result.status === 'fulfilled' ? result.value.data : null,error:result.status === 'rejected'}));
                    destinations = destinationResult.data || []; destinationError = destinationResult.error || '';
                }
            } else if (selectedChild || (id && id !== 'default')) {
                detail = (await read(selectedChild?.resource || selectedResource,selectedChild?.id || id)).data;
            } else {
                const result = await read(id === 'default' ? DESTINATIONS : selectedResource,null,offset);
                rows = result.data; const count = result.meta?.total_elements;
                total = Number.isInteger(count) && count >= 0 ? count : null;
            }
            if (!current()) return;
            loaded = true; updated = new Date();
        } catch (failure) {
            if (!current()) return;
            rows = []; clearDetail(); total = null; updated = null; loaded = true; error = failure.message;
        } finally { if (current()) { loading = false; render(); } }
    }
    globalThis.resetGateway = () => { key = ''; sequence++; };
    globalThis.renderGateway = current => {
        const account = current.account, nextKey = JSON.stringify([current.environment,account?.tenantId,!!account?.connected]);
        if (key !== nextKey) {
            key = nextKey; sequence++; context = {environment:current.environment,tenantId:account?.tenantId,connected:!!account?.connected};
            rows = []; clearDetail(); selectedId = null; child = null; offset = 0; total = null; updated = null;
            error = ''; loading = false; loaded = false; render();
        }
        if (visible() && !loaded && !loading && context?.connected) load();
    };
    globalThis.openGateway = () => { renderGateway(state); if (!loading && loaded) load(); };
    for (const element of document.querySelectorAll('[data-gateway-resource]')) element.addEventListener('click', () => {
        resource = element.dataset.gatewayResource; selectedId = null; child = null; rows = []; clearDetail(); offset = 0; total = null;
        $('gateway-search').value = ''; $('gateway-action-filter').value = 'all'; load();
    });
    for (const element of document.querySelectorAll('[data-default-section]')) element.addEventListener('click', () => {
        defaultSection = element.dataset.defaultSection; offset = 0; rows = []; $('gateway-search').value = ''; $('gateway-action-filter').value = 'all'; load();
    });
    $('gateway-refresh').addEventListener('click',load);
    $('gateway-search').addEventListener('input',table);
    $('gateway-action-filter').addEventListener('change',table);
    $('gateway-destination-search').addEventListener('input',renderDestinations);
    $('gateway-prev').addEventListener('click',() => { offset = Math.max(0,offset-limit); load(); });
    $('gateway-next').addEventListener('click',() => { offset += limit; load(); });
    setInterval(() => { if (visible() && $('gateway-auto-refresh').checked && !loading && !busy) load(); },30000);
    render();
})();
