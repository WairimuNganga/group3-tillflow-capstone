#!/usr/bin/env bash
# POS end-to-end demo against a running service + the local Docker Postgres.
#
# Seeds two shops with tills, attendants and sales, then proves the G2
# invariants through the real API and directly in the database:
# idempotency, integer minor-unit totals, the sale state machine, validation,
# and tenant isolation (API 404 + RLS on a raw runtime-role connection).
#
# Usage (POS running on :8000, DB container up — see README.md):
#   services/pos/local/e2e-demo.sh
#   POS_URL=http://localhost:8000 DB_CONTAINER=tillflow-pos-db services/pos/local/e2e-demo.sh
#
# Safe to re-run: every run uses fresh phone numbers, shortcodes and keys.
set -euo pipefail

POS_URL="${POS_URL:-http://localhost:8000}"
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

# req METHOD PATH [JSON] [extra curl args...] -> sets $CODE, body in $BODY
req() {
  local method="$1" path="$2" data="${3:-}"
  shift 3 || shift $#
  local args=(-s -o "$BODY" -w '%{http_code}' -X "$method" "$POS_URL$path" -H 'content-type: application/json')
  [[ -n "$data" ]] && args+=(-d "$data")
  CODE="$(curl "${args[@]}" "$@")"
}

expect() { # expect CODE DESCRIPTION
  if [[ "$CODE" == "$1" ]]; then ok "$2 (HTTP $CODE)"; else bad "$2 — expected $1, got $CODE: $(cat "$BODY")"; fi
}

check() { # check ACTUAL EXPECTED DESCRIPTION
  if [[ "$1" == "$2" ]]; then ok "$3"; else bad "$3 — expected '$2', got '$1'"; fi
}

onboard() { # onboard NAME PHONE_PREFIX SHORTCODE -> sets TID TILL ATT
  req POST /tenants "{\"name\":\"$1\",\"owner_phone\":\"${2}0$SUFFIX\",\"owner_name\":\"$1 Owner\"}"
  expect 201 "onboard shop '$1'"
  TID="$(jq -r .tenant.id "$BODY")"
  req POST /tills "{\"name\":\"Front counter\",\"shortcode\":\"$3$SUFFIX\"}" -H "X-Tenant-Id: $TID"
  expect 201 "add till to '$1'"
  TILL="$(jq -r .id "$BODY")"
  req POST /attendants "{\"phone\":\"${2}1$SUFFIX\",\"display_name\":\"$1 Attendant\"}" -H "X-Tenant-Id: $TID"
  expect 201 "add attendant to '$1'"
  ATT="$(jq -r .id "$BODY")"
}

step "0. Service is up"
req GET /ready ""
expect 200 "/ready (database reachable)"

step "1. Seed two shops"
onboard "Mama Mboga" 2547001 11
A_TID="$TID" A_TILL="$TILL" A_ATT="$ATT"
onboard "Kiosk Bora" 2547002 22
B_TID="$TID" B_TILL="$TILL" B_ATT="$ATT"

step "2. Create a sale (3 x Sukuma @ KES 20, 1 x Bread @ KES 65)"
SALE_JSON="{\"till_id\":\"$A_TILL\",\"attendant_id\":\"$A_ATT\",\"customer_msisdn\":\"254712345678\",
  \"items\":[{\"name\":\"Sukuma\",\"quantity\":3,\"unit_price_minor\":2000},
             {\"name\":\"Bread\",\"quantity\":1,\"unit_price_minor\":6500}]}"
KEY="sale-$RUN"
req POST /sales "$SALE_JSON" -H "X-Tenant-Id: $A_TID" -H "Idempotency-Key: $KEY"
expect 201 "new sale created"
SALE="$(jq -r .id "$BODY")"
check "$(jq -r .total_minor "$BODY")" 12500 "total is integer minor units: 3*2000 + 6500 = 12500 (KES 125.00)"
check "$(jq -r .status "$BODY")" pending "new sale starts 'pending'"

step "3. Idempotency — network retry must not create a second sale"
req POST /sales "$SALE_JSON" -H "X-Tenant-Id: $A_TID" -H "Idempotency-Key: $KEY"
expect 200 "replay with same Idempotency-Key returns existing sale"
check "$(jq -r .id "$BODY")" "$SALE" "replay returns the SAME sale id"
req POST /sales "{\"till_id\":\"$B_TILL\",\"attendant_id\":\"$B_ATT\",\"items\":[{\"name\":\"Milk\",\"quantity\":2,\"unit_price_minor\":6000}]}" \
  -H "X-Tenant-Id: $B_TID" -H "Idempotency-Key: $KEY"
expect 201 "same key in a different shop is a separate sale"
B_SALE="$(jq -r .id "$BODY")"

step "4. Sale state machine"
req POST "/sales/$SALE/transition" '{"target":"awaiting_payment"}' -H "X-Tenant-Id: $A_TID"
expect 200 "pending -> awaiting_payment (STK sent)"
req POST "/sales/$SALE/transition" '{"target":"paid"}' -H "X-Tenant-Id: $A_TID"
expect 200 "awaiting_payment -> paid (callback confirmed)"
req POST "/sales/$SALE/transition" '{"target":"paid"}' -H "X-Tenant-Id: $A_TID"
expect 200 "paid -> paid again is a no-op (replayed callback)"
req POST "/sales/$SALE/transition" '{"target":"cancelled"}' -H "X-Tenant-Id: $A_TID"
expect 409 "paid -> cancelled rejected (terminal state)"
req POST "/sales/$B_SALE/transition" '{"target":"paid"}' -H "X-Tenant-Id: $B_TID"
expect 409 "pending -> paid rejected (must go through awaiting_payment)"
req POST "/sales/$B_SALE/transition" '{"target":"cancelled"}' -H "X-Tenant-Id: $B_TID"
expect 200 "pending -> cancelled allowed"
req GET "/sales/$SALE" "" -H "X-Tenant-Id: $A_TID"
check "$(jq -r .status "$BODY")" paid "sale is persisted as 'paid'"

step "5. Validation"
req POST /sales "$SALE_JSON" -H "X-Tenant-Id: $A_TID"
expect 400 "missing Idempotency-Key rejected"
req POST /sales "$SALE_JSON" -H "Idempotency-Key: k-$RUN"
expect 400 "missing X-Tenant-Id rejected"
req POST /sales "{\"till_id\":\"$B_TILL\",\"attendant_id\":\"$A_ATT\",\"items\":[{\"name\":\"X\",\"quantity\":1,\"unit_price_minor\":100}]}" \
  -H "X-Tenant-Id: $A_TID" -H "Idempotency-Key: steal-$RUN"
expect 400 "shop A cannot sell on shop B's till"
req POST /sales "{\"till_id\":\"$A_TILL\",\"attendant_id\":\"$A_ATT\",\"items\":[{\"name\":\"X\",\"quantity\":0,\"unit_price_minor\":100}]}" \
  -H "X-Tenant-Id: $A_TID" -H "Idempotency-Key: zero-$RUN"
expect 422 "quantity 0 rejected"

step "6. Tenant isolation through the API"
req GET "/sales/$SALE" "" -H "X-Tenant-Id: $B_TID"
expect 404 "shop B cannot read shop A's sale"
req POST "/sales/$SALE/transition" '{"target":"failed"}' -H "X-Tenant-Id: $B_TID"
expect 404 "shop B cannot change shop A's sale"
req GET /sales "" -H "X-Tenant-Id: $B_TID"
check "$(jq --arg s "$SALE" '[.[] | select(.id == $s)] | length' "$BODY")" 0 "shop A's sale absent from shop B's list"

step "7. Tenant isolation in the database (RLS, as runtime role tillflow_pos)"
if docker inspect "$DB_CONTAINER" >/dev/null 2>&1; then
  psql_pos() { docker exec -i -e PGPASSWORD=pos_secret "$DB_CONTAINER" psql -h 127.0.0.1 -U tillflow_pos -d tillflow -tAq -c "$1"; }
  check "$(psql_pos "SELECT count(*) FROM pos.sales")" 0 \
    "no tenant set -> zero rows (not an error)"
  check "$(psql_pos "BEGIN; SELECT set_config('app.current_tenant_id','$B_TID',true); SELECT count(*) FROM pos.sales WHERE id='$SALE'; COMMIT;" | sed -n 2p)" 0 \
    "as shop B, shop A's sale is invisible even with a raw SQL query"
  check "$(psql_pos "BEGIN; SELECT set_config('app.current_tenant_id','$A_TID',true); SELECT status FROM pos.sales WHERE id='$SALE'; COMMIT;" | sed -n 2p)" paid \
    "as shop A, its own sale is visible"
  check "$(docker exec -i "$DB_CONTAINER" psql -U tillflow -d tillflow -tAc \
    "SELECT bool_and(relrowsecurity AND relforcerowsecurity) FROM pg_class WHERE relnamespace='pos'::regnamespace AND relkind='r' AND relname<>'alembic_version'")" t \
    "RLS enabled + FORCED on every pos table"
else
  printf '  SKIP DB checks: container %s not found\n' "$DB_CONTAINER"
fi

printf '\n\033[1mResult: %d passed, %d failed\033[0m\n' "$PASS" "$FAIL"
printf 'Shop A tenant: %s  sale: %s\nShop B tenant: %s  sale: %s\n' "$A_TID" "$SALE" "$B_TID" "$B_SALE"
[[ "$FAIL" -eq 0 ]]
