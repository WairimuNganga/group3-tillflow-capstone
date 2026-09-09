# _shared

Cross-service libraries. Split by file, not by folder — each file has one DRI.

| Area | DRI | Status |
|---|---|---|
| Telemetry — `tillflow_shared/` ([ADR-008](../../docs/adr/ADR-008-telemetry-conventions.md)) | Minage | implemented |
| M-Pesa adapter interface + fake ([ADR-007](../../docs/adr/ADR-007-m-pesa-adapter.md)) | Hunter | not started |
| Docker base + golden path | Wairimu | not started |
| Idempotency helpers ([ADR-004](../../docs/adr/ADR-004-idempotency-and-money-integrity.md)) | Hunter | not started |

## Frozen telemetry interface

These signatures will not change without a PR to this file. Build against them.

```python
from tillflow_shared import setup_telemetry, get_logger

setup_telemetry("pos")        # once, at startup, before anything else
log = get_logger(__name__)

log.info("sale created", extra={"sale_id": sale_id, "amount_minor": 150_000})
```

HTTP services add the middleware:

```python
from fastapi import FastAPI
from tillflow_shared.middleware import instrument_fastapi

app = FastAPI()
instrument_fastapi(app, service_name="pos")
```

Money-path operations open a named span:

```python
from tillflow_shared.middleware import traced

with traced("payments.stk_push", amount_minor=amount):
    ...
```

Service-to-service calls go through the shared client, never a bare `httpx`:

```python
from tillflow_shared.http_client import ServiceClient  # AsyncServiceClient for async

with ServiceClient(service_name="commission", base_url=PAYMENTS_URL) as client:
    client.post("/b2c", json=payload)
```

It carries the trace, `X-Tenant-Id` and `Idempotency-Key` to the other service, so the
sale and the payment it triggers are one trace and the downstream logs are attributed
to the right tenant. An explicit header on the call always wins. Timeouts are bounded
by default (5s read, 2s connect).

Everything else available:

| Call | Returns |
|---|---|
| `get_tenant_id()` | the current request's tenant, or `None` |
| `get_idempotency_key()` | the current request's idempotency key, or `None` |
| `request_context(tenant_id=..., idempotency_key=...)` | context manager, for workers with no HTTP request |
| `business_counter(name, description)` | an OTel counter, e.g. `payments_stk_initiated_total` |
| `hash_msisdn(value)` | a salted, stable, non-reversible phone-number reference |
| `redact(value)` | recursively strips PII and secrets from a dict/list/string |
| `shutdown_telemetry()` | flushes pending spans and metrics before exit |

## What you get for free

- Every log line is one JSON object with `ts, level, service, trace_id, span_id,
  tenant_id, msg` (ADR-008), plus anything passed via `extra=`.
- `X-Tenant-Id` and `Idempotency-Key` request headers are read into request context and
  attached to the span.
- `<service>_requests_total{route,method,status}` and
  `<service>_request_duration_seconds{route,method}` are recorded per request, with
  `/health` and `/ready` excluded.
- Phone numbers never reach stdout or a span in the clear, even if a call site passes
  one in raw.

## Required environment

| Variable | Set by | Purpose |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | shared Dockerfile | collector address; defaults to `http://localhost:4317` |
| `OTEL_RESOURCE_ATTRIBUTES` | shared Dockerfile | environment-level resource attributes, merged in |
| `GIT_COMMIT_SHA` | CI/CD | becomes `service.version` on every span and metric |
| `TILLFLOW_PII_HASH_SALT` | Secrets Manager | salt for MSISDN hashing; **without it phone numbers are dropped entirely rather than hashed** |
| `TILLFLOW_ENVIRONMENT` | task definition | `deployment.environment.name` |
| `TILLFLOW_TELEMETRY_EXPORT` | CI | `none` disables export; spans are still created |
| `TILLFLOW_TRACE_SAMPLE_RATIO` | optional | overrides the ADR-008 per-service ratio |
| `LOG_LEVEL` | optional | defaults to `INFO` |

## Develop and test

```bash
python3 -m venv .venv
.venv/bin/pip install -e "services/_shared[dev]"

cd services/_shared
../../.venv/bin/python -m pytest -q
```

The suite needs no collector and no Docker. To watch real telemetry flow, see
[`local/README.md`](local/README.md).
