// Only VGS-hosted iframes receive card values. This controller retains validation
// metadata and aliases; service-account secrets never leave the local helper.
const collectCard = (() => {
    // Public fixtures shared with the dashboard's sessions/cardForm.ts.
    const testCards = Object.freeze({visa4242:'4242424242424242',visa4111:'4111111111111111',mastercard5454:'5454545454545454'});
    const libraries = new Map();
    let form, fields = [], generation = 0, loaded = false, submitting = false;
    let metadata = {}, context, changed = () => {}, lengthsEdited = false, brand = '';
    let notice = '', mountTimer, cardAccount;
    const node = id => document.getElementById(id);
    const method = account => !account?.connected ? null : account.scopes?.some(s => s.name === 'aliases:write' && s.granted) ? 'aliases'
        : account.cardsWriteGranted || account.scopes?.some(s => s.name === 'cards:create' && s.granted) ? 'card' : null;
    const allowed = account => !!method(account);
    const aliasPattern = environment => 'tok_' + {dev:'(?:dev|sandbox)',sandbox:'sandbox',live:'live'}[environment] + '_[A-Za-z0-9_]{8,200}';
    const valid = () => loaded && metadata.panValid && metadata.cvcValid && (context?.method !== 'card' || metadata.expiryValid) && /^\d{6}(?:\d{2})?$/.test(metadata.bin || '');
    function render() {
        node('collect-status').textContent = notice;
        node('retry-collect').hidden = loaded || submitting || !notice.includes('could not load');
        node('add-card-panel').setAttribute('aria-busy', String(submitting));
        for (const container of document.querySelectorAll('.collect-field')) container.inert = submitting;
        const canUseTestCards = ['dev','sandbox'].includes(context?.environment) && allowed(cardAccount);
        node('collect-test-cards').hidden = !canUseTestCards;
        for (const button of node('collect-test-cards').querySelectorAll('button')) button.disabled = !canUseTestCards || !loaded || submitting;
    }
    function reset() {
        generation++; clearTimeout(mountTimer);
        const previous = form; form = undefined; loaded = false; submitting = false; metadata = {}; fields = [];
        // Invalidate callbacks before unmount (which itself emits a state update).
        try { previous?.unmount(); } catch (_) { /* The DOM is cleared below. */ }
        node('collect-pan').replaceChildren(); node('collect-cvc').replaceChildren(); node('collect-expiry').replaceChildren();
        notice = ''; context = null; cardAccount = null; render();
    }
    async function library(environment) {
        const key = environment === 'dev' ? 'dev' : 'public';
        if (!libraries.has(key)) libraries.set(key, new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = chrome.runtime.getURL('vendor/' + (key === 'dev' ? 'vgs-collect-dev-4.0.1.js' : 'vgs-collect-4.0.1.js'));
            script.onload = () => { const sdk = globalThis.VGSCollect; sdk.logLevel('none'); resolve(sdk); };
            script.onerror = () => { libraries.delete(key); script.remove(); reject(new Error('SDK unavailable')); };
            document.head.append(script);
        }));
        return libraries.get(key);
    }
    function validations(kind) {
        const digits = Number(node('collect-' + kind + '-length').value);
        return ['required', kind === 'pan' ? 'validCardNumber' : 'validCardSecurityCode',
            '/^(?:\\d\\s*){' + digits + '}$/'];
    }
    function updateLengths() {
        metadata.panValid = metadata.cvcValid = false;
        fields[0]?.update({validations: validations('pan')});
        fields[1]?.update({validations: validations('cvc')});
        changed();
    }
    async function open(environment, account, onChange, testCard) {
        if (testCard !== undefined && (!['dev','sandbox'].includes(environment) || !Object.hasOwn(testCards,testCard))) return;
        reset(); changed = onChange; cardAccount = account; context = {environment, tenantId: account.tenantId, method:method(account)};
        // Only these public test fixtures are ever passed as default values.
        // Human-entered values remain inside Collect's hosted fields.
        const defaults = testCard === undefined ? null : {pan:testCards[testCard],cvc:'123',expiry:`12/${String((new Date().getFullYear()+3)%100).padStart(2,'0')}`};
        const prefill = kind => defaults ? {defaultValue:defaults[kind]} : {};
        node('collect-expiry-row').hidden = context.method !== 'card';
        lengthsEdited = false; brand = ''; node('collect-pan-length').value = '16'; node('collect-cvc-length').value = '3';
        node('collect-lengths').open = false;
        if (!allowed(account)) { notice = 'Connect a service account with cards:write, cards:create, or aliases:write in Settings to add a card.'; render(); changed(); return; }
        const current = generation;
        notice = 'Loading VGS secure fields…'; render(); changed();
        mountTimer = setTimeout(() => {
            if (current !== generation || loaded) return;
            reset(); notice = 'VGS secure fields could not load. Check the connection and proxy settings, then retry.'; render(); changed();
        }, 25000);
        try {
            const sdk = await library(environment);
            if (current !== generation) return;
            form = sdk.create(account.tenantId, environment === 'live' ? 'live' : 'sandbox', fieldState => {
                if (current !== generation) return;
                const pan = fieldState.card_number || fieldState.pan || {}, cvc = fieldState.card_cvc || fieldState.cvc || {}, expiry = fieldState['exp-date'] || {};
                // Copy an explicit allowlist, never the whole field state.
                metadata = {panValid: pan.isValid === true, cvcValid: cvc.isValid === true, expiryValid:expiry.isValid === true,
                    bin: typeof pan.bin === 'string' && /^\d{6}(?:\d{2})?$/.test(pan.bin) ? pan.bin : ''};
                if (!lengthsEdited && pan.cardType && pan.cardType !== brand && fields.length >= 2) {
                    brand = pan.cardType;
                    node('collect-pan-length').value = brand === 'amex' ? '15' : brand === 'dinersclub' ? '14' : '16';
                    node('collect-cvc-length').value = brand === 'amex' ? '4' : '3';
                    updateLengths(); return;
                }
                if (loaded && !submitting) {
                    notice = valid() ? 'Ready to create aliases.' : (pan.isTouched || cvc.isTouched)
                        ? 'Check the card details. For a different number of digits, adjust Card lengths.' : 'Enter your card details in the secure fields.';
                }
                render(); changed();
            });
            const css = {fontFamily:'Arial, sans-serif',fontSize:'16px',color:'#071f62',padding:'14px',boxSizing:'border-box',width:'100%',height:'100%','::placeholder':{color:'#65728c'}};
            fields = [form.field('#collect-pan', {type:'card-number',name:context.method === 'card' ? 'pan' : 'card_number',placeholder:'Card number',iframeTitle:'Secure card number input',autoComplete:'off',hideValue:false,validations:validations('pan'),css,...prefill('pan'),
                tokenization:{format:'UUID',storage:'PERSISTENT'}}),
            form.field('#collect-cvc', {type:'card-security-code',name:context.method === 'card' ? 'cvc' : 'card_cvc',placeholder:'CVC / CVV',iframeTitle:'Secure security code input',autoComplete:'off',hideValue:false,validations:validations('cvc'),css,...prefill('cvc'),
                tokenization:{format:'UUID',storage:'VOLATILE'}})];
            if (context.method === 'card') fields.push(form.field('#collect-expiry', {type:'card-expiration-date',name:'exp-date',placeholder:'MM / YY',iframeTitle:'Secure expiry input',autoComplete:'off',validations:['required','validCardExpirationDate'],css,...prefill('expiry')}));
            await Promise.all(fields.map(field => field.promise));
            if (current !== generation) return;
            clearTimeout(mountTimer); loaded = true; notice = 'Enter your card details in the secure fields.'; render(); changed();
        } catch (_) {
            if (current !== generation) return;
            reset(); notice = 'VGS secure fields could not load. Check the connection and proxy settings, then retry.'; render(); changed();
        }
    }
    async function submit() {
        if (!valid() || submitting) throw new Error('Check both secure fields before creating aliases.');
        const current = generation, selected = {...context};
        const bin = metadata.bin, panLength = Number(node('collect-pan-length').value), cvcLength = Number(node('collect-cvc-length').value);
        submitting = true; notice = 'Creating aliases with VGS…'; render(); changed();
        try {
            // Do not use popup.request(): its responses become shared panel state.
            let authorization = await chrome.runtime.sendMessage({type:'getCollectToken', ...selected});
            if (current !== generation) throw new Error('The selected account changed. Add the card again.');
            if (!authorization?.ok || authorization.environment !== selected.environment || authorization.tenantId !== selected.tenantId || authorization.method !== selected.method || typeof authorization.accessToken !== 'string')
                throw new Error('Authorization failed. Reconnect the service account in Settings and check card or alias creation permission.');
            const response = await new Promise((resolve, reject) => {
                const timer = setTimeout(() => reject(new Error('VGS did not confirm alias creation. Add the card again to retry.')), 35000);
                const finish = (status, result) => {
                    clearTimeout(timer);
                    if ((Number(status) >= 200 && Number(status) < 300) || (selected.method === 'card' && Number(status) === 303)) resolve(result);
                    else reject(new Error('VGS could not create aliases. Check the account permissions and connection, then add the card again.'));
                };
                const failure = () => {
                    clearTimeout(timer); reject(new Error('VGS could not create aliases. Check the secure fields and account permissions, then add the card again.'));
                };
                try {
                    if (selected.method === 'card') form.createCard({auth:authorization.accessToken,data:{cardholder:{}}},finish,failure);
                    else form.createAliases({access_token:authorization.accessToken},finish,failure);
                } catch (_) { clearTimeout(timer); reject(new Error('VGS could not create aliases. Add the card again to retry.')); }

            });
            authorization = null;
            if (current !== generation) throw new Error('The selected account changed. Add the card again.');
            const pattern = new RegExp('^' + aliasPattern(selected.environment) + '$');
            const attributes = selected.method === 'card' ? response?.data?.attributes : null;
            const panAlias = attributes ? attributes.pan_alias : response?.card_number;
            const cvcAlias = attributes ? attributes.cvc_alias : response?.card_cvc;
            const returnedTenant = response?.metadata?.observability?.vault_id;
            if (returnedTenant && returnedTenant !== selected.tenantId) throw new Error('VGS returned a different vault. The card was not added.');
            if (selected.method === 'card' && attributes?.pan_alias && !attributes.cvc_alias)
                throw new Error('VGS returned an existing card without a fresh security-code alias. Connect an account with aliases:write to create both aliases.');
            if (typeof panAlias !== 'string' || typeof cvcAlias !== 'string' || !pattern.test(panAlias) || !pattern.test(cvcAlias) || panAlias === cvcAlias)
                throw new Error('VGS did not return both expected aliases. The card was not added.');
            return {environment:selected.environment, tenantId:selected.tenantId, aliases:[
                {alias:panAlias,format:'card_number',storage:'PERSISTENT',bin,length:panLength},
                {alias:cvcAlias,format:'card_cvc',storage:'VOLATILE',length:cvcLength}]};

        } finally { reset(); changed(); }
    }
    for (const id of ['collect-pan-length','collect-cvc-length']) node(id).addEventListener('change',()=>{lengthsEdited=true;updateLengths();});
    for (const button of node('collect-test-cards').querySelectorAll('button')) button.addEventListener('click',()=>{
        if (!loaded || submitting || !['dev','sandbox'].includes(context?.environment)) return;
        void open(context.environment,cardAccount,changed,button.dataset.testCard);
    });
    return {open, reset, submit, allowed, aliasPattern, get ready(){return valid();}, get submitting(){return submitting;}, render};
})();
