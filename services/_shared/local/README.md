# Local telemetry stack

Runs the collector, Prometheus, Grafana and Jaeger on your machine so you can see your
own instrumentation before any AWS infrastructure exists. **DRI: Minage.**

## Run it

```bash
cd services/_shared/local
docker compose up -d

cd ..
export TILLFLOW_PII_HASH_SALT=local-dev-salt
../../.venv/bin/python -m uvicorn examples.demo_service:app --port 8099
```

Then, in another terminal:

```bash
curl -s -X POST localhost:8099/demo/stk \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: dukawala-42' \
  -H 'Idempotency-Key: key-abc' \
  -d '{"amount_minor":150000,"attendant_msisdn":"0712345678"}'
```

| What | Where | Expect |
|---|---|---|
| JSON logs | the uvicorn terminal | one line per event with `trace_id`, `span_id`, `tenant_id`; the MSISDN appears only as `msisdn:<hash>` |
| Traces | http://localhost:16686 | service `payments`, a server span with a `payments.stk_push` child |
| Metrics | http://localhost:9090 | `payments_requests_total`, `payments_request_duration_seconds_bucket`, `payments_stk_initiated_total` |
| Dashboards | http://localhost:3000 | Prometheus and Jaeger data sources already provisioned |

`docker compose down -v` to stop.

To run without Docker at all, set `TILLFLOW_TELEMETRY_EXPORT=none`. Spans are still
created, so log correlation still works; nothing is exported. This is what CI uses.

## Open items on this stack

- **Tail sampling is not configured here.** ADR-008 says a span carrying an error is
  always sampled, but a head-based sampler decides at span start, before the outcome is
  known. The error rule has to be a `tail_sampling` policy in the deployed sidecar
  config. Local is passthrough so a developer sees everything.
- **Money-path sampling ignores the parent decision.** ADR-008 gives `pos` 10% and
  `payments` 100%; had `payments` deferred to its caller, 90% of payments would have no
  trace. The consequence is that a money-path trace sometimes has no `pos` parent span.
- Both of the above need an ADR-008 amendment.
- The deployed ADOT sidecar config (AMP remote-write, X-Ray, tail sampling) is not
  written yet.
- Grafana here is anonymous-admin because it is bound to localhost. How operators
  reach the private deployed instance is a pre-G3 requirement from the Gate 0 feedback
  and is not answered by this file.
