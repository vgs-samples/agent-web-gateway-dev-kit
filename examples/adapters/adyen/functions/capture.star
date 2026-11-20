load("@vgs//agent_gateway", session="session")
load("@stdlib//re", re="re")

IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"

def identifier_matches(name, suffix, text):
    # Larky's linear-time regex engine does not support lookaround assertions.
    characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_$"
    matches = []
    for match in re.finditer(name.replace("$", r"\$") + suffix, text):
        start = match.start()
        end = start + len(name)
        if (start == 0 or text[start - 1] not in characters) and (end == len(text) or text[end] not in characters):
            matches.append(match)
    return matches

def literal_value(token, script):
    if token[0] in ["'", '"']:
        return token[1:-1] if token[-1] == token[0] else None
    # Resolve a single, directly assigned constant. Conflicting assignments or
    # expressions are not evidence of a stable encryption setting.
    assignments = [m for m in identifier_matches(token, r"\s*=", script) if script[m.end():m.end() + 1] != "="]
    if len(assignments) != 1:
        return None
    tail = script[assignments[0].end():]
    value = re.match(r"""\s*(["'][A-Za-z0-9_-]+["'])\s*[,;]""", tail)
    if not value:
        return None
    quoted = value.group(1)
    return quoted[1:-1] if quoted[-1] == quoted[0] else None

def argument_default(prefix, variable, index):
    # Adyen's transpiled encryption function reads optional arguments 2 and 3.
    # Match the structure and verify all references use the same arguments array.
    number = str(index)
    pattern = r"\s*=\s*(" + IDENTIFIER + r")\.length\s*>\s*" + number
    pattern += r"\s*&&\s*void\s+0\s*!==\s*(" + IDENTIFIER + r")\[" + number + r"\]"
    pattern += r"\s*\?\s*(" + IDENTIFIER + r")\[" + number + r"\]\s*:\s*"
    pattern += r"""(["'][A-Za-z0-9_-]+["']|""" + IDENTIFIER + r")\s*[,;]"
    found = identifier_matches(variable, pattern, prefix)
    if len(found) != 1:
        return None
    match = found[0]
    if match.group(1) != match.group(2) or match.group(1) != match.group(3):
        return None
    return match.group(1), match.group(4)

def script_encryption_formats(script):
    # Read values wired into the protected header, not the SDK's algorithm list.
    # This recognizes the captured provider structure without executing JavaScript
    # or inferring settings from a merchant, SDK version, or algorithm allowlist.
    pattern = r"\.setProtectedHeader\s*\(\s*\{\s*alg\s*:\s*(" + IDENTIFIER + r")"
    pattern += r"\s*,\s*enc\s*:\s*(" + IDENTIFIER + r")\s*,\s*version\s*:\s*[\"']1[\"']\s*\}"
    formats = []
    for header in re.finditer(pattern, script):
        prefix = script[max(0, header.start() - 2048):header.start()]
        owners = list(re.finditer(r"(" + IDENTIFIER + r")\s*=\s*function\s*\(\s*\)\s*\{", prefix))
        if not owners:
            return None
        owner = owners[-1]
        function_prefix = prefix[owner.end():]
        enc = argument_default(function_prefix, header.group(2), 2)
        alg = argument_default(function_prefix, header.group(1), 3)
        if not enc or not alg or enc[0] != alg[0]:
            return None
        encryption = literal_value(enc[1], script)
        algorithm = literal_value(alg[1], script)
        if not encryption or not algorithm:
            return None
        # The captured helper has one declaration and one two-argument call.
        # Extra arguments, aliases, exports, or additional uses could override
        # its defaults; do not guess the active format in those cases.
        name = owner.group(1)
        uses = identifier_matches(name, "", script)
        calls = identifier_matches(name, r"\s*\(\s*" + IDENTIFIER + r"\s*,\s*" + IDENTIFIER + r"\s*\)", script)
        if len(uses) != 2 or len(calls) != 1:
            return None
        formats.append(algorithm + "/" + encryption)
    return formats

def encryption_format(text):
    formats = []
    for script in re.finditer(r"(?is)<script\b[^>]*>(.*?)</script\s*>", text):
        found = script_encryption_formats(script.group(1))
        if found == None:
            return None
        formats.extend(found)
    values = unique(formats)
    return values[0] if len(values) == 1 else None

def usable_key(value):
    parts = value.split("|")
    return len(parts) == 2 and parts[0] == "10001" and len(parts[1]) > 0 and len(parts[1]) % 2 == 0 and all([c.lower() in "0123456789abcdef" for c in parts[1].elems()])

def quoted_values(text, marker, quote="'"):
    values = []
    for piece in text.split(marker)[1:]:
        tail = piece.split(quote, 1)
        if len(tail) == 2 and tail[0] not in values:
            values.append(tail[0])
    return values

def unique(values):
    return list({v:True for v in values}.keys())

def usable_time(value):
    # The secured-fields server supplies UTC seconds, not the session creator's clock.
    return len(value) == 20 and value[4] == "-" and value[7] == "-" and value[10] == "T" and value[13] == ":" and value[16] == ":" and value[19] == "Z" and all([value[i] in "0123456789" for i in [0,1,2,3,5,6,8,9,11,12,14,15,17,18]])

def process(input, ctx):
    text = input.body()
    if type(text) != "string":
        return input
    # Secured-fields versions use either frozen properties or older assignments.
    # Both are provider formats; merchant-specific names belong in destinations.
    keys = unique(quoted_values(text, "Object.defineProperty(window, 'adyen', { value: Object.freeze({key: '") + quoted_values(text, 'adyen.key = "', '"'))
    times = unique(quoted_values(text, "Object.defineProperty(window, 'genTime', { value: '") + quoted_values(text, 'var genTime = "', '"'))
    # Store all three values together. Unrelated/ambiguous pages change nothing.
    if len(keys) == 1 and usable_key(keys[0]) and len(times) == 1 and usable_time(times[0]):
        format = encryption_format(text)
        if not format:
            fail("Adyen encryption format could not be identified from the response")
        session.put("adyen_public_key", keys[0])
        session.put("adyen_generationtime", times[0])
        session.put("adyen_encryption_format", format)
    return input
