# Provenance and adaptations

Packaged 2026-11-13 from the user's existing files:

- `vgs-checkout-adapter/SKILL.md` and `references/local-larky.md`: integration order, native runtime/hash, evidence standards and function behavior.
- `agent-gateway-test-kit/create-fresh-session.sh`, `create-card.sh`, `create-session.sh`, `lib.sh`, browser/status/cleanup scripts and `test_fresh_session.py`: session workflow and regression tests. Original hashes were recorded in the original bundle's `source-snapshot.json`, which is not included in this repository.
- Test-kit README, `ADAPTER-SMOKE.md`, capture-console README, Stripe/Adyen guides, H&M cleanup workflow and IKEA registration/local-test implementation: reviewed and condensed into references. Private findings and payloads were not copied.

Portable adaptations: personal custom-proxy endpoint removed in favor of explicit `EGRESS_ALLOWED_HOST`/`EGRESS_ALLOWED_PORT`; private fallback profile removed from Cloak launcher; timezone/locale default to UTC/en-US; named-adapter ledgers use configurable `ADAPTER_REGISTRY_DIR` and profile/tenant naming; profile names are restricted to safe filename characters. Offline tests use synthetic profiles. Original create-card/fresh-session semantics are retained, including the new-card-ID gate.

The HAR helper and bounded Larky runner are reusable helpers added for this bundle. The runtime smoke fixture is wholly synthetic and proves only runtime execution. Deployment examples are templates derived from observed request shapes, not registered resources or a universal API promise.

External binaries, dependency trees, Capture Console, private HARs, `.env` credentials, session/browser state, service accounts, registration IDs and personal proxy configuration are excluded. Use the current target schema and exact source ledger before deployment; older READMEs can lag deployed function behavior.
