# Glossary

| Term | Meaning |
|---|---|
| Adapter (`AD…`) | A named bundle of functions with numbered, immutable versions; one per integration, for example `adyen` |
| Adapter destination, binding (`AX…`) | Runs one pinned adapter version's functions on traffic matching a host, method and path |
| Agent destination (`AGD…`) | A host pattern the vault's agents may reach, with an action: `trust`, `guarded` or `block` |
| Alias | A vault's stand-in for a stored value, for example `tok_sandbox_…`. Held by the customer's backend |
| AWG | Agent Web Gateway |
| Capture function | A `route.response` function that stores something from a response in the session, for example the PSP's public key |
| Context | Strings the session's creator passes for functions to read with `session.context(key)` |
| CSE | Client-side encryption: the browser encrypts the card with the PSP's public key before sending it |
| Dry run | `POST /functions/{id}/invocations`: runs one function on a supplied request or response, without a card |
| Egress proxy | The customer's own outbound proxy, set per session in `egress_proxy_settings` (for example a residential provider), so the merchant sees one IP for VGS-routed and direct traffic |
| Extension point | Where a function runs: `route.request`, `route.response` or `invoke` |
| Function (`FN…`) | An immutable Larky program with the entry point `process(input, ctx)` |
| Larky | The Python dialect functions are written in |
| Never-host | A host that can never receive real values, such as public echo and request-bin services |
| PAC file | A proxy auto-config script. The session's PAC sends only chosen hosts through VGS |
| PSP | Payment service provider, for example Adyen or Stripe |
| Recipe | In `awg-sitecheck`, a Python file with one site's clicks from product page to card form |
| Registry | VGS's trusted destinations, functions and adapters that every vault inherits |
| Re-encrypt (encrypt) function | A `route.request` function that replaces the browser's encrypted card fields with fields encrypted from the real card |
| Reveal | Replacing an alias or session token with the real value. Counted in `reveal_count` |
| Reveal session (`RS…`) | One agent task's credential: card, hosts, lifetime, proxy login |
| Session token, stand-in, session alias | The per-session value the agent types in place of the card number or CVC. All three names appear in the sources |
| Step-up | An unlisted-host mode where a request is held while VGS calls the customer's webhook, until the customer approves or denies it with `PATCH /reveal-session-approvals/{id}` or the hold times out |
| Tenant | A vault, identified by its id (`tnt…`) in the `VGS-Tenant` header |
| Unlisted-host mode | What happens to hosts nothing allows: `strict`, `guarded` or `step_up` |
| Values | What functions store in a session with `session.put`, kept per adapter |
| `vgs-request-id` | The response header on every request that went through VGS; the key to all logs |
