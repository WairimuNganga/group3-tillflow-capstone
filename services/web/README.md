# web — TillFlow demo shell

**Owner:** Joyce (Product + POS)

Server-rendered Jinja UI + session cookie. Browser talks only to **web**;
web calls **POS** (`POS_BASE_URL`) over Service Connect. No Daraja.

## See the frontend

```bash
cd /Users/hunter/group3-tillflow-capstone
source .venv/bin/activate
cd services/_shared && pip install -e ".[dev]"
cd ../web && pip install -e ".[dev]"

# Fake POS (UI works without POS running):
TILLFLOW_TELEMETRY_EXPORT=none uvicorn web.main:app --reload --port 8080
```

Open **http://127.0.0.1:8080/** — home template, setup form, sale form.

With real POS + commission:

```bash
export POS_BASE_URL=http://127.0.0.1:8000
export COMMISSION_BASE_URL=http://127.0.0.1:8090
uvicorn web.main:app --reload --port 8070
```

## Routes

| Path | Purpose |
|------|---------|
| `GET /` | Home / open demo shop |
| `POST /setup` | Create tenant+till+attendant via POS |
| `GET/POST /sale` | Create sale + pay |
| `GET /sales` | Shop sales table (filters, pagination, commission estimate) |
| `GET /sales/{id}` | Sale status |
| `GET /payouts` | Commission B2C payout intents (filters by attendant / state) |
| `GET /commission` | Attendant day — volume, estimated + ledgered commission, payout |
| `POST /commission/close` | Trigger commission daily close |
| `POST /commission/payout` | Request attendant B2C via commission → payments |
| `GET /health`, `/ready` | Probes |
| `/static/app.css` | Styles |

## Security

CSP, `X-Frame-Options`, CSRF on POSTs, signed httponly session cookie (T1.5–T1.6).

## Tests

```bash
TILLFLOW_TELEMETRY_EXPORT=none pytest -v
```
