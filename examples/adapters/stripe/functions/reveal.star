load("@vgs//agent_gateway", session="session")
load("@vgs//vault", vault="vault")

# Current function API requires the explicit vault module import.
# Stripe accepts form-encoded card fields over HTTPS, without Adyen-style JWE.
# Preserve all unrelated form pairs byte-for-byte, including merchant credentials.
def form_decode_ascii(value):
    # Decode ASCII field names and PAN/CVC stand-ins once. The native 1.0.0
    # urllib decoder fails on its bytes-type check. Leave unrelated values raw.
    output = []
    skip = 0
    for i in range(len(value)):
        if i < skip:
            continue
        if value[i] == "+":
            output.append(" ")
        elif value[i] == "%" and i + 2 < len(value) and all([c in "0123456789abcdefABCDEF" for c in [value[i + 1], value[i + 2]]]):
            code = int(value[i + 1:i + 3], 16)
            output.append(chr(code) if code < 128 else value[i:i + 3])
            skip = i + 3
        else:
            output.append(value[i])
    return "".join(output)

def form_value(value):
    # Revealed PAN/CVC values and optional expiry are strings, not form syntax.
    return str(value).replace("%", "%25").replace("&", "%26").replace("=", "%3D").replace("+", "%2B").replace(" ", "+")

def process(input, ctx):
    content_types = [v.lower().split(";", 1)[0].strip() for k, v in input.headers() if k.lower() == "content-type"]
    body = input.body()
    if "application/x-www-form-urlencoded" not in content_types or type(body) != "string":
        return input
    pairs = body.split("&")
    names = [form_decode_ascii(pair.split("=", 1)[0]) if "=" in pair else "" for pair in pairs]
    roles = {prefix + "[" + role + "]": role for prefix in ["card", "payment_method_data[card]"] for role in ["number", "cvc"]}
    positions = []
    submitted = []
    for i in range(len(pairs)):
        role = roles.get(names[i])
        if role == None:
            continue
        value = form_decode_ascii(pairs[i].split("=", 1)[1])
        if role == "number":
            # Stripe.js formats PAN stand-ins as groups separated by spaces.
            value = value.replace(" ", "")
        if value:
            positions.append(i)
            submitted.append(value)
    if not submitted:
        return input
    # Reveal exactly what was submitted; never substitute another session card.
    # Index by occurrence so repeated fields can contain different stand-ins.
    plain = vault.reveal(submitted)
    values = dict(zip(positions, plain))
    # Expiry is not secret. Keep the browser value unless explicitly overridden.
    for prefix in ["card", "payment_method_data[card]"]:
        for role, context_key in [("exp_month", "stripe_expiry_month"), ("exp_year", "stripe_expiry_year")]:
            field = prefix + "[" + role + "]"
            override = session.context(context_key)
            if override != None:
                for i in range(len(names)):
                    if names[i] == field:
                        values[i] = override
    input.set_body("&".join([pairs[i].split("=", 1)[0] + "=" + form_value(values[i]) if i in values else pairs[i] for i in range(len(pairs))]))
    return input
