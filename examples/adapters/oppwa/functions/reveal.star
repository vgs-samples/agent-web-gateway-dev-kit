load("@vgs//vault", vault="vault")

# OPPWA sends PAN and CVV separately. Never require both fields or an expiry.
# Connection: POST eu-prod.oppwa.com /v1/checkouts/*, route.request.
def form_decode_ascii(value):
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
    return str(value).replace("%", "%25").replace("&", "%26").replace("=", "%3D").replace("+", "%2B").replace(" ", "+")

def process(input, ctx):
    # The connection glob also matches /bins and /logs. They must not reveal.
    path = input.uri().split("?", 1)[0]
    prefix = "/v1/checkouts/"
    if not path.startswith(prefix):
        return input
    checkout = path[len(prefix):]
    if not checkout or "/" in checkout:
        return input
    content_types = [v.lower().split(";", 1)[0].strip() for k, v in input.headers() if k.lower() == "content-type"]
    body = input.body()
    if "application/x-www-form-urlencoded" not in content_types or type(body) != "string":
        return input
    pairs = body.split("&")
    positions = []
    submitted = []
    for i in range(len(pairs)):
        parts = pairs[i].split("=", 1)
        if len(parts) != 2 or form_decode_ascii(parts[0]) not in ["card.number", "card.cvv"]:
            continue
        value = form_decode_ascii(parts[1])
        if value:
            positions.append(i)
            submitted.append(value)
    if not submitted:
        return input
    # Reveal the actual submitted stand-ins; never select a replacement card.
    plain = vault.reveal(submitted)
    if len(plain) != len(submitted) or any([v == None for v in plain]):
        fail("OPPWA_REVEAL_UNAVAILABLE")
    values = dict(zip(positions, plain))
    input.set_body("&".join([pairs[i].split("=", 1)[0] + "=" + form_value(values[i]) if i in values else pairs[i] for i in range(len(pairs))]))
    return input
