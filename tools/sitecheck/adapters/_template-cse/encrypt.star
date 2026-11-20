# TEMPLATE (route.request): rebuild a client-side-encrypted card form from the session's real card.
#
# The browser encrypted the agent's STAND-IN values with the provider's public key. Nobody can decrypt that (only the
# provider holds the private key), and nobody needs to: this function throws those fields away and encrypts the REAL
# values, revealed from the vault, with the same public key (captured by capture.star), in the same format.
#
# Start from adapters/adyen-cse/encrypt.star (tested end to end on H&M) and change only what your provider differs in:
#   1. where the encrypted fields sit in the request (binding input `form`, a JSONPath on request.body);
#   2. which field holds which value (FIELDS below);
#   3. the plaintext each field encrypts (Adyen: {"number": ..., "generationtime": ...}; others: the bare value);
#   4. the envelope: JWE RSA-OAEP-256 + A256GCM (Adyen, CyberSource Flex) via @vendor//jose/jwe, or what the
#      provider's JS library produces (read it: the SDK is public).
#
# Inputs: form (required, request.body JSONPath to the object holding the encrypted fields), card_label (optional).
# Never log or return revealed values. On a request you do not recognise, return input unchanged.
load("@vgs//agent_gateway", session="session")
load("@vgs//vault", vault="vault")
load("@vendor//jose/jwe", jwe="jwe")
load("@stdlib//json", json="json")
load("@stdlib//base64", base64="base64")
load("@stdlib//binascii", binascii="binascii")
adapter_input = None

# TODO: role -> field name in the provider's form
FIELDS = {"number": "encryptedCardNumber", "cvc": "encryptedSecurityCode"}
# TODO: role -> session context key for values that are not secret (expiry)
CONTEXT_FIELDS = {"expiryMonth": ("encryptedExpiryMonth", "expiry_month"), "expiryYear": ("encryptedExpiryYear", "expiry_year")}


def public_jwk(key):
    # TODO: convert what capture.star stored into a JWK. Adyen stores "10001|<modulus hex>":
    modulus = binascii.unhexlify(key.split("|")[1])
    return {"kty": "RSA", "e": "AQAB", "n": base64.urlsafe_b64encode(modulus).decode("utf-8").rstrip("=")}


def plaintext(role, value):
    # TODO: Adyen encrypts {"<role>": value, "generationtime": <page time>}; others may encrypt the bare value.
    return json.dumps({role: str(value), "generationtime": session.get("psp_generationtime")})


def process(input, ctx):
    text = input.body()
    if type(text) != "string" or not text.strip().startswith("{"):
        return input
    form = adapter_input(input, "form")
    if type(form) != "dict":
        return input
    body = json.loads(text)
    present = [role for role in FIELDS if FIELDS[role] in form]
    extra = {}
    for role, (field, ctx_key) in CONTEXT_FIELDS.items():
        v = session.context(ctx_key)
        if field in form and v != None:
            extra[role] = (field, str(v))
    if not present and not extra:
        return input
    key = session.get("psp_public_key")
    if not key:
        fail("Load the payment form in this session first: the provider's public key was not captured")
    values = {}
    if present:
        label = adapter_input(input, "card_label")
        card = session.card(label) if label else session.card()
        aliases = {"number": card.number, "cvc": getattr(card, "cvc", None)}
        present = [r for r in present if aliases.get(r)]   # never reveal a CVC the card does not have
        for role, value in zip(present, vault.reveal([aliases[r] for r in present])):
            values[role] = (FIELDS[role], value)
    values.update(extra)
    jwk = public_jwk(key)
    for role, (field, value) in values.items():
        token = jwe.encrypt(bytes(plaintext(role, value), encoding="utf-8"), jwk,
                            algorithm="RSA-OAEP-256", encryption="A256GCM", extra_headers={"version": "1"})
        form[field] = token.decode("utf-8")
    # The input is a copy: write the form back where the binding's JSONPath found it. TODO: match your path, e.g. for
    # "$.paymentMethod": body["paymentMethod"] = form; for "$.adyenData.encryptedAdyenForm" see adyen-cse/encrypt.star.
    body["paymentMethod"] = form
    input.set_body(json.dumps(body))
    return input
