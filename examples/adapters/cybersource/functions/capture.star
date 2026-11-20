load("@vgs//agent_gateway", session="session")
load("@stdlib//json", json="json")
load("@stdlib//binascii", binascii="binascii")
load("@stdlib//re", re="re")

def decode_segment(value):
    encoded = value.replace("-", "+").replace("_", "/") + "=" * ((4 - len(value) % 4) % 4)
    return binascii.a2b_base64(encoded)

def process(input, ctx):
    text = input.body()
    if type(text) != "string":
        return input
    contexts = {}
    # Merchant wrappers differ: raw JWT, JSON, HTML and JavaScript all carry
    # the same provider context. Select by CyberSource's payload contract,
    # never by a merchant-specific property name or page syntax.
    for match in re.finditer(r'(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)', text):
        token = match.group(1)
        segment = token.split(".")[1]
        if len(segment) % 4 == 1:
            continue
        raw = decode_segment(segment)
        if b'"flx"' not in raw or b'"https://flex.cybersource.com"' not in raw:
            continue
        payload = json.loads(raw.decode("utf-8"))
        flx = payload.get("flx") if type(payload) == "dict" else None
        if type(flx) == "dict" and flx.get("origin") == "https://flex.cybersource.com" and flx.get("path") == "/flex/v2/tokens":
            if type(flx.get("jwk")) != "dict":
                fail("CS_CAPTURE_KEY_MISSING")
            contexts[token] = True
    if not contexts:
        return input
    if len(contexts) != 1:
        fail("CS_CAPTURE_AMBIGUOUS")
    session.put("cybersource_capture_context", contexts.keys()[0])
    return input
