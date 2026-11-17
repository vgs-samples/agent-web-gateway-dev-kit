# Self-check

Answer from memory, then open the answer. Each answer names the page it comes from.

1. **What does the agent type into the payment form?**
   <details><summary>Answer</summary>The session tokens returned once when the session is created. Not the real card and not the vault aliases. (Page 2, page 4)</details>

2. **A token has `reveal-sessions:write` only. Can it read a session?**
   <details><summary>Answer</summary>No. Write scopes do not include read. (Page 3)</details>

3. **Which values from the create response must you store, and why then?**
   <details><summary>Answer</summary><code>proxy.url</code>, <code>proxy.pac_url</code> and the session tokens are returned only in the create response; later reads never return secrets. Save <code>proxy.ca_bundle</code> too, although it can also be read from <code>GET /reveal-sessions/proxy-ca</code>. (Page 1)</details>

4. **Can you set a session's lifetime in the create request?**
   <details><summary>Answer</summary>No. It comes from the vault's settings: default 300 seconds, minimum 30. Trying returns <code>ttl_not_configurable</code>. (Page 2)</details>

5. **A merchant uses Stripe Elements. Do you write an adapter?**
   <details><summary>Answer</summary>Not by default: plain card fields posted to the PSP's API are handled by the default swap once the PSP's API host is allowed. Confirm from a capture of the real card-bearing request rather than from the provider's name. (Page 5)</details>

6. **For Adyen client-side encryption, what do the two functions do?**
   <details><summary>Answer</summary>The capture function (<code>route.response</code>) stores the merchant's public key and Adyen's <code>genTime</code> from the secured-fields page in the session. The re-encrypt function (<code>route.request</code>) reveals the session card and replaces the browser's ciphertext with fields encrypted under that key. (Page 1; the extension points are in the glossary)</details>

7. **A checkout went out, no error, and <code>reveal_count</code> is 0. What happened?**
   <details><summary>Answer</summary>Either the function ran but returned its input unchanged because the body did not match what it expects, or no binding matched the request's host, method and path. A function that does nothing raises no error. (Page 1, page 5, page 7)</details>

8. **The agent gets `422 Request processing error. Request id: …`. Where do you look?**
   <details><summary>Answer</summary>A function stopped the request. Look up the request id with <code>vgs logs operations</code> (needs <code>access-logs:read</code>), check the session's <code>values</code>, and dry-run the function on the same body. (Page 7)</details>

9. **Session <code>values</code> is empty at an Adyen checkout. Why?**
   <details><summary>Answer</summary>The payment page did not go through VGS, so the capture function never ran: the PSP's page host is not in <code>allowed_hosts</code> or a binding, or the browser did not use the PAC file. (Page 7)</details>

10. **Why can a dry run not fully test a re-encrypt function?**
    <details><summary>Answer</summary>A dry run has no card: <code>session.card()</code> and aliases fail there, so a dry run covers only the parts of the function that run without a reveal, such as the expiry fields in <code>tools/sitecheck/adapters/adyen-cse/fixtures/encrypt-hm.json</code>. Use the level 2 harness, which goes through the real proxy. (Page 5)</details>

11. **In what order do you delete an integration?**
    <details><summary>Answer</summary>Bindings (adapter destinations), then adapters, then functions. (Page 5)</details>

12. **The probe says a site is blocked. How do you tell whether the gateway is the cause?**
    <details><summary>Answer</summary>Run with <code>--direct</code>, which loads the same URLs through the egress proxy only. Direct 200 and gateway 403 means the gateway path; both 403 means the site or the IP. (Page 6)</details>

13. **What must be true before you run <code>purchase --purchase</code>?**
    <details><summary>Answer</summary>A human has approved that item and a maximum total, and you pass it as <code>--max-total</code>. (Page 6, page 8)</details>

14. **Does a rising <code>reveal_count</code> prove the merchant accepted the payment?**
    <details><summary>Answer</summary>No. It shows a reveal happened. Merchant acceptance is a separate result. (Page 4, page 5, page 9)</details>

15. **Exercise from page 5: what is wrong with <code>hm_reencrypt_buggy.star</code>?**
    <details><summary>Answer</summary>Its loop over expiry fields lists only <code>expiryYear</code>, so <code>encryptedAdyenExpiryMonth</code> is never re-encrypted and the browser's value stays in the body. The harness reports that field as <code>FAIL</code> because its placeholder was not replaced. A dry run on the full checkout body would not show it: that body has a card-number field, so the run fails at the card reveal before anything is written. A dry run on an expiry-only body, such as <code>tools/sitecheck/adapters/adyen-cse/fixtures/encrypt-hm.json</code>, never reaches the reveal and would show the month field unchanged. (Run <code>diff examples/functions/hm_reencrypt.star examples/functions/hm_reencrypt_buggy.star</code>.)</details>
