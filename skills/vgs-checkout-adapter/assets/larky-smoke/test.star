# Synthetic runtime smoke only. This is not an adapter or a vault integration.
def run_case():
    fields = capture["body"].split("&")
    result = "&".join(["card.cvv=" + capture["revealed"] if field == "card.cvv=999" else field for field in fields])
    if result != "card.cvv=123&note=a%2Bb+c":
        fail("SMOKE_BODY_MISMATCH")
    print("LARKY_CASE_PASSED")
    return {"passed": True, "scope": "synthetic runtime smoke"}
run_case()
