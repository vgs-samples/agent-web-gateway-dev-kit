# Local native Larky testing

Use the official [Larky 1.0.0 Linux x86-64 executable](https://github.com/verygoodsecurity/starlarky/releases/download/v1.0.0/larky-1.0.0-linux).

SHA-256: `9a2d9f179984f2e019132e04e9fdc5d17e21d1f1e9cd12581018519acf7f34b3`.

Keep the binary outside the shared skill. `setup-larky.sh` downloads/verifies it and pulls the pinned Debian image. Stop on checksum mismatch; do not silently change the pin. Linux amd64 Docker/emulation is required, including on Apple silicon.

```sh
bash scripts/setup-larky.sh /absolute/private/larky-runtime
python3 scripts/run-larky.py \
  --runtime-dir /absolute/private/larky-runtime \
  --case-dir /absolute/path/to/vgs-checkout-adapter/assets/larky-smoke \
  --result-dir /absolute/private/smoke-result
```

The smoke proves native runtime execution only. Use a new result directory for every run; the runner refuses overwrite. It verifies the binary on each invocation, disables networking, mounts runtime/case read-only, imposes resource/time bounds, and requires both successful exit and `LARKY_CASE_PASSED` in the console output. It saves logs and a hash-bearing `report.json`.

## Real transformation cases

Create a private case directory with `input.star` and `test.star`. Load HAR-derived JSON as data, not executable Starlark. Generate safe input text with Python:

```python
input_text = ('load("@stdlib//json", json="json")\ncapture = json.loads('
              + json.dumps(json.dumps(fixture)) + ')\n')
```

Use the actual deployment function. Replace only unavailable gateway module imports/host bindings with explicit offline doubles (`session`, `vault`, input/message bridge); do not translate the algorithm into Python/JavaScript. Preserve function logic exactly and record how the harness is assembled. Check the bridge against the current backend contract, not a historical PDF.

Your harness calls the real entry point, asserts output, reveal calls and session state, then prints `LARKY_CASE_PASSED`. A marker without assertions is not a meaningful test. Pass `--source /absolute/path/function.star` to record the deployment source hash; this alone does not prove harness equivalence. Save source/fixture hashes, HAR hash/indices, runtime, expected outcomes and the doubles' limitations alongside the runner report.

For a negative case, use `--expected-error SPECIFIC_ERROR_CODE`. The harness should fail with `EXPECTED_ERROR_NOT_RAISED` if the expected operation unexpectedly returns. The runner requires a nonzero runtime result and the specific error, excluding Docker startup failure codes. Inspect error provenance rather than matching broad text such as `error`.

## Required behavioral coverage

- Captured matching requests, partial PAN/CVC submissions, blanks and non-card traffic.
- Preservation of unrelated fields, repeated form pairs, raw encoding and wrappers.
- Browser expiry unchanged absent an explicitly required override.
- Missing capture marker: unchanged response and session state, no reveals.
- Matching payment missing its key/secret: explicit failure; no secret fallback.
- Actual reveal/crypto failures and cross-phase session state.
- Positive wildcard variants and nearby negatives; shared GraphQL operation guards.
- For encryption, the captured algorithm/format and independent decryption with an owned test key, including integrity/tag checks.

Functions transform; payment providers validate. Do not require a full card object or enforce unrelated card/expiry formats just to reveal supported fields.

## Native vs JVM vs gateway

Larky is not full Python; verify built-ins in the real interpreter. The existing console can prefer a JVM engine when its JVM build exists. Explicitly select/check native execution for the required native evidence. Report native crypto/module failures as limitations. Supplemental JVM Larky tests may prove crypto with recorded source/image provenance, but never relabel them native passes. A Python/JS implementation is not Larky validation.

Do not mount service-account/proxy credentials into the offline container. Doubles do not prove gateway module availability, authorization, routing or merchant compatibility. Those need [separate gateway verification](gateway-verification.md).
