# M-Pesa integration — manual test evidence

**Branch:** `feature/mpesa-integration` (commit `c48c2fc` — *feat: implement payments service*)  
**Tester:** Minage (Reliability + operations)  
**Date:** 2026-09-15 / 2026-09-16  
**DRI review:** Hunter (Payments + integrity)  
**Scope:** Fake-adapter manual curls + Daraja sandbox STK end-to-end via ngrok

---

## Reproduction setup

```bash
git checkout feature/mpesa-integration
cd /path/to/group3-tillflow-capstone
source .venv/bin/activate

# Shared + payments packages
cd services/_shared && pip install -e ".[dev]"
cd ../payments && pip install -e ".[dev]"
```

| Mode | Required env |
|------|----------------|
| Fake | `TILLFLOW_TELEMETRY_EXPORT=none` `MPESA_ADAPTER=fake` |
| Sandbox | `services/payments/.env` (see `.env.example`), ngrok on `:8080` |

Start API:

```bash
cd services/payments
unset MPESA_ADAPTER          # let .env drive adapter selection
uvicorn payments.main:app --reload --port 8080
```

Sandbox additionally requires:

```bash
ngrok http 8080
# DARAJA_STK_CALLBACK_URL=https://<ngrok-host>/callbacks/mpesa/<MPESA_CALLBACK_SECRET>
```

---

## 1. Automated test suite (baseline)

**Command:**

```bash
cd services/payments
TILLFLOW_TELEMETRY_EXPORT=none MPESA_ADAPTER=fake pytest -v
```

**Result:** `43 passed` (includes API, domain state, and money invariant tests).

**Verdict:** PASS

---

## 2. Fake adapter — manual HTTP tests

**Environment:** `MPESA_ADAPTER=fake`, in-memory stores (no `DATABASE_URL`), API on `http://127.0.0.1:8080`.

### 2.1 Health probes

**Commands:**

```bash
curl -s http://127.0.0.1:8080/health | jq
curl -s http://127.0.0.1:8080/ready | jq
```

**Observed (tester terminal):**

```json
{
  "status": "ok",
  "service": "payments",
  "git_sha": "unknown"
}
```

```json
{
  "status": "not_ready",
  "service": "payments"
}
```

`/ready` → HTTP 503 without Postgres is **expected** for in-memory mode.

**Verdict:** PASS (health OK; readiness correctly reports no DB)

---

### 2.2 STK push — immediate success

**Command:**

```bash
curl -s -X POST http://127.0.0.1:8080/payments/stk \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: tenant-a' \
  -H 'Idempotency-Key: manual-fake-1' \
  -d '{
    "sale_id": "11111111-1111-1111-1111-111111111111",
    "phone_number": "254712345678",
    "amount_minor_units": 1500,
    "fake_scenario": "immediate_success"
  }' | jq
```

**Observed:**

```json
{
  "payment_id": "bf7f8b71-8bc9-4007-9d31-4bb6648b467d",
  "sale_id": "11111111-1111-1111-1111-111111111111",
  "tenant_id": "tenant-a",
  "state": "stk_sent",
  "amount_minor_units": 1500,
  "amount_whole_kes": 15,
  "merchant_request_id": "fake-merchant-b0bd9cf41a71",
  "checkout_request_id": "fake-checkout-5bcb55747249"
}
```

**Verdict:** PASS — HTTP 202, state `stk_sent`, minor units → whole KES conversion correct.

---

### 2.3 Idempotency replay

**Command:** Repeat §2.2 curl with identical headers/body.

**Observed:** Same `payment_id`, `merchant_request_id`, and `checkout_request_id` returned.

**Verdict:** PASS — no duplicate payment created.

---

### 2.4 Callback settlement (simulate Daraja POST)

**Command:**

```bash
curl -s -X POST http://127.0.0.1:8080/callbacks/mpesa/local-dev-callback-secret \
  -H 'Content-Type: application/json' \
  -d '{
    "Body": {
      "stkCallback": {
        "MerchantRequestID": "fake-merchant-b0bd9cf41a71",
        "CheckoutRequestID": "fake-checkout-5bcb55747249",
        "ResultCode": 0,
        "ResultDesc": "The service request is processed successfully.",
        "CallbackMetadata": {
          "Item": [
            {"Name": "Amount", "Value": 15},
            {"Name": "MpesaReceiptNumber", "Value": "FAKEMANUAL001"}
          ]
        }
      }
    }
  }' | jq
```

**Observed:**

```json
{
  "accepted": true,
  "reason": "settled_paid",
  "payment_id": "bf7f8b71-8bc9-4007-9d31-4bb6648b467d",
  "state": "paid",
  "ledger_written": true
}
```

**Verdict:** PASS — payment settled, ledger entry written.

---

### 2.5 Timeout → reconciliation

**STK command** (`fake_scenario: delayed_timeout`, `Idempotency-Key: manual-fake-timeout`):

**Observed STK response:**

```json
{
  "payment_id": "00fe7deb-8875-496f-a0c1-bfd3637b82c0",
  "state": "pending_reconciliation",
  "amount_minor_units": 2000,
  "amount_whole_kes": 20,
  "merchant_request_id": "fake-merchant-5d98b3a4ec4c",
  "checkout_request_id": "fake-checkout-e9478deb94c8"
}
```

**Reconcile command:**

```bash
curl -s -X POST http://127.0.0.1:8080/payments/reconcile/00fe7deb-8875-496f-a0c1-bfd3637b82c0 | jq
```

**Observed:**

```json
{
  "payment_id": "00fe7deb-8875-496f-a0c1-bfd3637b82c0",
  "state": "paid",
  "reason": "settled_paid",
  "ledger_written": true
}
```

**Verdict:** PASS — timeout path stays `pending_reconciliation` (not `failed`); reconcile settles once.

---

### 2.6 B2C payout flow

**Submit:**

```bash
curl -s -X POST http://127.0.0.1:8080/payments/b2c \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: tenant-a' \
  -H 'Idempotency-Key: tenant-a:2026-09-15:attendant-7' \
  -d '{
    "attendant_id": "attendant-7",
    "phone_number": "254712345678",
    "amount_minor_units": 50000,
    "originator_conversation_id": "tenant-a:2026-09-15:attendant-7"
  }' | jq
```

**Observed submit:**

```json
{
  "payout_id": "2891d26d-d816-4d0e-bad0-19dd4eaca7fb",
  "state": "submitted",
  "amount_whole_kes": 500,
  "conversation_id": "fake-b2c-f791722eaf5f"
}
```

**Result callback:**

```bash
curl -s -X POST http://127.0.0.1:8080/payments/b2c/result \
  -H 'Content-Type: application/json' \
  -d '{"conversation_id": "fake-b2c-f791722eaf5f", "success": true}' | jq
```

**Observed result:**

```json
{
  "payout_id": "2891d26d-d816-4d0e-bad0-19dd4eaca7fb",
  "state": "completed",
  "amount_whole_kes": 500,
  "conversation_id": "fake-b2c-f791722eaf5f"
}
```

**Verdict:** PASS — B2C submit → result completes payout.

---

### 2.7 Automated fake run (agent session)

An automated curl script in the same session additionally verified:

| Scenario | Key outcome |
|----------|-------------|
| Callback duplicate replay | `reason: duplicate_callback`, `ledger_written: false` |
| STK immediate failure + callback | `state: failed`, no ledger |
| B2C idempotency replay | Same payout returned |
| Wrong callback secret | HTTP 403, `callback secret segment mismatch` |

**Verdict:** PASS

---

## 3. Daraja sandbox — manual HTTP tests

**Environment:** `MPESA_ADAPTER=sandbox`, `services/payments/.env`, ngrok forwarding `https://rendering-exploring-custody.ngrok-free.dev → localhost:8080`.

### 3.1 Portal prerequisites (documented blockers resolved)

| Issue | Symptom | Resolution |
|-------|---------|------------|
| App missing STK product | Daraja `404.001.03 Invalid Access Token` on STK | Added **M-Pesa Express Simulate** to `tillflow` app via Daraja portal |
| Truncated passkey in `.env` | Daraja `500.001.1001 Wrong credentials` | Used **64-char passkey** from Daraja simulator test data (not the short 32-char doc default) |

Daraja portal simulator success (reference):

```json
{
  "MerchantRequestID": "0ca7-4cc6-9fb0-41ec21a66514187336",
  "CheckoutRequestID": "ws_CO_150920262356094708374149",
  "ResponseCode": "0",
  "ResponseDescription": "Success. Request accepted for processing",
  "CustomerMessage": "Success. Request accepted for processing"
}
```

---

### 3.2 Failed attempt — before product + passkey fix

**Command:** `Idempotency-Key: sandbox-sale-1` (no `fake_scenario`).

**Observed:**

```json
{
  "state": "stk_sent",
  "merchant_request_id": "",
  "checkout_request_id": ""
}
```

**Uvicorn / httpx log:**

```
HTTP Request: POST https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest "HTTP/1.1 404 Not Found"
```

Daraja body (probed separately): `errorCode: 404.001.03`, `errorMessage: Invalid Access Token`.

**Verdict:** FAIL (documented) — empty provider IDs returned despite HTTP 202 from payments API.

---

### 3.3 Failed attempt — wrong passkey

**Command:** `Idempotency-Key: sandbox-sale-3`.

**Uvicorn log:**

```
HTTP Request: POST https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest "HTTP/1.1 500 Internal Server Error"
MpesaProviderError: Daraja STK push failed with status 500
```

Daraja body: `errorCode: 500.001.1001`, `errorMessage: Wrong credentials`.

**Verdict:** FAIL (documented) — idempotency key left `in progress` on first 500.

---

### 3.4 Successful sandbox STK via payments API

**Command:**

```bash
curl -s -X POST http://127.0.0.1:8080/payments/stk \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: tenant-a' \
  -H 'Idempotency-Key: sandbox-sale-4' \
  -d '{
    "sale_id": "77777777-7777-7777-7777-777777777777",
    "phone_number": "254708374149",
    "amount_minor_units": 100
  }' | jq
```

**Observed:**

```json
{
  "payment_id": "a79b62c9-71e6-452f-8c85-00b67a576e7e",
  "sale_id": "77777777-7777-7777-7777-777777777777",
  "tenant_id": "tenant-a",
  "state": "stk_sent",
  "amount_minor_units": 100,
  "amount_whole_kes": 1,
  "merchant_request_id": "0ca7-4cc6-9fb0-41ec21a66514187489",
  "checkout_request_id": "ws_CO_150920262358351708374149"
}
```

**Verdict:** PASS — real Daraja IDs returned.

---

### 3.5 Daraja callback via ngrok (end-to-end)

**Uvicorn access log** (same session, after §3.4):

```
20:58:33  HTTP Request: GET  .../oauth/v1/generate?grant_type=client_credentials "HTTP/1.1 200 OK"
20:58:35  HTTP Request: POST .../mpesa/stkpush/v1/processrequest            "HTTP/1.1 200 OK"
20:58:35  127.0.0.1 - "POST /payments/stk HTTP/1.1" 202
20:58:45  196.201.212.69:0 - "POST /callbacks/mpesa/tillflow-sandbox-test-2026 HTTP/1.1" 200
```

**Observations:**

- OAuth token acquisition: **200 OK**
- Daraja STK push: **200 OK**
- Callback received from Safaricom IP `196.201.212.69` ~10s after STK
- Callback handler returned **HTTP 200**

**ngrok session:**

```
Forwarding  https://rendering-exploring-custody.ngrok-free.dev -> http://localhost:8080
Web Interface  http://127.0.0.1:4040
```

(Request detail visible in ngrok web UI at `:4040`; compact ngrok TUI did not list individual requests.)

**Verdict:** PASS — sandbox STK + asynchronous Daraja callback delivered through ngrok tunnel.

---

## 4. Summary matrix

| # | Flow | Adapter | Result |
|---|------|---------|--------|
| 1 | Automated pytest | fake | 43/43 PASS |
| 2 | Health / ready | fake | PASS |
| 3 | STK immediate success | fake | PASS |
| 4 | Idempotency replay | fake | PASS |
| 5 | Callback → paid | fake | PASS |
| 6 | Timeout → reconcile → paid | fake | PASS |
| 7 | B2C submit → result | fake | PASS |
| 8 | Callback secret rejection | fake | PASS (403) |
| 9 | Daraja STK (pre-fix) | sandbox | FAIL — documented |
| 10 | Daraja STK (passkey fix) | sandbox | PASS |
| 11 | Daraja callback via ngrok | sandbox | PASS |

---

## 5. Findings for DRI (non-blocking)

1. **Daraja errors not surfaced on STK response** — when Daraja returns 404/500, API may still respond `202`/`stk_sent` with empty `merchant_request_id` / `checkout_request_id` (§3.2). Consider propagating `ResponseCode` / provider errors to the client.
2. **Fake callbacks are not auto-delivered** — manual POST to `/callbacks/mpesa/{secret}` required in fake mode; document in `local/SANDBOX.md` / manual test guide.
3. **Daraja passkey length** — portal simulator uses a 64-char passkey; short 32-char sandbox default in docs caused `500.001.1001 Wrong credentials`.
4. **Idempotency on provider 500** — failed Daraja call left key `sandbox-sale-3` as `in progress`; server restart required before retry.

---

## 6. Sign-off

| Role | Name | Fake adapter | Sandbox |
|------|------|--------------|---------|
| Tester | Minage | PASS | PASS |
| DRI | Hunter | _pending review_ | _pending review_ |
