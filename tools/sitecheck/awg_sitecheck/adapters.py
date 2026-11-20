"""Adapters as code: apply an adapter spec (functions + adapter + bindings), dry-run its functions, tear it down.

Spec (adapters/<name>/adapter.yaml, paths relative to it):

  name: hm-adyen                      # adapter name, unique in the vault
  hosts: [www2.hm.com, checkoutshopper-live.adyen.com]   # agent destinations to make sure exist (action: guarded)
  functions:
    capture: {file: capture.star, extension_point: route.response, name: "Capture Adyen key"}
    encrypt: {file: encrypt.star, extension_point: route.request, name: "Encrypt Adyen form",
              inputs: [{name: adyen_form, required: true}, {name: card_label}]}
  bindings:
    - key: capture
      function: capture
      when: {host: checkoutshopper-live.adyen.com, method: GET, path: "/checkoutshopper/securedfields/*/*/securedFields*html"}
    - key: checkout
      function: encrypt
      when: {host: www2.hm.com, method: POST, path: "/*/v2/checkout/proceed"}
      inputs: {adyen_form: {from: request.body, path: "$.adyenData.encryptedAdyenForm"}}

State (ids created on a tenant) is kept next to the spec in state.<env>.<tenant>.json. `apply` is idempotent:
unchanged sources keep their function; a changed source becomes a new function (linked with previous_version), a new
adapter version, and the bindings move to it.
"""
import hashlib
import json
from pathlib import Path

import yaml

from .api import Api, ApiError


def _load(spec_path):
    spec_path = Path(spec_path)
    spec = yaml.safe_load(spec_path.read_text())
    for key in ("name", "functions", "bindings"):
        if key not in spec:
            raise SystemExit(f"{spec_path}: missing `{key}`")
    return spec_path, spec


def _state_path(spec_path, cfg):
    return spec_path.parent / f"state.{cfg.env}.{cfg.tenant}.json"


def _read_state(p):
    return json.loads(p.read_text()) if p.exists() else {"functions": {}, "bindings": {}}


def _write_state(p, st):
    p.write_text(json.dumps(st, indent=1))


def _ensure_hosts(api, hosts):
    st, doc = api.call("GET", "/agent-gateway-destinations")
    have = {d["attributes"]["host_pattern"] for d in (doc or {}).get("data", [])} if st == 200 else set()
    for h in hosts or []:
        if h in have:
            continue
        st, doc = api.call("POST", "/agent-gateway-destinations",
                           Api.resource("agent-gateway-destinations", host_pattern=h, action="guarded"))
        print(f"  agent destination {h}: HTTP {st}" + ("" if st in (201, 409) else f" {str(doc)[:300]}"))


def apply(api, cfg, spec_file, dry_run=False):
    spec_path, spec = _load(spec_file)
    state_p = _state_path(spec_path, cfg)
    state = _read_state(state_p)
    plan = []
    if not dry_run:
        _ensure_hosts(api, spec.get("hosts"))

    # 1. functions: new function when the source changed
    changed = False
    for key, f in spec["functions"].items():
        src = (spec_path.parent / f["file"]).read_text()
        sha = hashlib.sha256(src.encode()).hexdigest()
        prev = state["functions"].get(key)
        if prev and prev["sha256"] == sha:
            continue
        changed = True
        attrs = {"name": f.get("name", f"{spec['name']}: {key}"), "language": "larky", "source": src,
                 "extension_point": f["extension_point"], "inputs": f.get("inputs", [])}
        if prev:
            attrs["previous_version"] = prev["id"]
        plan.append(f"function {key}: {'new version of ' + prev['id'] if prev else 'create'}")
        if dry_run:
            continue
        d = api.data("POST", "/functions", Api.resource("functions", **attrs), f"create function {key}")
        if d["attributes"].get("sha256") != sha:
            raise SystemExit(f"function {key}: the API stored a different source (sha256 mismatch)")
        state["functions"][key] = {"id": d["id"], "sha256": sha}
        _write_state(state_p, state)

    fn_ids = [state["functions"][k]["id"] for k in spec["functions"] if k in state["functions"]]

    # 2. adapter: create, or add a version when a function changed
    if "adapter" not in state:
        plan.append(f"adapter {spec['name']}: create")
        if not dry_run:
            d = api.data("POST", "/agent-gateway-adapters",
                         Api.resource("agent-gateway-adapters", name=spec["name"], functions=fn_ids), "create adapter")
            state["adapter"] = {"id": d["id"], "version": d["attributes"].get("version") or 1}
    elif changed:
        plan.append(f"adapter {state['adapter']['id']}: new version")
        if not dry_run:
            d = api.data("POST", f"/agent-gateway-adapters/{state['adapter']['id']}",
                         Api.resource("agent-gateway-adapters", functions=fn_ids), "new adapter version")
            state["adapter"]["version"] = d["attributes"].get("version") or d["attributes"].get("latest_version")
    if not dry_run:
        _write_state(state_p, state)

    # 3. bindings (adapter destinations): create or move to the adapter version
    for b in spec["bindings"]:
        fkey = b["function"]
        prev = state["bindings"].get(b["key"])
        attrs = {"adapter_version": state.get("adapter", {}).get("version"), "enabled": b.get("enabled", True),
                 "when": b["when"],
                 "functions": [{"id": state["functions"].get(fkey, {}).get("id"), "inputs": b.get("inputs", {})}]}
        if prev and not changed and prev.get("when") == b["when"] and prev.get("inputs") == b.get("inputs", {}):
            continue
        plan.append(f"binding {b['key']}: {'update ' + prev['id'] if prev else 'create'} {b['when']}")
        if dry_run:
            continue
        try:
            if prev:
                d = api.data("PATCH", f"/agent-gateway-adapter-destinations/{prev['id']}",
                             Api.resource("agent-gateway-adapter-destinations", **attrs), f"update binding {b['key']}")
            else:
                d = api.data("POST", "/agent-gateway-adapter-destinations",
                             Api.resource("agent-gateway-adapter-destinations", adapter=state["adapter"]["id"], **attrs),
                             f"create binding {b['key']}")
        except ApiError as e:
            if e.status == 409 and "overlap" in str(e.body):
                raise SystemExit(f"binding {b['key']}: another enabled binding in this vault already runs a "
                                 f"{'response' if 'response' in str(spec['functions'][fkey]) else 'request'} function "
                                 f"on {b['when']}. Reuse it (list: awg-sitecheck adapter list) or narrow `when`.\n{e}")
            raise
        state["bindings"][b["key"]] = {"id": d["id"], "when": b["when"], "inputs": b.get("inputs", {})}
        _write_state(state_p, state)

    return {"plan": plan or ["nothing to do"], "state": state if not dry_run else None, "state_file": str(state_p)}


def teardown(api, cfg, spec_file):
    spec_path, spec = _load(spec_file)
    state_p = _state_path(spec_path, cfg)
    state = _read_state(state_p)
    out = []
    for key, b in list(state.get("bindings", {}).items()):
        st, _ = api.call("DELETE", f"/agent-gateway-adapter-destinations/{b['id']}")
        out.append(f"binding {key} {b['id']}: {st}")
        if st in (204, 404):
            state["bindings"].pop(key)
    if state.get("adapter"):
        st, _ = api.call("DELETE", f"/agent-gateway-adapters/{state['adapter']['id']}")
        out.append(f"adapter {state['adapter']['id']}: {st}")
        if st in (204, 404):
            state.pop("adapter")
    for key, f in list(state.get("functions", {}).items()):
        st, _ = api.call("DELETE", f"/functions/{f['id']}")
        out.append(f"function {key} {f['id']}: {st}")
        if st in (204, 404):
            state["functions"].pop(key)
    _write_state(state_p, state)
    return out


def dry_run(api, cfg, spec_file, function_key, fixture_file):
    """Run one function of the spec on a saved request or response, without a session or the merchant.

    Fixture (JSON): {"request": {method, url, headers, body}} or {"response": {status, headers, body}} or
    {"response": {..., "body_file": "page.html"}}, plus optional "inputs" {name: string} and
    "session" {"values": {...}, "context": {...}}.
    """
    spec_path, spec = _load(spec_file)
    state = _read_state(_state_path(spec_path, cfg))
    fid = state.get("functions", {}).get(function_key, {}).get("id")
    if not fid:
        raise SystemExit(f"function {function_key} is not applied on {cfg.tenant} yet (run `adapter apply`)")
    fx_path = Path(fixture_file)
    fx = {k: v for k, v in json.loads(fx_path.read_text()).items() if not k.startswith("_")}
    # "destination": "$binding:<key>" uses that binding's input sources (e.g. a request.body JSONPath) instead of
    # constant "inputs", so the function sees inputs exactly as it will live.
    dest = fx.get("destination")
    if isinstance(dest, str) and dest.startswith("$binding:"):
        bid = state.get("bindings", {}).get(dest.split(":", 1)[1], {}).get("id")
        if not bid:
            raise SystemExit(f"{dest}: binding not applied on {cfg.tenant} yet")
        fx["destination"] = bid
    for part in ("request", "response"):
        if part in fx and "body_file" in fx[part]:
            fx[part]["body"] = (fx_path.parent / fx[part].pop("body_file")).read_text()
        if part in fx and isinstance(fx[part].get("body"), (dict, list)):
            fx[part]["body"] = json.dumps(fx[part]["body"])
    d = api.data("POST", f"/functions/{fid}/invocations", Api.resource("function-invocations", **fx),
                 f"dry run {function_key}")
    return d["attributes"]


def list_live(api):
    out = {}
    for path in ("/agent-gateway-adapters", "/agent-gateway-adapter-destinations"):
        st, doc = api.call("GET", path)
        out[path] = [{"id": d["id"], **{k: d["attributes"].get(k) for k in ("name", "version", "owner", "when",
                                                                          "adapter", "adapter_version", "enabled")
                                       if k in d["attributes"]}} for d in (doc or {}).get("data", [])] if st == 200 \
            else f"HTTP {st}"
    return out
