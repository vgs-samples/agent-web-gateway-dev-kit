load("@vgs//agent_gateway", session="session")
load("@vgs//vault", vault="vault")
load("@vendor//jose/jwe", jwe="jwe")
load("@stdlib//json", json="json")
load("@stdlib//base64", base64="base64")
load("@stdlib//binascii", binascii="binascii")
adapter_input = None

def public_jwk(public_key):
    modulus = binascii.unhexlify(public_key.split("|")[1])
    return {"kty":"RSA", "e":"AQAB", "n":base64.urlsafe_b64encode(modulus).decode("utf-8").rstrip("=")}

def process(input, ctx):
    text = input.body()
    if type(text) != "string" or not text.strip().startswith("{"):
        return input
    # Configure this input with request.body: $.adyenData.encryptedAdyenForm.
    form = adapter_input(input, "adyen_form")
    if type(form) != "dict":
        return input
    body = json.loads(text)
    adyen = body.get("adyenData")
    if type(adyen) != "dict" or adyen.get("encryptedAdyenForm") != form:
        return input
    fields = {"number":"encryptedAdyenCardNumber", "cvc":"encryptedAdyenSecurityCode"}
    present = [role for role in ["number", "cvc"] if fields[role] in form]
    # Preserve browser expiry ciphertext unless the session explicitly overrides it.
    expiry = {}
    for role, field, context_key in [("expiryMonth", "encryptedAdyenExpiryMonth", "adyen_expiry_month"), ("expiryYear", "encryptedAdyenExpiryYear", "adyen_expiry_year")]:
        value = session.context(context_key)
        if field in form and value != None:
            fields[role] = field
            expiry[role] = str(value)
    if not present and not expiry:
        return input
    key = session.get("adyen_public_key")
    if not key:
        fail("Load the Adyen secured-fields page in this session before encrypting: public key unavailable")
    generationtime = session.get("adyen_generationtime")
    if not generationtime:
        fail("Load the Adyen secured-fields page in this session before encrypting: server genTime unavailable")
    resolved = expiry
    if present:
        label = adapter_input(input, "card_label")
        card = session.card(label) if label else session.card()
        aliases = {"number":card.number, "cvc":getattr(card, "cvc", None)}
        plain = vault.reveal([aliases[role] for role in present])
        resolved.update(dict(zip(present, plain)))
    jwk = public_jwk(key)
    for role, value in resolved.items():
        payload = {role:str(value), "generationtime":generationtime}
        encrypted = jwe.encrypt(bytes(json.dumps(payload), encoding="utf-8"), jwk,
            algorithm="RSA-OAEP-256", encryption="A256GCM", extra_headers={"version":"1"})
        form[fields[role]] = encrypted.decode("utf-8")
    # Body selectors read values; writing the H&M wrapper back is explicit.
    adyen["encryptedAdyenForm"] = form
    input.set_body(json.dumps(body))
    return input
