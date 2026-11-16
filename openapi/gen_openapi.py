#!/usr/bin/env python3
"""Generate the Agent Web Gateway OpenAPI 3.1 specs (tenant and admin) from the endpoint inventory.

Source of truth: vault-management `awg/stack-top` at d37e6452, as inventoried in docs/02-internal-api-detail.md.
Run: python3 gen_openapi.py  (writes awg-tenant-api.yaml and awg-admin-api.yaml next to this file)
"""
import copy, os, yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = "vault-management awg/stack-top d37e6452"


# ------------------------------------------------------------------ schema helpers
def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def s(type_, **kw):
    out = {"type": type_}
    out.update(kw)
    return out


def ro(schema):
    return dict(schema, readOnly=True)


def wo(schema):
    return dict(schema, writeOnly=True)


STR, INT, BOOL, TIME = s("string"), s("integer"), s("boolean"), s("string", format="date-time")
STRMAP = s("object", additionalProperties=STR)


def resource(name, type_value, attrs_schema, id_schema=None, id_example=None):
    """JSON:API resource, single document, list document and create/update request for `name`."""
    idd = id_schema or s("string")
    if id_example:
        idd = dict(idd, example=id_example)
    return {
        f"{name}Resource": s("object", required=["type", "attributes"], properties={
            "type": s("string", enum=[type_value]), "id": idd, "attributes": ref(attrs_schema)}),
        f"{name}Document": s("object", required=["data"], properties={"data": ref(f"{name}Resource")}),
        f"{name}ListDocument": s("object", required=["data"], properties={
            "data": s("array", items=ref(f"{name}Resource")), "meta": ref("PageMeta"), "links": ref("PageLinks")}),
        f"{name}Request": s("object", required=["data"], properties={"data": s("object", required=["attributes"], properties={
            "type": s("string", enum=[type_value]), "id": s("string"), "attributes": ref(attrs_schema)})}),
    }


def body(name):
    return {"required": True, "content": {"application/vnd.api+json": {"schema": ref(f"{name}Request")},
                                          "application/json": {"schema": ref(f"{name}Request")}}}


def ok(name, status="200", desc="OK", lst=False, headers=None):
    r = {"description": desc, "content": {"application/vnd.api+json": {"schema": ref(f"{name}{'List' if lst else ''}Document")}}}
    if headers:
        r["headers"] = headers
    return {status: r}


LOCATION = {"Location": {"description": "URL of the created resource", "schema": STR}}


def errors(*statuses, codes=None):
    out = {}
    text = {"400": "Validation error (carries a `code`)", "403": "Missing scope or role (message only, no code)",
            "404": "Unknown, deleted or another tenant's id (message only)", "409": "Conflict (carries a `code`)",
            "500": "Server error", "503": "A backing service is unavailable (carries a `code`)"}
    for st in statuses:
        out[st] = {"$ref": f"#/components/responses/E{st}"}
    return out


def op(op_id, summary, tag, scope, responses, description="", params=None, request=None, codes=None, security=True):
    o = {"operationId": op_id, "summary": summary, "tags": [tag], "responses": responses}
    desc = description
    if codes:
        desc += ("\n\n" if desc else "") + "Error codes: " + ", ".join(f"`{c}`" for c in codes) + "."
    if scope:
        desc += ("\n\n" if desc else "") + f"Requires `{scope}`."
        o["x-vgs-required-scope"] = scope
    if desc:
        o["description"] = desc
    if params:
        o["parameters"] = params
    if request:
        o["requestBody"] = request
    if not security:
        o["security"] = []
    return o


def path_id(desc, example):
    return {"name": "id", "in": "path", "required": True, "description": desc, "schema": dict(STR, example=example)}


def q(name, desc, schema=None, required=False):
    return {"name": name, "in": "query", "required": required, "description": desc, "schema": schema or STR}


PAGING = [q("offset", "Page offset, >= 0 (default 0)", s("integer", minimum=0, default=0)),
          q("limit", "Page size, 1..100 (default 30)", s("integer", minimum=1, maximum=100, default=30))]


# ------------------------------------------------------------------ shared components
def common_components(tenant=True):
    comps = {
        "Error": s("object", properties={
            "errors": s("array", items=s("object", properties={
                "status": INT, "code": dict(STR, description="Present on 400, 409 and 503 errors"),
                "title": STR, "detail": STR, "href": dict(STR, description="The request URL")}))}),
        "PageMeta": s("object", properties={"total_pages": INT, "total_elements": INT}),
        "PageLinks": s("object", additionalProperties=STR),
    }
    responses = {}
    for st, d in [("400", "Validation error; `errors[].code` names the rule"), ("403", "Missing scope or role"),
                  ("404", "Not found (unknown, deleted, malformed or another tenant's id)"),
                  ("409", "Conflict; `errors[].code` names it"),
                  ("500", "Server error; `reveal_session_proxy_host_unusable` when the proxy host cannot be built for the tenant"),
                  ("503", "Unavailable; `errors[].code` names it")]:
        responses[f"E{st}"] = {"description": d, "content": {"application/vnd.api+json": {"schema": ref("Error")}}}
    return comps, responses


def function_schemas():
    return {
        "FunctionInput": s("object", required=["name"], properties={
            "name": s("string", pattern="^[a-z][a-z0-9_]{0,63}$"), "required": dict(BOOL, default=False)}),
        "FunctionAttributes": s("object", properties={
            "name": s("string", minLength=1, maxLength=255),
            "language": s("string", enum=["larky"], default="larky"),
            "source": s("string", description="Larky source, <= 262144 UTF-8 bytes, no `${`, must parse; `vault` only via `load(\"@vgs//vault\", \"vault\")`"),
            "extension_point": s("string", enum=["route.request", "route.response", "invoke"]),
            "inputs": s("array", maxItems=32, items=ref("FunctionInput")),
            "previous_version": dict(STR, description="FN id of an earlier version owned by the same owner"),
            "sha256": ro(dict(STR, description="Hex SHA-256 of `source`")),
            "owner": ro(s("string", enum=["tenant", "vgs"])),
            "status": ro(s("string", enum=["ACTIVE", "DISABLED"])),
            "created_by": ro(STR), "created_at": ro(TIME), "updated_by": ro(STR), "updated_at": ro(TIME)}),
    }


def adapter_schemas():
    return {
        "AdapterAttributes": s("object", properties={
            "name": s("string", minLength=1, maxLength=255),
            "functions": s("array", minItems=1, maxItems=32, uniqueItems=True, items=dict(STR, description="FN id"),
                           description="On create and new version: the version's functions. In responses: the functions of the version shown"),
            "publish_at": wo(dict(STR, description="PATCH only: `now`, or an ISO-8601 date-time with offset")),
            "version": ro(INT), "latest_version": ro(INT), "published_version": ro(INT),
            "scheduled_version": ro(INT), "scheduled_at": ro(TIME),
            "owner": ro(s("string", enum=["tenant", "vgs"])), "status": ro(s("string", enum=["ACTIVE", "DISABLED"])),
            "created_by": ro(STR), "created_at": ro(TIME), "updated_by": ro(STR), "updated_at": ro(TIME)}),
    }


# ------------------------------------------------------------------ tenant spec
def tenant_spec():
    comps, responses = common_components()
    alias = s("object", properties={
        "alias": dict(STR, description="Vault alias (for card parts) or loose alias"),
        "format": s("string", enum=["card_number", "card_cvc", "text"], description="Loose aliases only; card parts are forced"),
        "bin": dict(STR, description="Required for card_number unless the alias is a 13-19 digit number; defaults to its first 6 digits"),
        "length": dict(INT, description="Card number default: alias length if numeric, else 16; CVC default 3"),
        "storage": s("string", enum=["PERSISTENT", "VOLATILE"], default="PERSISTENT"),
        "label": s("string", pattern="^[a-z0-9][a-z0-9_-]{0,31}$", description="Text aliases only"),
        "value": ro(dict(STR, description="The session alias handed to the agent; create response only"))})
    comps.update({
        "Alias": alias,
        "Card": s("object", required=["number"], properties={
            "label": s("string", pattern="^[a-z0-9][a-z0-9_-]{0,31}$", description="Required when the session has more than one card"),
            "number": ref("Alias"), "cvc": ref("Alias"), "expiry": ref("Alias"), "holder": ref("Alias")}),
        "Token": s("object", properties={"alias": STR, "format": STR, "value": STR}),
        "Proxy": s("object", properties={
            "url": dict(STR, description="`<scheme>://<session id>:<secret>@<host>:<port>`; the secret appears only here"),
            "ca_bundle": dict(STR, description="PEM of the forward proxy CA(s)"),
            "pac_url": dict(STR, description="Pre-signed PAC link, valid until the session expires")}),
        "EgressProxySettings": s("object", required=["type", "scheme", "hostname", "port"], properties={
            "type": s("string", enum=["custom"]), "scheme": s("string", enum=["http", "https"]),
            "hostname": dict(STR, description="Public host name; not a never-host"),
            "port": s("integer", minimum=1, maximum=65535),
            "username": s("string", maxLength=256), "password": wo(s("string", maxLength=256)),
            "has_password": ro(BOOL)}),
        "StepUp": s("object", properties={"webhook_url": STR, "hold_seconds": INT,
                                          "webhook_secret": ro(dict(STR, description="Create response only"))}),
        "RevealSessionAttributes": s("object", properties={
            "cards": s("array", items=ref("Card")),
            "aliases": s("array", items=ref("Alias"), description="`cards` or `aliases` is required; at most 20 parts in total"),
            "allowed_hosts": s("array", maxItems=20, items=dict(STR, description="Exact host name: no wildcard, port or IP")),
            "allowed_client_cidrs": s("array", maxItems=10, items=dict(STR, description="IPv4/IPv6 address or CIDR")),
            "egress_proxy_settings": ref("EgressProxySettings"),
            "context": s("object", maxProperties=32, propertyNames=s("string", pattern="^[a-z][a-z0-9_]{0,63}$"),
                         additionalProperties=s("string", maxLength=512),
                         description="At most 4096 characters in total (1024 for stateless sessions)"),
            "adapter": dict(STR, description="AD id or adapter name; stored as the id. Absent: every enabled binding matches"),
            "state": ro(s("string", enum=["active", "revoked", "expired"])),
            "created_at": ro(TIME), "expires_at": ro(TIME),
            "unlisted_host_mode": ro(s("string", enum=["strict", "guarded", "step_up"], description="From tenant preferences")),
            "tokens": ro(s("array", items=ref("Token"))),
            "session_aliases": ro(s("array", items=ref("Token"))),
            "proxy": ro(ref("Proxy")),
            "step_up": ro(ref("StepUp")),
            "pending_approvals": ro(INT), "reveal_count": ro(INT), "refusal_count": ro(INT),
            "values": ro(s("object", additionalProperties=STRMAP,
                           description="With `include=values`: values functions stored, keyed by adapter id then key"))}),
        "ProxyCaAttributes": s("object", properties={"host": STR, "scheme": STR, "port": INT, "ca_bundle": STR}),
        "ApprovalAttributes": s("object", properties={
            "reveal_session_id": ro(STR), "host": ro(STR), "method": ro(STR), "path": ro(STR),
            "state": s("string", enum=["pending", "approved", "denied", "expired"], description="PATCH: `approved` or `denied`"),
            "scope": s("string", enum=["request", "session"], default="request"),
            "requested_at": ro(TIME), "expires_at": ro(TIME), "decided_at": ro(TIME)}),
        "DestinationAttributes": s("object", properties={
            "host_pattern": dict(STR, description="Exact host or `*.` pattern; immutable after create"),
            "action": s("string", enum=["trust", "guarded", "block"]),
            "origin": ro(s("string", enum=["manual", "auto"])), "route_id": ro(STR),
            "created_by": ro(STR), "promoted_by": ro(STR), "promoted_at": ro(TIME), "created_at": ro(TIME), "updated_at": ro(TIME)}),
        "RegistryEntryAttributes": s("object", properties={"host_pattern": STR, "action": s("string", enum=["trust", "guarded"])}),
        "InvocationAttributes": s("object", properties={
            "input": wo(dict(STR, description="`invoke` functions only")),
            "request": wo(s("object", properties={"method": STR, "url": dict(STR, format="uri"), "headers": STRMAP,
                                                   "body": dict(STR, description="<= 1 MiB")})),
            "response": wo(s("object", properties={"status": s("integer", minimum=100, maximum=599), "headers": STRMAP,
                                                    "body": dict(STR, description="<= 1 MiB")})),
            "destination": wo(dict(STR, description="AX id whose bindings supply the inputs; not with `inputs`")),
            "inputs": wo(s("object", additionalProperties=s("string", maxLength=4096))),
            "session": wo(s("object", properties={"values": STRMAP, "context": STRMAP})),
            "function": ro(STR), "source": ro(s("string", enum=["api", "test"])), "dry_run": ro(BOOL),
            "status": ro(s("string", enum=["succeeded", "failed"])), "error": ro(STR), "duration_ms": ro(INT),
            "result": ro(s("object", description="Create response only", properties={
                "output": STR, "request": s("object", additionalProperties=True),
                "response": s("object", additionalProperties=True),
                "session": s("object", properties={"values": STRMAP})})),
            "created_by": ro(STR), "created_at": ro(TIME)}),
        "InputSource": s("object", required=["from"], properties={
            "from": s("string", enum=["constant", "request.body", "response.body", "request.header", "response.header",
                                      "request.query", "session.value"]),
            "value": dict(STR, description="`constant`: <= 4096 characters, no `${`"),
            "path": dict(STR, description="`*.body`: JSONPath (`$`, `.key`, `['key']`, `[index]`)"),
            "name": dict(STR, description="`*.header` / `request.query`"),
            "key": dict(STR, description="`session.value` (behind a feature flag)")}),
        "AdapterDestinationAttributes": s("object", properties={
            "adapter": dict(STR, description="AD id or name on input; AD id on output; immutable"),
            "adapter_version": INT, "enabled": dict(BOOL, default=True),
            "when": s("object", required=["host"], properties={
                "host": dict(STR, description="One of the vault's agent destinations, not blocked"),
                "method": s("string", enum=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]),
                "path": s("string", maxLength=1024, description="Starts with `/`; `*` matches any characters")}),
            "functions": s("array", minItems=1, maxItems=16, items=s("object", required=["id"], properties={
                "id": STR, "inputs": s("object", additionalProperties=ref("InputSource")),
                "extension_point": ro(s("string", enum=["route.request", "route.response"]))})),
            "revision": ro(INT), "created_by": ro(STR), "updated_by": ro(STR), "created_at": ro(TIME), "updated_at": ro(TIME)}),
    })
    comps.update(function_schemas())
    comps.update(adapter_schemas())
    for name, t, attrs, ex in [("RevealSession", "reveal-sessions", "RevealSessionAttributes", "RS" + "x" * 22),
                               ("ProxyCa", "reveal-session-proxy-ca", "ProxyCaAttributes", "proxy-ca"),
                               ("Approval", "reveal-session-approvals", "ApprovalAttributes", "AP" + "x" * 22),
                               ("Destination", "agent-gateway-destinations", "DestinationAttributes", "AGD" + "x" * 22),
                               ("RegistryEntry", "agent-gateway-registry-entries", "RegistryEntryAttributes", None),
                               ("Function", "functions", "FunctionAttributes", "FN" + "x" * 22),
                               ("Invocation", "function-invocations", "InvocationAttributes", "FI" + "x" * 22),
                               ("Adapter", "agent-gateway-adapters", "AdapterAttributes", "AD" + "x" * 22),
                               ("AdapterDestination", "agent-gateway-adapter-destinations", "AdapterDestinationAttributes", "AX" + "x" * 22)]:
        comps.update(resource(name, t, attrs, id_example=ex))

    RS, RW = "reveal-sessions:read", "reveal-sessions:write"
    AR, AW = "agent-gateway:read", "agent-gateway:write"
    E = errors
    paths = {
        "/reveal-sessions": {
            "post": op("createRevealSession", "Create a reveal session", "Reveal sessions", RW,
                       {**ok("RevealSession", "201", "Created; the only response carrying `proxy` and alias values", headers=LOCATION), **E("400", "403", "500", "503")},
                       "Lifetime and unlisted-host mode come from tenant preferences and cannot be set per session.",
                       request=body("RevealSession"),
                       codes=["missing_attributes", "missing_aliases", "too_many_aliases", "invalid_alias", "unknown_format", "missing_bin",
                              "invalid_storage", "invalid_label", "invalid_card", "invalid_card_label", "missing_card_number", "invalid_host",
                              "never_host", "too_many_hosts", "invalid_client_cidr", "too_many_client_cidrs", "invalid_context",
                              "invalid_adapter", "adapter_unavailable", "invalid_egress_proxy_settings", "invalid_egress_proxy_hostname",
                              "invalid_egress_proxy_port", "invalid_egress_proxy_credentials", "ttl_not_configurable",
                              "unlisted_host_mode_not_configurable", "step_up_not_configurable", "session_too_large", "invalid_ttl",
                              "stateless_unavailable", "reveal_session_proxy_host_unusable"]),
            "get": op("listRevealSessions", "List reveal sessions", "Reveal sessions", RS,
                      {**ok("RevealSession", lst=True), **E("400", "403")}, "Newest expiry first; items carry no `values`.",
                      params=[q("state", "`active` (default) or `revoked`", s("string", enum=["active", "revoked"]))] + PAGING,
                      codes=["invalid_state", "invalid_paging"])},
        "/reveal-sessions/{id}": {
            "parameters": [path_id("Reveal session id", "RS" + "x" * 22)],
            "get": op("getRevealSession", "Read a reveal session", "Reveal sessions", RS,
                      {**ok("RevealSession"), **E("400", "403", "404")}, "Never returns secrets. 404 also for stateless sessions.",
                      params=[q("include", "Only `values` is supported", s("string", enum=["values"]))], codes=["invalid_include"]),
            "delete": op("revokeRevealSession", "Revoke a reveal session", "Reveal sessions", RW,
                         {"204": {"description": "Revoked (idempotent)"}, **E("403", "404", "409")}, codes=["revocation_list_disabled"])},
        "/reveal-sessions/{id}/credentials": {
            "parameters": [path_id("Reveal session id", "RS" + "x" * 22)],
            "post": op("reissueRevealSessionCredentials", "Reissue the session's proxy password", "Reveal sessions", RW,
                       {**ok("RevealSession"), **E("403", "404", "409", "500")},
                       "Off unless the platform enables credential reissue (`404 credential_reissue_disabled`). Redis sessions only.",
                       codes=["credential_reissue_disabled", "session_not_active", "reveal_session_proxy_host_unusable"])},
        "/reveal-sessions/proxy-ca": {
            "get": op("getRevealSessionProxyCa", "The forward proxy CA bundle", "Reveal sessions", RS,
                      {**ok("ProxyCa"), **E("403", "404")})},
        "/reveal-sessions/{id}.pac": {
            "parameters": [path_id("Reveal session id", "RS" + "x" * 22)],
            "get": op("getRevealSessionPac", "The session's PAC file (pre-signed link)", "Reveal sessions", None,
                      {"200": {"description": "PAC script", "content": {"application/x-ns-proxy-autoconfig": {"schema": STR}}},
                       "404": {"description": "Any failure (empty body): expired link, bad signature, inactive session, PAC disabled"}},
                      "No token or tenant header: the signed query is the credential. Use `proxy.pac_url` as returned.",
                      params=[q("tenant", "Vault id", s("string", maxLength=128), True),
                              q("expires", "Epoch seconds, in the future", s("string", pattern="^[1-9][0-9]{0,11}$"), True),
                              q("signature", "base64url HMAC-SHA256, 43 characters", s("string", pattern="^[A-Za-z0-9_-]{43}$"), True)],
                      security=False)},
        "/reveal-session-approvals": {
            "get": op("listApprovals", "List a session's step-up approvals", "Step-up approvals", RS,
                      {**ok("Approval", lst=True), **E("400", "403", "404")},
                      params=[q("filter[reveal_session]", "Reveal session id", required=True)] + PAGING,
                      codes=["missing_filter", "invalid_paging"])},
        "/reveal-session-approvals/{id}": {
            "parameters": [path_id("Approval id", "AP" + "x" * 22)],
            "get": op("getApproval", "Read an approval", "Step-up approvals", RS, {**ok("Approval"), **E("403", "404")}),
            "patch": op("decideApproval", "Approve or deny a held request", "Step-up approvals", RW,
                        {**ok("Approval"), **E("400", "403", "404", "409")},
                        "`data.type` must be `reveal-session-approvals` and `data.id` the path id. `scope: session` with `approved` approves the host for the rest of the session.",
                        request=body("Approval"),
                        codes=["missing_attributes", "invalid_type", "id_mismatch", "invalid_state", "invalid_scope", "approval_closed"])},
        "/agent-gateway-destinations": {
            "get": op("listDestinations", "List agent destinations", "Destinations", AR, {**ok("Destination", lst=True), **E("400", "403")}),
            "post": op("createDestination", "Create an agent destination", "Destinations", AW,
                       {**ok("Destination", "201", "Created", headers=LOCATION), **E("400", "403", "409")},
                       "Creates a forward-proxy route; at most 1000 per vault. A `trust` records the caller as approver.",
                       request=body("Destination"),
                       codes=["missing_attributes", "invalid_host_pattern", "invalid_action", "never_host", "origin_not_writable",
                              "too_many_destinations", "destination_exists"])},
        "/agent-gateway-destinations/{id}": {
            "parameters": [path_id("Agent destination id", "AGD" + "x" * 22)],
            "get": op("getDestination", "Read an agent destination", "Destinations", AR, {**ok("Destination"), **E("400", "403", "404")}),
            "patch": op("updateDestination", "Change a destination's action", "Destinations", AW,
                        {**ok("Destination"), **E("400", "403", "404")}, request=body("Destination"),
                        codes=["missing_attributes", "invalid_action", "host_pattern_immutable", "origin_not_writable", "never_host", "route_tag_limit"]),
            "delete": op("deleteDestination", "Delete an agent destination", "Destinations", AW,
                         {"204": {"description": "Deleted (route, then row)"}, **E("400", "403", "404")},
                         "Hard delete. No in-use check against adapter destinations.")},
        "/agent-gateway-registry": {
            "get": op("listRegistry", "VGS trusted destinations as this vault sees them", "Destinations", AR,
                      {**ok("RegistryEntry", lst=True), **E("403")})},
        "/functions": {
            "get": op("listFunctions", "List own and VGS functions", "Functions", AR, {**ok("Function", lst=True), **E("400", "403")},
                      "Newest first, at most 200.", params=[q("filter[name]", "Exact name")]),
            "post": op("createFunction", "Create a function", "Functions", AW,
                       {**ok("Function", "201", "Created", headers=LOCATION), **E("400", "403")},
                       "Functions are immutable: a new version is a new function linked by `previous_version`.",
                       request=body("Function"),
                       codes=["missing_attributes", "invalid_name", "invalid_language", "invalid_extension_point", "invalid_source",
                              "source_too_large", "invalid_inputs", "invalid_previous_version"])},
        "/functions/{id}": {
            "parameters": [path_id("Function id", "FN" + "x" * 22)],
            "get": op("getFunction", "Read a function", "Functions", AR, {**ok("Function"), **E("400", "403", "404")}),
            "delete": op("deleteFunction", "Soft-delete an own function", "Functions", AW,
                         {"204": {"description": "Deleted"}, **E("400", "403", "404", "409")},
                         "404 for VGS functions.", codes=["function_in_use"])},
        "/functions/{id}/invocations": {
            "parameters": [path_id("Function id", "FN" + "x" * 22)],
            "post": op("invokeFunction", "Dry-run a route function, or run an invoke function", "Functions", AW,
                       {**ok("Invocation", "201", "Recorded, even when the run failed (`status: failed`)", headers=LOCATION),
                        **E("400", "403", "404", "503")},
                       "`route.request`: `request` (method, absolute URL). `route.response`: `response` only. `invoke`: `input` only. "
                       "10 s deadline, bodies <= 1 MiB. `session.card` and aliases always fail in a dry run.",
                       request=body("Invocation"),
                       codes=["missing_attributes", "invalid_invocation", "invalid_inputs", "invalid_function", "invocations_unavailable"])},
        "/function-invocations": {
            "get": op("listInvocations", "List function invocations", "Functions", AR, {**ok("Invocation", lst=True), **E("400", "403")},
                      "Newest first, at most 100; never `result`.",
                      params=[q("filter[function]", "FN id"), q("filter[source]", "`api` or `test`", s("string", enum=["api", "test"]))],
                      codes=["invalid_filter"])},
        "/function-invocations/{id}": {
            "parameters": [path_id("Invocation id", "FI" + "x" * 22)],
            "get": op("getInvocation", "Read a function invocation", "Functions", AR, {**ok("Invocation"), **E("400", "403", "404")})},
        "/agent-gateway-adapters": {
            "get": op("listAdapters", "List own and published VGS adapters", "Adapters", AR, {**ok("Adapter", lst=True), **E("400", "403")}),
            "post": op("createAdapter", "Create an adapter (version 1)", "Adapters", AW,
                       {**ok("Adapter", "201", "Created", headers=LOCATION), **E("400", "403", "409")}, request=body("Adapter"),
                       codes=["missing_attributes", "invalid_name", "invalid_functions", "adapter_exists"])},
        "/agent-gateway-adapters/{id}": {
            "parameters": [path_id("Adapter id", "AD" + "x" * 22)],
            "get": op("getAdapter", "Read an adapter", "Adapters", AR, {**ok("Adapter"), **E("400", "403", "404")}),
            "post": op("createAdapterVersion", "Add a version (`functions` only)", "Adapters", AW,
                       {**ok("Adapter"), **E("400", "403", "409")}, "VGS adapters are read-only to tenants.", request=body("Adapter"),
                       codes=["missing_attributes", "name_immutable", "invalid_functions", "adapter_not_found", "adapter_version_conflict"]),
            "patch": op("publishAdapter", "Publish the latest version (`publish_at`)", "Adapters", AW,
                        {**ok("Adapter"), **E("400", "403")}, request=body("Adapter"),
                        codes=["missing_attributes", "invalid_attributes", "invalid_publish_at", "adapter_not_found"]),
            "delete": op("deleteAdapter", "Soft-delete an own adapter", "Adapters", AW,
                         {"204": {"description": "Deleted; the name is free again"}, **E("400", "403", "404", "409")},
                         "404 for VGS adapters.", codes=["adapter_in_use"])},
        "/agent-gateway-adapter-destinations": {
            "get": op("listAdapterDestinations", "List adapter destinations", "Adapter destinations", AR,
                      {**ok("AdapterDestination", lst=True), **E("400", "403")}, params=[q("filter[adapter]", "AD id or name")]),
            "post": op("createAdapterDestination", "Bind an adapter version's functions to traffic", "Adapter destinations", AW,
                       {**ok("AdapterDestination", "201", "Created", headers=LOCATION), **E("400", "403", "409")},
                       "At most 100 per vault. Without `adapter`, exactly one function and no version: an `fn-<FN id>` adapter is created or reused.",
                       request=body("AdapterDestination"),
                       codes=["missing_attributes", "too_many_destinations", "invalid_adapter", "adapter_required", "invalid_functions",
                              "invalid_adapter_version", "host_required", "invalid_when", "unknown_host", "destination_blocked",
                              "function_not_in_adapter", "invalid_inputs", "input_source_unsupported", "destination_overlap", "adapter_conflict"])},
        "/agent-gateway-adapter-destinations/{id}": {
            "parameters": [path_id("Adapter destination id", "AX" + "x" * 22)],
            "get": op("getAdapterDestination", "Read an adapter destination", "Adapter destinations", AR,
                      {**ok("AdapterDestination"), **E("400", "403", "404")}),
            "patch": op("updateAdapterDestination", "Change version, enabled, when or functions", "Adapter destinations", AW,
                        {**ok("AdapterDestination"), **E("400", "403", "404", "409")},
                        "`functions` replaces the list; optimistic on `revision`.", request=body("AdapterDestination"),
                        codes=["adapter_immutable", "invalid_adapter", "function_not_in_adapter", "invalid_inputs", "concurrent_change",
                               "destination_overlap"]),
            "delete": op("deleteAdapterDestination", "Delete an adapter destination", "Adapter destinations", AW,
                         {"204": {"description": "Deleted (route entries, then row)"}, **E("400", "403", "404")})},
    }
    tenant_header = {"name": "VGS-Tenant", "in": "header", "required": True, "description": "Vault id", "schema": STR}
    for p, item in paths.items():
        if p.endswith(".pac"):
            continue
        item.setdefault("parameters", []).insert(0, {"$ref": "#/components/parameters/VgsTenant"})
    return {
        "openapi": "3.1.0",
        "info": {"title": "VGS Agent Web Gateway API", "version": "2026-11-12",
                 "description": "Reveal sessions, agent destinations, functions, adapters and adapter destinations. "
                                "JSON:API. Generated from " + SOURCE + ". Scopes are listed per operation (`x-vgs-required-scope`); "
                                "write scopes do not include read."},
        "servers": [{"url": "https://sandbox.vgsapi.com", "description": "Sandbox"},
                    {"url": "https://vgsapi.com", "description": "Live"}],
        "security": [{"bearerAuth": []}],
        "tags": [{"name": t} for t in ["Reveal sessions", "Step-up approvals", "Destinations", "Functions", "Adapters", "Adapter destinations"]],
        "paths": paths,
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                                                          "description": "Access token of a VGS service account with the operation's scope"}},
                       "parameters": {"VgsTenant": tenant_header}, "schemas": comps, "responses": responses},
    }


# ------------------------------------------------------------------ admin spec
def admin_spec():
    comps, responses = common_components()
    comps.update(function_schemas())
    comps.update(adapter_schemas())
    comps["AgentDestinationAttributes"] = s("object", properties={
        "host_pattern": dict(STR, description="Immutable after create"),
        "mode": s("string", enum=["trusted", "guarded"]), "status": s("string", enum=["active", "disabled"], default="active"),
        "created_by": ro(STR), "created_at": ro(TIME), "updated_at": ro(TIME)})
    comps.update(resource("AgentDestination", "agent-destinations", "AgentDestinationAttributes", s("string", format="uuid")))
    comps.update(resource("Function", "functions", "FunctionAttributes", id_example="FN" + "x" * 22))
    comps.update(resource("Adapter", "agent-gateway-adapters", "AdapterAttributes", id_example="AD" + "x" * 22))
    R, W = "admin/agent-gateway:read", "admin/agent-gateway:write"
    DR, DW = "admin/agent-gateway:read | admin/agent-destinations:read", "admin/agent-gateway:write | admin/agent-destinations:write"
    E = errors
    uuid_id = {"name": "id", "in": "path", "required": True, "schema": s("string", format="uuid")}
    paths = {
        "/admin/agent-destinations": {
            "get": op("adminListAgentDestinations", "List registry destinations", "Registry destinations", DR,
                      {**ok("AgentDestination", lst=True), **E("403", "503")}),
            "post": op("adminCreateAgentDestination", "Add a registry destination (applies to every tenant)", "Registry destinations", DW,
                       {**ok("AgentDestination", "201", "Created", headers=LOCATION), **E("400", "403", "409", "503")},
                       request=body("AgentDestination"),
                       codes=["missing_attributes", "invalid_host_pattern", "never_host", "invalid_mode", "invalid_status",
                              "destination_exists", "agent_destinations_admin_disabled"])},
        "/admin/agent-destinations/{id}": {
            "parameters": [uuid_id],
            "get": op("adminGetAgentDestination", "Read a registry destination", "Registry destinations", DR,
                      {**ok("AgentDestination"), **E("400", "403", "404", "503")}),
            "patch": op("adminUpdateAgentDestination", "Change mode or status", "Registry destinations", DW,
                        {**ok("AgentDestination"), **E("400", "403", "404", "503")}, request=body("AgentDestination"),
                        codes=["host_pattern_immutable", "missing_attributes", "invalid_mode", "invalid_status"]),
            "delete": op("adminDeleteAgentDestination", "Delete a registry destination (hard delete)", "Registry destinations", DW,
                         {"204": {"description": "Deleted"}, **E("403", "404", "503")})},
        "/admin/functions": {
            "get": op("adminListFunctions", "List VGS functions", "VGS functions", R, {**ok("Function", lst=True), **E("403", "503")},
                      params=[q("filter[name]", "Exact name")]),
            "post": op("adminCreateFunction", "Create a VGS function (readable by every vault)", "VGS functions", W,
                       {**ok("Function", "201", "Created", headers=LOCATION), **E("400", "403", "503")}, request=body("Function"),
                       codes=["missing_attributes", "invalid_name", "invalid_extension_point", "invalid_source", "source_too_large",
                              "invalid_inputs", "invalid_previous_version", "agent_gateway_admin_disabled"])},
        "/admin/functions/{id}": {
            "parameters": [path_id("Function id", "FN" + "x" * 22)],
            "get": op("adminGetFunction", "Read a VGS function", "VGS functions", R, {**ok("Function"), **E("403", "404", "503")}),
            "delete": op("adminDeleteFunction", "Soft-delete a VGS function", "VGS functions", W,
                         {"204": {"description": "Deleted"}, **E("403", "404", "409", "503")},
                         "409 while an adapter of any owner bundles it.", codes=["function_in_use"])},
        "/admin/agent-gateway-adapters": {
            "get": op("adminListAdapters", "List VGS adapters (all versions, schedules and drafts)", "VGS adapters", R,
                      {**ok("Adapter", lst=True), **E("403", "503")}),
            "post": op("adminCreateAdapter", "Create a VGS adapter", "VGS adapters", W,
                       {**ok("Adapter", "201", "Created", headers=LOCATION), **E("400", "403", "409", "503")},
                       "Its functions must be VGS functions.", request=body("Adapter"),
                       codes=["missing_attributes", "invalid_name", "invalid_functions", "adapter_exists"])},
        "/admin/agent-gateway-adapters/{id}": {
            "parameters": [path_id("Adapter id", "AD" + "x" * 22)],
            "get": op("adminGetAdapter", "Read a VGS adapter", "VGS adapters", R, {**ok("Adapter"), **E("403", "404", "503")}),
            "post": op("adminCreateAdapterVersion", "Add a version", "VGS adapters", W, {**ok("Adapter"), **E("400", "403", "409", "503")},
                       request=body("Adapter"), codes=["name_immutable", "adapter_not_found", "invalid_functions", "adapter_version_conflict"]),
            "patch": op("adminPublishAdapter", "Publish the latest version to every vault, now or at a time", "VGS adapters", W,
                        {**ok("Adapter"), **E("400", "403", "503")}, request=body("Adapter"),
                        codes=["invalid_attributes", "invalid_publish_at", "adapter_not_found"]),
            "delete": op("adminDeleteAdapter", "Soft-delete a VGS adapter", "VGS adapters", W,
                         {"204": {"description": "Deleted; the name is free again"}, **E("403", "404", "409", "503")},
                         "409 while an adapter destination of any vault uses it.", codes=["adapter_in_use"])},
    }
    return {
        "openapi": "3.1.0",
        "info": {"title": "VGS Agent Web Gateway Admin API (internal)", "version": "2026-11-12",
                 "description": "VGS-only: the trusted-destination registry and VGS-owned functions and adapters. "
                                "Requires a client role of Keycloak client `vault-mgmt-http-api` (listed per operation in "
                                "`x-vgs-required-scope`) and OPA; without OPA every call answers 503. Generated from " + SOURCE + "."},
        "servers": [{"url": "https://{host}", "variables": {"host": {"default": "vault-management.example.internal",
                     "description": "The vault-management host for the environment"}}}],
        "security": [{"bearerAuth": []}],
        "tags": [{"name": t} for t in ["Registry destinations", "VGS functions", "VGS adapters"]],
        "paths": paths,
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}},
                       "schemas": comps, "responses": responses},
    }


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


if __name__ == "__main__":
    for name, spec in [("awg-tenant-api.yaml", tenant_spec()), ("awg-admin-api.yaml", admin_spec())]:
        with open(os.path.join(HERE, name), "w") as fh:
            yaml.dump(spec, fh, Dumper=NoAliasDumper, sort_keys=False, width=120, allow_unicode=True)
        ops = sum(1 for p in spec["paths"].values() for m in p if m in ("get", "post", "put", "patch", "delete"))
        print(f"{name}: {len(spec['paths'])} paths, {ops} operations")
