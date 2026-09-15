# Daraja sandbox smoke test

Use **sandbox credentials only**. Keep values in `services/payments/.env` (gitignored).

## 1. Create your env file

```bash
cd services/payments
cp .env.example .env
# edit .env — paste sandbox key/secret/passkey/shortcode
```

Pick a long random `MPESA_CALLBACK_SECRET` (not the default).

## 2. Expose localhost to Daraja

Daraja cannot call `http://127.0.0.1`. Use a tunnel:

```bash
ngrok http 8080
```

Set in `.env`:

```
DARAJA_STK_CALLBACK_URL=https://<your-ngrok-host>/callbacks/mpesa/<MPESA_CALLBACK_SECRET>
MPESA_ADAPTER=sandbox
```

## 3. Run payments

```bash
cd services/payments
# with local Postgres:
export DATABASE_URL="postgresql+asyncpg://payments:secret@localhost:5432/tillflow"

python3 -m uvicorn payments.main:app --reload --port 8080
```

`.env` is loaded automatically by settings.

## 4. Initiate STK (no fake_scenario)

Use a sandbox test MSISDN from Safaricom docs:

```bash
curl -s -X POST http://127.0.0.1:8080/payments/stk \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: tenant-a' \
  -H 'Idempotency-Key: sandbox-sale-1' \
  -d '{
    "sale_id": "33333333-3333-3333-3333-333333333333",
    "phone_number": "2547XXXXXXXX",
    "amount_minor_units": 100
  }'
```

Watch the API logs for the callback hit on `/callbacks/mpesa/...`. Payment should move to `paid` when the sandbox STK succeeds.

## Safety

| OK | Not OK |
|---|---|
| Sandbox app credentials | Production Daraja |
| `.env` on your machine | Committing `.env` |
| `MPESA_ADAPTER=fake` in CI | Sandbox in CI/k6 |
