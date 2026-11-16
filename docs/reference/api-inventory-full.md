# Agent Web Gateway (AWG) API inventory - vault-management

Source: vault-management commit d37e6452 (branch awg/stack-top).

Citation base: file paths are relative to
`vault-management-service/src/main/java/com/verygood/security/vault/management/` unless they start with `opa/`
(repo root) or `resources/application.yaml` (`vault-management-service/src/main/resources/`). Format `file:line`.
Where a rule lives in a class outside this repo it is marked UNKNOWN.

Endpoint count: 49 (7 reveal sessions, 3 approvals, 5 tenant destinations, 1 registry, 5 admin agent destinations,
4 functions, 3 invocations, 6 adapters, 5 adapter destinations, 4 admin functions, 6 admin adapters).

---

## 0. Conventions that apply to every endpoint

**Wire format.** JSON:API. Request: `{"data": {"type": "...", "attributes": {...}}}` (`json/JsonApiResource.java:16-20`,
`json/JsonApiData.java`). The `id` is `data.id` only, never an attribute (every DTO marks `id` `@JsonIgnore`). `type` on
a request is not checked, except for `PATCH /reveal-session-approvals/{id}` (RevealSessionApprovalController.java:95).
Response `type` strings come from `json/JsonApiResourceFactory.java:42-60`:

| DTO | `data.type` |
|---|---|
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

Attributes are `@JsonInclude(NON_NULL)` on every DTO except `RevealSessionProxyCaDto` (null `ca_bundle` is not
omitted by that class; the endpoint 404s when there is no bundle).
List responses (`createResources`) have `data` only. Paged lists (`createPageableResources`,
json/JsonApiResourceFactory.java:90-105) add `meta.total_pages`, `meta.total_elements` and `links`.

**Tenant.** The request tenant comes from the `VGS-Tenant` header (helpers/VgsHttpHeaders.java:5,
helpers/TenantResolver.java:99) or the host name (TenantResolver.java:125). Every controller below except the admin ones
reads it via `TenantIdentifierUtil`. All tenant-scoped AWG controllers other than reveal sessions and approvals call
`VgsOwner.requestTenant()`, which answers **400 `reserved_tenant`** when the tenant is `vgs` (agentgateway/VgsOwner.java:32).

**Auth layers (both apply).**
1. Spring JWT, then in-code scope check. Scopes are read from the JWT authorities (agentgateway/AgentGatewayScopes.java:19-37).
   Scope constants: helpers/SecurityRoles.java:35 (`reveal-sessions:read`), :40 (`reveal-sessions:write`), :49
   (`agent-gateway:read`), :54 (`agent-gateway:write`). **Write does not imply read** (SecurityRoles.java:31-33, :46-47).
2. OPA (when `opa.enabled=true`), per path/method: `opa/policies/http/reveal_sessions.rego`,
   `opa/policies/http/agent_gateway.rego` (resource permission `read`/`write` on the vault), and
   `opa/policies/http/admin_access.rego:62-89` for the admin paths. `resources/application.yaml:343-370` is the OPA exclude list
   (only `GET /reveal-sessions/*.pac` among AWG paths).
   Reveal sessions need OPA or `vgs.revealSessions.allowWithoutOpa=true` (resources/application.yaml:261-266).

**Admin (VGS-only) endpoints** (`/admin/agent-destinations`, `/admin/functions`, `/admin/agent-gateway-adapters`) require a
**client role** of Keycloak client `vault-mgmt-http-api` (`resource_access["vault-mgmt-http-api"].roles`), not a scope:
read = `admin/agent-gateway:read` | `admin/agent-gateway:write` | `admin/agent-destinations:read`; write =
`admin/agent-gateway:write` | `admin/agent-destinations:write` (helpers/SecurityRoles.java:227-242, :205-216; client id
controller/AgentDestinationAdminController.java:61; check agentgateway/AgentGatewayScopes.java:44-69). Realm roles and
other clients' roles do not count (AgentGatewayScopes.java:40-43). OPA mirror: opa/policies/http/admin_access.rego:62-89.
A missing role is **403** with message `The <first role> scope is required` (AgentGatewayScopes.java:67).

**Feature gates (404 when off).**
- Reveal sessions + approvals controllers: `vgs.revealSessions.enabled` (RevealSessionController.java:66,
  RevealSessionApprovalController.java:39). When off the paths are unmapped (404 `Endpoint not found`,
  controller/RestExceptionHandler.java:329-334).
- Tenant AWG controllers, `/admin/functions`, `/admin/agent-gateway-adapters`: `vgs.agentGateway.enabled=true`
  (e.g. AgentGatewayDestinationController.java:56, AgentGatewayRegistryAdminController.java:48).
- `/admin/agent-destinations` is always mapped (AgentDestinationAdminController.java:55-58) and answers 503
  `agent_destinations_admin_disabled` unless OPA is on (or `vgs.agentGateway.admin.allowWithoutOpa=true`) and
  `vgs.agentGateway.db.enabled=true` (AgentDestinationAdminController.java:86-95, AgentDestinationAdminConfig.java:25-39).
  `/admin/functions` and `/admin/agent-gateway-adapters` answer 503 `agent_gateway_admin_disabled` without OPA
  (AgentGatewayRegistryAdminController.java:195-200).

**Error envelope.** `{"errors":[{"status":<int>,"code":"<code>","title":"...","detail":"...","href":"<request url>"}]}`
(RestExceptionHandler.java:253-262). Mapping of exception to status (RestExceptionHandler.java):

| Exception | Status | code | line |
|---|---|---|---|
| `ResourceNotFoundException` | 404 | none (message only) | :81-88 |
| `RevealSessionValidationException(code, detail)` | 400 | the code | :188-194 |
| `AgentGatewayValidationException(code, detail)` | 400 | the code | :264-270 |
| `RevealSessionConflictException` | 409 | `revocation_list_disabled` | :216-223 |
| `RevealSessionNotActiveException` | 409 | `session_not_active` | :235-242 |
| `ApprovalClosedException` | 409 | `approval_closed` | :244-251 |
| `AgentGatewayConflictException(code, detail)` | 409 | the code | :272-278 |
| `RevealSessionCredentialReissueDisabledException` | 404 | `credential_reissue_disabled` | :225-233 |
| `RevealSessionUnavailableException` | 503 | `stateless_unavailable` | :196-203 |
| `AgentGatewayUnavailableException(code, detail)` | 503 | the code | :280-287 |
| `RevealSessionProxyHostUnusableException` | 500 | `reveal_session_proxy_host_unusable` | :205-214 |
| `AgentGatewayScopeException` / `RevealSessionScopeException` | 403 | none; message `The <scope> scope is required` | :296-302, :313-319 |
| `AgentGatewayRouteException` | 403 | `agent_gateway_route` / `agent_gateway_route_field` | :289-294 |
| `PreferencesUnavailableException` | 503 | `preferences_unavailable` | :304-311 |
| any other `Exception` | 500 | none | :321-327 |

Abbreviations used below: **E-SCOPE** = 403 missing scope/role (no code). **E-RES** = 400 `reserved_tenant`
(VgsOwner.java:32). **E-ATTR** = 400 `missing_attributes` ("data.attributes is required"; the check differs per controller,
cited per endpoint). A request body with no `data` at all: `JsonApiResource.data` is `@NotNull @Valid`
(json/JsonApiResource.java:18-20); the 400 handler for `MethodArgumentNotValidException` is declared with a parameter type of
`MethodArgumentTypeMismatchException` (RestExceptionHandler.java:101-114), so its exact response body is UNKNOWN.

**Ids.** Reveal session `RS`+22 base58 (revealsession/RevealSessionService.java:56); approval `AP`+22 base58
(revealsession/ApprovalService.java:24); tenant destination `AGD`+22 base58 of the route UUID (agentgateway/AgentDestinationId.java:10-20);
function `FN`, invocation `FI`, adapter `AD`, adapter destination `AX`, each + 22 base58 (agentgateway/functions/FunctionIds.java:14-17,
:60-69). A malformed id is treated as not found (404) for AGD/FN/AX/FI lookups (AgentGatewayDestinationController.java:165-168,
FunctionService.java:87, AdapterDestinationService.java:222, FunctionInvocationService.java:227); for adapters, `GET` of a
malformed id is 404 (AdapterService.java:101-103) but `POST`/`PATCH /{id}` on a missing/foreign id is 400 `adapter_not_found`
(AdapterService.java:170-175).

---

# 1. Reveal sessions - `/reveal-sessions`

Controller: controller/RevealSessionController.java. Service: revealsession/RevealSessionService.java.
Gate: `vgs.revealSessions.enabled`. Scopes: `reveal-sessions:read` for reads, `reveal-sessions:write` for POST/DELETE;
checked in-controller (RevealSessionController.java:435-444) and by OPA (opa/policies/http/reveal_sessions.rego).

## 1.1 POST /reveal-sessions

- Scope: `reveal-sessions:write` (RevealSessionController.java:104). OPA: reveal_sessions.rego:7-12.
- Query params: none.
- Body: `data.type` unchecked, `data.attributes` = RevealSessionDto (dto/RevealSessionDto.java). Attributes accepted on create:

| Attribute | Type | Req | Rules (cite) |
|---|---|---|---|
| `aliases` | array of Alias | one of `aliases`/`cards` required | `missing_aliases` if both absent/empty (RevealSessionService.java:289-292); total parts (aliases + every card part) <= 20, else `too_many_aliases` (:314-317, constant :41) |
| `aliases[].alias` | string | yes | non-blank, else `invalid_alias` (RevealSessionService.java:741-743); null element `invalid_alias` (SessionParts.java:44) |
| `aliases[].format` | string | yes | `card_number` \| `card_cvc` \| `text` (case-insensitive), else `unknown_format` (RevealSessionService.java:744-749). Old name `category` is refused: `category_renamed` (RevealSessionController.java:291, :325) |
| `aliases[].bin` | string | card_number: required unless alias is a 13-19 digit number | else `missing_bin` (RevealSessionService.java:781-785); bin defaults to alias first 6 digits (:787); card_cvc/text ignore it (revealsession/RevealSessionRequest.java:76-82) |
| `aliases[].length` | integer | no | card_number default = alias length if numeric else 16 (RevealSessionService.java:789-792); card_cvc default 3 (:794); documented 13-19 / 3-4 (RevealSessionRequest.java:76-81), no range check found in the service |
| `aliases[].storage` | string | no | `PERSISTENT` (default) or `VOLATILE`, any case, else `invalid_storage` (RevealSessionService.java:752-762) |
| `aliases[].label` | string | no | text aliases only, else `invalid_label` (SessionParts.java:49-51); `[a-z0-9][a-z0-9_-]{0,31}`, unique in the session, else `invalid_label` (SessionParts.java:29, :52-55) |
| `cards` | array of Card | see above | `card` null -> `invalid_card` (SessionParts.java:63) |
| `cards[].label` | string | required when the session has >1 card | `[a-z0-9][a-z0-9_-]{0,31}`, unique, else `invalid_card_label` (SessionParts.java:66-69) |
| `cards[].number` | Alias | yes | else `missing_card_number` (SessionParts.java:70-72); format forced `card_number` |
| `cards[].cvc` | Alias | no | format forced `card_cvc` |
| `cards[].expiry`, `cards[].holder` | Alias | no | format forced `text` |
| (card parts) | | | A card part that sends a different `format` -> `invalid_card`; a card part with `label` -> `invalid_label` (SessionParts.java:87-95). Parts reuse the Alias fields `alias`, `bin`, `length`, `storage` |
| `allowed_hosts` | string[] | no | each: trimmed, lower-cased, trailing dot removed (RevealSessionLimits.java:73-82); must be an exact hostname: contains a dot, <=253 chars, labels `[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?`, not an IPv4 literal, no port, no wildcard -> else `invalid_host` (RevealSessionLimits.java:84-94, RevealSessionService.java:714-717); a never-host or subdomain of one -> `never_host` (RevealSessionService.java:718-721, revealsession/NeverHostsList.java:8-15); >20 distinct -> `too_many_hosts` (:725-728, constant :42); duplicates collapse (:722) |
| `allowed_client_cidrs` | string[] | no | IPv4/IPv6 address or CIDR, canonicalized (network address, `/prefix`); invalid -> `invalid_client_cidr` (revealsession/ClientCidrs.java:42-92); >64 raw or >10 distinct -> `too_many_client_cidrs` (ClientCidrs.java:16-18, :27-29, :35-38); empty = any client |
| `egress_proxy_settings` | object | no | see 1.1a. Old name `proxy_settings` refused: `proxy_settings_renamed` (RevealSessionController.java:306-309) |
| `context` | map string->string | no | <=32 keys; key `[a-z][a-z0-9_]{0,63}`; value non-null, <=512 chars; keys+values total <=4096 chars (<=1024 in stateless storage) -> else `invalid_context` (SessionParts.java:19-27, :103-130) |
| `adapter` | string | no | AD id or adapter name; resolved to the AD id and only the id is stored (RevealSessionController.java:274-283). Adapters unavailable -> `adapter_unavailable`; not visible -> `invalid_adapter` (:278, :281); non-AD id after resolution -> `invalid_adapter` (SessionParts.java:140-142). Blank = none = session matches every enabled destination (RevealSessionDto.java:89) |
| `ttl_seconds` | integer | **must be absent** | any value -> `ttl_not_configurable` (RevealSessionService.java:691-695) |
| `unlisted_host_mode` | string | **must be absent** | any value -> `unlisted_host_mode_not_configurable` (RevealSessionService.java:293-296) |
| `step_up` | object | **must be absent** | any value -> `step_up_not_configurable` (RevealSessionService.java:297-300) |
| `tokens`, `session_aliases`, `proxy`, `values`, `state`, `created_at`, `expires_at`, `reveal_count`, `refusal_count`, `pending_approvals` | | read-only | response fields. `session_aliases` and `values` are `READ_ONLY` (RevealSessionDto.java:86, :93); the rest have no setter guard, so a value sent is deserialized but UNKNOWN whether it is dropped by the service (the service reads only the fields mapped in `toRequest`, RevealSessionController.java:285-318, so they are ignored) |

  1.1a `egress_proxy_settings` (revealsession/EgressSettings.java:12-43; DTO RevealSessionDto.java:248-268):

| Field | Type | Rules |
|---|---|---|
| `type` | string | must be `custom`, else `invalid_egress_proxy_settings` (:16-19) |
| `scheme` | string | `http` or `https`, else `invalid_egress_proxy_settings` (:20-24) |
| `hostname` | string | public hostname by the allowed-host rules, not a never-host, else `invalid_egress_proxy_hostname` (:25-29) |
| `port` | integer | 1-65535, else `invalid_egress_proxy_port` (:30-33) |
| `username` | string | optional; must be given together with `password`; no `:`; <=256 chars; no control chars -> else `invalid_egress_proxy_credentials` (:34-40, constant :10) |
| `password` | string | **WRITE_ONLY** (RevealSessionDto.java:264); same rules as username; stored with the session, never returned or logged |
| `has_password` | boolean | **READ_ONLY** (RevealSessionDto.java:267), response only |

- Response: **201**, `Location: /reveal-sessions/{id}` (RevealSessionController.java:116-118). Attributes (toDto(created), :357-392):

| Attribute | Notes |
|---|---|
| `state` | `active` (RevealSessionService.java:360, :370) |
| `expires_at` | ISO-8601 instant |
| `allowed_hosts` | normalized list |
| `allowed_client_cidrs` | omitted when empty (:363-364) |
| `unlisted_host_mode` | `strict` \| `guarded` \| `step_up` (lower-cased stored mode, RevealSessionService.java:340-344, :361) |
| `tokens` | array of `{alias, format, value}`, every part including card parts; legacy shape kept for old clients (RevealSessionController.java:366-369). `value` = the session alias handed to the agent. Only create returns `value`s |
| `session_aliases` | `{alias, format, value, label}` for non-card aliases only (:370-373) |
| `cards` | request shape, each part `{alias, format, value}` (`value` READ_ONLY on AliasDto, RevealSessionDto.java:138-139) (:335-355) |
| `proxy` | `{url, ca_bundle, pac_url}` (see 1.8) |
| `egress_proxy_settings` | `{type:"custom", scheme, hostname, port, username, has_password}` - no password (:377-386) |
| `step_up` | `{webhook_url, hold_seconds, webhook_secret}` only when mode is `step_up`; `webhook_secret` appears here only (:387-390, RevealSessionCreated.java:48-56) |

  Not in the create response: `created_at`, `aliases`, `context`, `adapter`, counts.
- Errors: E-SCOPE (403, :104). 400 codes: `missing_attributes` (RevealSessionController.java:108), plus every code in the table above, `unknown_format`,
  `invalid_alias`, `missing_bin`, `invalid_storage`, `session_too_large` (stateless only: `Basic base64(sid:jwe)` > 8192 bytes,
  RevealSessionService.java:353-357, constant :46), `invalid_ttl` (the effective tenant TTL is below 30, :701-705). 503 `stateless_unavailable`
  (storage=stateless without a current JWE key, :286-288). 500 `reveal_session_proxy_host_unusable` (proxy host has `{tenant}` and the tenant is not a DNS label,
  :378-386; `vgs.revealSessions.proxyHost`). 503 `preferences_unavailable` is not raised on this path: a missing preferences response becomes
  `MISSING_PREFERENCES` = STRICT (RevealSessionController.java:264-268, revealsession/AgentGatewayPreferenceRules.java:19-20).

### Reveal session lifecycle, TTL, modes (service facts)

- **States** returned by the API: `active`, `revoked`, `expired` (computed on read: stored `revoked` wins; else `exp <= now` -> `expired`; else `active`)
  (revealsession/RedisRevealSessionRepository.java:426-429). Create sets `active` (:221).
- **TTL.** The caller cannot choose it (`ttl_not_configurable`). Effective TTL = `min(tenantTtl, platformCap)` where
  `tenantTtl` = preference `revealSessionDefaultTtlSeconds` if > 0, else `min(300, revealSessionMaxTtlSeconds)` when the deprecated max > 0, else **300**
  (RevealSessionService.java:690-707; RevealSessionLimits.java:14-15). Minimum **30** s (RevealSessionLimits.java:14); platform cap
  `vgs.revealSessions.maxSessionLifetimeSeconds`, default **86400** (revealsession/RevealSessionRedisConfig.java:158; RevealSessionLimits.java:18); startup fails if the cap < 30
  (RevealSessionService.java:264-267). Preference write rule: 0 or 30..cap (revealsession/RevealSessionPreferenceRules.java:34-49;
  codes `invalid_reveal_session_default_ttl_seconds`, `invalid_reveal_session_max_ttl_seconds`). `revealSessionMaxTtlSeconds` is deprecated (RevealSessionPreferenceRules.java:10-13).
- **Storage** (`vgs.revealSessions.storage`, all tenants): `redis` (default, revocable record, hash TTL = session TTL, RedisRevealSessionRepository.java:154, :202-214) or `stateless`
  (session carried in an encrypted proxy password; no record) (revealsession/SessionStorage.java:12-25).
- **`unlisted_host_mode`** is derived from tenant preferences, never from the request (RevealSessionService.java:634-660):
  1. `agentGatewayAutoGuardedRoutes = true` -> `guarded`.
  2. else if `agentGatewayStepUpWebhookUrl` is non-blank: valid URL and hold (`agentGatewayStepUpHoldSeconds`, 0 -> default 20, otherwise 5..30) -> `step_up`
     (webhook URL normalized); invalid stored step-up settings -> `strict` with a warning.
  3. else `agentGatewayAutoGuardedRoutes = false` explicitly -> `strict`; preference unset -> `guarded`.
  Values: `strict`, `guarded`, `step_up`. Webhook rules: https only, exact public hostname, not a never-host, no userinfo/fragment, port absent or 443, <=2048 chars
  (RevealSessionLimits.java:30-71); write-time codes `invalid_step_up_webhook_url`, `invalid_step_up_hold_seconds`, `invalid_browser_emulation`
  (revealsession/AgentGatewayPreferenceRules.java:36-60). Hold constants: default 20, min 5, max 30 (RevealSessionLimits.java:19-21).
- **allowed_hosts** are exact hostnames only (no wildcard, no port). Limits 20 hosts, 20 parts, 10 CIDRs.
- **Where values live.** Token `value`s (session aliases) exist only in the create response. Values stored by functions with `session.put` are kept as Redis hash fields
  `cap:<adapter id>:<key>` (RedisRevealSessionRepository.java:263-289) and are returned by `GET /reveal-sessions/{id}?include=values` as
  `values: {"<adapter id>": {"<key>": "<value>"}}` (RevealSessionDto.java:82-87). Stateless sessions return `{}`.
- **Request tenant / adapter.** `adapter` is stored by AD id; renaming an adapter never moves a live session (RevealSessionController.java:270-273).
- **Audit.** Create, revoke and decisions publish events; resource audit is off by default (`vgs.agentGateway.audit.resourceAudit.enabled`, RevealSessionService.java:97-104).

## 1.2 GET /reveal-sessions

- Scope: `reveal-sessions:read` (RevealSessionController.java:236). OPA: reveal_sessions.rego:14-19.
- Query: `state` = `active` (default when blank) or `revoked`, case-insensitive; `expired` is not listable -> `invalid_state` (RevealSessionService.java:575-578).
  `offset` default 0, `limit` default 30; `offset >= 0`, `1 <= limit <= 100` else `invalid_paging` (RevealSessionController.java:233-241, MAX :70). The page start is aligned to
  `(offset/limit)*limit` (:244).
- Response: **200**, paged JSON:API list (`meta.total_pages`, `meta.total_elements`, `links`), newest expiry first (RedisRevealSessionRepository.java:367-399). Each item = the read shape in 1.3 (without `values`).
  `state=revoked` with stateless storage lists revocation markers: `state=revoked`, `expires_at`/`created_at` = marker expiry, other fields empty (RevealSessionService.java:580-583; RedisRevealSessionRepository.java:342-360).
- Errors: E-SCOPE; 400 `invalid_state`, `invalid_paging`.

## 1.3 GET /reveal-sessions/{id}

- Scope: `reveal-sessions:read` (RevealSessionController.java:195). OPA: reveal_sessions.rego:21-26.
- Query: `include` comma-separated; only `values` is supported, anything else -> 400 `invalid_include` (RevealSessionController.java:75-77, :210-227).
- Response: **200**. Attributes (toDto(view), :394-433; never token values, password or webhook secret):

| Attribute | Notes |
|---|---|
| `state` | `active` \| `revoked` \| `expired` |
| `pending_approvals` | count of unexpired pending approvals; `0` for non-step-up sessions; omitted (null) if the count could not be read (revealsession/RevealSessionView.java:11, RedisRevealSessionRepository.java:401-421) |
| `step_up` | `{webhook_url, hold_seconds}` (no secret) when step-up |
| `unlisted_host_mode` | `strict` \| `guarded` \| `step_up` |
| `created_at`, `expires_at` | ISO-8601 |
| `allowed_hosts` | list |
| `aliases` | `[{alias, format, storage}]`; `storage` upper-cased (`PERSISTENT`/`VOLATILE`); no values |
| `context` | map; omitted when empty (not secret) |
| `adapter` | AD id or omitted |
| `reveal_count`, `refusal_count` | long counters |
| `allowed_client_cidrs` | omitted when empty |
| `egress_proxy_settings` | `{type:"custom", scheme, hostname, port, username, has_password}`; no password |
| `values` | **READ_ONLY**, only with `include=values` (RevealSessionController.java:201-203) |

  Not returned on read: `proxy`, `tokens`, `session_aliases`, `cards`.
- Errors: E-SCOPE; 400 `invalid_include`; 404 `Reveal session not found` (no code; unknown id, other tenant's id, **or a stateless session**, which has no record)
  (:198-199; RevealSessionService.java:547-549).

## 1.4 DELETE /reveal-sessions/{id}

- Scope: `reveal-sessions:write` (RevealSessionController.java:257). OPA: reveal_sessions.rego:28-33.
- Response: **204**, no body (:255).
- Behaviour (RevealSessionService.java:587-626): if a Redis record exists, it is marked `revoked` in place (hash kept until its original expiry; moved from the active to the revoked index;
  repeating it is idempotent -> 204) (RedisRevealSessionRepository.java:157-166, :293-298). If no record exists and the tenant preference `revealSessionRevocationList` is true, **any well-formed `RS` id**
  gets a stateless revocation marker and the call returns 204 (marker TTL = `maxSessionLifetimeSeconds + 60`, :617-621); a malformed id -> 404. If no record and the list is off: 409
  `revocation_list_disabled` when platform storage is stateless, else 404.
- Errors: E-SCOPE; 404 `Reveal session not found` (:260); 409 `revocation_list_disabled` (RevealSessionService.java:609-611).

## 1.5 POST /reveal-sessions/{id}/credentials (reissue proxy credentials)

- Scope: `reveal-sessions:write` (RevealSessionController.java:177). OPA: reveal_sessions.rego:35-40.
- Body: none read. Gate: `vgs.revealSessions.credentialReissueEnabled` (default false) (revealsession/RevealSessionRedisConfig.java:163).
- Response: **200** (not 201). Attributes: `state: "active"`, `expires_at` (unchanged), `proxy: {url, ca_bundle, pac_url}` with a new password (RevealSessionController.java:181-187). Replaces the SHA-256 of the stored secret;
  the old password stops working for new proxy connections only (resources/application.yaml:243-247). Redis sessions only.
- Errors: E-SCOPE; 404 `credential_reissue_disabled` (flag off, RevealSessionService.java:513-515); 404 `Reveal session not found` (unknown, other tenant, or stateless; :179-180, :518-520);
  409 `session_not_active` (state `revoked` or `expired`, :522-524, :536-537); 500 `reveal_session_proxy_host_unusable`.

## 1.6 GET /reveal-sessions/proxy-ca

- Scope: `reveal-sessions:read` (RevealSessionController.java:159). Literal path, never a session id (:154). OPA: matches `GET /reveal-sessions/:id` (reveal_sessions.rego:21-26).
- Response: **200**, type `reveal-session-proxy-ca`, `data.id` = `proxy-ca`, attributes `host`, `scheme`, `port`, `ca_bundle` (PEM) (dto/RevealSessionProxyCaDto.java:19-31;
  RevealSessionService.java:493-499). `host` has `{tenant}` expanded (`vgs.revealSessions.proxyHost`).
- Errors: E-SCOPE; 404 `No forward proxy CA bundle is configured` (`vgs.revealSessions.proxyCaBundlePath` blank, RevealSessionController.java:164-165).

## 1.7 GET /reveal-sessions/{id}.pac (PAC file)

- Auth: **none** - no token, no tenant header, no OPA (SecurityConfig.java:84-87; resources/application.yaml:362-364; helpers/Endpoints.java:22-23). Spring does not match suffixes, so the path is
  mapped explicitly (RevealSessionController.java:121-127). The pre-signed query is the credential.
- Query (all required; any problem is a silent 404): `tenant` (<=128 chars), `expires` (epoch seconds, `[1-9][0-9]{0,11}`, must be in the future), `signature` (43 chars `[A-Za-z0-9_-]`, base64url HMAC-SHA256 with no padding of
  `"pac/v1\n"+tenant+"\n"+id+"\n"+expires`) (RevealSessionService.java:61-64, :401-418; revealsession/PacLinks.java:14-16, :107-120). The link is issued in `proxy.pac_url`
  with `expires` = session expiry (RevealSessionService.java:339, PacLinks.java:102-105: `<pacBaseUrl>/reveal-sessions/{id}.pac?tenant=..&expires=..&signature=..`).
- Response: **200**, `Content-Type: application/x-ns-proxy-autoconfig`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, body = PAC script `FindProxyForURL(url, host)` (RevealSessionController.java:144-148). Script:
  all requests via the VGS proxy directive (`PROXY host:port`, or `HTTPS host:port` when `proxyScheme=https`), or, for a live Redis session, a split: the session's `allowed_hosts` plus the `when.host` of the tenant's enabled
  adapter destinations go to VGS, every other host goes to the session's egress proxy or `DIRECT`. Stateless sessions, a failed host lookup and an unsafe pattern send everything through VGS
  (RevealSessionService.java:449-482; revealsession/SessionPac.java:11-18, :37-65; revealsession/AwgPacHostSources.java). The script carries no credentials.
- Errors: every failure is **404 with an empty body** and no code: PAC off (`vgs.revealSessions.pacSigningKey` blank), malformed parameters, expired link, bad signature, session not `active`, stateless marker revoked, tenant not usable
  for the proxy host, unsafe host, or an exception (RevealSessionController.java:133-143; RevealSessionService.java:401-447; reasons are logged only).

## 1.8 `proxy` object (create and reissue responses only)

`{url, ca_bundle, pac_url}` (RevealSessionDto.java:210-246). `url` = `<scheme>://<session id>:<secret>@<host>:<port>` with RFC 3986 userinfo percent-encoding; the secret is returned only here and on reissue
(revealsession/ProxyUrl.java:1-21, RevealSessionCreated.java:85-97). `ca_bundle` = PEM of the forward proxy CA(s), omitted when not configured. `pac_url` = pre-signed PAC link, omitted when PAC is off. In stateless storage the
"secret" is the encrypted session token (RevealSessionService.java:362-363).

---

# 2. Reveal session approvals - `/reveal-session-approvals`

Controller: controller/RevealSessionApprovalController.java. Service: revealsession/ApprovalService.java. Gate `vgs.revealSessions.enabled` (:39). Approvals are written by the proxy when a `step_up` session meets an unlisted host
and the request is held; they are listed and decided here. Read scope `reveal-sessions:read` (:124-132), decide scope `reveal-sessions:write`. OPA: reveal_sessions.rego:42-61.

Approval attributes (dto/ApprovalDto.java; built at RevealSessionApprovalController.java:108-121): `reveal_session_id`, `host`, `method`, `path`, `state` (`pending` \| `approved` \| `denied` \| `expired`; a pending approval past `expires_at` reads as `expired`, revealsession/ApprovalRepository.java:126-129),
`scope` (null until decided: `request` or `session`), `requested_at`, `expires_at`, `decided_at` (null until decided).

## 2.1 GET /reveal-session-approvals

- Scope: `reveal-sessions:read` (:57).
- Query: `filter[reveal_session]` **required** (blank/absent -> 400 `missing_filter`, :58-61); `offset` (default 0), `limit` (default 30, 1..100) else `invalid_paging` (:62-66).
- Response: **200**, paged list, newest first, expired hashes skipped (ApprovalService.java:48-59; ApprovalRepository.java:81).
- Errors: E-SCOPE; 400 `missing_filter`, `invalid_paging`; 404 `Reveal session not found` when the id is not `RS`+22 base58 (ApprovalService.java:53-55). Works for stateless session ids too if well-formed.

## 2.2 GET /reveal-session-approvals/{id}

- Scope: `reveal-sessions:read` (:79). Response **200** one approval. Errors: E-SCOPE; 404 `Approval not found` (malformed id, or unknown; ApprovalService.java:62-68).

## 2.3 PATCH /reveal-session-approvals/{id}

- Scope: `reveal-sessions:write` (:89).
- Body: `data.type` must be `reveal-session-approvals` (`invalid_type`, :95-97); `data.id` must equal the path id (`id_mismatch`, :98-101); `data.attributes` required (`missing_attributes`, :90-94).

| Attribute | Type | Req | Rules |
|---|---|---|---|
| `state` | string | yes | `approved` or `denied` (case-insensitive), else `invalid_state` (ApprovalService.java:80-83) |
| `scope` | string | no | `request` (default) or `session`, else `invalid_scope` (:84-88). `session` + `approved` approves the host for the rest of the session (ApprovalRepository.java:18, :40); `denied` always stores `request` (:92) |

- Response: **200**, the updated approval. Decision publishes a `RevealSessionAudit` (STEP_UP_APPROVED/DENIED) and an AWG step-up operation event (ApprovalService.java:105-112).
- Errors: E-SCOPE; 400 `missing_attributes`, `invalid_type`, `id_mismatch`, `invalid_state`, `invalid_scope`; 404 `Approval not found` (:89-90, :95, :97-99); 409 `approval_closed` (already `approved`/`denied`/`expired`;
  `detail` carries the state) (:100-102, ApprovalClosedException.java:9).

---

# 3. Tenant agent destinations - `/agent-gateway-destinations`

Controller: controller/AgentGatewayDestinationController.java; store agentgateway/AgentDestinationStore.java. Gate `vgs.agentGateway.enabled=true`. A destination is a row in `agent_gateway.tenant_agent_destination` plus a
forward-proxy route (kind AGENT_GATEWAY); `route_id` is that route's UUID (:49-54). Scopes `agent-gateway:read` / `agent-gateway:write`; OPA agent_gateway.rego:7-40. Max **1000** per tenant (:61).

Attributes (dto/AgentGatewayDestinationDto.java): `host_pattern` (string), `action` (`trust` \| `guarded` \| `block`, case-insensitive on input; invalid -> `invalid_action`, agentgateway/AgentDestinationRules.java:41-43, :50-59),
`origin` (`manual` \| `auto`; **read-only**: sending it -> 400 `origin_not_writable`, :170-174), `route_id`, `created_by`, `promoted_by`, `promoted_at` (all READ_ONLY, DTO :30-40; `promoted_by/at` = who approved a `trust`,
AgentDestinationStore.java:153-165), `created_at`, `updated_at`.
Enum definitions (`TenantAgentDestinationAction`, `TenantAgentDestinationOrigin`) are in a library outside this repo: UNKNOWN beyond the constants TRUST, GUARDED, BLOCK / MANUAL, AUTO used in this repo.

## 3.1 GET /agent-gateway-destinations
- Scope: `agent-gateway:read` (:73). No params, not paged. Response **200** list. Errors: E-SCOPE, E-RES.

## 3.2 GET /agent-gateway-destinations/{id}
- Scope: `agent-gateway:read` (:82). Response **200**. Errors: E-SCOPE, E-RES; 404 `Agent gateway destination not found` (non-AGD id, unknown, or row whose route is gone; :165-168, AgentDestinationStore.java:288-289).

## 3.3 POST /agent-gateway-destinations
- Scope: `agent-gateway:write` (:91).
- Body: `host_pattern` (required), `action` (required); `origin` must be absent. Other read-only fields ignored.
- Response: **201**, `Location: /agent-gateway-destinations/{id}`; `origin` = `manual`; a `trust` records the caller (email / preferred_username / sub) as approver (:115-116, :204-216).
- Errors: E-SCOPE, E-RES; 400 `missing_attributes` (:94, :97, :181), `invalid_host_pattern` (AgentDestinationRules.java:21), `invalid_action` (:42), `never_host` (non-block action on a never-host,
  AgentDestinationRules.java:26-31; a `block` may name one), `origin_not_writable` (:172), `too_many_destinations` (:107); 409 `destination_exists` (same `host_pattern`, incl. racing creates, :111, :119, :184-187);
  400 `InvalidPayloadException` from route validation (AgentDestinationStore.java:296-315; no code); route limit via `limitChecker` (AgentDestinationStore.java:140) - exception class UNKNOWN (external).
  Pattern grammar (`AgentDestinationPattern.parse`): UNKNOWN (class outside this repo; `*.suffix` and exact host are the two forms the proxy matcher has, per revealsession/SessionPac.java:11-12).

## 3.4 PATCH /agent-gateway-destinations/{id}
- Scope: `agent-gateway:write` (:131).
- Body: `action` required; `host_pattern` must be absent (400 `host_pattern_immutable`, :134-137); `origin` must be absent. Sets `origin` to `manual` ("a person decided", :126). The route's `vgs-reveal-guard` tag follows the action
  (guarded sets it; trust/block remove it) (AgentDestinationStore.java:187-207, :263-268).
- Response: **200**. Errors: E-SCOPE, E-RES; 400 `missing_attributes` (:140), `invalid_action`, `host_pattern_immutable`, `origin_not_writable`, `never_host` (changing a block on a never-host to trust/guarded, :145-148),
  `route_tag_limit` (guarded needs one more tag than a route may carry, AgentDestinationStore.java:208); 404 not found (:144, :189).

## 3.5 DELETE /agent-gateway-destinations/{id}
- Scope: `agent-gateway:write` (:156). Response **204**. Deletes the route, then the row (AgentDestinationStore.java:216-229). Errors: E-SCOPE, E-RES; 404 not found. No in-use check was found on this path
  (adapter destinations that name the host are not checked here): see UNKNOWN list.

# 4. VGS registry as a tenant sees it - `/agent-gateway-registry`

## 4.1 GET /agent-gateway-registry
- Controller: controller/AgentGatewayRegistryController.java. Scope `agent-gateway:read` (:43). OPA agent_gateway.rego:42-47. Read-only. No params.
- Response: **200** list of `agent-gateway-registry-entries` (dto/AgentGatewayRegistryEntryDto.java): `id` (UUID of the registry row), `host_pattern`, `action` (`guarded` if registry mode is GUARDED, else `trust`)
  (:51-58). Only entries with status ACTIVE and a non-null mode (:45).
- Errors: E-SCOPE.

---

# 5. Admin (VGS staff) agent destination registry - `/admin/agent-destinations`

Controller: controller/AgentDestinationAdminController.java. Tenant-less. Auth: client role of `vault-mgmt-http-api` (see section 0); OPA admin_access.rego:72-76. Every request first runs `requireEnabled` (503
`agent_destinations_admin_disabled`, :86-95). A registry entry is trusted for every tenant (AgentDestinationAdminConfig.java:21-24).

Attributes (dto/AgentDestinationDto.java): `host_pattern`, `mode` (`trusted` \| `guarded`, lower-cased enum name; constants TRUSTED/GUARDED seen in this repo, full enum UNKNOWN), `status` (`active` \| `disabled`;
default ACTIVE on create), `created_by`, `created_at`, `updated_at` (no READ_ONLY annotation on the DTO; server-set). `data.id` = UUID. `updated_by` is written (V1_5) but not exposed
(agentgateway/AgentDestinationRegistryWriter.java:18-31).

| # | Method path | Role | Body | Response | Errors (all also 403 role, 503 disabled) |
|---|---|---|---|---|---|
| 5.1 | GET /admin/agent-destinations | read (:100, :188) | - | 200 list | - |
| 5.2 | GET /admin/agent-destinations/{id} | read (:108) | - | 200 | 404 `Agent destination not found` (:209-211); `{id}` is a UUID path variable, a non-UUID is 400 from type mismatch (RestExceptionHandler.java:101-113) |
| 5.3 | POST /admin/agent-destinations | write (:117, :191-194) | `host_pattern` + `mode` required, `status` optional | 201 + `Location /admin/agent-destinations/{uuid}` | 400 `missing_attributes` (:120, :123, :200), `invalid_host_pattern`, `never_host` (:126), `invalid_mode`, `invalid_status` (AgentDestinationRules.java:33-39); 409 `destination_exists` (:131, :138, :204-207) |
| 5.4 | PATCH /admin/agent-destinations/{id} | write (:151) | `mode` and/or `status`; `host_pattern` forbidden | 200; records caller as `updated_by` in the same transaction | 400 `host_pattern_immutable` (:154), `missing_attributes` "mode or status is required" (:158), `invalid_mode`, `invalid_status`; 404 behaviour of `AgentDestinationService.update` UNKNOWN (class outside this repo) |
| 5.5 | DELETE /admin/agent-destinations/{id} | write (:173) | - | 204 (hard delete; only an INFO log line records the actor, :178-184) | 404 behaviour of `AgentDestinationService.delete` UNKNOWN |

---

# 6. Functions - `/functions`

Controller: controller/FunctionController.java; service agentgateway/functions/FunctionService.java. Gate `vgs.agentGateway.enabled=true`. A function's code is **immutable**: its id is its version; a new version is a new function
that may name its predecessor in `previous_version` (FunctionController.java:41-45, AgentGatewayFunction.java:10-13). A tenant sees its own functions and the VGS-owned ones (JdbcFunctionStore.java:78-87). Storage:
`vgs.agentGateway.functionStorage` = `postgres` (default) or `redis` (agentgateway/functions/FunctionStorage.java:14-24).

Function attributes (dto/FunctionDto.java): `name`, `language` (`larky`), `source`, `extension_point`, `inputs` (`[{name, required}]`), `previous_version`, and READ_ONLY (DTO :38-63): `sha256` (hex SHA-256 of source),
`owner` (`vgs` \| `tenant`), `created_by`, `created_at`, `status` (`ACTIVE` \| `DISABLED`; upper-case), `updated_by`, `updated_at`. `id` = `FN...`. A deleted function is never returned.

**Extension points** (agentgateway/functions/AgentGatewayFunction.java:68-72): `route.request`, `route.response`, `invoke`. These are the only three. `route.request`/`route.response` functions run at the proxy in a destination's route
(request phase / response phase, destinations/DestinationRoutes.java:103); `invoke` functions run only through the invocations API and cannot be bound to a destination (AdapterDestinationService.java:155-158, :330-333).

## 6.1 GET /functions
- Scope `agent-gateway:read` (FunctionController.java:61). Query `filter[name]` (exact name). Response **200**, own + VGS functions, newest first, max **200** (JdbcFunctionStore.java:101, FunctionService.java:37). Errors: E-SCOPE, E-RES.

## 6.2 GET /functions/{id}
- Scope `agent-gateway:read` (:68). Response **200**. Errors: E-SCOPE, E-RES; 404 `Function not found` (:133-135; malformed id, other tenant's, deleted).

## 6.3 POST /functions
- Scope `agent-gateway:write` (:75).
- Body:

| Attribute | Type | Req | Rules |
|---|---|---|---|
| `name` | string | yes | stripped, 1..255 chars, else `invalid_name` (FunctionService.java:112-118). No uniqueness check found (see UNKNOWN) |
| `language` | string | no | default and only value `larky`, else `invalid_language` (:69-72) |
| `extension_point` | string | yes | `route.request` \| `route.response` \| `invoke`, else `invalid_extension_point` (:73-76) |
| `source` | string | yes | non-blank (`invalid_source`, :121-123); <= 262144 UTF-8 bytes (`source_too_large`, :124-126, constant :35); must not contain `${` (`invalid_source`, :127-130); must parse as Larky (`invalid_source` with the parser message, :131-133; agentgateway/functions/FunctionSourceValidator.java:37-41). A function must reach vault via `load("@vgs//vault", "vault")`, the global is refused (:33-35, :47-48); `adapter_input` is predeclared (:49-51) |
| `inputs` | `[{name, required}]` | no | <= 32; `name` `[a-z][a-z0-9_]{0,63}`, unique, else `invalid_inputs` (:137-155); `required` defaults false (FunctionController.java:105) |
| `previous_version` | string | no | must be an FN id of the caller's own function, else `invalid_previous_version` (:160-170) |

- Response: **201**, `Location: /functions/{id}`. Errors: E-SCOPE, E-RES; 400 `missing_attributes` (FunctionController.java:79) + the codes above.

## 6.4 DELETE /functions/{id}
- Scope `agent-gateway:write` (:94). Response **204**. Soft delete (`deleted_at`, `deleted_by`) of the caller's own function only (JdbcFunctionStore.java:104-122). Errors: E-SCOPE, E-RES; 404 `Function not found` (unknown, malformed id, already deleted,
  **or a VGS-owned function**: owner mismatch gives NOT_FOUND, :95-97); 409 `function_in_use` while any version of a not-deleted adapter bundles it (FunctionService.java:105-108; SQL JdbcFunctionStore.java:113-115).

---

# 7. Function invocations - dry runs - `/functions/{id}/invocations`, `/function-invocations`

Controller: controller/FunctionInvocationController.java; service agentgateway/invocations/FunctionInvocationService.java. Gate `vgs.agentGateway.enabled=true`. Runs go to Compute (atlas-horizon) with a **10 s deadline**
(FunctionInvocationService.java:62). Input and output are **not stored** (agentgateway/invocations/FunctionInvocation.java:5-8).

Attributes (dto/FunctionInvocationDto.java). Request (all WRITE_ONLY): `input` (string, invoke only), `request` {`method`, `url`, `headers`, `body`}, `response` {`status`, `headers`, `body`}, `destination` (AX id), `inputs` (map name->string constant),
`session` {`values`, `context`}. Response (READ_ONLY): `function` (FN id), `source` (`api` \| `test`), `dry_run` (boolean), `status` (`succeeded` \| `failed`), `error`, `duration_ms`, `result`, `created_by`, `created_at`. `id` = `FI...`.

## 7.1 POST /functions/{id}/invocations
- Scope `agent-gateway:write` (FunctionInvocationController.java:53). OPA agent_gateway.rego:154-159. The function may be the tenant's or a VGS one (FunctionInvocationService.java:148).
- Request shape per extension point (FunctionInvocationService.java:272-311):
  - `invoke`: `input` required; `request` / `response` forbidden -> 400 `invalid_invocation`. Recorded `source=api`, `dry_run=false`. Runs `function.source()` directly. No session is given (session calls fail, as off reveal-session traffic, :336-340).
  - `route.request`: `request` required with `method` and an absolute `http://`/`https://` `url`; `response` and `input` forbidden. Dry run, `source=test`, `dry_run=true`, sends nothing upstream.
  - `route.response`: **`response` only** with `status` 100..599; `request` and `input` are rejected (`a route.response function takes response only, not request or input`, :298-301). Dry run.
  - Each body <= 1 MiB (`invalid_invocation`, :313-318; `MAX_BODY` :63).
- Inputs of a route function (not for `invoke`): `destination` (AX id; uses that destination's bindings for this function; combining with `inputs` -> `invalid_invocation` "send destination or inputs, not both"; unknown AX or function not at that destination ->
  `invalid_invocation`) or `inputs` as string constants (each <= 4096 chars, no `${`, no control chars -> `invalid_inputs`; missing required input, or a name the function does not declare -> `invalid_inputs`) (:237-270).
- `session` (dry run of a route function only): `values` for `session.get(key)` and captured-value (`session.value`) inputs, `context` for `session.context(key)`. A dry run has no reveal session: without `session` every read is `None`; **`session.card` and
  `session.alias` always fail** in a dry run (documented at dto/FunctionInvocationDto.java:48-52 and FunctionInvocationService.java:87-91; enforced by Compute, which is outside this repo: UNKNOWN beyond these comments).
- Response: **201**, `Location: /function-invocations/{id}` (FunctionInvocationController.java:66). The run is recorded even when it fails: a failure is **201** with `status=failed` and `error` = `<status>: <message>`, `TIMEOUT: ...` or
  `UPSTREAM_ERROR: ...` (:169-189). `result` (only on this response, and only when the run returned something; controller :62-65):

| `result` field | Notes |
|---|---|
| `output` | string, for `invoke` (or bytes decoded as UTF-8) |
| `request` | {`method`, `url`, `headers`, `body`} the rewritten request (route.request) |
| `response` | {`status`, `headers`, `body`} the rewritten response (route.response) |
| `session.values` | dry runs of route functions: the session values after the run = the given ones plus the function's `session.put`s; only when Compute returned them (older Compute: omitted). `session.context` is not echoed. A failed run returns none (:107-111, :198-213) |

- Errors: E-SCOPE, E-RES; 400 `missing_attributes` (controller :56), `invalid_invocation`, `invalid_inputs`, `invalid_function` (generated script could not be built, :218-224); 404 `Function not found` (:148-149); 503 `invocations_unavailable`
  (no Compute client, :150-153; or interrupted, :185).

## 7.2 GET /function-invocations
- Scope `agent-gateway:read` (:75). Query `filter[function]` (FN id), `filter[source]` (`api` \| `test`, else 400 `invalid_filter`, FunctionInvocationService.java:231-233). Newest first, max **100** (agentgateway/invocations/FunctionInvocationStore.java:13;
  JdbcFunctionInvocationStore.java:63). Response **200**; `result` is never present. Errors: E-SCOPE, E-RES; 400 `invalid_filter`.

## 7.3 GET /function-invocations/{id}
- Scope `agent-gateway:read` (:83). Response **200** (no `result`). Errors: E-SCOPE, E-RES; 404 `Function invocation not found` (:85; id must start with `FI`, FunctionInvocationService.java:226-228).

---

# 8. Adapters - `/agent-gateway-adapters`

Controller: controller/AgentGatewayAdapterController.java; service agentgateway/adapters/AdapterService.java. Gate `vgs.agentGateway.enabled=true`. An adapter is a named bundle of functions with **numbered, immutable versions**
(adapters/Adapter.java:8-12). Versions only get inserted (JdbcAdapterStore.java:27-29). Stored by `tenant_id`; VGS-owned = `tenant_id` `vgs`.

**Version model.** Create = version 1. `POST /{id}` adds version `latest+1` (optimistic: `latest_version` must be unchanged else 409). `PATCH /{id}` with `publish_at` makes the **latest** version live: `now` (or a past time) sets `published_version = latest`
and clears any schedule; a future time sets `scheduled_version = latest` and `scheduled_at` (JdbcAdapterStore.java:98-114; AdapterService.java:206-221). The version in effect is the scheduled version once `scheduled_at <= now`, else `published_version`
(adapters/Adapter.java:45-53) - returned as `published_version`.
- **Tenant's own adapter**: the tenant sees (and an adapter destination may pin) any version up to `latest_version`, published or not (AdapterService.java:125-129, :144-146). `published_version` is informational for own adapters.
- **VGS adapter**: a tenant sees it only once it has an effective version, and only up to that version; `latest_version`, `scheduled_version`, `scheduled_at` are hidden from tenants (AgentGatewayAdapterController.java:135-149,
  AdapterService.java:142-151). The admin API shows them (`registry=true`).
- `functions` / `version` in a response = the version shown: latest for the tenant's own adapter, the effective one for a VGS adapter (DTO comment :25-26).

Attributes (dto/AgentGatewayAdapterDto.java): `name`, `functions` (FN ids), `publish_at` (**WRITE_ONLY**, PATCH only), READ_ONLY: `version`, `latest_version`, `published_version`, `scheduled_version`, `scheduled_at` (ISO with `Z`), `owner` (`vgs` \| `tenant`),
`created_by`, `created_at`, `updated_at`, `status` (`ACTIVE` \| `DISABLED`), `updated_by`.

## 8.1 GET /agent-gateway-adapters
- Scope `agent-gateway:read` (AgentGatewayAdapterController.java:57). Response **200**: tenant's own + published VGS adapters, ordered by name, id (JdbcAdapterStore.java:122-130). Errors: E-SCOPE, E-RES.

## 8.2 GET /agent-gateway-adapters/{id}
- Scope `agent-gateway:read` (:64). Response **200**. Errors: E-SCOPE, E-RES; 404 `Adapter not found` (malformed id, unknown, deleted, or an unpublished VGS adapter) (:65-66; AdapterService.java:100-105).

## 8.3 POST /agent-gateway-adapters (create)
- Scope `agent-gateway:write` (:73).
- Body: `name` (required, stripped, 1..255, else `invalid_name`, AdapterService.java:177-184); `functions` (required): 1..32 unique FN ids, each visible to the tenant (its own or VGS-owned), else `invalid_functions` (:190-203; MAX :32).
- Response: **201**, `Location: /agent-gateway-adapters/{id}`; version 1; `published_version` absent until published.
- Errors: E-SCOPE, E-RES; 400 `missing_attributes` (:127), `invalid_name`, `invalid_functions`; 409 `adapter_exists` (duplicate name; AdapterService.java:70; the Redis store enforces it per owner, RedisAdapterStore.java:140-147; the Postgres constraint is in another repo: UNKNOWN).

## 8.4 POST /agent-gateway-adapters/{id} (new version)
- Scope `agent-gateway:write` (:88). Body: `functions` only (same rules); `name` must be absent (400 `name_immutable`, :90-92).
- Response: **200** (not 201), the adapter at the new latest version. Not published until PATCHed.
- Errors: E-SCOPE, E-RES; 400 `missing_attributes`, `name_immutable`, `invalid_functions`, `adapter_not_found` ("No adapter of yours has this id; VGS registry adapters are read-only", AdapterService.java:170-175); 409 `adapter_version_conflict`
  (concurrent version, AdapterService.java:82-85).

## 8.5 PATCH /agent-gateway-adapters/{id} (publish)
- Scope `agent-gateway:write` (:103). Body: `publish_at` only; `name` or `functions` present -> 400 `invalid_attributes` (:105-108). `publish_at` = `now`, or an ISO-8601 date-time with offset; a time not after now publishes immediately (AdapterService.java:206-221).
- Response: **200**. Errors: E-SCOPE, E-RES; 400 `missing_attributes`, `invalid_attributes`, `invalid_publish_at` (blank/unparsable, :208, :217), `adapter_not_found`.

## 8.6 DELETE /agent-gateway-adapters/{id}
- Scope `agent-gateway:write` (:119). Response **204**. Soft delete (`deleted_at`/`deleted_by`) of the caller's own adapter; the name is free again afterwards (the live-name rule applies to non-deleted rows; JdbcAdapterStore.java:140-157, agentgateway/LifecycleStatus.java:4-7).
- Errors: E-SCOPE, E-RES; 404 `Adapter not found` (unknown, malformed, already deleted, **or a VGS adapter**: owner mismatch); 409 `adapter_in_use` while any live adapter destination (any vault) references the adapter (AdapterService.java:164-166; SQL JdbcAdapterStore.java:148-150).

---

# 9. Adapter destinations - `/agent-gateway-adapter-destinations`

Controller: controller/AgentGatewayAdapterDestinationController.java; service agentgateway/destinations/AdapterDestinationService.java. Gate `vgs.agentGateway.enabled=true`. An adapter destination connects one **pinned adapter version** to traffic:
`when` (host/method/path) selects requests, `functions` lists which of the version's functions run and where each input comes from (agentgateway/destinations/AdapterDestination.java:11-13). Saving writes managed rule entries into the route of the
tenant agent destination named by `when.host` (destinations/DestinationRoutes.java:59-90); a disabled destination's entries are removed. Max **100** per vault (AdapterDestinationService.java:48, :115-118).

Attributes (dto/AgentGatewayAdapterDestinationDto.java): `adapter` (AD id or name on input; always the AD id on output), `adapter_version` (integer), `enabled` (boolean, default true on create), `when` {`host`, `method`, `path`}, `functions`
[{`id`, `inputs`, `extension_point` (READ_ONLY, `route.request`/`route.response`, from the function)}], READ_ONLY: `revision` (starts 1, +1 per update), `created_by`, `updated_by`, `created_at`, `updated_at`. `id` = `AX...`.

`when` rules (AdapterDestinationService.java:266-290): `host` required (stripped, lower-cased), a host name or `*.` pattern (<=253 chars, valid labels, contains a dot), else `host_required` / `invalid_when`; `method` optional, one of GET POST PUT PATCH DELETE HEAD OPTIONS
(case-insensitive) else `invalid_when`; `path` optional, starts with `/`, <=1024, no whitespace, `?`, `#`, `${`, nor any of `\ [ ] ^ "`; `*` matches any characters, else `invalid_when`.
`when.host` must be one of the vault's agent destinations (exact pattern, else the longest covering `*.` pattern) that is not blocked: `unknown_host`, `destination_blocked` (:296-311).

`functions[].inputs` (map input name -> source), checked against the function's declared inputs (:340-363): every required input mapped, no undeclared names, else `invalid_inputs`. Sources (`from`) (:365-400):

| `from` | Fields | Phase |
|---|---|---|
| `request.body` / `response.body` | `path` (JSON path: `$` then `.key`, `['key']`, `[index]`) | request function reads request.*, response function reads response.* (else `invalid_inputs`) |
| `request.header` / `response.header` / `request.query` | `name` (header token <=256) | same phase rule |
| `constant` | `value` (<=4096 chars, no `${`, no control chars except \n \r \t) | any |
| `session.value` | `key` `[a-z][a-z0-9_]{0,63}` (value captured by a response function's `session.put`) | only when `vgs.agentGateway.sessionValueInputs=true`, else `input_source_unsupported` (:107-110, :388-393) |

Any other field on a source, or an unknown `from`, is `invalid_inputs`.

## 9.1 GET /agent-gateway-adapter-destinations
- Scope `agent-gateway:read` (:59). Query `filter[adapter]` (AD id or name; unknown adapter -> empty list, AdapterDestinationService.java:228-233). Response **200**, ordered by `created_at, id` (JdbcAdapterDestinationStore.java:82). Errors: E-SCOPE, E-RES.

## 9.2 GET /agent-gateway-adapter-destinations/{id}
- Scope `agent-gateway:read` (:67). Response **200**. Errors: E-SCOPE, E-RES; 404 `Adapter destination not found` (:68-69).

## 9.3 POST /agent-gateway-adapter-destinations
- Scope `agent-gateway:write` (:76).
- Body: `adapter` (AD id or name; own adapter wins over a VGS adapter of the same name) or, if omitted, exactly **one** function in `functions` and no `adapter_version` - the service then creates/reuses the tenant's adapter `fn-<FN id>` holding that function
  (AdapterDestinationService.java:51-54, :141-174); `adapter_version` (default: own adapter -> latest; VGS adapter -> effective version, :235-242); `enabled` (default true); `when` (required); `functions` (1..16, unique FN ids).
- Response: **201**, `Location: /agent-gateway-adapter-destinations/{id}`, `revision` 1.
- Errors: E-SCOPE, E-RES; 400 `missing_attributes` (:101), `too_many_destinations` (:116), `invalid_adapter` (:144), `adapter_required` (:149), `invalid_functions` (:155, :157 invoke function, :315, :322, :331), `invalid_adapter_version`
  (version missing, above the visible limit, or a VGS version not yet effective; :239, :252), `host_required`/`invalid_when`/`unknown_host`/`destination_blocked`, **`function_not_in_adapter`** (a bound function id is not in the pinned version, or not visible; :324-330),
  `invalid_inputs`, `input_source_unsupported`, **`destination_overlap`** (409, see below), `adapter_conflict` (409, `fn-<FN>` adapter no longer holds only that function, :169-172). Route write failures (e.g. route limits, validation) roll the destination back and propagate (:125-131).
- **`destination_overlap`** (409, AdapterDestinationService.java:418-431): for an *enabled* destination, another enabled destination of the same vault that has a function in the **same phase** (`route.request` or `route.response`) and whose `when` can match the same request
  (hosts equal or covering `*.` patterns, method equal or either null, paths equal or glob-compatible) is refused. The check is conservative: it may reject conditions that never meet (agentgateway/destinations/DestinationOverlap.java:5-9). Disabled destinations are skipped.

## 9.4 PATCH /agent-gateway-adapter-destinations/{id}
- Scope `agent-gateway:write` (:86). Body: any of `adapter_version`, `enabled`, `when`, `functions` (a null/absent field keeps its value; `functions` replaces the whole list); `adapter` may be sent only if it equals the current one (else 400 `adapter_immutable`,
  AdapterDestinationService.java:182-185). Moving `adapter_version` is the upgrade path; functions are re-checked against the new version (`function_not_in_adapter` if one is not in it).
- Response: **200**, `revision` incremented. Optimistic locking on `revision`.
- Errors: E-SCOPE, E-RES; 404 `Adapter destination not found` (:181); 400 `adapter_immutable`, `invalid_adapter` ("the destination's adapter is no longer visible", :187), plus all 9.3 validation codes; 409 `concurrent_change` (:196), `destination_overlap`. If the route write fails the destination is restored (new revision)
  and the error is rethrown (:198-206).

## 9.5 DELETE /agent-gateway-adapter-destinations/{id}
- Scope `agent-gateway:write` (:93). Response **204**. Removes the destination's route entries, then the row (AdapterDestinationService.java:213-219). Errors: E-SCOPE, E-RES; 404 `Adapter destination not found`.

---

# 10. Admin registry of VGS functions and adapters

Controller: controller/AgentGatewayRegistryAdminController.java. Same calls as the tenant API but without a vault; the owner is always `vgs` (`VgsOwner.TENANT`, agentgateway/VgsOwner.java:15). Auth: client role of `vault-mgmt-http-api`
(section 0; read :202-205, write :207-210); OPA admin_access.rego:78-89. 503 `agent_gateway_admin_disabled` unless OPA is on (:195-200). Gate `vgs.agentGateway.enabled=true`. VGS functions and adapters are written only through these endpoints; a tenant request never acts
as `vgs` (VgsOwner.java:6-9). Functions are readable by every vault; an adapter is readable by every vault once an adapter version is published.

## Functions (DTO and rules as section 6; codes as section 6)
| # | Method path | Role | Notes |
|---|---|---|---|
| 10.1 | GET /admin/functions | read (:69) | Query `filter[name]`. Lists VGS functions only (`functions.list("vgs", name)` lists vgs-owned; the store matches `tenant_id IN ('vgs','vgs')`). 200 |
| 10.2 | GET /admin/functions/{id} | read (:76) | 200; 404 `Function not found` if not VGS-owned (:185-188) |
| 10.3 | POST /admin/functions | write (:83) | Same body/rules/errors as 6.3 (`FunctionService.create("vgs", ...)`); `previous_version` must be a VGS function. 201 `Location /admin/functions/{id}`; 400 `missing_attributes` (:214) |
| 10.4 | DELETE /admin/functions/{id} | write (:97) | 204 soft delete; 404 `Function not found`; 409 `function_in_use` **while an adapter of any owner bundles it** (:93, FunctionService.java:105-108) |

## Adapters (DTO and rules as section 8, but `registry=true`: latest, scheduled version and drafts are shown)
| # | Method path | Role | Notes |
|---|---|---|---|
| 10.5 | GET /admin/agent-gateway-adapters | read (:110) | 200; VGS-owned only |
| 10.6 | GET /admin/agent-gateway-adapters/{id} | read (:117) | 200; 404 `Adapter not found` if not VGS-owned (:190-193) |
| 10.7 | POST /admin/agent-gateway-adapters | write (:126) | Body `name`, `functions` (each must be a VGS function: lookups run as `vgs`, AdapterService.java:198-201). 201 `Location /admin/agent-gateway-adapters/{id}`; 400 `invalid_name`, `invalid_functions`, `missing_attributes`; 409 `adapter_exists` |
| 10.8 | POST /admin/agent-gateway-adapters/{id} | write (:141) | New version, `functions` only; 400 `name_immutable` (:143-145), `adapter_not_found` (not VGS-owned), `invalid_functions`; 409 `adapter_version_conflict`. 200 |
| 10.9 | PATCH /admin/agent-gateway-adapters/{id} | write (:158) | Publish: `publish_at` only (400 `invalid_attributes`, :160-164; `invalid_publish_at`; `adapter_not_found`). `now` publishes the latest version to every vault; a future time schedules it. 200 |
| 10.10 | DELETE /admin/agent-gateway-adapters/{id} | write (:176) | 204 soft delete, frees the name; 404 `Adapter not found`; 409 `adapter_in_use` while an adapter destination of **any vault** uses it (:170-173; AdapterService.java:164-166) |

All admin endpoints also: 403 role missing; 503 `agent_gateway_admin_disabled`. (E-RES does not apply: the admin controllers pass `VgsOwner.TENANT` explicitly and take no vault.)

---

# 11. Ownership and soft delete summary

- **Owner field.** Functions and adapters expose `owner`: `vgs` (row `tenant_id = 'vgs'`, `VgsOwner.TENANT`) or `tenant` (FunctionController.java:120; AgentGatewayAdapterController.java:151). Tenant agent destinations are always tenant rows; the VGS registry of destinations
  (`agent_gateway.agent_destination`) is separate and tenant-less (section 5). Tenant id `vgs` is reserved: tenant requests naming it get 400 `reserved_tenant` (VgsOwner.java:25-36).
- **What tenants may do with VGS items.** Read VGS functions; read published VGS adapters (effective version only); bundle VGS functions in their own adapters; pin a VGS adapter version in their adapter destinations; run VGS functions via invocations. They cannot create, version,
  publish or delete VGS rows: tenant DELETE of a VGS function/adapter is 404 (owner mismatch); tenant `POST/PATCH /agent-gateway-adapters/{id}` on a VGS adapter is 400 `adapter_not_found`.
- **What the admin endpoints change.** Create/delete VGS functions; create, version, publish (now or scheduled) and delete VGS adapters; create/update/delete the global trusted-destination registry that every tenant inherits (`GET /agent-gateway-registry`).
- **Soft delete** (functions, adapters): sets `deleted_at` and `deleted_by`, keeps `status`; the row is never returned or changed afterwards, and the name may be reused (agentgateway/LifecycleStatus.java:4-7; JdbcFunctionStore.java:26-28, :112-115; JdbcAdapterStore.java:42, :148-150).
  `*_in_use` 409s: `function_in_use` (a live adapter version bundles the function), `adapter_in_use` (any adapter destination references the adapter). Tenant destinations (AGD), adapter destinations (AX) and VGS registry destinations are **hard** deletes.
  Function immutability: there is no function update endpoint.
- **Status.** `status` is `ACTIVE` or `DISABLED` (LifecycleStatus.java:8-10). No endpoint in the controllers covered here sets `DISABLED` (see UNKNOWN).

---

# 12. UNKNOWN / not determinable from this checkout

1. UNKNOWN: Full definitions of `AgentDestinationMode`, `AgentDestinationStatus`, `TenantAgentDestinationAction`, `TenantAgentDestinationOrigin` and the grammar of `AgentDestinationPattern`. Looked in this repo (`grep -rn "enum "`, class search): defined in an external library. Only the constants TRUSTED/GUARDED, ACTIVE/DISABLED, TRUST/GUARDED/BLOCK, MANUAL/AUTO are referenced (and API values are their lower-cased names, AgentDestinationRules.java:46-48).
2. UNKNOWN: 404/validation behaviour of `AgentDestinationService.update` and `.delete` (used by `/admin/agent-destinations` PATCH/DELETE). The class is outside this repo.
3. UNKNOWN: Whether function `name` has a uniqueness constraint. `FunctionService.create` performs no name check and no `function_exists`-style code exists; a DB constraint (vault-provisioning-ng migrations, not in this repo) was not inspected. Same for the Postgres uniqueness scope of adapter `name` (the Redis store is per owner, RedisAdapterStore.java:128-147).
4. UNKNOWN: What sets a function/adapter `status` to `DISABLED`. Searched `agentgateway/**` for writers (`setStatus`, `LifecycleStatus.DISABLED`): none; only defaults to ACTIVE.
5. UNKNOWN: Whether deleting a tenant destination (AGD, `DELETE /agent-gateway-destinations/{id}`) is blocked or cascades when an adapter destination's `when.host` references it. `AgentDestinationStore.delete` (:216-229) has no such check.
6. UNKNOWN: Exact response body of the 400 for a request with no JSON:API `data` (see section 0).
7. UNKNOWN: Compute-side enforcement that `session.card` / `session.alias` fail in dry runs and that `session.get` returns None without `session` values; the repo only documents it (dto/FunctionInvocationDto.java:48-52, FunctionInvocationService.java:87-91, :336-340).
8. UNKNOWN: Range validation of `aliases[].length` and `aliases[].bin` digit counts. Documented as bin 6-8 digits, length 13-19 (cvc 3-4) at revealsession/RevealSessionRequest.java:76-82, but `RevealSessionService.generate` passes them to `SessionTokenGenerator` (revealsession/SessionTokenGenerator.java, not read in detail) without a visible range check.
9. UNKNOWN: Exact exception/status for the tenant route-count limit hit by `POST /agent-gateway-destinations` (`limitChecker.checkLimitReached`, AgentDestinationStore.java:140; library class).
10. UNKNOWN: Which Postgres/Redis path stores a revoked non-stateless session after its original expiry (hash TTL elapsed): `GET` then 404, and `DELETE` falls into the stateless-marker path above when `revealSessionRevocationList` is on (RevealSessionService.java:593-626). The behaviour is derived from code reading, not from a run.
