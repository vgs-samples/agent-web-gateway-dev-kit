// Mirrors the dashboard CreateSessionForm's fields and request shape.
const el = id => document.getElementById(id);
let operation = null, operationTimer = null;
let creationId = sessionStorage.getItem('creationId');
let creationEnvironment = sessionStorage.getItem('creationEnvironment') || 'dev';
let cardOperation = null, cardTimer = null;
let cardRequestId = sessionStorage.getItem('cardRequestId');
let cardEnvironment = sessionStorage.getItem('cardEnvironment') || 'dev';
// Keep any previous job IDs stored for a later opted-in page, without polling
// Dev operations or locking the normal Sandbox/Live form in the meantime.
if (!allowDevEnv && creationEnvironment === 'dev') creationId = null;
if (!allowDevEnv && cardEnvironment === 'dev') cardRequestId = null;
let aliasRows = [], nextAliasKey = 0, formEnvironment = null;
let adapters = [], adaptersLoaded = false, adaptersLoading = false;
const creationRunning = () => collectCard.submitting || operation?.status === 'running' || cardOperation?.status === 'running'
    || (!!creationId && !operation) || (!!cardRequestId && !cardOperation);
const splitEntries = text => [...new Set(text.split(/[\s,]+/).filter(Boolean))];

function resetCreation() {
    collectCard.reset();
    aliasRows = []; nextAliasKey = 0; adapters = []; adaptersLoaded = false; adapterMenuOpen = false;
    el('create-form').reset(); el('adapter-select').value = ''; el('created-session').hidden = true;
    el('add-card-panel').hidden = true; el('card-notice').textContent = '';
    el('creation-status').textContent = ''; el('form-error').hidden = true;
    formEnvironment = state.environment || 'sandbox';
    const profile = state.account?.egressConfig;
    el('egress-type').value = profile ? 'profile' : 'none';
    renderAliases(); renderAdapters(); renderCreation();
}

function renderAliases(focusKey) {
    const container = el('alias-rows'); container.replaceChildren();
    const prefix = {dev:'tok_dev_',sandbox:'tok_sandbox_',live:'tok_live_'}[state.environment];
    for (const [index, row] of aliasRows.entries()) {
        const line = document.createElement('div'); line.className = 'alias-row';
        line.dataset.key = String(row.key);
        // Static template; all API values below are assigned as text/value properties.
        line.innerHTML = `<div><label>Alias ${index + 1}</label><input data-field="alias" autocomplete="off" spellcheck="false"></div>
          <div><label>Format</label><select data-field="format"><option value="card_number">Card number</option><option value="card_cvc">Security code</option><option value="text">Text</option></select></div>
          <div class="alias-bin"><label title="Card number aliases need a 6 or 8 digit BIN.">BIN</label><input data-field="bin" inputmode="numeric" placeholder="Required"></div>
          <div class="alias-length"><label>Length</label><input data-field="length" inputmode="numeric"></div>
          <div><label>Storage</label><select data-field="storage"><option value="PERSISTENT">Persistent</option><option value="VOLATILE">Volatile</option></select></div>
          <button type="button" class="text-button remove-alias">Remove</button>`;
        for (const input of line.querySelectorAll('[data-field]')) {
            input.id = `alias-${row.key}-${input.dataset.field}`;
            input.previousElementSibling.htmlFor = input.id;
            input.value = row[input.dataset.field] ?? '';
            input.addEventListener(input.tagName === 'SELECT' ? 'change' : 'input', () => {
                row[input.dataset.field] = input.value;
                if (input.dataset.field === 'format') {
                    row.bin = ''; row.length = '';
                    row.storage = row.format === 'card_cvc' ? 'VOLATILE' : 'PERSISTENT';
                    renderAliases(); renderCreation();
                    el(`alias-${row.key}-format`).focus();
                }
            });
        }
        const alias = line.querySelector('[data-field=alias]');
        alias.placeholder = prefix + '…'; alias.pattern = collectCard.aliasPattern(state.environment); alias.required = true;
        line.querySelector('.alias-bin').hidden = row.format !== 'card_number';
        line.querySelector('.alias-length').hidden = row.format === 'text';
        line.querySelector('[data-field=bin]').required = row.format === 'card_number';
        line.querySelector('[data-field=length]').placeholder = row.format === 'card_cvc' ? '3' : '16';
        const remove = line.querySelector('.remove-alias'); remove.setAttribute('aria-label', 'Remove alias ' + (index + 1));
        remove.addEventListener('click', () => {
            aliasRows = aliasRows.filter(r => r.key !== row.key); renderAliases(); renderCreation(); el('add-alias').focus();
        });
        container.append(line);
    }
    el('aliases-empty').hidden = !!aliasRows.length || !el('add-card-panel').hidden;
    if (focusKey !== undefined) el(`alias-${focusKey}-alias`)?.focus();
}

function adapterProblem() {
    const selected = el('adapter-select').value;
    if (!selected) return '';
    if (!adaptersLoaded) return 'The selected adapter could not be verified. Retry loading adapters or choose Automatic.';
    return adapters.some(a => a.id === selected) ? '' : 'This adapter is no longer available. Choose another adapter or Automatic.';
}
let adapterMenuOpen = false, adapterActive = 0, adapterMatches = [];
function renderAdapters() {
    const selected = el('adapter-select').value;
    const query = adapterMenuOpen ? el('adapter-search').value.trim().toLowerCase() : '';
    const options = [{id:'',name:'Automatic',description:'Match enabled connections across adapters'}, ...adapters.map(a => ({
        id:a.id,name:a.name+' · '+(a.owner==='vgs'?'Registered':'Custom'),description:a.id
    }))];
    adapterMatches = options.filter(a => (a.name+' '+a.description).toLowerCase().includes(query));
    adapterActive = Math.max(0,Math.min(adapterActive,adapterMatches.length-1));
    const list = el('adapter-options'); list.replaceChildren();list.hidden=!adapterMenuOpen;
    el('adapter-search').setAttribute('aria-expanded',String(adapterMenuOpen));
    if(!adapterMenuOpen) el('adapter-search').value=options.find(a=>a.id===selected)?.name || selected;
    for(const [index, option] of adapterMatches.entries()) {
        const row=document.createElement('div');row.id='adapter-option-'+index;row.setAttribute('role','option');
        row.setAttribute('aria-selected',String(index===adapterActive));row.textContent=option.name;
        const description=document.createElement('span');description.className='adapter-option-description';description.textContent=option.description;row.append(description);
        row.addEventListener('mousedown',event=>event.preventDefault());row.addEventListener('click',()=>chooseAdapter(option.id));list.append(row);
    }
    if(!adapterMatches.length){const empty=document.createElement('div');empty.className='adapter-empty';empty.textContent='No matching adapters';list.append(empty);}
    if(adapterMenuOpen && adapterMatches.length)el('adapter-search').setAttribute('aria-activedescendant','adapter-option-'+adapterActive);
    else el('adapter-search').removeAttribute('aria-activedescendant');
    const problem=adapterProblem();
    el('adapter-error').hidden=adaptersLoaded&&!problem;
    el('adapter-error').textContent=problem || (adaptersLoading?'Loading adapters…':'Adapters could not be loaded. Retry to choose a specific adapter, or use Automatic.');
    el('retry-adapters').hidden=adaptersLoaded||adaptersLoading;
    el('adapter-help').textContent=selected ? 'Only this adapter’s enabled destination connections can run. Each connection keeps its pinned version. Default search and replace and destination policies still apply.' : 'Automatic matches enabled destination connections across adapters. Default provides catch-all search and replace. Destination policies still control where data can be revealed.';
}
function chooseAdapter(id){el('adapter-select').value=id;adapterMenuOpen=false;renderAdapters();renderCreation();el('adapter-search').focus();}
function openAdapterMenu(){if(busy||creationRunning())return;adapterMenuOpen=true;adapterActive=0;el('adapter-search').value='';renderAdapters();}
async function loadAdapters() {
    adaptersLoading = true; renderAdapters();
    const environment = state.environment;
    const result = await request({type: 'getAdapters', environment});
    if (result && state.environment === environment) {
        adapters = result.adapters || []; adaptersLoaded = result.adaptersLoaded === true;
    }
    adaptersLoading = false; renderAdapters(); renderCreation();
}

function renderCreation() {
    const account = state.account || {};
    if (formEnvironment && formEnvironment !== state.environment && !creationRunning()) {
        formEnvironment = null; resetCreation(); return;
    }
    el('creation-tenant').textContent = account.tenantId || 'Not configured';
    const running = creationRunning();
    for (const field of el('create-form').elements) field.disabled = busy || running;
    for (const id of ['back-create', 'cancel-create', 'cancel-card']) el(id).disabled = running;
    for (const nav of document.querySelectorAll('[data-view], #environment-shortcut')) nav.disabled = running;
    el('add-card').disabled = busy || running || !el('add-card-panel').hidden || aliasRows.length > 18;
    el('add-alias').disabled = busy || running || !el('add-card-panel').hidden || aliasRows.length >= 20;
    el('create-aliases').disabled = busy || running || !collectCard.ready;
    el('create-aliases').textContent = collectCard.submitting ? 'Creating aliases…' : 'Create aliases';
    collectCard.render();
    el('create-session').disabled = busy || running || !account.creationAvailable || !el('add-card-panel').hidden || !!adapterProblem();
    el('create-session').textContent = operation?.status === 'running' ? 'Creating session…' : operation?.status === 'unknown' ? 'Check creation status' : 'Create session';
    const profile = !!account.egressConfig;
    el('egress-type').disabled = busy || running || profile;
    el('egress-type').querySelector('[value=profile]').hidden = !profile;
    if (profile) el('egress-type').value = 'profile';
    el('egress-fields').hidden = el('egress-type').value !== 'custom';
    for (const input of el('egress-fields').querySelectorAll('input,select')) {
        input.disabled = busy || running || profile;
    }
    el('egress-help').textContent = profile ? 'Uses your saved proxy configuration.' : '';
    el('aliases-empty').hidden = !!aliasRows.length || !el('add-card-panel').hidden;
}

function collectOptions() {
    if (!aliasRows.length) throw new Error('Add at least one alias.');
    const aliases = aliasRows.map((row, index) => {
        const alias = row.alias.trim(), format = row.format;
        const result = {alias, format, storage: row.storage};
        if (format === 'card_number') {
            if (!/^\d{6}(?:\d{2})?$/.test(row.bin.trim())) throw new Error(`Alias ${index + 1}: enter a 6 or 8 digit BIN.`);
            if (row.storage !== 'PERSISTENT') throw new Error('Card number aliases must use Persistent storage.');
            result.bin = row.bin.trim();
        }
        if (format === 'card_cvc' && row.storage !== 'VOLATILE') throw new Error('Security code aliases must use Volatile storage.');
        if (format !== 'text' && row.length.trim()) {
            if (!/^\d+$/.test(row.length.trim())) throw new Error(`Alias ${index + 1}: the length must be a whole number.`);
            result.length = Number(row.length.trim());
        }
        return result;
    });
    const formats = new Set(aliases.map(a => a.format));
    if (formats.has('card_number') !== formats.has('card_cvc')) throw new Error('Include both card number and security code aliases.');
    const hosts = splitEntries(el('allowed-hosts').value.toLowerCase()), cidrs = splitEntries(el('allowed-client-cidrs').value);
    if (hosts.length > 20) throw new Error('At most 20 allowed hosts.');
    if (hosts.some(h => /[:/\*]/.test(h))) throw new Error('Allowed hosts are exact host names, without https://, a port, a path or a wildcard.');
    if (cidrs.length > 10) throw new Error('At most 10 client address ranges.');
    const options = {aliases, allowedHosts: hosts, allowedClientCidrs: cidrs, adapter: el('adapter-select').value, egressMode: el('egress-type').value};
    if (options.egressMode === 'custom') {
        const hostname = el('egress-hostname').value.trim(), portText = el('egress-port').value.trim();
        const username = el('egress-username').value, password = el('egress-password').value;
        if (!hostname || /[:/\s]/.test(hostname)) throw new Error('Egress proxy: enter a host name without https://, port or path.');
        if (!/^\d+$/.test(portText) || Number(portText) < 1 || Number(portText) > 65535) throw new Error('Egress proxy: the port must be 1 to 65535.');
        if (!!username !== !!password || username.includes(':')) throw new Error('Egress proxy: enter a user name without a colon and its password together, or neither.');
        options.egress = {type:'custom', scheme:el('egress-scheme').value, hostname, port:Number(portText), ...(username ? {username,password} : {})};
    }
    return options;
}

function renderOperation(value) {
    operation = value;
    const label = el('creation-status');
    if (value.status === 'running') {
        label.textContent = `Creating in ${environmentLabel(value.environment || creationEnvironment)}. Your current session stays selected.`;
        clearTimeout(operationTimer);
        operationTimer = setTimeout(() => request({type:'creationStatus',requestId:value.requestId,environment:value.environment || creationEnvironment}),1000);
    } else if (value.status === 'complete') {
        label.textContent = 'Created. Return to sessions and choose Use selected session to switch.';
        el('created-session').hidden = (value.environment || creationEnvironment) !== state.environment;
        el('created-session-id').textContent = value.sessionId;
        const tokens = el('session-tokens'); tokens.replaceChildren();
        for (const token of value.tokens || []) {
            const dt = document.createElement('dt'), dd = document.createElement('dd');
            dt.textContent = token.format + ' stand-in'; dd.textContent = token.value; tokens.append(dt,dd);
        }
        creationId = null; sessionStorage.removeItem('creationId'); sessionStorage.removeItem('creationEnvironment');
        el('egress-password').value = ''; renderedSessions = '';
        if ((value.environment || creationEnvironment) === state.environment) setTimeout(async () => {
            await request({type:'refreshSessions'}); sessionSelect.value=value.sessionId; render();
        },0);
    } else {
        label.textContent = value.error || 'Creation did not complete.';
        if (value.status === 'failed') { creationId=null; sessionStorage.removeItem('creationId');sessionStorage.removeItem('creationEnvironment'); }
    }
}
function renderCardOperation(value) {
    cardOperation = value;
    if (value.status === 'running') {
        el('card-notice').textContent = 'Creating card number and security code aliases…';
        clearTimeout(cardTimer); cardTimer=setTimeout(() => request({type:'cardStatus',requestId:value.requestId,environment:value.environment || cardEnvironment}),1000);
    } else if (value.status === 'complete') {
        if ((value.environment || cardEnvironment) === state.environment) {
            const formats = new Set((value.aliases || []).map(a=>a.format));
            if (!formats.has('card_number') || !formats.has('card_cvc')) {
                el('card-notice').textContent='Both aliases are required. The card was not added.';
            } else {
                for (const a of value.aliases.filter(a => !aliasRows.some(row => row.alias === a.alias))) aliasRows.push({key:nextAliasKey++,alias:a.alias,format:a.format,storage:a.storage,bin:a.bin || '',length:String(a.length || '')});
                el('add-card-panel').hidden=true; renderAliases(aliasRows.at(-2)?.key);
                el('card-notice').textContent='Aliases ready. Security code aliases expire; create your session soon.';
            }
        }
        cardRequestId=null;sessionStorage.removeItem('cardRequestId');sessionStorage.removeItem('cardEnvironment');
    } else {
        el('card-notice').textContent=value.error || 'Card aliases were not created.';
        if(value.status==='failed'){cardRequestId=null;sessionStorage.removeItem('cardRequestId');sessionStorage.removeItem('cardEnvironment');}
    }
}

el('open-create').addEventListener('click', async () => {
    if (!state.account?.creationAvailable) { showView('settings'); el('account-file').focus(); return; }
    resetCreation(); showView('create'); el('create-title').focus(); await loadAdapters();
});
for(const id of ['back-create','cancel-create','created-back']) el(id).addEventListener('click',()=>{
    if(creationRunning())return;
    resetCreation();showView('controls');el('open-create').focus();
});
el('add-alias').addEventListener('click',()=>{
    if(aliasRows.length>=20)return;
    const key=nextAliasKey++,format=aliasRows.length===1?'card_cvc':'card_number';
    aliasRows.push({key,alias:'',format,bin:'',length:'',storage:format==='card_cvc'?'VOLATILE':'PERSISTENT'});
    renderAliases(key);renderCreation();
});
async function openCollectCard() {
    el('add-card-panel').hidden=false; el('card-notice').textContent=''; renderCreation();
    await collectCard.open(state.environment,state.account || {},renderCreation);
}
el('add-card').addEventListener('click',openCollectCard);
el('retry-collect').addEventListener('click',openCollectCard);
el('cancel-card').addEventListener('click',()=>{collectCard.reset();el('add-card-panel').hidden=true;renderCreation();el('add-card').focus();});
el('create-aliases').addEventListener('click',async()=>{
    if(busy||creationRunning())return;
    try {
        const result = await collectCard.submit();
        if (result.environment !== state.environment || result.tenantId !== state.account?.tenantId) throw new Error('The selected account changed. Add the card again.');
        renderCardOperation({...result,status:'complete'});
    } catch (error) {
        el('card-notice').textContent=error.message;
        el('add-card-panel').hidden=true; el('add-card').focus();
    }
    renderCreation();
});
el('retry-adapters').addEventListener('click',loadAdapters);
el('adapter-search').addEventListener('click',()=>{if(!adapterMenuOpen)openAdapterMenu();});
el('adapter-search').addEventListener('input',()=>{adapterMenuOpen=true;adapterActive=0;renderAdapters();});
el('adapter-search').addEventListener('blur',()=>{adapterMenuOpen=false;renderAdapters();});
el('adapter-search').addEventListener('keydown',event=>{
    if(['ArrowDown','ArrowUp'].includes(event.key)){
        event.preventDefault();if(!adapterMenuOpen){openAdapterMenu();return;}
        adapterActive=Math.max(0,Math.min(adapterMatches.length-1,adapterActive+(event.key==='ArrowDown'?1:-1)));renderAdapters();
    }else if(event.key==='Enter'&&adapterMenuOpen){event.preventDefault();if(adapterMatches[adapterActive])chooseAdapter(adapterMatches[adapterActive].id);}
    else if(event.key==='Escape'&&adapterMenuOpen){event.preventDefault();adapterMenuOpen=false;renderAdapters();}
});
el('egress-type').addEventListener('change',renderCreation);
el('create-form').addEventListener('submit',event=>{
    event.preventDefault();if(busy||creationRunning())return;
    if(creationId){request({type:'creationStatus',requestId:creationId,environment:creationEnvironment});return;}
    try{
        const options=collectOptions();el('form-error').hidden=true;
        creationId=crypto.randomUUID();creationEnvironment=state.environment;
        sessionStorage.setItem('creationId',creationId);sessionStorage.setItem('creationEnvironment',creationEnvironment);
        request({type:'createSession',environment:creationEnvironment,options:{...options,requestId:creationId}});
    }catch(error){el('form-error').textContent=error.message;el('form-error').hidden=false;}
});
if(creationId)setTimeout(()=>request({type:'creationStatus',requestId:creationId,environment:creationEnvironment}),1000);
if(cardRequestId)setTimeout(()=>request({type:'cardStatus',requestId:cardRequestId,environment:cardEnvironment}),1000);

function handleCreationTransportFailure(message) {
    const value = {status:'unknown',requestId:message.requestId || message.options?.requestId,environment:message.environment,
        error:'The helper did not confirm the result. Check its status before starting another request.'};
    if(['createCard','cardStatus'].includes(message.type))renderCardOperation(value);
    if(['createSession','creationStatus'].includes(message.type))renderOperation(value);
}
