# API detail

Every AWG endpoint in vault-management with its attributes, rules and error codes, each cited to `file:line` in vault-management `awg/stack-top` at `d37e6452` (paths relative to `vault-management-service/src/main/java/com/verygood/security/vault/management/`, or `opa/` and `resources/application.yaml`). Read from code, not from a run, except where noted. 49 endpoints: 7 reveal sessions, 3 approvals, 5 tenant destinations, 1 registry, 5 admin agent destinations, 4 functions, 3 invocations, 6 adapters, 5 adapter destinations, 4 admin functions, 6 admin adapters.

## 0. Conventions

**Wire format.** JSON:API: `{"data": {"type": "...", "attributes": {...}}}` (`json/JsonApiResource.java:16-20`). The id is `data.id` only; every DTO marks `id` `@JsonIgnore`. Request `type` is not checked except on `PATCH /reveal-session-approvals/{id}` (`RevealSessionApprovalController.java:95`). Attributes are `@JsonInclude(NON_NULL)` except on `RevealSessionProxyCaDto`. Paged lists add `meta.total_pages`, `meta.total_elements` and `links` (`json/JsonApiResourceFactory.java:90-105`).

| DTO | `data.type` |
| --- | --- |
| RevealSessionDto | `reveal-sessions` |
| RevealSessionProxyCaDto | `reveal-session-proxy-ca` |
| ApprovalDto | `reveal-session-approvals` |
| AgentDestinationDto (admin registry) | `agent-destinations` |
| AgentGatewayDestinationDto | `agent-gateway-destinations` |
| AgentGatewayRegistryEntryDto | `agent-gateway-registry-entries` |
| FunctionDto | `functions` |
| AgentGatewayAdapterDto | `agent-gateway-adapters` |
| AgentGatewayAdapterDestinationDto | `agent-gateway-adapter-destinations` |
| FunctionInvocationDto | `function-invocations` |

**Tenant.** From the `VGS-Tenant` header (`helpers/TenantResolver.java:99`) or the host name (`:125`). Tenant AWG controllers other than sessions and approvals call `VgsOwner.requestTenant()`, which answers `400 reserved_tenant` for tenant `vgs` (`agentgateway/VgsOwner.java:32`).

**Auth.** (1) JWT scopes checked in code (`agentgateway/AgentGatewayScopes.java:19-37`; constants `helpers/SecurityRoles.java:35, :40, :49, :54`); write does not imply read (`SecurityRoles.java:31-33, :46-47`). (2) OPA per path and method when `opa.enabled`: `opa/policies/http/reveal_sessions.rego`, `agent_gateway.rego`, `admin_access.rego:62-89`; `resources/application.yaml:343-370` excludes only `GET /reveal-sessions/*.pac`. Reveal sessions need OPA or `vgs.revealSessions.allowWithoutOpa` (`application.yaml:261-266`). Admin endpoints need a client role of `vault-mgmt-http-api`: read `admin/agent-gateway:read`, `admin/agent-gateway:write` or `admin/agent-destinations:read`; write `admin/agent-gateway:write` or `admin/agent-destinations:write` (`SecurityRoles.java:205-242`, `AgentGatewayScopes.java:44-69`). A missing role or scope is `403` with message `The <scope> scope is required`.

**Feature gates.** `vgs.revealSessions.enabled` maps sessions and approvals; `vgs.agentGateway.enabled` maps the tenant AWG controllers and `/admin/functions`, `/admin/agent-gateway-adapters` (unmapped means `404 Endpoint not found`). `/admin/agent-destinations` is always mapped and answers `503 agent_destinations_admin_disabled` without OPA (or `vgs.agentGateway.admin.allowWithoutOpa`) and `vgs.agentGateway.db.enabled`; the other admin paths answer `503 agent_gateway_admin_disabled` without OPA.

**Errors.** `{"errors":[{status, code, title, detail, href}]}` (`controller/RestExceptionHandler.java:253-262`).

| Exception | Status | Code |
| --- | --- | --- |
| `ResourceNotFoundException` | 404 | none |
| `RevealSessionValidationException`, `AgentGatewayValidationException` | 400 | the code |
| `RevealSessionConflictException` | 409 | `revocation_list_disabled` |
| `RevealSessionNotActiveException` | 409 | `session_not_active` |
| `ApprovalClosedException` | 409 | `approval_closed` |
| `AgentGatewayConflictException` | 409 | the code |
| `RevealSessionCredentialReissueDisabledException` | 404 | `credential_reissue_disabled` |
| `RevealSessionUnavailableException` | 503 | `stateless_unavailable` |
| `AgentGatewayUnavailableException` | 503 | the code |
| `RevealSessionProxyHostUnusableException` | 500 | `reveal_session_proxy_host_unusable` |
| `AgentGatewayScopeException`, `RevealSessionScopeException` | 403 | none |
| `AgentGatewayRouteException` | 403 | `agent_gateway_route`, `agent_gateway_route_field` |
| `PreferencesUnavailableException` | 503 | `preferences_unavailable` |
| any other | 500 | none |

**Ids.** `RS`, `AP`, `AGD` (base58 of the route UUID), `FN`, `FI`, `AD`, `AX`, each plus 22 base58 characters. A malformed id is a `404` for AGD, FN, AX and FI lookups and for `GET` of an adapter; `POST`/`PATCH /agent-gateway-adapters/{id}` on a missing or foreign id is `400 adapter_not_found` (`AdapterService.java:170-175`).

## 1. Reveal sessions

`controller/RevealSessionController.java`, `revealsession/RevealSessionService.java`. Scopes `reveal-sessions:read` / `reveal-sessions:write`.

### POST /reveal-sessions

Scope `reveal-sessions:write` (`:104`). Response `201`, `Location: /reveal-sessions/{id}`.

| Attribute | Type | Rules |
| --- | --- | --- |
| `aliases` | Alias\[\] | `aliases` or `cards` required (`missing_aliases`, `RevealSessionService.java:289-292`); all parts ≤ 20 (`too_many_aliases`, `:314-317`) |
| `aliases[].alias` | string | non-blank (`invalid_alias`, `:741-743`) |
| `aliases[].format` | string | `card_number`, `card_cvc`, `text` (`unknown_format`, `:744-749`); the old name `category` is refused (`category_renamed`) |
| `aliases[].bin` | string | required for `card_number` unless the alias is a 13-19 digit number (`missing_bin`, `:781-785`); defaults to the alias's first 6 digits |
| `aliases[].length` | integer | card number: alias length if numeric, else 16; CVC: 3; no range check found |
| `aliases[].storage` | string | `PERSISTENT` (default) or `VOLATILE` (`invalid_storage`, `:752-762`) |
| `aliases[].label` | string | text aliases only, `[a-z0-9][a-z0-9_-]{0,31}`, unique (`invalid_label`, `SessionParts.java:29, :49-55`) |
| `cards[]` | Card | `label` required with more than one card, same pattern, unique (`invalid_card_label`); `number` required (`missing_card_number`); `cvc`, `expiry`, `holder` optional; a part with another `format` is `invalid_card` (`SessionParts.java:63-95`) |
| `allowed_hosts` | string\[\] | trimmed, lower-cased; exact host names with a dot, ≤ 253 characters, no IPv4, port or wildcard (`invalid_host`, `RevealSessionLimits.java:73-94`); never-hosts refused (`never_host`); ≤ 20 distinct (`too_many_hosts`) |
| `allowed_client_cidrs` | string\[\] | IPv4/IPv6 or CIDR, canonicalized (`invalid_client_cidr`); ≤ 10 distinct (`too_many_client_cidrs`, `ClientCidrs.java:16-92`) |
| `egress_proxy_settings` | object | `type` `custom`; `scheme` `http`/`https`; public `hostname`; `port` 1-65535; `username` with `password` (write-only), ≤ 256 characters, no `:` (codes `invalid_egress_proxy_settings` / `_hostname` / `_port` / `_credentials`, `EgressSettings.java:12-43`); old name `proxy_settings` refused |
| `context` | map | ≤ 32 keys `[a-z][a-z0-9_]{0,63}`; values ≤ 512 characters; total ≤ 4096 (1024 stateless) (`invalid_context`, `SessionParts.java:19-27, :103-130`) |
| `adapter` | string | AD id or name, stored as the id (`invalid_adapter`, `adapter_unavailable`, `RevealSessionController.java:274-283`); blank matches every enabled binding |
| `ttl_seconds`, `unlisted_host_mode`, `step_up` |  | must be absent (`ttl_not_configurable`, `unlisted_host_mode_not_configurable`, `step_up_not_configurable`) |

Response attributes: `state` `active`, `expires_at`, `allowed_hosts`, `allowed_client_cidrs`, `unlisted_host_mode`, `tokens` (`{alias, format, value}` for every part; only create returns `value`), `session_aliases`, `cards` (with `value`), `proxy {url, ca_bundle, pac_url}`, `egress_proxy_settings` (with `has_password`, never the password), `step_up {webhook_url, hold_seconds, webhook_secret}` in step-up mode (the secret appears only here). Other errors: `session_too_large` (stateless credential over 8192 bytes), `invalid_ttl`, `503 stateless_unavailable`, `500 reveal_session_proxy_host_unusable`.

**Lifecycle.** States `active`, `revoked`, `expired` (computed on read; `RedisRevealSessionRepository.java:426-429`). TTL = min(tenant `revealSessionDefaultTtlSeconds` or 300, platform `maxSessionLifetimeSeconds` default 86400), minimum 30 (`RevealSessionService.java:690-707`). Storage `redis` (default) or `stateless` (the session rides an encrypted proxy password). `unlisted_host_mode` from preferences: `agentGatewayAutoGuardedRoutes = true` gives `guarded`; else a valid step-up webhook (hold 5-30 s, default 20) gives `step_up`; else explicit `false` gives `strict`; unset gives `guarded` (`:634-660`). Function values are Redis hash fields `cap:<adapter id>:<key>` (`RedisRevealSessionRepository.java:263-289`).

### GET /reveal-sessions

Scope `reveal-sessions:read` (`:236`). Query `state` `active` (default) or `revoked` (`invalid_state`; `expired` is not listable), `offset` ≥ 0, `limit` 1-100 (default 30) (`invalid_paging`). Paged, newest expiry first; items without `values`.

### GET /reveal-sessions/{id}

Scope `reveal-sessions:read` (`:195`). `include=values` only (`invalid_include`). Returns `state`, `pending_approvals`, `step_up` (no secret), `unlisted_host_mode`, `created_at`, `expires_at`, `allowed_hosts`, `aliases` (no values), `context`, `adapter`, `reveal_count`, `refusal_count`, `allowed_client_cidrs`, `egress_proxy_settings`, and `values: {"<adapter id>": {"<key>": "<value>"}}` with the include. Never `proxy`, `tokens`, `cards`. `404` for unknown, foreign or stateless sessions.

### DELETE /reveal-sessions/{id}

Scope `reveal-sessions:write` (`:257`). `204`. A Redis record is marked `revoked` in place (idempotent). With no record and the tenant's `revealSessionRevocationList` on, any well-formed `RS` id gets a revocation marker (TTL `maxSessionLifetimeSeconds + 60`); with it off, `409 revocation_list_disabled` under stateless storage, else `404`.

### POST /reveal-sessions/{id}/credentials

Scope `reveal-sessions:write` (`:177`). Gate `vgs.revealSessions.credentialReissueEnabled` (default off: `404 credential_reissue_disabled`). `200` with `state`, `expires_at` and a new `proxy`; the old password stops working for new connections. `409 session_not_active` when revoked or expired. Redis sessions only.

### GET /reveal-sessions/proxy-ca

Scope `reveal-sessions:read` (`:159`). `200`, `data.id` `proxy-ca`, attributes `host`, `scheme`, `port`, `ca_bundle`. `404` when no bundle is configured.

### GET /reveal-sessions/{id}.pac

No auth, no tenant header, no OPA (`SecurityConfig.java:84-87`); the signed query is the credential. Query `tenant`, `expires` (epoch seconds, future), `signature` (base64url HMAC-SHA256 of `pac/v1\n<tenant>\n<id>\n<expires>`, `PacLinks.java:14-16, :107-120`); issued in `proxy.pac_url` with `expires` = session expiry. `200`, `application/x-ns-proxy-autoconfig`, `no-store`. Script: everything to VGS (`PROXY` or `HTTPS host:port`), or for a live Redis session the split: `allowed_hosts` plus enabled bindings' `when.host` to VGS, the rest to the egress proxy or `DIRECT`; stateless sessions, a failed lookup or an unsafe pattern send everything to VGS (`SessionPac.java:11-65`). Every failure is an empty `404`; reasons are only logged.

### The `proxy` object

`url` = `<scheme>://<session id>:<secret>@<host>:<port>` (RFC 3986 userinfo encoding), `ca_bundle` (PEM, omitted when not configured), `pac_url` (omitted when PAC is off). Returned on create and reissue only.

## 2. Step-up approvals

`controller/RevealSessionApprovalController.java`. Written by the proxy when a `step_up` session holds a request for an unlisted host. Attributes: `reveal_session_id`, `host`, `method`, `path`, `state` (`pending`, `approved`, `denied`, `expired`), `scope` (`request`, `session`), `requested_at`, `expires_at`, `decided_at`.

| Endpoint | Scope | Rules and codes |
| --- | --- | --- |
| `GET /reveal-session-approvals` | read (`:57`) | `filter[reveal_session]` required (`missing_filter`); `offset`, `limit` 1-100 (`invalid_paging`); newest first |
| `GET /reveal-session-approvals/{id}` | read (`:79`) | `404 Approval not found` |
| `PATCH /reveal-session-approvals/{id}` | write (`:89`) | `data.type` `reveal-session-approvals` (`invalid_type`), `data.id` = path id (`id_mismatch`); `state` `approved`/`denied` (`invalid_state`); `scope` `request` (default) or `session` (`invalid_scope`); `409 approval_closed`; publishes `RevealSessionAudit` STEP\_UP\_APPROVED/DENIED |

## 3. Tenant agent destinations

`controller/AgentGatewayDestinationController.java`. A row in `agent_gateway.tenant_agent_destination` plus a forward-proxy route (kind AGENT\_GATEWAY). At most 1000 per tenant. Attributes: `host_pattern`, `action` (`trust`, `guarded`, `block`; `invalid_action`), `origin` (`manual`, `auto`; read-only, `origin_not_writable`), and read-only `route_id`, `created_by`, `promoted_by`, `promoted_at`, `created_at`, `updated_at`.

| Endpoint | Scope | Rules and codes |
| --- | --- | --- |
| `GET /agent-gateway-destinations` | read (`:73`) | not paged |
| `GET /agent-gateway-destinations/{id}` | read (`:82`) | `404` |
| `POST /agent-gateway-destinations` | write (`:91`) | `host_pattern`, `action` required; `201`; a `trust` records the approver; `invalid_host_pattern`, `invalid_action`, `never_host` (non-block on a never-host), `too_many_destinations`, `409 destination_exists` |
| `PATCH /agent-gateway-destinations/{id}` | write (`:131`) | `action` only (`host_pattern_immutable`); sets `origin` `manual`; the route's `vgs-reveal-guard` tag follows the action (`route_tag_limit`) |
| `DELETE /agent-gateway-destinations/{id}` | write (`:156`) | `204`; deletes route then row; no in-use check against bindings |

## 4. Registry as tenants see it

`GET /agent-gateway-registry`, scope `agent-gateway:read` (`AgentGatewayRegistryController.java:43`): ACTIVE registry entries as `{id, host_pattern, action}` with `action` `guarded` or `trust`.

## 5. Admin registry destinations

`controller/AgentDestinationAdminController.java`, tenant-less; a registry entry applies to every tenant. Attributes: `host_pattern`, `mode` (`trusted`, `guarded`), `status` (`active`, `disabled`), `created_by`, `created_at`, `updated_at`; `data.id` is a UUID.

| Endpoint | Role | Rules and codes |
| --- | --- | --- |
| `GET /admin/agent-destinations` | read | list |
| `GET /admin/agent-destinations/{id}` | read | `404 Agent destination not found`; a non-UUID id is a `400` |
| `POST /admin/agent-destinations` | write | `host_pattern`, `mode` required, `status` optional; `invalid_host_pattern`, `never_host`, `invalid_mode`, `invalid_status`, `409 destination_exists` |
| `PATCH /admin/agent-destinations/{id}` | write | `mode` and/or `status`; `host_pattern_immutable`; records `updated_by` |
| `DELETE /admin/agent-destinations/{id}` | write | `204`, hard delete; the actor is only logged |

## 6. Functions

`controller/FunctionController.java`, `agentgateway/functions/FunctionService.java`. A function's code is immutable: its id is its version, and a new version is a new function naming its predecessor in `previous_version`. A tenant sees its own functions and VGS's. Storage `vgs.agentGateway.functionStorage`: `postgres` (default) or `redis`.

Attributes: `name`, `language` (`larky`), `source`, `extension_point`, `inputs` (`[{name, required}]`), `previous_version`; read-only `sha256` (hex SHA-256 of the source), `owner` (`vgs`, `tenant`), `created_by`, `created_at`, `status` (`ACTIVE`, `DISABLED`), `updated_by`, `updated_at`. A deleted function is never returned.

Extension points (`AgentGatewayFunction.java:68-72`): `route.request` and `route.response` run in the proxy in a binding's route; `invoke` runs only through the invocations API and cannot be bound.

| Endpoint | Scope | Rules and codes |
| --- | --- | --- |
| `GET /functions` | read (`:61`) | `filter[name]` (exact); own and VGS functions, newest first, max 200 |
| `GET /functions/{id}` | read (`:68`) | `404 Function not found` (malformed, foreign, deleted) |
| `POST /functions` | write (`:75`) | `name` 1-255 (`invalid_name`; no uniqueness check found); `language` `larky` (`invalid_language`); `extension_point` (`invalid_extension_point`); `source` non-blank, ≤ 262144 UTF-8 bytes (`source_too_large`), no `${`, must parse as Larky, must load `vault` with `load("@vgs//vault", "vault")` (the global is refused), `adapter_input` predeclared (`invalid_source`, `FunctionSourceValidator.java:37-51`); `inputs` ≤ 32, names `[a-z][a-z0-9_]{0,63}` unique (`invalid_inputs`); `previous_version` an own FN id (`invalid_previous_version`). `201` |
| `DELETE /functions/{id}` | write (`:94`) | `204` soft delete (`deleted_at`, `deleted_by`) of an own function; `404` for VGS functions; `409 function_in_use` while a version of a live adapter bundles it (`FunctionService.java:105-108`) |

## 7. Function invocations

`controller/FunctionInvocationController.java`, `agentgateway/invocations/FunctionInvocationService.java`. Runs go to Compute (atlas-horizon) with a 10 s deadline; input and output are not stored.

Request attributes (write-only): `input` (invoke only), `request {method, url, headers, body}`, `response {status, headers, body}`, `destination` (AX id), `inputs` (name to string), `session {values, context}`. Response (read-only): `function`, `source` (`api`, `test`), `dry_run`, `status` (`succeeded`, `failed`), `error`, `duration_ms`, `result`, `created_by`, `created_at`; id `FI…`.

**POST /functions/{id}/invocations** (scope write, `:53`; the function may be the tenant's or VGS's):

- `invoke`: `input` required; `request`/`response` refused (`invalid_invocation`); recorded `source=api`, `dry_run=false`; no session.
- `route.request`: `request` with `method` and an absolute `http(s)` `url`; dry run (`source=test`), nothing sent upstream.
- `route.response`: `response` only, `status` 100-599; `request` and `input` refused.
- Each body ≤ 1 MiB. Route functions take `destination` (that binding's inputs) or `inputs` (constants ≤ 4096 characters, no `${`, no control characters; required inputs present, no undeclared names; `invalid_inputs`), not both.
- `session.values` feeds `session.get` and `session.value` inputs; `session.context` feeds `session.context`; `session.card` and `session.alias` always fail (documented in `FunctionInvocationDto.java:48-52`; enforced by Compute).
- `201` even when the run fails (`status=failed`, `error` `<status>: <message>`, `TIMEOUT: …` or `UPSTREAM_ERROR: …`). `result` (this response only): `output` (invoke), `request` or `response` (rewritten), `session.values` (given plus `session.put`s; omitted on failure or older Compute).
- Codes: `invalid_invocation`, `invalid_inputs`, `invalid_function`, `404 Function not found`, `503 invocations_unavailable`.

**GET /function-invocations** (read, `:75`): `filter[function]`, `filter[source]` (`invalid_filter`), newest first, max 100, never `result`. **GET /function-invocations/{id}** (read, `:83`): `404` unless an `FI` id of the tenant.

## 8. Adapters

`controller/AgentGatewayAdapterController.java`, `agentgateway/adapters/AdapterService.java`. Numbered, immutable versions; create is version 1, `POST /{id}` adds `latest + 1` (optimistic), `PATCH /{id}` with `publish_at` makes the latest version live now or schedules it. The effective version is the scheduled one once due, else `published_version`. A tenant's own adapter: any version up to `latest_version` is visible and pinnable. A VGS adapter: visible only once it has an effective version, and only up to it; `latest_version`, `scheduled_version`, `scheduled_at` are hidden from tenants.

Attributes: `name`, `functions`, `publish_at` (write-only, PATCH only); read-only `version`, `latest_version`, `published_version`, `scheduled_version`, `scheduled_at`, `owner`, `created_by`, `created_at`, `updated_at`, `status`, `updated_by`.

| Endpoint | Scope | Rules and codes |
| --- | --- | --- |
| `GET /agent-gateway-adapters` | read (`:57`) | own plus published VGS adapters, by name |
| `GET /agent-gateway-adapters/{id}` | read (`:64`) | `404 Adapter not found` (also unpublished VGS adapters) |
| `POST /agent-gateway-adapters` | write (`:73`) | `name` 1-255 (`invalid_name`); `functions` 1-32 unique visible FN ids (`invalid_functions`); `201`; `409 adapter_exists` |
| `POST /agent-gateway-adapters/{id}` | write (`:88`) | new version, `functions` only (`name_immutable`); `200`; `adapter_not_found` (VGS adapters are read-only); `409 adapter_version_conflict` |
| `PATCH /agent-gateway-adapters/{id}` | write (`:103`) | `publish_at` only (`invalid_attributes`): `now` or an ISO-8601 time with offset (`invalid_publish_at`); `200` |
| `DELETE /agent-gateway-adapters/{id}` | write (`:119`) | `204` soft delete, frees the name; `404` for VGS adapters; `409 adapter_in_use` while any binding of any vault references it |

## 9. Adapter destinations

`controller/AgentGatewayAdapterDestinationController.java`, `agentgateway/destinations/AdapterDestinationService.java`. Connects one pinned adapter version to traffic; saving writes managed rule entries into the route of the agent destination named by `when.host`, and a disabled binding's entries are removed. At most 100 per vault.

Attributes: `adapter` (id or name in, id out), `adapter_version`, `enabled` (default true), `when {host, method, path}`, `functions [{id, inputs, extension_point (read-only)}]`; read-only `revision`, `created_by`, `updated_by`, `created_at`, `updated_at`; id `AX…`.

`when` (`:266-311`): `host` required, a host or `*.` pattern (`host_required`, `invalid_when`), and one of the vault's agent destinations (exact, else the longest covering `*.` pattern) that is not blocked (`unknown_host`, `destination_blocked`); `method` one of GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS; `path` starting with `/`, ≤ 1024, no whitespace, `?`, `#`, `${`, `\`, `[`, `]`, `^`, `"`; `*` matches any characters.

Input sources (`:365-400`): `request.body` / `response.body` (`path`: `$` then `.key`, `['key']`, `[index]`); `request.header` / `response.header` / `request.query` (`name`); `constant` (`value` ≤ 4096, no `${`); `session.value` (`key`, only with `vgs.agentGateway.sessionValueInputs`, else `input_source_unsupported`). A request function reads only request sources and a response function only response sources; every required input mapped, no undeclared names (`invalid_inputs`).

| Endpoint | Scope | Rules and codes |
| --- | --- | --- |
| `GET /agent-gateway-adapter-destinations` | read (`:59`) | `filter[adapter]` (id or name; unknown gives an empty list) |
| `GET /agent-gateway-adapter-destinations/{id}` | read (`:67`) | `404` |
| `POST /agent-gateway-adapter-destinations` | write (`:76`) | `adapter` (own wins over a VGS adapter of the same name) or exactly one function and no version, which creates or reuses the tenant adapter `fn-<FN id>`; `adapter_version` defaults to latest (own) or effective (VGS); `functions` 1-16. `201`, `revision` 1. Codes: `too_many_destinations`, `invalid_adapter`, `adapter_required`, `invalid_functions` (also for `invoke` functions), `invalid_adapter_version`, the `when` codes, `function_not_in_adapter`, `invalid_inputs`, `input_source_unsupported`, `409 destination_overlap`, `409 adapter_conflict`. A failed route write rolls the binding back |
| `PATCH /agent-gateway-adapter-destinations/{id}` | write (`:86`) | any of `adapter_version`, `enabled`, `when`, `functions` (replaces the list); `adapter` only if unchanged (`adapter_immutable`); functions re-checked against a new version; `200`, `revision` + 1; `409 concurrent_change`, `409 destination_overlap` |
| `DELETE /agent-gateway-adapter-destinations/{id}` | write (`:93`) | `204`; route entries removed, then the row (hard delete) |

`destination_overlap` (`:418-431`): an enabled binding is refused when another enabled binding of the vault has a function in the same phase and its `when` can match the same request (equal or covering hosts, equal or absent methods, equal or glob-compatible paths). The check is conservative and may refuse conditions that never meet (`DestinationOverlap.java:5-9`).

## 10. Admin VGS functions and adapters

`controller/AgentGatewayRegistryAdminController.java`. As sections 6 and 8 with owner `vgs` and no vault; `503 agent_gateway_admin_disabled` without OPA. VGS functions are readable by every vault; a VGS adapter once a version is published.

| Endpoint | Role | Notes |
| --- | --- | --- |
| `GET /admin/functions`, `GET /admin/functions/{id}` | read | VGS functions only; `404` for others |
| `POST /admin/functions` | write | as `POST /functions`; `previous_version` must be a VGS function |
| `DELETE /admin/functions/{id}` | write | soft delete; `409 function_in_use` while an adapter of any owner bundles it |
| `GET /admin/agent-gateway-adapters`, `GET …/{id}` | read | VGS adapters, including latest, scheduled and unpublished versions |
| `POST /admin/agent-gateway-adapters` | write | `functions` must be VGS functions; `409 adapter_exists` |
| `POST /admin/agent-gateway-adapters/{id}` | write | new version; `409 adapter_version_conflict` |
| `PATCH /admin/agent-gateway-adapters/{id}` | write | `publish_at`: `now` publishes the latest version to every vault; a future time schedules it |
| `DELETE /admin/agent-gateway-adapters/{id}` | write | soft delete; `409 adapter_in_use` while a binding of any vault uses it |

## 11. Ownership and deletes

- `owner` is `vgs` (row `tenant_id = 'vgs'`) or `tenant`; tenant id `vgs` is reserved for tenant requests (`400 reserved_tenant`).
- Tenants read VGS functions and published VGS adapters, bundle VGS functions, pin VGS adapter versions and run VGS functions in dry runs; they cannot create, version, publish or delete VGS rows (`404` on DELETE, `400 adapter_not_found` on version or publish).
- Functions and adapters are soft-deleted (`deleted_at`, `deleted_by`, `status` kept, never returned again, name reusable). Agent destinations, adapter destinations and registry destinations are hard deletes. There is no function update endpoint.
- `status` is `ACTIVE` or `DISABLED`; no endpoint covered here sets `DISABLED`.

## 12. Open questions (not determinable from this checkout)

1. Full enum definitions for destination modes, statuses, actions and origins, and the host-pattern grammar: defined in an external library; only TRUSTED/GUARDED, ACTIVE/DISABLED, TRUST/GUARDED/BLOCK, MANUAL/AUTO are referenced.
2. `404` and validation behavior of the admin registry PATCH and DELETE (`AgentDestinationService`, external).
3. Whether function names, or Postgres adapter names, are unique (no service check; the Redis adapter store is unique per owner).
4. What sets a function or adapter to `DISABLED`.
5. Whether deleting an agent destination is blocked while a binding's `when.host` uses it (no check found).
6. The exact `400` body for a request without `data`.
7. Compute-side enforcement of the dry-run `session.card` / `session.alias` failure.
8. Range validation of alias `bin` and `length` (documented as 6-8 digits and 13-19 / 3-4, no check found).
9. The status for the tenant route-count limit on destination create.
10. Behavior of a revoked Redis session after its original expiry (derived from code, not run).
