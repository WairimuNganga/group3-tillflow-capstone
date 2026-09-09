# `_shared` — Step 4 shared foundations

Cross-service Python package (`tillflow-shared`). Split **by file** across three DRIs:

| Path | Owner | ADR |
|---|---|---|
| `tillflow_shared/mpesa/` | **Hunter** | [ADR-007](../../docs/adr/ADR-007-m-pesa-adapter.md) |
| `tillflow_shared/otel/` | **Minage** | [ADR-008](../../docs/adr/ADR-008-telemetry-conventions.md) |
| `tillflow_shared/health/` | **Wairimu** | Golden path `/health` + `/ready` |
| `Dockerfile.base` | **Wairimu** | Multi-stage service base (TODO) |

## Install (local dev)

```bash
cd services/_shared
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run tests

```bash
cd services/_shared
MPESA_ADAPTER=fake pytest -v
```

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

## OTel bootstrap (Minage — stub)

`init_telemetry(service_name, money_path=False)` is a placeholder until the OpenTelemetry SDK
and ADOT sidecar export are wired. `redact_msisdn()` is ready for log/span masking.

## Health routes (Wairimu)

```python
from fastapi import FastAPI
from tillflow_shared.health import create_health_router

app = FastAPI()
app.include_router(create_health_router(service_name="payments", git_sha="abc123"))
```
