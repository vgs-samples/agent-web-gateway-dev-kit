load("@vgs//agent_gateway", session="session")
load("@vgs//vault", vault="vault")
load("@vendor//jose/jwe", jwe="jwe")
load("@stdlib//json", json="json")
load("@stdlib//binascii", binascii="binascii")
load("@stdlib//codecs", codecs="codecs")

def decode_segment(value):
    encoded = value.replace("-", "+").replace("_", "/") + "=" * ((4 - len(value) % 4) % 4)
    return json.loads(binascii.a2b_base64(encoded).decode("utf-8"))

def process(input, ctx):
    text = input.body()
    if type(text) != "string" or not text.startswith("AWGCS1:"):
        return input
    relay = text[7:]
    alphabet = "abcdefghijklmnop"
    if len(relay) % 2 != 0 or any([c not in alphabet for c in relay.elems()]):
        fail("CS_RELAY_ENCODING_INVALID")
    encoded = "".join(["0123456789abcdef"[alphabet.find(c)] for c in relay.elems()])
    payload = json.loads(binascii.unhexlify(encoded).decode("utf-8"))
    data = payload.get("data") if type(payload) == "dict" else None
    card_data = data.get("CARD") if type(data) == "dict" else None
    if type(card_data) != "dict":
        return input
    fields = [name for name in ["number", "securityCode"] if name in card_data]
    if not fields:
        return input
    capture = session.get("cybersource_capture_context")
    if not capture:
        fail("CS_CONTEXT_MISSING")
    if payload.get("context") != capture:
        fail("CS_CONTEXT_MISMATCH")
    # Never trust a browser-supplied encryption key: the complete signed context
    # must equal the one captured from the merchant response in this session.
    flx = decode_segment(capture.split(".")[1]).get("flx")
    if type(flx) != "dict" or flx.get("origin") != "https://flex.cybersource.com" or flx.get("path") != "/flex/v2/tokens":
        fail("CS_CONTEXT_DESTINATION_MISMATCH")
    key = flx.get("jwk")
    if type(key) != "dict" or key.get("kty") != "RSA" or not key.get("n") or not key.get("e"):
        fail("CS_CAPTURE_KEY_MISSING")
    binding_key = adapter_input(input, "session_binding_key")
    if binding_key and session.context("cybersource_binding_key") != binding_key:
        fail("CS_SESSION_BINDING_MISMATCH")
    expected = {
        "number":adapter_input(input, "standin_number") if binding_key else session.context("cybersource_number_standin"),
        "securityCode":adapter_input(input, "standin_cvc") if binding_key else session.context("cybersource_cvc_standin"),
    }
    for name in fields:
        if type(expected[name]) != "string" or not expected[name] or card_data[name] != expected[name]:
            fail("CS_STANDIN_MISMATCH")
    label = adapter_input(input, "card_label")
    card = session.card(label) if label else session.card()
    aliases = {"number":getattr(card, "number", None), "securityCode":getattr(card, "cvc", None)}
    if any([not aliases[name] for name in fields]):
        fail("CS_ALIAS_MISSING")
    values = vault.reveal([aliases[name] for name in fields])
    for i in range(len(fields)):
        card_data[fields[i]] = str(values[i])
    # This is the observed Microform 2.12.1 format: RSA-OAEP uses SHA-1.
    # Preserve submitted expiry, index, context, and all unrelated data.
    encrypted = jwe.encrypt(codecs.encode(json.dumps(payload), encoding="utf-8", unescape=False), key,
        algorithm="RSA-OAEP", encryption="A256GCM", extra_headers={"kid":key.get("kid", "")})
    input.set_body(encrypted.decode("utf-8"))
    return input
