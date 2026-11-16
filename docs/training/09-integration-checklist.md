# 9. Integration checklist

Use this when you design or review a customer's integration. Each item is drawn from the sources in this repository; the source is named at the end of the line. Items marked "recommendation" are this page's advice, not a statement from a source.

## Before the first session

- [ ] The card is stored in the vault, and the customer's systems keep only its aliases. (Developer guide, Overview)
- [ ] The service account has the scopes the integration uses. Write scopes do not include read. (Developer guide, API reference) Give it no more than that. (Recommendation)
- [ ] The vault is enabled for AWG. If a fresh session gets `407` with the correct password, and other sessions of the vault fail the same way, the vault may not be enabled; escalate. (Runbook)
- [ ] You know the vault's unlisted-host mode (`strict`, `guarded` or `step_up`) and its session lifetime. Neither can be set per session. (Developer guide, Reveal sessions)
- [ ] For each merchant, you know from a capture of the real checkout which host receives the card and whether the card is sent plain or encrypted in the browser. (Skill, `har-review.md`)
- [ ] If the card is encrypted in the browser, an adapter exists and has passed a dry run and, for Adyen, the level 2 harness. The harness covers Adyen only today. (Page 5; `adapters/README.md`)

## Each agent task

- [ ] Create one session per task, when the agent is about to pay. (Developer guide, Reveal sessions; October doc set, Security notes)
- [ ] `allowed_hosts` lists exact host names, including the payment provider's host. (Developer guide; `adapters/README.md`) List nothing the task does not need. (Recommendation)
- [ ] Consider `allowed_client_cidrs` when the agent's addresses are known; requests from other addresses are then refused. (Developer guide)
- [ ] Set `egress_proxy_settings` when the merchant should see one IP for VGS-routed and direct traffic, for example a residential provider's. (Engineering spec, Egress)
- [ ] Pass `proxy.url`, the PAC link and the session tokens straight to the browser and the agent. Do not log them; they are returned once. (Developer guide; October doc set, Security notes)
- [ ] The agent receives session tokens only, never vault aliases or card data. The reference docs call session tokens "aliases" or "session aliases" in places; they mean the per-session values. (Page 2; skill `SKILL.md`)

## The browser

- [ ] A full Chromium or Chrome, not Playwright's default headless shell, which ignores `--proxy-pac-url`. (Developer guide, PAC)
- [ ] A persistent context, because a new context does not inherit the command-line PAC. (Runbook)
- [ ] The proxy's `407` is answered with the session id and the password from `proxy.url`. (Developer guide, PAC)
- [ ] The session's CA is trusted for the hosts that go through VGS. (Developer guide) Prefer that to disabling certificate checks: the kit's launcher trusts only the VGS CA, and keeps `--insecure` as a diagnostic fallback. (`launch-chromium.sh`)
- [ ] A human handles 3-D Secure challenges and CAPTCHAs. (`AGENTS.md`)

The developer guide's Playwright example, unchanged:

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

## After the task

- [ ] End the session when the task is done (`DELETE /reveal-sessions/{id}`). (Developer guide, Quickstart)
- [ ] Check `reveal_count` and `refusal_count`. If the checkout request went through and `reveal_count` is still `0`, it went out with the stand-in card. (Runbook)
- [ ] Keep the `vgs-request-id` of the payment request. It is the key to the access, operation and reveal-decision logs. (Developer guide, Testing and debugging)
- [ ] Treat a rising `reveal_count` as evidence of a reveal, not of the merchant's acceptance. (Skill, `SKILL.md`)

## What the sources do not cover

- No AWG document in this repository explains PCI DSS scope. VGS's "Agent Web Gateway" deck (November 2026) describes the product as transferring card data in a headless browser session "without PCI exposure", but gives no detail. Do not make a scope statement to a customer on the strength of this training; ask the compliance team.
- No AWG source names the hosted browser platforms AWG has been tested with.
- 3-D Secure through AWG was listed as untested on 2026-11-12.

---

Sources: `docs/reference/04-developer-guide.md`, `docs/reference/03-support-runbook.md`, `docs/reference/01-internal-engineering-spec.md` (Egress, Known gaps), `tools/sitecheck/AGENTS.md`, `tools/sitecheck/adapters/README.md`, `skills/vgs-checkout-adapter/SKILL.md` and `references/har-review.md`, `skills/vgs-checkout-adapter/scripts/session-kit/launch-chromium.sh`.
