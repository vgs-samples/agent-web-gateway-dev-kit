load("@vgs//agent_gateway", session="session")

def usable_key(value):
    parts = value.split("|")
    return len(parts) == 2 and parts[0] == "10001" and len(parts[1]) > 0 and len(parts[1]) % 2 == 0 and all([c.lower() in "0123456789abcdef" for c in parts[1].elems()])

def quoted_values(text, marker):
    values = []
    for piece in text.split(marker)[1:]:
        tail = piece.split("'", 1)
        if len(tail) == 2 and tail[0] not in values:
            values.append(tail[0])
    return values

def usable_time(value):
    # The secured-fields server supplies UTC seconds, not the session creator's clock.
    return len(value) == 20 and value[4] == "-" and value[7] == "-" and value[10] == "T" and value[13] == ":" and value[16] == ":" and value[19] == "Z" and all([value[i] in "0123456789" for i in [0,1,2,3,5,6,8,9,11,12,14,15,17,18]])

def process(input, ctx):
    text = input.body()
    if type(text) != "string":
        return input
    keys = quoted_values(text, "Object.defineProperty(window, 'adyen', { value: Object.freeze({key: '")
    times = quoted_values(text, "Object.defineProperty(window, 'genTime', { value: '")
    # Store a pair from the same page. Error/unrelated/ambiguous pages change nothing.
    if len(keys) == 1 and usable_key(keys[0]) and len(times) == 1 and usable_time(times[0]):
        session.put("adyen_public_key", keys[0])
        session.put("adyen_generationtime", times[0])
    return input
