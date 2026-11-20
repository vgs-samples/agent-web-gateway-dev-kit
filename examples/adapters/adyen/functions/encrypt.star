load("@vgs//agent_gateway", session="session")
load("@vgs//vault", vault="vault")
load("@vendor//jose/jwe", jwe="jwe")
load("@stdlib//json", json="json")
load("@stdlib//base64", base64="base64")
load("@stdlib//binascii", binascii="binascii")
load("@stdlib//codecs", codecs="codecs")
load("@stdlib//re", re="re")
adapter_input = None

def json_path_steps(path):
    if path == None or path == "":
        return None
    if type(path) != "string" or not path.startswith("$"):
        fail("JSONPath must start with $")
    steps = []
    end = 0
    # Same definite selectors as destination body inputs: .key, ['key'], [index].
    for match in re.finditer(r"\.([A-Za-z_][A-Za-z0-9_]*)|\['([^']+)'\]|\[([0-9]+)\]", path[1:]):
        if match.start() != end:
            fail("Unsupported JSONPath selector")
        steps.append(match.group(1) or match.group(2) or int(match.group(3)))
        end = match.end()
    if end != len(path) - 1:
        fail("Unsupported JSONPath selector")
    return steps

def path_present(body, steps):
    if steps == None:
        return False
    value = body
    for part in steps:
        if type(part) == "int":
            if type(value) != "list" or part >= len(value):
                return False
        elif type(value) != "dict" or part not in value:
            return False
        value = value[part]
    return True

def path_get(body, steps):
    value = body
    for part in steps:
        value = value[part]
    return value

def path_set(body, steps, value):
    if not steps:
        return value
    parent = body
    for part in steps[:-1]:
        parent = parent[part]
    parent[steps[-1]] = value
    return body

def public_jwk(public_key):
    modulus = binascii.unhexlify(public_key.split("|")[1])
    return {"kty":"RSA", "e":"AQAB", "n":base64.urlsafe_b64encode(modulus).decode("utf-8").rstrip("=")}

def form_decode(value):
    # Decode UTF-8 percent bytes directly; urllib's type inspection is unavailable
    # in the pinned native runtime. Invalid percent escapes remain literal.
    parts = value.replace("+", " ").split("%")
    result = bytes(parts[0], encoding="utf-8")
    for part in parts[1:]:
        if len(part) >= 2 and all([c.lower() in "0123456789abcdef" for c in part[:2].elems()]):
            result += binascii.unhexlify(part[:2]) + bytes(part[2:], encoding="utf-8")
        else:
            result += bytes("%" + part, encoding="utf-8")
    return codecs.utf_8_decode(result, "strict", True)[0]

def form_encode(value):
    encoded = binascii.hexlify(bytes(value, encoding="utf-8")).decode("ascii")
    output = []
    for i in range(0, len(encoded), 2):
        pair = encoded[i:i + 2]
        code = int(pair, 16)
        if (code >= 48 and code <= 57) or (code >= 65 and code <= 90) or (code >= 97 and code <= 122) or code in [45, 46, 95, 126]:
            output.append(chr(code))
        else:
            output.append("+" if code == 32 else "%" + pair.upper())
    return "".join(output)

def form_index(parts, name):
    matches = [i for i in range(len(parts)) if form_decode(parts[i].split("=", 1)[0]) == name]
    if len(matches) > 1:
        fail("Configured form field occurs more than once")
    return matches[0] if matches else None

def form_set(parts, index, value):
    # Preserve the original key encoding and every untouched form segment.
    parts[index] = parts[index].split("=", 1)[0] + "=" + form_encode(value)

def select_data(body, steps):
    # JSON strings encountered along the selector are decoded for traversal and
    # recorded so their original string envelope can be restored after mutation.
    parent = {"root":body}
    key = "root"
    encoded = []
    for i in range(len(steps) + 1):
        value = parent[key]
        if type(value) == "string" and value.strip().startswith(("{", "[")):
            parent[key] = json.loads(value)
            encoded.append((parent, key))
        if i == len(steps):
            return parent[key], encoded
        if not path_present(parent[key], [steps[i]]):
            return None, encoded
        parent = parent[key]
        key = steps[i]
    return None, encoded

def overlap(a, b):
    length = min(len(a), len(b))
    return a[:length] == b[:length]

def process(input, ctx):
    text = input.body()
    if type(text) != "string":
        return input
    data_type = adapter_input(input, "data_type") or "json"
    if data_type not in ["json", "form"]:
        fail("Unsupported data_type; expected json or form")
    parts = None
    if data_type == "form":
        parts = text.split("&")
        body = {}
        for part in parts:
            pair = part.split("=", 1)
            name = form_decode(pair[0])
            if name not in body:
                body[name] = form_decode(pair[1]) if len(pair) == 2 else ""
    else:
        if not text.strip().startswith(("{", "[")):
            return input
        body = json.loads(text)
    data_steps = json_path_steps(adapter_input(input, "data_selector") or "$")
    card_body, encoded = select_data(body, data_steps)
    if type(card_body) not in ["dict", "list"]:
        return input
    expected_query = adapter_input(input, "graphql_query")
    if expected_query != None:
        query = body.get("query") if type(body) == "dict" else None
        if query == None and type(card_body) == "dict":
            query = card_body.get("query")
        if query != expected_query:
            return input
    configured = {role:json_path_steps(adapter_input(input, name)) for role, name in [
        ("number", "card_number_selector"),
        ("cvc", "card_cvc_selector"),
        ("expiryMonth", "expiry_month_selector"),
        ("expiryYear", "expiry_year_selector"),
    ]}
    targets = {role:steps for role, steps in configured.items() if path_present(card_body, steps)}
    if any([not steps for steps in targets.values()]):
        fail("Card JSONPath must select a field")
    if len({json.dumps(p):True for p in targets.values()}) != len(targets):
        fail("Card field mappings must point to distinct locations")
    resolved = {}
    # Browser expiry is already encrypted. Override it only when explicitly supplied.
    for role, context_key in [("expiryMonth", "adyen_expiry_month"), ("expiryYear", "adyen_expiry_year")]:
        if role in targets:
            value = session.context(context_key)
            if value == None:
                targets.pop(role)
            else:
                resolved[role] = str(value)
    if not targets:
        return input
    metadata = {}
    # Metadata never causes a reveal. It follows an already selected PAN target.
    if "number" in targets:
        for name, format in [("bin_selector", "number_bin6"), ("masked_number_selector", "number_masked")]:
            steps = json_path_steps(adapter_input(input, name))
            if path_present(body, steps):
                if not steps or any([overlap(steps, data_steps + p) for p in targets.values()]):
                    fail("Metadata selector must not overwrite card data")
                if any([overlap(steps, p) for p in metadata.values()]):
                    fail("Metadata mappings must point to distinct locations")
                metadata[format] = steps
    changed_form = {}
    if parts != None:
        for steps in [data_steps + p for p in targets.values()] + metadata.values():
            name = steps[0]
            changed_form[name] = form_index(parts, name)
    key = session.get("adyen_public_key")
    if not key:
        fail("Adyen key unavailable for encryption")
    # Prefer the time captured alongside the provider key; JSON-only integrations
    # may supply an explicit generation time through the established context key.
    generationtime = session.get("adyen_generationtime") or session.context("adyen_generationtime")
    if not generationtime:
        fail("Adyen generation time unavailable for encryption")
    # The response function captures the destination's evidence-backed format
    # alongside its key. No request-header inference or silent algorithm default.
    format = session.get("adyen_encryption_format")
    if not format:
        fail("Adyen encryption format unavailable for encryption")
    algorithm, encryption = format.split("/")
    present = [role for role in ["number", "cvc"] if role in targets]
    if present:
        label = adapter_input(input, "card_label")
        card = session.card(label) if label else session.card()
        aliases = {"number":card.number, "cvc":getattr(card, "cvc", None)}
        plain = vault.reveal([aliases[role] for role in present])
        resolved.update(dict(zip(present, plain)))
    jwk = public_jwk(key)
    for role, steps in targets.items():
        payload = {role:str(resolved[role]), "generationtime":generationtime}
        encrypted = jwe.encrypt(bytes(json.dumps(payload), encoding="utf-8"), jwk,
            algorithm=algorithm, encryption=encryption, extra_headers={"version":"1"})
        path_set(card_body, steps, encrypted.decode("utf-8"))
    for format, steps in metadata.items():
        number = str(resolved["number"])
        value = number[:6] if format == "number_bin6" else "*" * max(0, len(number) - 4) + number[-4:]
        path_set(body, steps, value)
    for i in range(len(encoded) - 1, -1, -1):
        parent, key = encoded[i]
        parent[key] = json.dumps(parent[key])
    if parts != None:
        for name, index in changed_form.items():
            form_set(parts, index, body[name])
        input.set_body("&".join(parts))
    else:
        input.set_body(json.dumps(body))
    return input
