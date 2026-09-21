# X-Ray trace — sale → STK → callback → settlement (2026-09-21)

**Environment:** dev · **Region:** us-west-1 · **Account:** 240462142849
**Captured:** 2026-09-21 18:02 UTC / 21:02 EAT
**Sale ID (correlation key):** `2c1cbb8b-4389-421a-b60c-e31dd58cd89b`

Sandbox data only. The callback path segment is a secret and is redacted below as
`<callback-secret>`.

---

## Summary

The transaction produces **three traces, not one**. Safaricom initiates the
callback as a new inbound HTTP request with no upstream context to continue, so
it cannot be stitched to the STK trace. They are correlated by sale ID, not by
trace ID. Presenting them as a single continuous trace would misrepresent what
X-Ray actually captured.

| # | Trace ID | Duration | Services | Hop |
|---|----------|----------|----------|-----|
| 1 | `1-f9c854e2-60292f314acf2756b35d6933` | 2.946s | payments | STK push to Daraja |
| 2 | `1-36eca49c-b1002c99118ffde2f7227f4e` | 0.059s | web, pos | Web → POS sale read |
| 3 | `1-bafcca63-80239dc21ef6b719ac120203` | 0.144s | payments, pos | Callback → POS settlement |

---

## Timeline (UTC / EAT = UTC+3)

| UTC | EAT | Event | Result |
|-----|-----|-------|--------|
| 18:02:33.747 | 21:02:33 | `POST /payments/stk` begins | |
| 18:02:36.693 | 21:02:36 | STK push returns (2946 ms) | **202** |
| 18:02:40.799 | 21:02:40 | `GET /sales/{id}` via Web | |
| 18:02:40.826 | 21:02:40 | Web → POS `GET /sales/{id}` (28 ms) | **200** |
| 18:02:40.858 | 21:02:40 | Web responds (59 ms) | **200** |
| 18:02:47.445 | 21:02:47 | Daraja callback inbound | |
| 18:02:47.559 | 21:02:47 | Payments → POS `payment-result` (26 ms) | **200** |
| 18:02:47.588 | 21:02:47 | Callback responds (144 ms) | **200** |

Callback arrived **10.8 s** after the STK call completed, **13.7 s** after it
began — well inside the Payments SLO's 60 s callback budget.

---

## Trace 1 — STK push

```
payments  POST http://payments:8080/payments/stk -> 202   2946.1 ms
  └─ payments.stk_push
```

Single segment. See [Known gap](#known-gap--pos--payments-context-propagation).

## Trace 2 — Web → POS

```
web  GET .../sales/2c1cbb8b-...-e31dd58cd89b -> 200   59.0 ms
  └─ web.http_request -> http://pos:8080/sales/2c1cbb8b-...
pos  GET http://pos:8080/sales/2c1cbb8b-...-e31dd58cd89b -> 200   28.3 ms
```

Context propagates across the Service Connect hop: one trace, two services.

## Trace 3 — Callback → settlement (headline artifact)

```
payments  POST .../callbacks/mpesa/<callback-secret> -> 200   143.6 ms
  └─ payments.callback_http
     └─ payments.callback_process
        └─ payments.http_request -> http://pos:8080/internal/sales/2c1cbb8b-.../payment-result
pos       POST http://pos:8080/internal/sales/2c1cbb8b-.../payment-result -> 200   25.9 ms
```

This is the money-path hop the brief asks for: the callback handler settles the
payment and notifies POS, and the whole chain appears in one trace across two
services. Nested subsegments (`callback_http` → `callback_process` →
`http_request`) show where the 144 ms went.

X-Ray records the route **template** (`callback_secret`) in the subsegment
names, but the segment-level `http.request.url` holds the **resolved** path,
which contains the live secret. The committed JSON has been redacted:
`callbacks/mpesa/<secret>` → `callbacks/mpesa/REDACTED-callback-secret`. That is
the only edit to the captured artifacts; trace IDs, timings and the segment
tree are untouched.

This is the same class of exposure as the uvicorn access logs, which write the
resolved callback path to CloudWatch in plaintext. Since callback authenticity
rests entirely on that path segment being unguessable (ADR-007 / TB5), anyone
with log or trace read access can forge a settlement callback. Tracked as a
finding; the durable fix is to redact the segment in the access-log formatter
and move authenticity to an HMAC header.

---

## Known gap — POS → Payments context propagation

Trace 1 contains **only a payments segment**, with no upstream web or POS
parent, even though the sale originated in the UI. Three of the four hops
propagate correctly:

| Hop | Propagates |
|-----|------------|
| Web → POS | yes (trace 2) |
| Payments → POS settlement | yes (trace 3) |
| POS → Payments (STK initiation) | **no** |

Web and Payments make outbound calls through the instrumented client
(`web.http_request`, `payments.http_request` subsegments are present). No
equivalent subsegment appears on the POS side, so POS's outbound call to
Payments is most likely not using
`tillflow_shared.otel.http_client`. Until that is changed, STK initiation cannot
be followed from the browser in a single trace.

Recorded as a gap rather than worked around; not fixed in this capture.

---

## Root cause of the earlier zero-trace state

Before this capture, X-Ray had **no traces at all**. Two independent defects,
both surfacing as "tracing is broken":

1. **IAM resource scoping.** The task role granted all four `xray:*` actions,
   but the whole `Telemetry` statement was scoped to
   `Resource = <AMP workspace ARN>`. Only `aps:RemoteWrite` accepts that ARN;
   X-Ray ingestion does not support resource-level permissions and requires
   `"*"`. Live logs showed
   `AccessDeniedException: ... not authorized to perform: xray:PutTraceSegments`.
   Because the old expression fell back to `["*"]` when AMP was unset, this
   broke silently the day AMP was enabled.

2. **Network reachability, hidden behind the first.** With IAM fixed, `web`,
   `pos` and `commission` still failed — `context deadline exceeded` against
   `xray.us-west-1.amazonaws.com`. Only `payments` has internet egress (AR-7),
   and there was no X-Ray VPC endpoint. AMP remote write was failing the same
   way (830 / 816 / 193 errors in one hour).

Fixed in PR #66: telemetry statements split and scoped per service, plus
`xray` and `aps-workspaces` interface endpoints so the three egress-free
services reach both backends over PrivateLink rather than widening egress.
Both are covered by assertions in
`infra/envs/dev/tests/architecture.tftest.hcl`.

---

## Reproduction

```bash
export AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1
cd "$(git rev-parse --show-toplevel)"
DATE=$(date -u +%Y%m%d); OUT=evidence/reliability/phase-f/traces; mkdir -p "$OUT"
: "${OUT:?run setup first}" "${DATE:?run setup first}"
```

Perform one sale → STK → callback through the UI at
`https://k8ve9ik8zl.execute-api.us-west-1.amazonaws.com/v1/`, wait ~60 s (tail
sampling holds 10 s, then X-Ray indexes), then:

```bash
aws xray get-trace-summaries \
  --start-time $(date -u -v-30M +%s) --end-time $(date -u +%s) \
  --output json > "$OUT/xray-summaries-${DATE}.json"

jq -r '.TraceSummaries[] | [.Id,.Duration,.HasError,.HasFault] | @tsv' \
  "$OUT/xray-summaries-${DATE}.json"
```

Do **not** add `--filter-expression 'service(id(name: "payments"))'` — it hides
the Web → POS trace and makes a working capture look empty.

Fetch a specific trace and list its services:

```bash
aws xray batch-get-traces --trace-ids <TRACE_ID> --output json > "$OUT/<name>.json"
jq -r '[.Traces[].Segments[].Document | fromjson | .name] | unique | join(", ")' "$OUT/<name>.json"
```

Verify the IAM fix is deployed before capturing (all four SIDs must be present):

```bash
aws iam get-role-policy --role-name devops-g3-payments-task \
  --policy-name service-permissions \
  --query 'PolicyDocument.Statement[].Sid' --output text
# XrayTraceIngestion XraySampling PrometheusRemoteWrite WriteOwnLogs ...
```

Verify both VPC endpoints exist:

```bash
aws ec2 describe-vpc-endpoints \
  --query 'VpcEndpoints[?contains(ServiceName,`xray`)||contains(ServiceName,`aps-workspaces`)].ServiceName' \
  --output text
```

## Artifacts

| File | Contents |
|------|----------|
| [xray-summaries-20260921.json](./xray-summaries-20260921.json) | 4 summaries for the capture window |
| [xray-trace-stk-20260921.json](./xray-trace-stk-20260921.json) | Trace 1 — payments |
| [xray-trace-web-pos-20260921.json](./xray-trace-web-pos-20260921.json) | Trace 2 — web, pos |
| [xray-trace-callback-settlement-20260921.json](./xray-trace-callback-settlement-20260921.json) | Trace 3 — payments, pos |
