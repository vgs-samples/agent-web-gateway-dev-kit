# Register or update adapters

These examples preserve the observed API contract from the working registration scripts. Verify the target environment's current schema before use; they are not automatic deployment commands. Use current service-account/CLI credentials privately. API mutations require authorization already present in the user's task or explicit approval of the prepared change.

## Prepare a concrete change

1. Verify native local results for the exact function source and fixture hashes. For a native crypto limitation, retain the failure and supplemental real-Larky evidence; resolve or clearly obtain an explicitly scoped exception before claiming the required native gate passed.
2. Inspect `/functions`, `/agent-gateway-adapters`, `/agent-gateway-destinations`, and `/agent-gateway-adapter-destinations` in the exact tenant/environment. Follow pagination. Reuse compatible provider adapters; stop on ambiguous duplicates or unexpected concurrent changes.
3. Prepare functions, adapter version/membership, exact host policy, bindings and inputs. Show the concrete target/diff when approval is needed. Deployment authorization is not authorization to change unrelated vault settings.

## API shapes

Use JSON:API envelopes with `Content-Type`/`Accept: application/vnd.api+json`, bearer authentication, and `VGS-Tenant` for these management endpoints. See `assets/deployment/` for credential-free payload examples.

| Operation | Observed endpoint / semantics |
| --- | --- |
| Create function | `POST /functions`; language `larky`, `extension_point` `route.request` or `route.response`, source string, declared inputs |
| Read function | `GET /functions/{id}`; compare source and SHA-256 |
| Create adapter | `POST /agent-gateway-adapters`; name and function IDs |
| Update membership | Observed `POST /agent-gateway-adapters/{id}` with function IDs; read returned version; verify schema rather than assuming PATCH |
| Host prerequisite | `/agent-gateway-destinations`; exact `host_pattern` with appropriate action; do not override an existing block |
| Create binding | `POST /agent-gateway-adapter-destinations`; adapter ID/version, enabled, `when`, functions with input mappings |
| Update binding | Observed `PATCH /agent-gateway-adapter-destinations/{id}`; read back |

Create/reuse the function by source hash, extension point and input contract, not name alone. Resolve API-issued function IDs before creating adapter membership. `FNlocal` authoring IDs are not deployed IDs. Take the actual returned adapter version, not a guessed increment.

Hosts must exist and be unblocked before binding. Use the captured payment host; do not expand to a provider-wide wildcard without evidence. `when` contains host/method/path; phase comes from each function's `extension_point`. Select only functions in the pinned adapter version. String constants and selector shapes must follow the actual declared input contract; do not invent `session.value` or expiry aliases.

Generalize varying checkout/version segments only when the shared structure is understood and positive/nearby-negative tests pass. Preserve merchant wrapper and GraphQL guards. Test wildcard handling in the real gateway too; local glob matching is only a model.

## Read back and retain provenance

Read functions (source/hash/phase/inputs), adapter (version/membership), host policy and every binding (enabled, version, match and input mapping). A successful POST alone is insufficient. Save IDs after each successful mutation so a partial failure is recoverable without blind duplication.

Maintain a private registration ledger linking API/tenant, function source hashes, adapter/version, binding IDs, HAR/entry references and local reports. Named session-kit shortcuts use `<profile>-<tenant>-stripe.json` or `...-adyen.json` containing `adapterId` in `ADAPTER_REGISTRY_DIR`.

For updates record the prior version/bindings and exact changed IDs. If readback fails, stop further changes, report partial state and use the prior binding/version only within authorized rollback scope. Do not delete a shared provider adapter as cleanup.

Proceed to [gateway verification](gateway-verification.md) when requested. Session `adapter` selection, host reveal authorization and adapter destination dispatch are separate controls. Registering a binding does not automatically grant reveal permission or prove merchant acceptance.
