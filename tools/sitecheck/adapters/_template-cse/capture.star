# TEMPLATE (route.response): capture a payment provider's public key from the page or API response that delivers it.
#
# Bind it to the response that carries the key (`when` = that host/method/path). It stores the key, and anything else
# the encryption needs (a server time, a key id), in the reveal session with session.put. The encrypt function reads
# them with session.get. Pages that are not the one you expect must change nothing: return input unchanged.
#
# Inputs (all constants on the binding; delete what you do not use):
#   key_marker    text right before the key in the body, e.g. "Object.freeze({key: '"   (text/HTML/JS bodies)
#   key_end       text right after the key, e.g. "'"
#   key_json      set instead of the markers when the response is JSON: bind it as
#                 {"from": "response.body", "path": "$.publicKey"} (the input then holds the value itself)
#   session_key   the session value name, e.g. "psp_public_key"
#
# Test: awg-sitecheck adapter dry-run <spec> capture <fixture with the saved response>  -> result.session.values
load("@vgs//agent_gateway", session="session")
adapter_input = None


def between(text, start, end):
    """Every distinct value between start and end markers."""
    found = []
    for piece in text.split(start)[1:]:
        tail = piece.split(end, 1)
        if len(tail) == 2 and tail[0] and tail[0] not in found:
            found.append(tail[0])
    return found


def plausible_key(value):
    # TODO: tighten for your provider, e.g. Adyen "10001|<hex>", a PEM header, a JWK with "kty": "RSA".
    return type(value) == "string" and len(value) >= 64


def process(input, ctx):
    name = adapter_input(input, "session_key") or "psp_public_key"
    value = adapter_input(input, "key_json")
    if value == None:
        text = input.body()
        if type(text) != "string":
            return input
        start = adapter_input(input, "key_marker")
        end = adapter_input(input, "key_end") or "'"
        if not start:
            return input
        values = between(text, start, end)
        # exactly one candidate on this page, or it is not the page we want: change nothing
        if len(values) != 1:
            return input
        value = values[0]
    if plausible_key(value):
        session.put(name, value)
    return input
