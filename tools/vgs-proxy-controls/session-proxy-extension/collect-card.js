// Only VGS-hosted iframes receive card values. This controller retains validation
// metadata and aliases; service-account secrets never leave the local helper.
const collectCard = (() => {
    // Public fixtures shared with the dashboard's sessions/cardForm.ts.
    const testCards = Object.freeze({visa4242:'4242424242424242',visa4111:'4111111111111111',mastercard5454:'5454545454545454'});
    const libraries = new Map();
    let form, fields = [], generation = 0, loaded = false, submitting = false;
    let metadata = {}, context, changed = () => {}, lengthsEdited = false, brand = '';
    let notice = '', mountTimer, cardAccount;
    // A card saved by the local helper: its ID, number alias, BIN and last four digits. Only its security code is entered again.
    let saved = null, savedCards = [], panField, cvcField;
    const node = id => document.getElementById(id);
    // The Cards API is the default; the vault alias API is only for accounts without a card scope.
    const method = account => !account?.connected ? null : account.cardsWriteGranted || account.scopes?.some(s => s.name === 'cards:create' && s.granted) ? 'card'
        : account.scopes?.some(s => s.name === 'aliases:write' && s.granted) ? 'aliases' : null;
    const allowed = account => !!method(account);
    const canUpdate = account => !!account?.connected && (account.cardsWriteGranted || account.scopes?.some(s => s.name === 'cards:update' && s.granted));
    const aliasPattern = environment => 'tok_' + {dev:'(?:dev|sandbox)',sandbox:'sandbox',live:'live'}[environment] + '_[A-Za-z0-9_]{8,200}';
    const valid = () => saved ? loaded && metadata.cvcValid === true
        : loaded && metadata.panValid && metadata.cvcValid && (context?.method !== 'card' || metadata.expiryValid) && /^\d{6}(?:\d{2})?$/.test(metadata.bin || '');
    function render() {
        node('collect-status').textContent = notice;
        node('retry-collect').hidden = loaded || submitting || !notice.includes('could not load');
        node('add-card-panel').setAttribute('aria-busy', String(submitting));
        for (const container of document.querySelectorAll('.collect-field')) container.inert = submitting;
        const canUseTestCards = ['dev','sandbox'].includes(context?.environment) && allowed(cardAccount);
        node('collect-test-cards').hidden = !canUseTestCards;
        for (const button of node('collect-test-cards').querySelectorAll('button')) button.disabled = !canUseTestCards || !loaded || submitting;
        node('collect-saved-cards').hidden = !savedCards.length || !canUpdate(cardAccount);
        for (const button of node('collect-saved-cards').querySelectorAll('button')) button.disabled = !loaded || submitting;
    }
    function drawSaved() {
        const group = node('collect-saved-cards'), label = document.createElement('span');
        label.textContent = 'Saved cards'; group.replaceChildren(label);
        for (const card of savedCards) {
            const button = document.createElement('button'); button.type = 'button';
            button.textContent = card.last4 ? '•••• ' + card.last4 : 'BIN ' + card.bin;
            button.setAttribute('aria-pressed', String(saved?.cardId === card.cardId));
            button.addEventListener('click', () => {
                if (!loaded || submitting) return;
                void open(context.environment, cardAccount, changed, undefined, card);
            });
            group.append(button);
        }
        if (!saved) return;
        const forget = document.createElement('button'); forget.type = 'button'; forget.textContent = 'Forget this card';
        forget.addEventListener('click', async () => {
            if (!loaded || submitting) return;
            const environment = context.environment, account = cardAccount, onChange = changed;
            try { await chrome.runtime.sendMessage({type:'saveCard', environment, card:{remove:saved.cardId}}); } catch (_) { /* The list is read again below. */ }
            void open(environment, account, onChange);
        });
        group.append(forget);
    }
    async function loadSaved(current, environment) {
        if (!canUpdate(cardAccount)) return;
        try {
            const result = await chrome.runtime.sendMessage({type:'getSavedCards', environment});
            if (current !== generation || !result?.ok || !Array.isArray(result.cards)) return;
            savedCards = result.cards.filter(c => c && typeof c.cardId === 'string' && typeof c.alias === 'string' && typeof c.bin === 'string');
            drawSaved(); render();
        } catch (_) { /* Saved cards are a convenience; the form works without them. */ }
    }
    function reset() {
        generation++; clearTimeout(mountTimer);
        const previous = form; form = undefined; loaded = false; submitting = false; metadata = {}; fields = []; panField = cvcField = undefined;
        // Invalidate callbacks before unmount (which itself emits a state update).
        try { previous?.unmount(); } catch (_) { /* The DOM is cleared below. */ }
        node('collect-pan').replaceChildren(); node('collect-cvc').replaceChildren(); node('collect-expiry').replaceChildren();
        notice = ''; context = null; cardAccount = null; saved = null; savedCards = []; drawSaved(); render();
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
        panField?.update({validations: validations('pan')});
        cvcField?.update({validations: validations('cvc')});
        changed();
    }
    async function open(environment, account, onChange, testCard, savedCard) {
        if (testCard !== undefined && (!['dev','sandbox'].includes(environment) || !Object.hasOwn(testCards,testCard))) return;
        reset(); changed = onChange; cardAccount = account; saved = savedCard && canUpdate(account) ? savedCard : null;
        // A saved card is refreshed with Collect's updateCard: only its security code is collected.
        context = {environment, tenantId: account.tenantId, method: saved ? 'update' : method(account)};
        // Only these public test fixtures are ever passed as default values.
        // Human-entered values remain inside Collect's hosted fields.
        const defaults = testCard === undefined ? null : {pan:testCards[testCard],cvc:'123',expiry:`12/${String((new Date().getFullYear()+3)%100).padStart(2,'0')}`};
        const prefill = kind => defaults ? {defaultValue:defaults[kind]} : {};
        node('collect-expiry-row').hidden = context.method !== 'card';
        node('collect-pan').parentElement.hidden = !!saved;
        lengthsEdited = false; brand = ''; node('collect-pan-length').value = '16'; node('collect-cvc-length').value = '3';
        if (saved) { lengthsEdited = true; node('collect-pan-length').value = String(saved.length); node('collect-cvc-length').value = String(saved.cvcLength); }
        node('collect-lengths').open = false;
        drawSaved();
        if (!allowed(account)) { notice = 'Connect a service account with cards:write, cards:create, or aliases:write in Settings to add a card.'; render(); changed(); return; }
        const current = generation;
        notice = 'Loading VGS secure fields…'; render(); changed();
        void loadSaved(current, environment);
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
                if (!lengthsEdited && pan.cardType && pan.cardType !== brand && panField && cvcField) {
                    brand = pan.cardType;
                    node('collect-pan-length').value = brand === 'amex' ? '15' : brand === 'dinersclub' ? '14' : '16';
                    node('collect-cvc-length').value = brand === 'amex' ? '4' : '3';
                    updateLengths(); return;
                }
                if (loaded && !submitting) {
                    notice = valid() ? 'Ready to create aliases.' : (pan.isTouched || cvc.isTouched)
                        ? 'Check the card details. For a different number of digits, adjust Card lengths.'
                        : saved ? 'Enter the security code for the saved card.' : 'Enter your card details in the secure fields.';
                }
                render(); changed();
            });
            const css = {fontFamily:'Arial, sans-serif',fontSize:'16px',color:'#071f62',padding:'14px',boxSizing:'border-box',width:'100%',height:'100%','::placeholder':{color:'#65728c'}};
            if (!saved) panField = form.field('#collect-pan', {type:'card-number',name:context.method === 'card' ? 'pan' : 'card_number',placeholder:'Card number',iframeTitle:'Secure card number input',autoComplete:'off',hideValue:false,validations:validations('pan'),css,...prefill('pan'),
                tokenization:{format:'UUID',storage:'PERSISTENT'}});
            cvcField = form.field('#collect-cvc', {type:'card-security-code',name:context.method === 'aliases' ? 'card_cvc' : 'cvc',placeholder:'CVC / CVV',iframeTitle:'Secure security code input',autoComplete:'off',hideValue:false,validations:validations('cvc'),css,...prefill('cvc'),
                tokenization:{format:'UUID',storage:'VOLATILE'}});
            fields = [panField, cvcField].filter(Boolean);
            if (context.method === 'card') fields.push(form.field('#collect-expiry', {type:'card-expiration-date',name:'exp-date',placeholder:'MM / YY',iframeTitle:'Secure expiry input',autoComplete:'off',validations:['required','validCardExpirationDate'],css,...prefill('expiry')}));
            await Promise.all(fields.map(field => field.promise));
            if (current !== generation) return;
            clearTimeout(mountTimer); loaded = true;
            notice = saved ? 'Enter the security code for the saved card.' : 'Enter your card details in the secure fields.'; render(); changed();
        } catch (_) {
            if (current !== generation) return;
            reset(); notice = 'VGS secure fields could not load. Check the connection and proxy settings, then retry.'; render(); changed();
        }
    }
    async function submit() {
        if (!valid() || submitting) throw new Error('Check both secure fields before creating aliases.');
        const current = generation, selected = {...context}, card = saved;
        const bin = card ? card.bin : metadata.bin, panLength = Number(node('collect-pan-length').value), cvcLength = Number(node('collect-cvc-length').value);
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
                    if (card) form.updateCard({cardId:card.cardId,auth:authorization.accessToken},finish,failure);
                    else if (selected.method === 'card') form.createCard({auth:authorization.accessToken,data:{cardholder:{}}},finish,failure);
                    else form.createAliases({access_token:authorization.accessToken},finish,failure);
                } catch (_) { clearTimeout(timer); reject(new Error('VGS could not create aliases. Add the card again to retry.')); }

            });
            authorization = null;
            if (current !== generation) throw new Error('The selected account changed. Add the card again.');
            const pattern = new RegExp('^' + aliasPattern(selected.environment) + '$');
            const attributes = selected.method === 'aliases' ? null : response?.data?.attributes;
            const panAlias = card ? card.alias : attributes ? attributes.pan_alias : response?.card_number;
            const cvcAlias = attributes ? attributes.cvc_alias : response?.card_cvc;
            const returnedTenant = response?.metadata?.observability?.vault_id;
            if (returnedTenant && returnedTenant !== selected.tenantId) throw new Error('VGS returned a different vault. The card was not added.');
            if (card && !attributes?.cvc_alias)
                throw new Error('VGS did not return a fresh security-code alias for the saved card. The card was not added.');
            if (selected.method === 'card' && attributes?.pan_alias && !attributes.cvc_alias)
                throw new Error('VGS returned an existing card without a fresh security-code alias. The card was not added.');
            // The Cards API answers with format-preserving aliases: digits, the same length as the card number and the code.
            // They are accepted only together with the card ID VGS returned, which the helper checks before using them.
            const cardId = card ? card.cardId : attributes && typeof response?.data?.id === 'string' ? response.data.id : undefined;
            const panOk = typeof panAlias === 'string' && (pattern.test(panAlias) || (!!cardId && /^\d{13,19}$/.test(panAlias)));
            const cvcOk = typeof cvcAlias === 'string' && (pattern.test(cvcAlias) || (!!cardId && /^\d{3,4}$/.test(cvcAlias)));
            if (!panOk || !cvcOk || panAlias === cvcAlias)
                throw new Error('VGS did not return both expected aliases. The card was not added.');
            const digits = /^\d+$/.test(panAlias);
            // Keep the new card for later sessions. Saving is local and best-effort; the aliases are returned either way.
            const length = digits ? panAlias.length : panLength, codeLength = /^\d+$/.test(cvcAlias) ? cvcAlias.length : cvcLength;
            if (selected.method === 'card' && cardId)
                chrome.runtime.sendMessage({type:'saveCard', environment:selected.environment, card:{cardId, alias:panAlias, bin, length, cvcLength:codeLength,
                    last4:/^\d{4}$/.test(attributes.last4 || '') ? attributes.last4 : ''}}).catch(() => {});
            const source = cardId ? {cardId} : {};
            return {environment:selected.environment, tenantId:selected.tenantId, aliases:[
                {alias:panAlias,format:'card_number',storage:'PERSISTENT',bin,length,...source},
                {alias:cvcAlias,format:'card_cvc',storage:'VOLATILE',length:codeLength,...source}]};

        } finally { reset(); changed(); }
    }
    for (const id of ['collect-pan-length','collect-cvc-length']) node(id).addEventListener('change',()=>{lengthsEdited=true;updateLengths();});
    for (const button of node('collect-test-cards').querySelectorAll('button')) button.addEventListener('click',()=>{
        if (!loaded || submitting || !['dev','sandbox'].includes(context?.environment)) return;
        void open(context.environment,cardAccount,changed,button.dataset.testCard);
    });
    return {open, reset, submit, allowed, aliasPattern, get ready(){return valid();}, get submitting(){return submitting;}, render};
})();
