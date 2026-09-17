# Payments confirmations — commission view + `devops-g3/daraja`

**From:** Hunter (Payments + integrity)  
**For:** Commission (Joyce) · Platform / secrets (Lwam)  
**Date:** 2026-09-16  
**Source of truth:** `services/payments` migrations + `tillflow_shared.mpesa.settings`

---

## 1. Commission read-only view (ADR-002)

Commission must **not** get raw `SELECT` on `payments.payments`. Payments owns a view; Lwam grants `SELECT` on the view only to `tillflow_commission`.

### Source table

| | |
|---|---|
| Schema | `payments` |
| Table | `payments.payments` |
| Unique sale key | `(tenant_id, sale_id)` |

Related tables (`payment_callbacks`, `payment_ledger`, `payouts`, `idempotency_keys`) are **not** for the commission eligibility read.

### Payment `state` values

| Value | Commission-eligible? |
|-------|----------------------|
| `pending` | No |
| `stk_sent` | No |
| `pending_reconciliation` | No |
| `failed` | No |
| **`paid`** | **Yes** (only this) |

There is no separate `settled` / `reconciled` enum. Settlement is `state = 'paid'` **and** `settled_at IS NOT NULL` (set on successful callback or STK Query — threat model M8).

### Columns commission should see

| Column | Type | Why |
|--------|------|-----|
| `id` | UUID | Payment id (optional join / audit) |
| `tenant_id` | text | Tenant scope |
| `sale_id` | UUID | Link to POS sale |
| `amount_minor_units` | bigint | Money base (prefer this) |
| `amount_whole_kes` | bigint | Daraja whole-shilling amount |
| `state` | text | Always `paid` in the view |
| `settled_at` | timestamptz | Eligibility / period cutoff |
| `mpesa_receipt_number` | text | Optional audit |
| `created_at` / `updated_at` | timestamptz | Optional |

**Do not expose** `phone_number` (customer MSISDN / PII). Attendant MSISDN for B2C lives in commission’s own data; payouts go through `POST /payments/b2c`.

### Proposed view (payments migration; grant by platform)

```sql
CREATE OR REPLACE VIEW payments.v_paid_sales_for_commission AS
SELECT
  id AS payment_id,
  tenant_id,
  sale_id,
  amount_minor_units,
  amount_whole_kes,
  state,
  settled_at,
  mpesa_receipt_number,
  created_at,
  updated_at
FROM payments.payments
WHERE state = 'paid'
  AND settled_at IS NOT NULL;

-- Platform (Lwam) after view exists:
-- GRANT SELECT ON payments.v_paid_sales_for_commission TO tillflow_commission;
```

Eligibility rule for the daily close: rows in this view whose `settled_at` falls in the payout period. Do **not** treat `stk_sent` or callback-shaped events as paid.

---

## 2. Secrets Manager — `devops-g3/daraja`

Deployed env forces `MPESA_ADAPTER=sandbox` (Terraform). Payments then needs these values at process start.

### JSON keys to put in the secret

Values come from the Safaricom Daraja **sandbox** app (not production). Use the **64-char** Lipa Na M-Pesa Online passkey from the portal simulator test credentials if STK returns `500.001.1001 Wrong credentials`.

```json
{
  "DARAJA_CONSUMER_KEY": "<sandbox consumer key>",
  "DARAJA_CONSUMER_SECRET": "<sandbox consumer secret>",
  "DARAJA_PASSKEY": "<64-char Lipa Na M-Pesa Online passkey>",
  "DARAJA_SHORTCODE": "<sandbox shortcode / BusinessShortCode>",
  "DARAJA_INITIATOR": "<sandbox B2C initiator name>",
  "DARAJA_SECURITY_CREDENTIAL": "<encrypted initiator security credential>",
  "MPESA_CALLBACK_SECRET": "<long random path segment; not a Daraja value>"
}
```

| Key | Required for | Notes |
|-----|----------------|-------|
| `DARAJA_CONSUMER_KEY` | STK / OAuth | Sandbox app |
| `DARAJA_CONSUMER_SECRET` | STK / OAuth | Sandbox app |
| `DARAJA_PASSKEY` | STK password | Prefer 64-char portal passkey |
| `DARAJA_SHORTCODE` | STK | BusinessShortCode |
| `DARAJA_INITIATOR` | B2C | Needed when smoke covers payouts |
| `DARAJA_SECURITY_CREDENTIAL` | B2C | Encrypted credential from Daraja |
| `MPESA_CALLBACK_SECRET` | Callback auth | Must match path in public callback URL ([ADR-007]) |

### Not inside the secret (plain task env / ALB-derived)

| Env | Why |
|-----|-----|
| `DARAJA_BASE_URL` | Default `https://sandbox.safaricom.co.ke` is fine |
| `DARAJA_STK_CALLBACK_URL` | Must be public HTTPS → ALB → `/callbacks/mpesa/<MPESA_CALLBACK_SECRET>` |
| `DARAJA_B2C_RESULT_URL` | Public HTTPS → `/payments/b2c/result` (or agreed path) |
| `MPESA_ADAPTER` | Already set by Terraform to `sandbox` |

Populate (out-of-band; never commit):

```bash
aws secretsmanager put-secret-value \
  --secret-id devops-g3/daraja \
  --secret-string file://daraja.json
# shred daraja.json
```

### Injection gap (needs Lwam + Hunter)

Today Terraform injects the **entire** secret as one env var `DARAJA_CREDENTIALS`, while the app reads **flat** `DARAJA_*` / `MPESA_CALLBACK_SECRET` via `MpesaSettings`.

Until one of these lands, sandbox smoke will fail even if the JSON is correct:

1. **Preferred (match `DB_CREDENTIALS` pattern):** ECS secret entries per key, e.g.  
   `DARAJA_CONSUMER_KEY = "<arn>:DARAJA_CONSUMER_KEY::"` (and the same for each key above), **or**
2. Payments unpacks `DARAJA_CREDENTIALS` JSON into env / settings at startup.

Health (`/health`) does not require Daraja. Sandbox STK / smoke **does**.

### Minimum set for STK-only smoke

`DARAJA_CONSUMER_KEY`, `DARAJA_CONSUMER_SECRET`, `DARAJA_PASSKEY`, `DARAJA_SHORTCODE`, `MPESA_CALLBACK_SECRET`, plus task env `DARAJA_STK_CALLBACK_URL` pointing at the ALB callback path.
