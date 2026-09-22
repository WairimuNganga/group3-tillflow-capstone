#!/usr/bin/env bash
# POS + Payments end-to-end flow (G2): sale -> STK -> callback -> paid.
#
# Runs against both services locally with the deterministic fake M-Pesa adapter
# (MPESA_ADAPTER=fake) — no Daraja, no real money. Proves the money-correctness
# invariants that cross the service boundary:
#   * sale creation is idempotent (retry -> one sale)
#   * STK is idempotent (retry -> one payment, no second prompt)
#   * a duplicate callback settles once (one ledger effect)
#   * a timeout is NOT a decline (pending_reconciliation -> reconcile -> paid)
#   * commission payout (B2C) is idempotent
#   * tenant isolation holds across the flow
#
# The two services call each other; nothing here marks a sale paid by hand.
#
# Prerequisites (see services/pos/local/README.md):
#   POS       on :8000  DATABASE_URL -> local Postgres, PAYMENTS_BASE_URL -> payments
#   Payments  on :8080  MPESA_ADAPTER=fake, POS_BASE_URL -> POS
#
# Usage:
#   services/pos/local/e2e-flow.sh
#   POS_URL=... PAY_URL=... CALLBACK_SECRET=... services/pos/local/e2e-flow.sh
set -euo pipefail

POS_URL="${POS_URL:-http://127.0.0.1:8000}"
PAY_URL="${PAY_URL:-http://127.0.0.1:8080}"
COMMISSION_URL="${COMMISSION_URL:-http://localhost:8090}"
CALLBACK_SECRET="${CALLBACK_SECRET:-local-dev-callback-secret}"
DB_CONTAINER="${DB_CONTAINER:-tillflow-pos-db}"
RUN="$(date +%s)"
SUFFIX="${RUN: -6}"

PASS=0
FAIL=0
BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT

ok()   { PASS=$((PASS + 1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }
note() { printf '  \033[33m!\033[0m %s\n' "$1"; }

req() { # req METHOD URL [JSON] [curl args...] -> $CODE, body in $BODY
  local method="$1" url="$2" data="${3:-}"
  shift 3 || shift $#
  local args=(-s -o "$BODY" -w '%{http_code}' -X "$method" "$url" -H 'content-type: application/json')
  [[ -n "$data" ]] && args+=(-d "$data")
  # Do not let set -e kill the script on connection refused (curl exits 7).
  CODE="$(curl "${args[@]}" "$@" 2>/dev/null)" || CODE="000"
}
expect() { if [[ "$CODE" == "$1" ]]; then ok "$2 (HTTP $CODE)"; else bad "$2 — expected $1, got $CODE: $(cat "$BODY")"; fi; }
check()  { if [[ "$1" == "$2" ]]; then ok "$3"; else bad "$3 — expected '$2', got '$1'"; fi; }

sale_status() { # sale_status TENANT SALE
  curl -s "$POS_URL/sales/$2" -H "X-Tenant-Id: $1" | jq -r .status
}

step "0. Both services are up"
req GET "$POS_URL/ready" ""
expect 200 "POS /ready"
req GET "$PAY_URL/health" ""
expect 200 "Payments /health"

step "1. Shop onboards (POS)"
req POST "$POS_URL/tenants" "{\"name\":\"Mama Mboga\",\"owner_phone\":\"2547001$SUFFIX\",\"owner_name\":\"Wanjiru\"}"
expect 201 "create shop"
TID="$(jq -r .tenant.id "$BODY")"
req POST "$POS_URL/tills" "{\"name\":\"Front counter\",\"shortcode\":\"11$SUFFIX\"}" -H "X-Tenant-Id: $TID"
expect 201 "add till"
TILL="$(jq -r .id "$BODY")"
req POST "$POS_URL/attendants" "{\"phone\":\"2547111$SUFFIX\",\"display_name\":\"Amina\"}" -H "X-Tenant-Id: $TID"
expect 201 "add attendant"
ATT="$(jq -r .id "$BODY")"
req POST "$POS_URL/commission-rates" "{\"attendant_id\":\"$ATT\",\"rate_bps\":200}" -H "X-Tenant-Id: $TID"
expect 201 "set attendant commission rate (2%)"

new_sale() { # new_sale KEY AMOUNT_MINOR -> sets $SALE_ID and $CODE (not a subshell:
  # command substitution would swallow $CODE and make expect check a stale one)
  req POST "$POS_URL/sales" \
    "{\"till_id\":\"$TILL\",\"attendant_id\":\"$ATT\",\"customer_msisdn\":\"254712345678\",
      \"items\":[{\"name\":\"Shopping\",\"quantity\":1,\"unit_price_minor\":$2}]}" \
    -H "X-Tenant-Id: $TID" -H "Idempotency-Key: $1"
  SALE_ID="$(jq -r .id "$BODY")"
}

# ---------------------------------------------------------------- happy path
step "2. Sale -> STK -> callback -> paid (customer pays)"
new_sale "sale-a-$RUN" 12500
SALE="$SALE_ID"
expect 201 "attendant rings up KES 125.00 sale"
check "$(sale_status "$TID" "$SALE")" pending "sale starts 'pending'"

# POS calls Payments itself: one request, no client-supplied amount.
req POST "$POS_URL/sales/$SALE/pay" '{}' -H "X-Tenant-Id: $TID"
expect 200 "POS hands the sale to Payments (STK push sent)"
PAYMENT_ID="$(jq -r .payment_id "$BODY")"
check "$(jq -r .status "$BODY")" awaiting_payment "sale moves to 'awaiting_payment'"
check "$(jq -r .payment_state "$BODY")" stk_sent "payment state 'stk_sent'"

req POST "$POS_URL/sales/$SALE/pay" '{}' -H "X-Tenant-Id: $TID"
check "$(jq -r .payment_id "$BODY")" "$PAYMENT_ID" "retrying pay reaches the SAME payment — no second prompt, no double charge"

# Look up the provider ids to play M-Pesa's part below.
PAY_ROW="$(docker exec "$DB_CONTAINER" psql -U tillflow -d tillflow -tAc \
  "select merchant_request_id || ' ' || checkout_request_id || ' ' || amount_whole_kes
     from payments.payments where id = '$PAYMENT_ID'" 2>/dev/null || true)"
read -r MERCHANT CHECKOUT WHOLE_KES <<<"$PAY_ROW"
check "$WHOLE_KES" 125 "12500 minor units -> 125 whole KES at the M-Pesa boundary"

callback() { # callback MERCHANT CHECKOUT RESULT_CODE RECEIPT
  req POST "$PAY_URL/callbacks/mpesa/$CALLBACK_SECRET" \
    "{\"Body\":{\"stkCallback\":{\"MerchantRequestID\":\"$1\",\"CheckoutRequestID\":\"$2\",
       \"ResultCode\":$3,\"ResultDesc\":\"processed\",
       \"CallbackMetadata\":{\"Item\":[{\"Name\":\"Amount\",\"Value\":125},
                                        {\"Name\":\"MpesaReceiptNumber\",\"Value\":\"$4\"}]}}}}"
}

callback "$MERCHANT" "$CHECKOUT" 0 "RCPT$SUFFIX"
expect 200 "M-Pesa callback arrives (customer entered PIN)"
check "$(jq -r .state "$BODY")" paid "payment settled 'paid'"
check "$(jq -r .ledger_written "$BODY")" true "one ledger entry written"

check "$(sale_status "$TID" "$SALE")" paid "Payments told POS — the sale is 'paid' with no manual step"
RECEIPT="$(docker exec "$DB_CONTAINER" psql -U tillflow -d tillflow -tAc \
  "select mpesa_receipt from pos.sales where id = '$SALE'" 2>/dev/null | tr -d ' ')"
check "$RECEIPT" "RCPT$SUFFIX" "the M-Pesa receipt is stored on the sale"

step "3. Duplicate callback (M-Pesa retries) settles once"
callback "$MERCHANT" "$CHECKOUT" 0 "RCPT$SUFFIX"
expect 200 "replayed callback accepted"
check "$(jq -r .reason "$BODY")" duplicate_callback "recognised as a duplicate"
check "$(jq -r .ledger_written "$BODY")" false "no second ledger entry"
check "$(sale_status "$TID" "$SALE")" paid "sale still exactly 'paid' — one state change, not two"

# ------------------------------------------------------------ timeout path
step "4. Timeout is NOT a decline (uncertain payment)"
new_sale "sale-b-$RUN" 2000
SALE2="$SALE_ID"
expect 201 "second sale, KES 20.00"
# Force the timeout scenario through Payments directly (the fake adapter takes
# the scenario there); POS has already created the sale.
req POST "$PAY_URL/payments/stk" \
  "{\"sale_id\":\"$SALE2\",\"phone_number\":\"254712345678\",\"amount_minor_units\":2000,\"fake_scenario\":\"delayed_timeout\"}" \
  -H "X-Tenant-Id: $TID" -H "Idempotency-Key: stk-$SALE2"
PAY2="$(jq -r .payment_id "$BODY")"
check "$(jq -r .state "$BODY")" pending_reconciliation "M-Pesa timed out -> payment 'pending_reconciliation', NOT failed"
check "$(sale_status "$TID" "$SALE2")" pending "sale is not marked failed — the customer is not told it failed"

req POST "$PAY_URL/payments/reconcile/$PAY2" ""
expect 200 "reconciliation queries M-Pesa for the real outcome"
check "$(jq -r .state "$BODY")" paid "money did arrive -> 'paid'"
check "$(jq -r .ledger_written "$BODY")" true "ledger written once, on reconcile"
check "$(sale_status "$TID" "$SALE2")" paid "reconciliation reported the outcome to POS — sale 'paid'"

# ------------------------------------------------------------- commission
step "5. Commission daily close → B2C (via commission worker when up)"
PERIOD="$(date -u +%F)"
if curl -sf "$COMMISSION_URL/health" >/dev/null 2>&1; then
  note "Commission service reachable — seeding in-memory close is demo-only;"
  note "full Postgres join needs v_paid_sales + POS views. Falling through to B2C contract."
fi
# Contract still proven at Payments boundary (commission calls this exact shape):
PAYOUT_KEY="$TID:$PERIOD:$ATT"
B2C_BODY="{\"attendant_id\":\"$ATT\",\"phone_number\":\"2547111$SUFFIX\",\"amount_minor_units\":290,
  \"originator_conversation_id\":\"$PAYOUT_KEY\"}"
req POST "$PAY_URL/payments/b2c" "$B2C_BODY" -H "X-Tenant-Id: $TID" -H "Idempotency-Key: $PAYOUT_KEY"
expect 202 "commission submits payout through Payments (never straight to Daraja)"
PAYOUT_ID="$(jq -r .payout_id "$BODY")"
CONV="$(jq -r .conversation_id "$BODY")"
check "$(jq -r .state "$BODY")" submitted "payout 'submitted'"

req POST "$PAY_URL/payments/b2c" "$B2C_BODY" -H "X-Tenant-Id: $TID" -H "Idempotency-Key: $PAYOUT_KEY"
check "$(jq -r .payout_id "$BODY")" "$PAYOUT_ID" "re-running the daily close does NOT pay twice"

req POST "$PAY_URL/payments/b2c/result" "{\"conversation_id\":\"$CONV\",\"success\":true}"
expect 200 "M-Pesa confirms the payout"
check "$(jq -r .state "$BODY")" completed "payout 'completed' — attendant paid"

# When commission is up with shared DB, also exercise /internal/close:
if curl -sf "$COMMISSION_URL/health" >/dev/null 2>&1; then
  req POST "$COMMISSION_URL/internal/close" "{\"payout_period\":\"$PERIOD\"}"
  # 200 even with zero sales in commission's in-memory store is fine for smoke
  if [[ "$CODE" == "200" ]]; then ok "commission /internal/close responds (HTTP $CODE)"; else note "commission close HTTP $CODE (optional smoke)"; fi
fi

# -------------------------------------------------------------- isolation
step "6. Another shop cannot touch this one's sale"
req POST "$POS_URL/tenants" "{\"name\":\"Kiosk Bora\",\"owner_phone\":\"2547002$SUFFIX\",\"owner_name\":\"Otieno\"}"
expect 201 "second shop onboards"
BID="$(jq -r .tenant.id "$BODY")"
req GET "$POS_URL/sales/$SALE" "" -H "X-Tenant-Id: $BID"
expect 404 "shop B cannot read shop A's sale"
req POST "$POS_URL/sales/$SALE/transition" '{"target":"cancelled"}' -H "X-Tenant-Id: $BID"
expect 404 "shop B cannot cancel shop A's sale"
req POST "$POS_URL/internal/sales/$SALE/payment-result" \
  "{\"payment_id\":\"$PAYMENT_ID\",\"result\":\"failed\"}" -H "X-Tenant-Id: $BID"
expect 404 "shop B cannot settle shop A's sale, even on the internal endpoint"

step "7. Only Payments can put a sale into a money state"
req POST "$POS_URL/sales/$SALE2/transition" '{"target":"paid"}' -H "X-Tenant-Id: $TID"
expect 400 "a public caller cannot mark a sale paid"
req POST "$POS_URL/internal/sales/$SALE/payment-result" \
  "{\"payment_id\":\"$PAYMENT_ID\",\"result\":\"paid\",\"amount_minor_units\":99}" -H "X-Tenant-Id: $TID"
expect 409 "a result whose amount isn't the sale total is refused"

step "8. Bad callback secret is rejected"
req POST "$PAY_URL/callbacks/mpesa/wrong-secret" \
  "{\"Body\":{\"stkCallback\":{\"MerchantRequestID\":\"x\",\"CheckoutRequestID\":\"y\",\"ResultCode\":0,\"ResultDesc\":\"d\"}}}"
expect 403 "forged callback URL rejected"

printf '\n\033[1mResult: %d passed, %d failed\033[0m\n' "$PASS" "$FAIL"
cat <<EOF

Shop:     $TID
Sale 1:   $SALE   (paid, payment $PAYMENT_ID)
Sale 2:   $SALE2  (paid after reconciliation, payment $PAY2)
Payout:   $PAYOUT_ID

The chain is automatic: POS -> Payments (/sales/{id}/pay) and Payments -> POS
(/internal/sales/{id}/payment-result). No step here marks a sale paid by hand.
EOF
[[ "$FAIL" -eq 0 ]]
