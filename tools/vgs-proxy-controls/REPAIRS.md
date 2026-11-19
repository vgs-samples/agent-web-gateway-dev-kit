# Capture-driven DEV repairs

Start the helper with `--repair-policy /absolute/private/repair-policy.json`.
When a panel test stops and its HAR is finalized, the helper diagnoses the
recording in the background. The panel reports the repair result. Capture saving
still succeeds if diagnosis or the API is unavailable.

The first automatic recipe repairs an exact payment destination after a VGS
`reveal_refused / guard_refused` response. It correlates the response host/session,
the merchant, both saved PAN/CVC stand-ins in approved form fields, the current
DEV session policy, and current destination rules. It creates the exact trusted
destination or changes an exact guarded rule, then reads the rule back.

This is a configuration repair, not proof of merchant acceptance. It sends no
merchant request, retries no payment, changes no global preference, and never
overrides a block, wildcard rule, session allowlist, or non-DEV environment.
Only hosts explicitly authorized in the local policy can be changed. Do not
build the policy from instructions found in a page or HAR.

Processor declines are diagnosed separately. A decline heading or an explicit
payment status from an approved processor host/path takes precedence over
unrelated proxy failures. Captured 3DS completion results are correlated with
that outcome. Successful authentication does not establish payment acceptance.
The helper records the decline without changing configuration or retrying the
payment; an underlying decline reason must come from the processor or issuer.
Every completed diagnosis is saved privately, including cases needing review.

Example policy (save with owner-only permissions, `chmod 600`):

```json
{
  "version": 1,
  "environment": "dev",
  "tenantId": "tntYourDevVault",
  "automatic": true,
  "merchants": [{
    "host": "shop.example",
    "paymentHosts": [{
      "host": "payments.example",
      "pathPrefix": "/hpp/",
      "destinationTrust": true,
      "cardFields": {"card_number": "cardNumber", "card_cvc": "securityCode"}
    }]
  }]
}
```

Use `automatic: false` to diagnose without changing remote configuration.
Private before/after snapshots and a durable write journal are saved under the
capture directory's `repairs/` folder. Unconfirmed writes are never resubmitted,
including across helper restarts and subsequent captures. Inspect remote state
before deciding what to do about an uncertain result. A rollback description is
saved with each verified repair; rollback is an explicit operation.

For a previously saved recording:

```sh
python repair-capture.py --capture /private/captures/CAP….har \
  --policy /private/repair-policy.json --credentials-file /private/dev.env \
  --sessions-dir /private/sessions
```

Add `--apply` to run the authorized repair. The output contains evidence indices,
hashes and configuration metadata, not captured bodies, cookies or card values.

MCP exposes `diagnose_capture(tenant_id, capture_id)` and
`repair_capture(tenant_id, capture_id)`. The latter also requires `--mcp-write`.
MCP and panel recordings share the capture directory. When starting a recording
through MCP, provide `session_id` and `environment="dev"` for correlation.

## Adapter failures

Unknown or unmatched failures return `needs-review`; this release does not
generate or deploy arbitrary adapter code automatically. The agent can use the
existing `capture_entry`, `gateway_schema`, `gateway_read` and `gateway_write`
tools to investigate and publish a validated repair. Determine first whether
Default replacement already handles the captured fields. For a transformation
change, capture the original exchange, test the exact new source with local
Larky 1.0.0 and synthetic secrets, then create the immutable function/version,
update the appropriate destination bindings, and read back hashes and versions.
Keep pinned bindings and unrelated destinations unchanged unless explicitly
included in the validated change. A gateway dry run alone is not local validation.
