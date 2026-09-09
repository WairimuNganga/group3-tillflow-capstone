# `_shared` — Step 4 shared foundations

Cross-service Python package (`tillflow-shared`). One subpackage per DRI, so two owners
never edit the same file:

| Path | Owner | ADR | Status |
|---|---|---|---|
| `tillflow_shared/mpesa/` | **Hunter** | [ADR-007](../../docs/adr/ADR-007-m-pesa-adapter.md) | implemented |
| `tillflow_shared/otel/` | **Minage** | [ADR-008](../../docs/adr/ADR-008-telemetry-conventions.md) | implemented |
| `tillflow_shared/health/` | **Wairimu** | Golden path `/health` + `/ready` | implemented |
| `Dockerfile.base` | **Wairimu** | Multi-stage service base | TODO |

## Install (local dev)

```bash
cd services/_shared
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run tests

```bash
cd services/_shared
MPESA_ADAPTER=fake pytest -v
```

No collector, no Docker and no AWS required — the telemetry suite runs with export
switched off (see below).

## M-Pesa adapter (Hunter)

Factory selects the implementation from `MPESA_ADAPTER`:

| Value | Implementation | Used in |
|---|---|---|
| `fake` | `FakeMpesaAdapter` | CI, k6, unit tests, drills |
| `sandbox` | `DarajaSandboxAdapter` | Deployed dev environment |

```python
from tillflow_shared import MpesaSettings, create_mpesa_adapter
from tillflow_shared.mpesa.types import StkPushRequest

settings = MpesaSettings()  # reads MPESA_ADAPTER from env
adapter = create_mpesa_adapter(settings)

response = await adapter.initiate_stk_push(
    StkPushRequest(
        tenant_id="tenant-1",
        idempotency_key="sale-abc",
        phone_number="254712345678",
        amount_whole_kes=10,
        account_reference="sale-abc",
        fake_scenario=None,  # FakeMpesaAdapter only
    )
)
```

### Fake scenarios (`FakeScenario`)

| Scenario | Behaviour |
|---|---|
| `immediate_success` | STK accepted + one success callback |
| `immediate_failure` | STK accepted + failure callback |
| `delayed_timeout` | Raises `MpesaTimeoutError` (timeout ≠ decline) |
| `duplicate_callback` | Two identical callbacks queued |
| `out_of_order_callback` | Failure callback, then success callback |

Tests drain callbacks via `FakeMpesaAdapter.drain_callbacks(checkout_request_id)`.

### Sandbox env vars

Set via Secrets Manager in deployed environments — never commit values:

- `DARAJA_CONSUMER_KEY`, `DARAJA_CONSUMER_SECRET`, `DARAJA_PASSKEY`
- `DARAJA_SHORTCODE`, `DARAJA_INITIATOR`, `DARAJA_SECURITY_CREDENTIAL`
- `DARAJA_STK_CALLBACK_URL`, `DARAJA_B2C_RESULT_URL`
- `DARAJA_BASE_URL` (default: Safaricom sandbox)

## Telemetry (Minage)

### Frozen interface

These signatures will not change without a PR to this file.

```python
from tillflow_shared import setup_telemetry, get_logger

setup_telemetry("pos")        # once, at startup, before anything else
log = get_logger(__name__)

log.info("sale created", extra={"sale_id": sale_id, "amount_minor": 150_000})
```

HTTP services add the middleware:

```python
from fastapi import FastAPI
from tillflow_shared.health import create_health_router
from tillflow_shared.otel.middleware import instrument_fastapi

app = FastAPI()
app.include_router(create_health_router(service_name="pos", git_sha=GIT_SHA))
instrument_fastapi(app, service_name="pos")
```

Money-path operations open a named span:

```python
from tillflow_shared.otel.middleware import traced

with traced("payments.stk_push", amount_minor=amount):
    ...
```

Service-to-service calls go through the shared client, never a bare `httpx`:

```python
from tillflow_shared.otel.http_client import ServiceClient  # AsyncServiceClient too

with ServiceClient(service_name="commission", base_url=PAYMENTS_URL) as client:
    client.post("/b2c", json=payload)
```

It carries the trace, `X-Tenant-Id` and `Idempotency-Key` to the other service, so a
sale and the payment it triggers are one trace and the downstream logs are attributed
to the right tenant. An explicit header on the call always wins. Timeouts are bounded
by default (5s read, 2s connect).

### Everything else available

All importable from `tillflow_shared.otel`:

| Call | Returns |
|---|---|
| `get_tenant_id()` | the current request's tenant, or `None` |
| `get_idempotency_key()` | the current request's idempotency key, or `None` |
| `request_context(tenant_id=..., idempotency_key=...)` | context manager, for workers with no HTTP request |
| `business_counter(name, description)` | an OTel counter, e.g. `payments_stk_initiated_total` |
| `hash_msisdn(value)` / `redact_msisdn(value)` | a salted, stable, non-reversible phone-number reference |
| `redact(value)` | recursively strips PII and secrets from a dict/list/string |
| `shutdown_telemetry()` | flushes pending spans and metrics before exit |

### What you get for free

- Every log line is one JSON object with `ts, level, service, trace_id, span_id,
  tenant_id, msg`, plus anything passed via `extra=`.
- `X-Tenant-Id` and `Idempotency-Key` request headers are read into request context and
  attached to the span; outbound calls carry them onward.
- `<service>_requests_total{route,method,status}` and
  `<service>_request_duration_seconds{route,method}` per request, with `/health` and
  `/ready` excluded so probe traffic cannot inflate an SLI denominator.
- Phone numbers never reach stdout or a span in the clear, even if a call site passes
  one in raw.

### Environment

| Variable | Set by | Purpose |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | shared Dockerfile | collector address; defaults to `http://localhost:4317` |
| `OTEL_RESOURCE_ATTRIBUTES` | shared Dockerfile | environment-level resource attributes, merged in |
| `GIT_COMMIT_SHA` | CI/CD | becomes `service.version` on every span and metric |
| `TILLFLOW_PII_HASH_SALT` | Secrets Manager | MSISDN hash salt; **without it phone numbers are dropped, not hashed** |
| `TILLFLOW_ENVIRONMENT` | task definition | `deployment.environment.name` |
| `TILLFLOW_TELEMETRY_EXPORT` | CI | `none` disables export; traces are still created |
| `TILLFLOW_TRACE_SAMPLE_RATIO` | optional | overrides the ADR-008 per-service ratio |
| `TILLFLOW_METRIC_EXPORT_INTERVAL_MS` | optional | defaults to 15000 |
| `LOG_LEVEL` | optional | defaults to `INFO` |

### Seeing it work

[`local/README.md`](local/README.md) runs a collector, Prometheus, Grafana and Jaeger
in Docker, and `examples/demo_service.py` exercises the library against them. Full
walkthrough and the two open ADR-008 findings:
[`evidence/reliability/telemetry-walkthrough.md`](../../evidence/reliability/telemetry-walkthrough.md).

## Health routes (Wairimu)

```python
from fastapi import FastAPI
from tillflow_shared.health import create_health_router

app = FastAPI()
app.include_router(create_health_router(service_name="payments", git_sha="abc123"))
```
