# Offline host interfaces only. Provider transformation code is loaded unchanged.
load("@stdlib//larky", larky="larky")
load("@stdlib//binascii", test_binascii="binascii")
_test_state = {"body": capture["body"], "headers": capture["headers"], "values": capture.get("captured", {}), "reveals": []}
def _test_get(key):
    return _test_state["values"].get(key)
def _test_put(key, value):
    _test_state["values"][key] = value
def _test_context(key):
    return capture.get("context", {}).get(key)
def _test_card(label=None):
    return larky.struct(number="synthetic_pan_alias", cvc="synthetic_cvc_alias")
def _test_reveal(values):
    _test_state["reveals"].extend(values)
    known = capture["vault"]
    for value in values:
        if value not in known:
            fail("ALIAS_UNAVAILABLE")
    return [known[value] for value in values]
session = larky.struct(get=_test_get, put=_test_put, context=_test_context, card=_test_card)
vault = larky.struct(reveal=_test_reveal)
def adapter_input(input, name):
    return capture.get("inputs", {}).get(name)
def _test_body():
    return _test_state["body"]
def _test_raw_body():
    return test_binascii.unhexlify(capture["bodyHex"])
def _test_uri():
    return capture["path"]
def _test_headers():
    return _test_state["headers"]
def _test_set_body(value):
    _test_state["body"] = value
def _test_set_headers(value):
    _test_state["headers"] = value
message = larky.struct(body=_test_body, raw_body=_test_raw_body, uri=_test_uri, headers=_test_headers,
                       set_body=_test_set_body, set_headers=_test_set_headers)
