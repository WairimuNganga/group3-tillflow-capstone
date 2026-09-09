# Shared telemetry library — walkthrough

**Area:** Reliability + operations · **DRI:** Minage · **ADR:** [ADR-008](../../docs/adr/ADR-008-telemetry-conventions.md)
**Covers:** the OTel/instrumentation slice of `services/_shared/` (§4 of the implementation plan)

---

## 1. What this is, in one paragraph

Five services need to report on themselves in the same way, or the dashboards, the
SLOs and the error budgets can't be built once and reused. This library is that shared
reporting code. A service author calls two functions at startup and then writes normal
log lines; everything else — the JSON format, the trace IDs, the tenant ID, the request
counters, the phone-number redaction — happens automatically.

It is not the dashboards and not the load tests. It is the equipment those things later
measure with, which is why the plan puts it on days 1–3 and everything else after.

## 2. Why it had to come first

Every service switches this on at startup, so it is a hard dependency for POS,
Payments, Commission and Web. If it arrived after those services were written, each
author would have invented their own logging, none of it would carry a trace ID, and
following one sale from the till through to M-Pesa would be impossible without asking
three people to rewrite finished code.

## 3. The mental model

```
your Python code
    │  log.info(...) / traced(...)
    ▼
tillflow_shared            ← this library
    │  OTLP over gRPC to localhost:4317
    ▼
ADOT collector (sidecar in the same ECS task)
    │
    ├──► Amazon Managed Prometheus  ──► Grafana (self-hosted on ECS)
    └──► AWS X-Ray
```

The application never talks to Prometheus or X-Ray directly (ADR-008). It only ever
talks to the collector next to it. That is why the default endpoint is `localhost` —
in ECS the collector is a second container in the same task, and locally it is a
container from `services/_shared/local/docker-compose.yml`. Nothing in the application
changes between those two cases; only the collector's config does.

## 4. Vocabulary

| Term | Meaning |
|---|---|
| **OpenTelemetry (OTel)** | An open standard plus libraries for producing telemetry. Vendor-neutral, so swapping the backend doesn't change service code. |
| **Trace** | The full record of one request as it moves through the system. |
| **Span** | One step inside a trace. A trace is a tree of spans. |
| **trace_id / span_id** | The IDs that tie a log line to the exact request that produced it. |
| **OTLP** | The protocol OTel uses to ship data. Our services speak it to `localhost:4317`. |
| **Collector / sidecar** | The process that receives OTLP and forwards it on. Runs beside the app. |
| **ADOT** | AWS's build of the OTel collector. |
| **AMP** | Amazon Managed Prometheus, where metrics are stored. |
| **Sampling** | Recording only a fraction of traces, to control cost. |
| **RED metrics** | Rate, Errors, Duration — the three numbers every SLI is built from. |
| **MSISDN** | A phone number in international format. The PII in this system. |

---

## 5. File by file, function by function

`services/_shared` is one Python package with one subpackage per DRI, so two owners
never edit the same file:

```
tillflow_shared/
  mpesa/     Hunter    — adapter interface, Daraja sandbox, deterministic fake
  otel/      Minage    — everything below
  health/    Wairimu   — /health and /ready for the golden path
```

Only `tillflow_shared/__init__.py`, `tests/conftest.py`, `pyproject.toml` and
`README.md` are shared, and they are all small and rarely change.

### `tillflow_shared/otel/context.py` — who this request belongs to

A server handles many requests at once, so "the current tenant" can't live in an
ordinary variable — one request would overwrite another's. This uses Python
*context variables*, which keep a separate value per request automatically.

| Function | What it does |
|---|---|
| `get_tenant_id()` | Which shop this request is for, or `None` outside a request. |
| `get_idempotency_key()` | The key that stops a payment being processed twice. |
| `request_context(tenant_id=..., idempotency_key=...)` | A `with` block that sets both values, and always clears them on exit — including after a crash, so one tenant's ID can never leak into the next piece of work. |

This is the shared-context agreement with Joyce: her database layer reads
`get_tenant_id()` to set `app.current_tenant_id` for row-level security
([ADR-005](../../docs/adr/ADR-005-multi-tenancy-isolation.md)), and the logger reads the
same value. One source of truth, not two mechanisms that can drift.

### `tillflow_shared/otel/pii.py` — phone numbers never get written down

| Function | What it does |
|---|---|
| `hash_msisdn(value)` | Turns `0712345678` into `msisdn:bed450aab7d6`. One-way, but stable — the same number always gives the same code, so an operator can still follow one subscriber through an incident. |
| `_normalise_msisdn(raw)` | Converts `0712345678` and `+254712345678` to the same canonical form first, so one person doesn't end up with two different codes. |
| `redact_text(value)` | Finds and replaces phone numbers inside any sentence. |
| `redact(value)` | Walks a whole nested dict/list doing the same, and additionally drops anything whose *name* is dangerous (`password`, `consumer_secret`, `authorization`) regardless of its contents. |

If `TILLFLOW_PII_HASH_SALT` isn't set, `hash_msisdn` returns `[redacted]` instead of a
hash. An unsalted hash of a 12-digit number can be brute-forced in seconds by trying
every Kenyan number, so an unset salt has to fail closed rather than emit something
that only looks safe.

### `tillflow_shared/otel/logging.py` — one log call becomes a full record

`JsonFormatter.format()` is the core. Every `log.info(...)` anywhere in any service
runs through it and produces a single line of JSON containing the time, level, service,
`trace_id`, `span_id`, `tenant_id`, message, logger name, and anything passed via
`extra=`. Exceptions become a structured `error` object with type, message and stack.

The final step is passing the whole payload through `redact()`. That ordering is the
reason ADR-008's promise holds: a developer can pass a raw phone number into a log call
and it still cannot reach stdout in the clear.

| Function | What it does |
|---|---|
| `_timestamp(created)` | RFC 3339 in UTC with milliseconds. |
| `JsonFormatter` | Renders one record as one line of JSON. |
| `configure_logging(service, level)` | Attaches the formatter to the root logger. Deliberately *removes* existing handlers first, because uvicorn installs its own on import and you would otherwise get every line twice. Also routes uvicorn's own logs through the same formatter. |
| `get_logger(name)` | Returns a plain Python logger. |

### `tillflow_shared/otel/sampling.py` — which traces get kept

`ratio_for_service()` returns 100% for `payments` and `commission`, 10% for `pos` and
`web`, per ADR-008. `TILLFLOW_TRACE_SAMPLE_RATIO` overrides it (clamped to 0–1) so a k6
run or an incident investigation can raise the rate without a code change.
`sampler_for_service()` turns that number into the sampler object.

**Two problems in ADR-008 were found while writing this file.**

The first is fixed in code. The normal setting makes a service obey whatever its caller
decided about sampling. A sale starts in `pos` at 10% and then calls `payments` — so
90% of payments would have had no trace at all, directly contradicting the 100%
commitment and removing the evidence ADR-004 requires. `payments` and `commission` now
decide for themselves. The cost is that a money-path trace sometimes has no `pos`
parent span, which is the right trade: the money spans are the evidence.

The second cannot be fixed in code. ADR-008 says a span carrying an error is always
sampled. A head-based sampler decides when a request *starts*, before the outcome is
known. That rule has to be a `tail_sampling` policy in the collector instead.

**Both need an ADR-008 amendment.**

### `tillflow_shared/otel/metrics.py` — the numbers

| Function | What it does |
|---|---|
| `build_red_metrics(service, meter)` | Creates `<service>_requests_total` (a counter) and `<service>_request_duration_seconds` (a histogram). |
| `business_counter(name, description)` | Creates a domain counter like `payments_stk_initiated_total`, without the caller touching the meter provider. |

The names come straight from ADR-008 and must be identical across services, or a single
Grafana query and a single burn-rate alert can't be written once and reused.

### `tillflow_shared/otel/bootstrap.py` — the one function everyone calls

`setup_telemetry("pos")` does five things: builds the service's identity, pins the
propagation format, installs tracing with this service's sampling policy, installs
metrics, and switches on JSON logging. Calling it twice is a no-op rather than a
duplicate set of exporters, which matters because auto-reloaders import modules more
than once.

| Function | What it does |
|---|---|
| `_resource(service, extra)` | Builds the identity: service name, `service.version` from `GIT_COMMIT_SHA`, and the environment. Also merges `OTEL_RESOURCE_ATTRIBUTES` from the environment — the handover point with Wairimu's Dockerfile. |
| `_install_tracing(...)` | Creates the tracer provider and the OTLP span exporter. |
| `_install_metrics(...)` | Creates the meter provider and the periodic OTLP metric exporter. |
| `setup_telemetry(...)` | The public entry point. |
| `shutdown_telemetry()` | Flushes queued spans and metrics. Without it, a short-lived task — the commission worker's daily run especially — can lose the telemetry describing its final moments. |
| `get_tracer()` / `get_meter()` | Small accessors so nothing else reaches into the globals. |

Setting `TILLFLOW_TELEMETRY_EXPORT=none` still creates real, recording traces but
exports nothing. That is how the test suite and CI run without Docker.

The propagation format is pinned explicitly rather than left to `OTEL_PROPAGATORS`. If
two services disagreed on the wire format, cross-service traces would break silently,
with no error appearing anywhere.

### `tillflow_shared/otel/middleware.py` — runs on every HTTP request

`TelemetryMiddleware.__call__()` reads the `X-Tenant-Id` and `Idempotency-Key` headers
into request context, attaches them to the span, runs the request, then records how
long it took and whether it succeeded. If the request raises an unhandled exception it
still records a 500 before re-raising — an uncounted failure would be invisible to the
error budget, which is worse than one that shows up on a dashboard.

It is written as raw ASGI rather than Starlette's `BaseHTTPMiddleware`, which runs the
handler in a separate task and makes context-variable propagation unreliable. The
tenant ID is the one value that must never silently go missing.

| Function | What it does |
|---|---|
| `_header(scope, name)` | Pulls one header out of the raw request. |
| `_route_template(scope)` | Returns `/sales/{sale_id}`, never `/sales/S-1007`. The real path would create one Prometheus series per sale and eventually exhaust the metrics store. |
| `_status_class(code)` | Reduces status codes to `2xx`/`4xx`/`5xx`, for the same cardinality reason. |
| `TelemetryMiddleware` | The per-request work described above. |
| `instrument_fastapi(app, service_name=...)` | One-line setup for a service. Order matters inside: the OTel server span must be installed *outside* this middleware so the middleware can annotate it with the tenant. |
| `traced(name, **attrs)` | Opens a named business span, e.g. `traced("payments.stk_push")`, automatically tagged with tenant and idempotency key. |

`/health` and `/ready` are excluded from both metrics and tracing. Probes run every few
seconds against every task; counting them would swamp real traffic in every panel and
inflate the denominator of every SLI, making the error budget look healthier than it is.

`traced` marks a failed span as errored but deliberately does **not** copy the stack
trace onto the span. Exception messages routinely contain the value that caused them,
and on this code path that value can be a phone number. The full stack still reaches
the log, which is redacted.

### `tillflow_shared/otel/http_client.py` — calling another service

| Class | What it does |
|---|---|
| `ServiceClient` | A synchronous `httpx.Client` that carries context to another service. |
| `AsyncServiceClient` | The same, for async handlers. |
| `_propagate(headers)` | Injects `traceparent`, plus `X-Tenant-Id` and `Idempotency-Key` from request context. An explicit header on the call always wins. |
| `_client_span(...)` | Opens a `<service>.http_request` span around the call. |

Without this, a sale created in `pos` and the payment it triggers in `payments` are two
unrelated traces, and the downstream service logs `tenant_id: null` on every line —
which breaks the attribution control in threat model T3.3.

Forwarding the idempotency key is deliberate. The plan requires Commission to call the
Payments B2C endpoint with the *same* key it used for its own ledger line, so both
dedupe layers agree on what "the same payout" means.

Timeouts are bounded by default (5s read, 2s connect). An unbounded call turns another
service's slowdown into this service's outage.

### Development-only files

`examples/demo_service.py` is a fake service with `/demo/stk` and `/demo/boom`. It
passes a raw phone number into a log call on purpose, to show that redaction is
central. Delete it once POS and Payments are real.

`local/` holds the Docker Compose stack — collector, Prometheus, Grafana, Jaeger —
plus their configs and a README. Jaeger stands in for X-Ray and a scrape endpoint
stands in for AMP remote-write.

---

## 6. What the tests prove

53 tests across all three `_shared` areas. No Docker, no collector, no AWS.

```bash
cd services/_shared
../../.venv/bin/python -m pytest -q
```

| File | Proves |
|---|---|
| `tests/otel/test_pii.py` | All five phone formats are stripped; one person hashes the same across formats; a missing salt drops the value; dangerous field names are dropped; **trace IDs and money amounts are not mangled** (over-redaction is its own bug). |
| `tests/otel/test_logging.py` | Required fields present; timestamp format; trace and span IDs match the live span; tenant comes from context; extras merged; redaction covers both message and extras; exceptions structured; one record is exactly one line. |
| `tests/otel/test_sampling.py` | The 100%/10% split; the env override and its clamping; money-path services ignore their caller's decision. |
| `tests/otel/test_middleware.py` | Headers reach the handler; context doesn't leak between requests; the metric label is the parameterised route; `/health` is not counted at all; a crash still counts as a 5xx. |
| `tests/otel/test_http_client.py` | `traceparent` is injected; **the downstream service joins the same trace**; tenant and idempotency key are forwarded; explicit headers win; no tenant header outside a request; timeouts are bounded; the async client behaves identically. |

## 7. Reproducing the runtime proof

Start the stack and the demo service:

```bash
cd services/_shared/local && docker compose up -d
cd .. && export TILLFLOW_PII_HASH_SALT=local-dev-salt
../../.venv/bin/python -m uvicorn examples.demo_service:app --port 8099
```

Send a request:

```bash
curl -s -X POST localhost:8099/demo/stk \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: dukawala-42' \
  -H 'Idempotency-Key: key-abc' \
  -d '{"amount_minor":150000,"attendant_msisdn":"0712345678"}'
```

Observed log line:

```json
{"ts":"2026-09-09T18:49:03.726Z","level":"info","service":"payments","trace_id":"492f92506fc703756a2393098c29701c","span_id":"94281ed9d041dd75","tenant_id":"dukawala-42","msg":"stk push requested for msisdn:bed450aab7d6","logger":"examples.demo_service","amount_minor":150000}
```

Note that `0712345678` was passed straight into the log call and appears only as
`msisdn:bed450aab7d6`.

To prove inbound propagation, supply a trace context and confirm the service joins it
instead of starting a new trace:

```bash
curl -s -X POST localhost:8099/demo/stk \
  -H 'Content-Type: application/json' \
  -H 'traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01' \
  -H 'X-Tenant-Id: dukawala-42' \
  -d '{"amount_minor":150000,"attendant_msisdn":"0712345678"}'
```

Observed: `"trace_id":"4bf92f3577b34da6a3ce929d0e0e4736"` — the supplied ID, adopted.

| Where to look | Expect |
|---|---|
| http://localhost:16686 | service `payments`, a server span with a `payments.stk_push` child |
| http://localhost:9090 | `payments_requests_total`, `payments_request_duration_seconds_bucket`, `payments_stk_initiated_total` |
| http://localhost:3000 | Prometheus and Jaeger data sources already provisioned |

---

## 8. The contract for the rest of the team

Frozen signatures — these will not change without a PR to
[`services/_shared/README.md`](../../services/_shared/README.md).

```python
from tillflow_shared import setup_telemetry, get_logger
from tillflow_shared.otel.middleware import instrument_fastapi, traced
from tillflow_shared.otel.http_client import ServiceClient

setup_telemetry("pos")                          # once, at startup
log = get_logger(__name__)
instrument_fastapi(app, service_name="pos")     # HTTP services only

log.info("sale created", extra={"sale_id": sale_id})

with traced("payments.stk_push", amount_minor=amount):
    ...

with ServiceClient(service_name="commission", base_url=PAYMENTS_URL) as client:
    client.post("/b2c", json=payload)
```

**Wairimu** — the image must set `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`
and `OTEL_RESOURCE_ATTRIBUTES`; CI must set `GIT_COMMIT_SHA` so `service.version` is
populated. Install the `http` extra for web services and the plain package for the
commission worker. `ruff` config is already in `pyproject.toml`. The real `/health` and
`/ready` handlers are his and must expose the commit SHA and image digest (T7.3) — the
ones in `examples/` are placeholders.

**Hunter** — wrap Daraja calls in `traced("payments.stk_push")` and similar; use
`business_counter` for `payments_stk_initiated_total` and
`payments_callback_processed_total`; read `get_idempotency_key()` rather than threading
it through arguments.

**Joyce** — `setup_telemetry("pos")` plus `instrument_fastapi(...)`; the database layer
reads `get_tenant_id()` for row-level security. Do not build a second tenant mechanism.

**Lwam** — the app-side contract is fixed: OTLP gRPC on `localhost:4317`. The demo
service is close to the golden-path app he needs for the first ECS deploy.

## 9. Environment variables

| Variable | Set by | Purpose |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | shared Dockerfile | collector address; defaults to `http://localhost:4317` |
| `OTEL_RESOURCE_ATTRIBUTES` | shared Dockerfile | environment-level resource attributes, merged in |
| `GIT_COMMIT_SHA` | CI/CD | becomes `service.version` on every span and metric |
| `TILLFLOW_PII_HASH_SALT` | Secrets Manager | MSISDN hash salt; **without it phone numbers are dropped, not hashed** |
| `TILLFLOW_ENVIRONMENT` | task definition | `deployment.environment.name` |
| `TILLFLOW_TELEMETRY_EXPORT` | CI | `none` disables export; traces are still created |
| `TILLFLOW_TRACE_SAMPLE_RATIO` | optional | overrides the per-service ratio |
| `TILLFLOW_METRIC_EXPORT_INTERVAL_MS` | optional | defaults to 15000 |
| `LOG_LEVEL` | optional | defaults to `INFO` |

## 10. Still open in this area

- **ADR-008 amendment** for the two sampling findings in §5 and for the
  `/health`/`/ready` exclusion from the SLI denominators.
- **Deployed ADOT sidecar config** — AMP remote-write, X-Ray, and the `tail_sampling`
  policy that implements the always-sample-errors rule.
- **Database spans.** ADR-008 promises a child span per outbound call including DB
  queries. The Daraja and inter-service halves are covered; the Postgres driver can't
  be instrumented until a driver is chosen.
- **Secure operator access to private Grafana** — a pre-G3 requirement from the Gate 0
  feedback, still unanswered.
- **Grafana dashboards as code**, k6 suite, Slack alert contract, runbook — all G3/G4.
