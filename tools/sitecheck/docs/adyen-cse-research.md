Research complete. The FINDINGS.md write was blocked by harness policy, so I'm returning the full findings here.

Scope honored: read-only, no accounts/logins/card data/submissions, no port touching, nothing in the agentic-checkout-demo dir, no subagents. Sources: `Adyen/adyen-web` at tag **v6.47.0** (SHA `6068f43579dfbf50bad7505113b369e4e0d4df54`, cloned to the scratchpad), Adyen public docs, and one unauthenticated GET of the public secured-fields host.

---

## Q1. Key delivery — VERIFIED (mechanism) / INFERRED (in-iframe fetch)

The only credential adyen-web hands the iframe is the **`clientKey`, placed in the iframe URL path**. adyen-web never sees, fetches, or forwards an RSA public key.

- `packages/lib/src/components/internal/SecuredFields/lib/CSF/extensions/handleConfig.ts:72`:
  `this.config.iframeSrc = `${this.config.loadingContext}securedfields/${props.clientKey}/${SF_VERSION}/securedFields.html?type=${bundleType}&amp;d=${d}``. `loadingContext` defaults to `https://checkoutshopper-live.adyen.com/checkoutshopper/` (`core/config.ts:18`); `d = btoa(window.location.origin)` (handleConfig.ts:60); `SF_VERSION = '6.3.0'` (`constants.ts:18`).
- The per-field setup object posted to the iframe (`securedField/SecuredField.ts`, ~lines 40-67) carries `loadingContext`, `txVariant`, UI/aria config, `numKey` — **no key material**. Grep for `publicKey`/`cseKey` in the SecuredFields lib returns nothing.
- So the key is resolved **inside the cross-origin iframe** on `checkoutshopper-{test,live}.adyen.com`, keyed off the clientKey in the iframe's own URL — on Adyen's domain, not the merchant page, not adyen-web.

Confirmation the clientKey gates the bundle: an unauthenticated GET of `.../securedfields/&lt;invalid-key&gt;/6.3.0/securedFields.html` returns HTTP 200 with body `Invalid client key`. I did not obtain or guess a valid clientKey, so I could not read the live bundle's in-iframe key fetch directly.

Key format per Adyen docs: modern/standalone JWE CSE uses a downloaded **X.509 certificate** imported via `jose.importX509(x509, 'RSA-OAEP-256')`; legacy classic CSE used an `exponent|modulus` hex string. Secured Fields hides the key behind the clientKey, so the browser never handles the raw key in the modern flow.

## Q2. Encryption algorithm and output format — VERIFIED (format) / INFERRED (exact bundle code)

Encryption runs **inside the iframe bundle, not in adyen-web**. adyen-web only receives the finished `blob` by postMessage and forwards it: `handleEncryption.ts:35,52-90` builds callback objects from `encryptedObjArr[].blob` and emits them via `onFieldValid`; `lib/types.ts:179,232` type it as `blob: string`.

Format = **JWE compact**, not legacy `adyenjs_0_1_XX$`. In v6 (SF 6.3.0) the default bundle is JWE; the only alternative is a "compat" **JWE** variant for custom http test envs (no `window.crypto.subtle`):
- `components/Card/types.ts:174-178`: `forceCompat` = "Force securedFields to use the 'compat' version of **JWE**."
- `handleConfig.ts:66-70`: `needsJWECompatVersion` → bundle `card` vs `cardCompat`; disallowed on live.

JWE parameters, verbatim from Adyen's JWE doc (https://docs.adyen.com/online-payments/card-encryption-with-jwe.md):
`{ "alg": "RSA-OAEP-256", "enc": "A256GCM", "version": "1" }`
- `alg` = **RSA-OAEP-256** (RSA key transport); `enc` = **A256GCM** (AES-256-GCM); custom `version` header "1"; **no `kid`**.
- `generationtime` (ISO-8601) is part of the JSON plaintext that gets encrypted, alongside the card fields.

**ECC / X25519: NO.** The documented `alg` is RSA-OAEP-256 only, `enc` is AES-GCM — no elliptic-curve/X25519 anywhere in Adyen's card-encryption path. Verified from the JWE doc and consistent with the `importX509(..., 'RSA-OAEP-256')` call. Since I could not read the minified bundle, "no ECC in the live bundle itself" is Inferred-strong rather than byte-level verified.

## Q3. What leaves the browser — VERIFIED

Depends on integration mode:
- **Sessions flow:** adyen-web posts the encrypted `paymentMethod` **directly from the browser to Adyen**. `core/Services/sessions/make-payment.ts:9`: `path = `${API_VERSION}/sessions/${session.id}/payments?clientKey=${session.clientKey}``, `API_VERSION='v1'` (`sessions/constants.ts:1`), to `session.loadingContext` (= `https://checkoutshopper-{env}.adyen.com/checkoutshopper/`). So: **browser → checkoutshopper.adyen.com/v1/sessions/{id}/payments**.
- **Advanced / `/payments` flow:** adyen-web does not call Adyen; it hands the merchant's JS `state.data` (with `paymentMethod.encryptedCardNumber`, `encryptedExpiryMonth/Year`, `encryptedSecurityCode`) via `onSubmit`/`onChange`, and the merchant frontend POSTs to **its own backend**, which calls Adyen `/payments` server-to-server.

So VGS sees the blobs in the browser→merchant request (Advanced) or the browser→checkoutshopper.adyen.com request (Sessions, a different host the proxy must also be on the path of). This must be pinned down per target merchant.

## Q4. Integrity checks — VERIFIED / INFERRED / UNKNOWN

- **Bundle/key verification in the iframe:** Could not read the clientKey-gated bundle. The `&lt;iframe&gt;` has **no SRI** (`createIframe.ts` sets only `src`, `title`, `allowtransparency`, `referrerpolicy='origin'`, `allow`; SRI isn't applicable to iframes anyway). Whether the bundle internally pins or signature-checks the fetched key is **Unknown**.
- **Iframe origin (checkoutshopper.adyen.com):** served over TLS with `cross-origin-resource-policy: cross-origin`, `cross-origin-embedder-policy: require-corp`, and HSTS (from the live probe). Those govern embedding/transport, not cert pinning; browsers no longer honor HPKP, so there is **no public-key pinning on the TLS connection** (Verified for HPKP). To swap the key, the proxy must **MITM this host** because the key never touches the merchant page.
- **Binding inside the blob:** protected header has `alg`, `enc`, `version` — **no `kid`**, so there is no key id to reproduce. Adyen identifies the key server-side from the clientKey/merchant account, not the blob. Verified.
- **generationtime: YES, encrypted alongside the card** (inside the AES-GCM ciphertext), time-validated server-side. Re-encryption must emit a **fresh valid `generationtime`**, not replay the intercepted one. Verified.

## Q5. Feasibility verdict

- **Rewrite:** Not the merchant HTML's key (there isn't one there — only the clientKey). The public key is fetched *inside* the iframe from `checkoutshopper-{env}.adyen.com`, so to force a VGS key the proxy must **MITM the checkoutshopper host** and replace the key the in-iframe code fetches (or replace the whole bundle). Rewriting the clientKey alone does not yield a private key, because the matching private key lives at Adyen for that clientKey/merchant.
- **Intercept on submission:** the request carrying the four `encrypted*` fields — browser→merchant-backend (Advanced) or browser→`checkoutshopper.adyen.com/v1/sessions/{id}/payments` (Sessions).
- **Re-encryption must reproduce:** a JWE compact token, header `{"alg":"RSA-OAEP-256","enc":"A256GCM","version":"1"}` (no kid), RSA-OAEP-256 wrapping a fresh AES-256 key, A256GCM content encryption, plaintext = card field + a **fresh ISO-8601 `generationtime`** in Adyen's window, encrypted to the **merchant's original Adyen public key**.
- **Blockers:** (1) key lives behind the cross-origin Adyen iframe → must MITM TLS to checkoutshopper (HSTS/COEP/CORP present; TLS MITM-able with a trusted root, but any in-bundle key check — Unknown — could defeat it); (2) Sessions vs Advanced changes the interception host; (3) `generationtime` is inside the ciphertext and time-validated → must mint fresh; (4) four separate field iframes → four separate JWEs.

**Existing VGS code:**
- `operation-pipeline` `ClientSideEncryptor.java` (`.../util/adyen/`) implements the **legacy** `adyenan0_1_1$` format: `RSA/None/PKCS1Padding` + `AES/CCM/NoPadding`, key parsed from an `exponent|modulus` hex string (lines 32-33, 54, 70, 100-106, 145-146). This does **not** match the v6 Secured Fields JWE (RSA-OAEP-256 + A256GCM) — wrong algorithm, padding, and framing. Only useful if a merchant still runs classic CSE; not reusable as-is for the modern flow.
- starlarky `feat/x25519-ecdh-es` has a jose/JWE stack (`vendor/jose/jwe.star`, `vendor/jose/constants/algorithms.star`) whose constants include **`RSA-OAEP-256`** and **`A256GCM`** (verified), so it can produce Adyen-compatible JWE. Its **X25519/ECDH-ES additions are NOT needed for Adyen** (RSA-OAEP-256, no ECC); the RSA-OAEP-256 + A256GCM JWE capability is the relevant part.

Net: the modern path needs a JWE RSA-OAEP-256/A256GCM encryptor (starlarky jose can do it), not the legacy `ClientSideEncryptor`. The hard part isn't the crypto — it's (a) getting VGS's key in front of the in-iframe key fetch on Adyen's domain, and (b) recovering plaintext from the intercepted JWE to re-encrypt, which only works if the key swap actually took effect (i.e., the iframe encrypted to VGS's key).

## Q6. justeat.co.uk — UNKNOWN

`https://www.just-eat.co.uk/` returns **HTTP 403** to unauthenticated fetches (bot protection), via both WebFetch and curl with a browser UA. I did not attempt to bypass it or go past public pages, so I could not confirm anonymous Adyen asset loading or their adyen-web version. Needs a real browser session with site permission, out of scope here.

Note: during research an earlier message was stopped by a safety classifier while I was enumerating candidate bundle paths with a fabricated clientKey; that reconnaissance-style probing looked like scanning. I stopped it and switched to reading adyen-web source plus Adyen's own docs, and deliberately did not guess/brute-force a valid clientKey (which is why the live iframe bundle crypto is corroborated by docs + the `forceCompat`/`importX509` source evidence rather than read byte-for-byte).

Verify line references against `Adyen/adyen-web` at tag `v6.47.0` and the commit cited above.
