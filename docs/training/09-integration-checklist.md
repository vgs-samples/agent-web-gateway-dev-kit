# 9. Integration checklist

**When you finish this page you can** check your integration before it goes live.

Go through the four lists in order. Each item is one thing to confirm.

## 1. Before the first session

- [ ] The card is stored in the vault, and your systems keep only its aliases.
- [ ] The service account has the scopes the integration uses. Write scopes do not include read.
- [ ] The tenant is enabled for Agent Web Gateway.
- [ ] You know the tenant's unlisted-host mode and its session lifetime. Neither can be set per session.
- [ ] For each merchant, you know which host receives the card, and whether the card is sent plain or encrypted in the browser.
- [ ] If it is encrypted in the browser, an adapter exists and has been tested (page 5).

## 2. For each agent task

- [ ] One session per task, created when the agent is about to pay.
- [ ] `allowed_hosts` lists exact host names, including the payment provider's host.
- [ ] `proxy.url`, the PAC link and the session tokens go straight to the browser and the agent, and are not logged.
- [ ] The agent receives session tokens only. Never vault aliases, never card data.

## 3. The browser

- [ ] Full Chromium or Chrome, not Playwright's default headless browser.
- [ ] A persistent browser context.
- [ ] The proxy's login prompt (`407`) is answered with the session id and the password from `proxy.url`.
- [ ] The session's CA is trusted for the hosts that go through VGS.
- [ ] A person handles 3-D Secure challenges and CAPTCHAs.

## 4. After the task

- [ ] The session is ended when the task is done (`DELETE /reveal-sessions/{id}`).
- [ ] `reveal_count` is checked. If the checkout request went through and it is still `0`, the merchant got the stand-in card.
- [ ] The payment request's `vgs-request-id` is kept. It is the key to the logs.

## Questions to raise with VGS

Ask your VGS contact about these before you go live:

- **PCI DSS scope** for your integration.
- **Hosted browser platforms** you plan to use.
- **3-D Secure.** A person must complete any challenge; ask how your flow should handle it.

---

## Details

**Optional settings worth raising**

- `allowed_client_cidrs`, when the agent's addresses are known. Requests from other addresses are then refused.
- `egress_proxy_settings`, when the merchant should see one IP for VGS-routed and direct traffic, for example a residential provider's.

**Recommendations.** These two are this page's advice, not statements from a source: give the service account no more scopes than it uses, and list no host the task does not need.

**More on the items above**

- **Tenant not enabled.** If a fresh session gets `407` with the correct password, and other sessions of the tenant fail the same way, the tenant may not be enabled; contact VGS support.
- **Unlisted-host modes** are `strict`, `guarded` and `step_up` (page 2).
- **Finding the card-bearing request.** From a capture of the real checkout (`skills/vgs-checkout-adapter/references/har-review.md`).
- **Adapter testing.** A dry run and, for Adyen, the level 2 harness. The harness covers Adyen only today.
- **Words.** Some VGS documents call session tokens "aliases" or "session aliases" in places; they mean the per-session values.
- **Why full Chromium.** Playwright's default headless shell ignores `--proxy-pac-url`. A new context does not inherit the command-line PAC.
- **Certificates.** Prefer trusting the CA to disabling certificate checks. The session kit's launcher trusts only the VGS CA, and keeps `--insecure` as a diagnostic fallback.
- **`reveal_count`.** A rising count shows a reveal, not the merchant's acceptance.

**Launching the browser with Playwright.** The developer guide's example, unchanged:

```javascript
import { chromium } from '@playwright/test';

const session = /* POST /reveal-sessions response */.data.attributes;
const proxy = new URL(session.proxy.url);

// a persistent context is the default profile, which the command-line PAC applies to
const context = await chromium.launchPersistentContext(profileDir, {
  channel: 'chromium',
  args: [`--proxy-pac-url=${session.proxy.pac_url}`],
});
const page = context.pages()[0] ?? await context.newPage();
const cdp = await context.newCDPSession(page);
await cdp.send('Fetch.enable', { handleAuthRequests: true, patterns: [{ urlPattern: '*' }] });
cdp.on('Fetch.requestPaused', e => cdp.send('Fetch.continueRequest', { requestId: e.requestId }));
cdp.on('Fetch.authRequired', e => cdp.send('Fetch.continueWithAuth', {
  requestId: e.requestId,
  authChallengeResponse: e.authChallenge.source === 'Proxy'
    ? { response: 'ProvideCredentials',
        username: decodeURIComponent(proxy.username),
        password: decodeURIComponent(proxy.password) }
    : { response: 'CancelAuth' },
}));
```

