# Web demo shell — evidence

**Owner:** Joyce · **Capture:** Hunter  
**Date:** 2026-09-20  
**URL:** http://127.0.0.1:8070/

## Screenshots

Captured with Chromium (Playwright) against the local demo shell
(`POS_BASE_URL` + `COMMISSION_BASE_URL` pointed at `:8000` / `:8090`).

| # | File | What it shows |
|---|------|----------------|
| 1 | [`web-screenshots/01-home-open-shop.png`](web-screenshots/01-home-open-shop.png) | Home — brand + open-shop form |
| 2 | [`web-screenshots/02-home-shop-open.png`](web-screenshots/02-home-shop-open.png) | Home — shop open (Start sale / View sales) |
| 3 | [`web-screenshots/03-new-sale.png`](web-screenshots/03-new-sale.png) | New sale — whole KES amount |
| 4 | [`web-screenshots/04-sale-status.png`](web-screenshots/04-sale-status.png) | Sale status after STK handoff (auto-poll while awaiting) |
| 5 | [`web-screenshots/05-sales-list.png`](web-screenshots/05-sales-list.png) | Sales table — rate, commission, pagination |
| 6 | [`web-screenshots/06-sales-filtered.png`](web-screenshots/06-sales-filtered.png) | Sales filtered by status |
| 7 | [`web-screenshots/07-commission-day.png`](web-screenshots/07-commission-day.png) | **Attendant day** — EAT/GMT+3 period, rate, estimated vs ledgered, close + B2C |
| 8 | [`web-screenshots/08-payouts-list.png`](web-screenshots/08-payouts-list.png) | **Payouts** table — period, attendant, phone, amount, state, payments id |
| 9 | [`web-screenshots/09-payouts-filtered.png`](web-screenshots/09-payouts-filtered.png) | Payouts filtered by state (`submitted`) |
| 10 | [`web-screenshots/10-sales-list-eat.png`](web-screenshots/10-sales-list-eat.png) | Sales list with timestamps shown in EAT (GMT+3) |

Nav on every authenticated page: Home · Sales · Commission · **Payouts** · New sale.

## Templates

Jinja under `services/web/web/templates/`:

| Template | Route | Purpose |
|----------|-------|---------|
| `home.html` | `GET /` | Brand + open shop |
| `sale.html` | `GET /sale` | New sale form (whole KES) |
| `sale_status.html` | `GET /sales/{id}` | Status after STK handoff (auto-poll) |
| `sales_list.html` | `GET /sales` | Shop sales + filters + pagination + commission |
| `commission.html` | `GET /commission` | Attendant day — close, ledger, B2C (EAT day) |
| `payouts.html` | `GET /payouts` | Payout intent tracking table |
| `base.html` | — | Brand, nav (incl. Payouts), flash, CSP |

## Behaviour called out in UI

| Behaviour | Where |
|-----------|--------|
| Payout period = **EAT / GMT+3** calendar day | Commission lede + close bucketing |
| One B2C per attendant per day; replay explains next day | Flash after `POST /commission/payout`; locked button + “Next payout” |
| Payout tracking table | `/payouts` (+ attendant / state filters) |
| Estimated commission = `amount × rate_bps // 10000` | Sales + commission day |

## Reproduce

```bash
# POS :8000, Payments :8080, Commission :8090 (with DATABASE_URL on shared tillflow DB), then:
cd services/web
export TILLFLOW_TELEMETRY_EXPORT=none
export POS_BASE_URL="http://127.0.0.1:8000"
export COMMISSION_BASE_URL="http://127.0.0.1:8090"
uvicorn web.main:app --reload --host 127.0.0.1 --port 8070
# open http://127.0.0.1:8070/
```

Commission local bootstrap (once):

```bash
docker exec -i tillflow-pos-db psql -U tillflow -d tillflow \
  < services/commission/local/init-db.sql
cd services/commission
export DATABASE_URL="postgresql+asyncpg://commission:secret@localhost:5432/tillflow"
export PAYMENTS_BASE_URL="http://127.0.0.1:8080"
python3 -m alembic upgrade head
COMMISSION_WORKER_ENABLED=false uvicorn commission.main:app --reload --port 8090
```

Re-capture screenshots (Chromium / Playwright):

```bash
cd /path/to/repo   # with services up
python3 - <<'PY'
from pathlib import Path
from playwright.sync_api import sync_playwright
out = Path("evidence/product/web-screenshots")
base = "http://127.0.0.1:8070"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    page.goto(f"{base}/", wait_until="networkidle")
    # open shop via form if needed, then:
    page.goto(f"{base}/commission?period=2026-09-20", wait_until="networkidle")
    page.screenshot(path=str(out / "07-commission-day.png"), full_page=True)
    page.goto(f"{base}/payouts", wait_until="networkidle")
    page.screenshot(path=str(out / "08-payouts-list.png"), full_page=True)
    page.goto(f"{base}/payouts?state=submitted", wait_until="networkidle")
    page.screenshot(path=str(out / "09-payouts-filtered.png"), full_page=True)
    page.goto(f"{base}/sales", wait_until="networkidle")
    page.screenshot(path=str(out / "10-sales-list-eat.png"), full_page=True)
    browser.close()
PY
```

After **Run daily close** + **Request B2C payout** on that shop, `/payouts` shows rows
(period, amount, `submitted`/`completed`, payments id). Re-requesting the same day
flashes *Already paid for … Next payout after close on YYYY-MM-DD*.

Tests:

```bash
cd services/web
TILLFLOW_TELEMETRY_EXPORT=none pytest -v
```

## Checks

| Check | Proof |
|-------|--------|
| Brand on first viewport | `01-home-open-shop.png` + home HTML |
| CSRF rejects bad token | `test_setup_requires_csrf` |
| Setup → sale flow (fake POS) | `test_setup_and_sale_flow_with_fake_pos` |
| Sales list + filters + commission + pagination | screenshots 05–06, 10 + same test |
| Attendant day (EAT) + close/payout | screenshot 07 + commission template |
| Payouts tracking table + state filter | screenshots 08–09 + `GET /payouts` / `GET /internal/payouts` |
| Payouts nav link | `base.html` + screenshots 07–09 |
| CSP header | `test_home_renders_brand_and_csp` |

## Related packs

- [`commission-close-b2c.md`](commission-close-b2c.md) — close → ledger → B2C invariants
- Commission API used by the shell: `GET /internal/summary`, `GET /internal/payouts`,
  `POST /internal/close`, `POST /internal/payout`
