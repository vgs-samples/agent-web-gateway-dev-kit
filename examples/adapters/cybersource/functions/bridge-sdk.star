load("@vgs//agent_gateway", session="session")
load("@stdlib//json", json="json")
load("@stdlib//hashlib", hashlib="hashlib")

def process(input, ctx):
    text = input.body()
    anchor = "function je(e,t){let r=arguments.length>2&&void 0!==arguments[2]?arguments[2]:0;"
    if type(text) != "string" or anchor not in text:
        return input
    expected = adapter_input(input, "sdk_sha256")
    observed = hashlib.sha256(input.raw_body()).hexdigest()
    if not expected or observed != expected or text.count(anchor) != 1:
        fail("CS_SDK_VERSION_MISMATCH sha256=" + observed + " expected=" + str(expected) + " anchors=" + str(text.count(anchor)))
    binding_key = adapter_input(input, "session_binding_key")
    if binding_key and session.context("cybersource_binding_key") != binding_key:
        fail("CS_SESSION_BINDING_MISMATCH")
    standins = {
        "number":adapter_input(input, "standin_number") if binding_key else session.context("cybersource_number_standin"),
        "securityCode":adapter_input(input, "standin_cvc") if binding_key else session.context("cybersource_cvc_standin"),
    }
    if not all([type(v) == "string" and v for v in standins.values()]):
        fail("CS_STANDINS_MISSING")
    # Only exact session stand-ins use this TLS-protected relay. Real card values
    # and mixed inputs retain the provider's original browser encryption path.
    bridge = 'const awgCsCard=e&&e.CARD,awgCsStandins=' + json.dumps(standins) + ';'
    bridge += 'const awgCsFields=awgCsCard?["number","securityCode"].filter(k=>Object.prototype.hasOwnProperty.call(awgCsCard,k)):[];'
    # Letter-only encoding avoids automatic PAN/CVC replacement anywhere inside
    # the signed context or relay payload before the custom request function runs.
    bridge += 'if(awgCsFields.length&&awgCsFields.every(k=>typeof awgCsCard[k]==="string"&&awgCsCard[k]===awgCsStandins[k]))return Promise.resolve("AWGCS1:"+Array.from(new TextEncoder().encode(JSON.stringify({data:e,context:t.raw,index:r})),b=>String.fromCharCode(97+(b>>4),97+(b&15))).join(""));'
    input.set_body(text.replace(anchor, anchor + bridge))
    # The transformed script contains session-specific stand-ins. Never cache it.
    headers = [(k, v) for k, v in input.headers() if k.lower() not in ["cache-control", "pragma", "expires", "etag", "last-modified"]]
    input.set_headers(headers + [("Cache-Control", "no-store, private"), ("Pragma", "no-cache")])
    return input
