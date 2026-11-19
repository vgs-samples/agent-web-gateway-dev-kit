# Review captured failures

For Sandbox and Live, start with the Recording tab or the optional MCP companion
to record one selected tab. HAR files stay local and may contain sensitive
headers, bodies and checkout details. The connected assistant can read that
capture when you explicitly configure MCP access.

Automatic destination repair is unavailable in customer environments. Recording
a test does not authorize changing destination policies, approving guarded
hosts, publishing adapters, or retrying a payment.

## Investigate and validate a change

1. Use `capture_entry`, `gateway_schema` and `gateway_read` to correlate a failed
   request with its destination, adapter version and function inputs.
2. Determine whether default replacement already handles the captured fields.
   Check destination policy, session scope, request matching and alias availability.
3. Test any transformation change locally with synthetic secrets. A gateway dry
   run does not prove that real alias reveal or merchant acceptance will succeed.
4. After explicit authorization, use `gateway_write` with `--mcp-write` to publish
   the validated function/version and update the specific destination binding.
5. Read back hashes, versions and destination inputs. Preserve unrelated bindings
   and destinations, then repeat the intended test.

A browser HAR records traffic before gateway transformation. Use independent
gateway or echo evidence to verify the transformed request. A successful 3DS
challenge does not establish payment acceptance. Do not retry a payment based
only on a browser error or an uncertain result.
