from __future__ import annotations

import os
import secrets
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from tillflow_shared import setup_telemetry
from tillflow_shared.health import create_health_router
from tillflow_shared.money import from_whole_kes, to_whole_kes
from tillflow_shared.otel.middleware import instrument_fastapi

from web.clients.commission import CommissionUnavailableError
from web.clients.pos import (
    SALE_STATUSES,
    PosUnavailableError,
    commission_minor,
    format_kes_from_minor,
)
from web.config import settings
from web.deps import get_commission_client, get_pos_client
from web.security import SecurityHeadersMiddleware
from web.session import (
    clear_session,
    cookie_path,
    load_session,
    save_session,
    verify_csrf,
)
from web.timeutil import format_when_eat, sale_date_eat, today_eat

if "TILLFLOW_TELEMETRY_EXPORT" not in os.environ:
    os.environ.setdefault("TILLFLOW_TELEMETRY_EXPORT", "none")

setup_telemetry(settings.service_name)

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))

app = FastAPI(title="TillFlow Web", version="0.1.0")
app.add_middleware(SecurityHeadersMiddleware)
app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")
app.include_router(
    create_health_router(
        service_name=settings.service_name,
        git_sha=settings.git_commit_sha,
        ready_check=lambda: True,
    )
)
instrument_fastapi(app, service_name=settings.service_name)


def _public_path(path: str = "/") -> str:
    """Return a browser URL that retains the API Gateway stage prefix."""
    base = settings.base_path.rstrip("/")
    normalized = "/" + path.lstrip("/")
    return f"{base}{normalized}" if base else normalized


def _shop_from_session(session: dict) -> dict | None:
    if not session.get("tenant_id"):
        return None
    return {
        "tenant_id": session["tenant_id"],
        "till_id": session["till_id"],
        "attendant_id": session["attendant_id"],
        "shop_name": session.get("shop_name", "Shop"),
        "attendant_name": session.get("attendant_name", ""),
        "attendant_phone": session.get("attendant_phone", ""),
    }


def _csrf_token(request: Request) -> str:
    return request.cookies.get(settings.csrf_cookie_name) or secrets.token_urlsafe(32)


def _attach_csrf(request: Request, response: HTMLResponse, token: str) -> None:
    if not request.cookies.get(settings.csrf_cookie_name):
        response.set_cookie(
            settings.csrf_cookie_name,
            token,
            httponly=False,
            samesite="lax",
            secure=settings.cookie_secure,
            max_age=60 * 60 * 12,
            path=cookie_path(),
        )


def _render(
    request: Request,
    name: str,
    *,
    status_code: int = 200,
    flash: dict | None = None,
    **ctx,
) -> HTMLResponse:
    session = load_session(request)
    token = _csrf_token(request)
    if flash is None:
        raw_flash = request.cookies.get("tillflow_flash")
        if raw_flash and "|" in raw_flash:
            kind, message = raw_flash.split("|", 1)
            flash = {"kind": kind, "message": message}
    response = templates.TemplateResponse(
        request,
        name,
        {
            "request": request,
            "shop": _shop_from_session(session),
            "flash": flash,
            "csrf_token": token,
            "base_path": settings.base_path.rstrip("/"),
            "pos_configured": bool(settings.pos_base_url),
            "commission_configured": bool(settings.commission_base_url),
            **ctx,
        },
        status_code=status_code,
    )
    _attach_csrf(request, response, token)
    if request.cookies.get("tillflow_flash"):
        response.delete_cookie("tillflow_flash", path=cookie_path())
    return response


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return _render(request, "home.html")


@app.post("/setup")
async def setup_shop(
    request: Request,
    csrf_token: str = Form(...),
    shop_name: str = Form(...),
    owner_phone: str = Form(...),
    attendant_name: str = Form(...),
    attendant_phone: str = Form(...),
    shortcode: str = Form(...),
):
    if not verify_csrf(request, csrf_token):
        return _render(
            request,
            "home.html",
            status_code=403,
            flash={"kind": "error", "message": "CSRF check failed — reload and try again."},
        )
    try:
        shop = await get_pos_client().ensure_shop(
            shop_name=shop_name.strip(),
            owner_phone=owner_phone.strip(),
            attendant_name=attendant_name.strip(),
            attendant_phone=attendant_phone.strip(),
            shortcode=shortcode.strip(),
        )
    except PosUnavailableError as exc:
        return _render(
            request,
            "home.html",
            status_code=502,
            flash={"kind": "error", "message": f"POS unavailable: {exc}"},
        )

    response = RedirectResponse(_public_path("/"), status_code=303)
    save_session(
        response,
        {
            "tenant_id": shop.tenant_id,
            "till_id": shop.till_id,
            "attendant_id": shop.attendant_id,
            "shop_name": shop.shop_name,
            "attendant_name": shop.attendant_name,
            "attendant_phone": shop.attendant_phone,
        },
    )
    _attach_csrf(request, response, _csrf_token(request))
    return response


@app.post("/reset")
async def reset_shop(request: Request, csrf_token: str = Form(...)):
    if not verify_csrf(request, csrf_token):
        return _render(
            request,
            "home.html",
            status_code=403,
            flash={"kind": "error", "message": "CSRF check failed."},
        )
    response = RedirectResponse(_public_path("/"), status_code=303)
    clear_session(response)
    _attach_csrf(request, response, _csrf_token(request))
    return response


@app.get("/sale", response_class=HTMLResponse)
async def sale_form(request: Request) -> HTMLResponse:
    session = load_session(request)
    if not session.get("tenant_id"):
        return RedirectResponse(_public_path("/"), status_code=303)
    return _render(request, "sale.html")


@app.post("/sale")
async def create_sale(
    request: Request,
    csrf_token: str = Form(...),
    item_name: str = Form(...),
    amount_kes: int = Form(...),
    customer_phone: str = Form(...),
):
    session = load_session(request)
    if not session.get("tenant_id"):
        return RedirectResponse(_public_path("/"), status_code=303)
    if not verify_csrf(request, csrf_token):
        return _render(
            request,
            "sale.html",
            status_code=403,
            flash={"kind": "error", "message": "CSRF check failed."},
        )
    if amount_kes < 1:
        return _render(
            request,
            "sale.html",
            status_code=400,
            flash={"kind": "error", "message": "Amount must be at least KES 1."},
        )
    amount_minor = from_whole_kes(amount_kes)
    try:
        sale = await get_pos_client().create_and_pay(
            tenant_id=session["tenant_id"],
            till_id=session["till_id"],
            attendant_id=session["attendant_id"],
            item_name=item_name.strip(),
            amount_minor=amount_minor,
            customer_phone=customer_phone.strip(),
        )
    except PosUnavailableError as exc:
        return _render(
            request,
            "sale.html",
            status_code=502,
            flash={"kind": "error", "message": f"POS unavailable: {exc}"},
        )
    return RedirectResponse(_public_path(f"/sales/{sale.sale_id}"), status_code=303)


def _sale_date(created_at: str | None) -> date | None:
    return sale_date_eat(created_at)


def _format_when(created_at: str | None) -> str:
    return format_when_eat(created_at)


PAGE_SIZE = 10


@app.get("/sales", response_class=HTMLResponse)
async def sales_list(
    request: Request,
    attendant_id: str | None = None,
    status: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    session = load_session(request)
    if not session.get("tenant_id"):
        return RedirectResponse(_public_path("/"), status_code=303)

    attendant_id = (attendant_id or "").strip() or None
    status = (status or "").strip() or None
    if status and status not in SALE_STATUSES:
        status = None
    page = max(1, page)

    try:
        raw_sales = await get_pos_client().list_sales(tenant_id=session["tenant_id"])
        rate_by_attendant = await get_pos_client().list_commission_rates(
            tenant_id=session["tenant_id"]
        )
    except PosUnavailableError as exc:
        return _render(
            request,
            "home.html",
            status_code=502,
            flash={"kind": "error", "message": f"POS unavailable: {exc}"},
        )

    attendant_id_filter = attendant_id
    status_filter = status
    session_attendant_id = session.get("attendant_id")
    session_attendant_name = session.get("attendant_name") or "Attendant"

    attendants_map: dict[str, str] = {}
    if session_attendant_id:
        attendants_map[session_attendant_id] = session_attendant_name

    rows = []
    for sale in raw_sales:
        aid = sale.attendant_id or ""
        name = sale.attendant_name or attendants_map.get(aid) or (aid[:8] + "…" if aid else "—")
        if aid and aid not in attendants_map:
            attendants_map[aid] = name
        if attendant_id_filter and aid != attendant_id_filter:
            continue
        if status_filter and sale.status != status_filter:
            continue

        rate_bps = rate_by_attendant.get(aid)
        commission_display = "—"
        rate_display = "—"
        if rate_bps is not None:
            rate_display = f"{rate_bps / 100:g}%"
        if sale.status == "paid" and rate_bps is not None:
            owed = commission_minor(sale.total_minor, rate_bps)
            commission_display = f"KES {format_kes_from_minor(owed)}"

        rows.append(
            {
                "sale_id": sale.sale_id,
                "status": sale.status,
                "total_kes": to_whole_kes(sale.total_minor),
                "attendant_id": aid,
                "attendant_name": name,
                "customer_msisdn": sale.customer_msisdn or "—",
                "created_at": _format_when(sale.created_at),
                "created_sort": sale.created_at or "",
                "item_name": sale.item_name or "Sale",
                "rate_display": rate_display,
                "commission_display": commission_display,
            }
        )

    rows.sort(key=lambda r: r["created_sort"], reverse=True)

    total = len(rows)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) if total else 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * PAGE_SIZE
    page_rows = rows[start : start + PAGE_SIZE]

    attendants = [
        {"id": aid, "name": name}
        for aid, name in sorted(attendants_map.items(), key=lambda x: x[1].lower())
    ]
    query = {}
    if attendant_id_filter:
        query["attendant_id"] = attendant_id_filter
    if status_filter:
        query["status"] = status_filter

    def _page_href(p: int) -> str:
        params = {**query, "page": str(p)}
        return "/sales?" + "&".join(f"{k}={v}" for k, v in params.items())

    return _render(
        request,
        "sales_list.html",
        sales=page_rows,
        attendants=attendants,
        statuses=SALE_STATUSES,
        filters={
            "attendant_id": attendant_id_filter or "",
            "status": status_filter or "",
        },
        pagination={
            "page": page,
            "page_size": PAGE_SIZE,
            "total": total,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "prev_href": _page_href(page - 1) if page > 1 else None,
            "next_href": _page_href(page + 1) if page < total_pages else None,
            "from_item": start + 1 if total else 0,
            "to_item": start + len(page_rows),
        },
    )


@app.get("/commission", response_class=HTMLResponse)
async def commission_day(
    request: Request,
    period: str | None = None,
    attendant_id: str | None = None,
) -> HTMLResponse:
    session = load_session(request)
    if not session.get("tenant_id"):
        return RedirectResponse(_public_path("/"), status_code=303)

    try:
        day = date.fromisoformat(period) if period else today_eat()
    except ValueError:
        day = today_eat()

    attendant_id = (attendant_id or "").strip() or session.get("attendant_id") or ""
    session_attendant_id = session.get("attendant_id") or ""
    session_attendant_name = session.get("attendant_name") or "Attendant"

    try:
        raw_sales = await get_pos_client().list_sales(tenant_id=session["tenant_id"])
        rate_by_attendant = await get_pos_client().list_commission_rates(
            tenant_id=session["tenant_id"]
        )
    except PosUnavailableError as exc:
        return _render(
            request,
            "home.html",
            status_code=502,
            flash={"kind": "error", "message": f"POS unavailable: {exc}"},
        )

    attendants_map: dict[str, str] = {}
    if session_attendant_id:
        attendants_map[session_attendant_id] = session_attendant_name
    for sale in raw_sales:
        aid = sale.attendant_id or ""
        if aid and aid not in attendants_map:
            attendants_map[aid] = sale.attendant_name or (aid[:8] + "…")

    if attendant_id not in attendants_map and session_attendant_id:
        attendant_id = session_attendant_id

    rate_bps = rate_by_attendant.get(attendant_id)
    rate_display = f"{rate_bps / 100:g}%" if rate_bps is not None else "—"

    paid_sales = []
    gmv_minor = 0
    estimated_minor = 0
    for sale in raw_sales:
        if (sale.attendant_id or "") != attendant_id:
            continue
        if _sale_date(sale.created_at) != day:
            continue
        if sale.status != "paid":
            continue
        gmv_minor += sale.total_minor
        owed = commission_minor(sale.total_minor, rate_bps) if rate_bps is not None else 0
        estimated_minor += owed
        paid_sales.append(
            {
                "sale_id": sale.sale_id,
                "item_name": sale.item_name or "Sale",
                "created_at": _format_when(sale.created_at),
                "total_kes": to_whole_kes(sale.total_minor),
                "commission_display": (
                    f"KES {format_kes_from_minor(owed)}" if rate_bps is not None else "—"
                ),
                "status": sale.status,
            }
        )
    paid_sales.sort(key=lambda s: s["created_at"], reverse=True)

    close_status = "not run"
    ledgered_commission = "—"
    payout_state = "—"
    payout_amount = "—"
    payments_payout_id = None
    payout_locked = False
    next_payout_period = (day + timedelta(days=1)).isoformat()
    try:
        summary = await get_commission_client().get_summary(
            tenant_id=session["tenant_id"], payout_period=day
        )
        close_status = summary.close_status or "not run"
        attendant_lines = [
            line for line in summary.ledger_lines if line.attendant_id == attendant_id
        ]
        ledger_total = sum(line.commission_minor_units for line in attendant_lines)
        if attendant_lines or summary.close_status:
            ledgered_commission = f"KES {format_kes_from_minor(ledger_total)}"
        intent = next(
            (i for i in summary.payout_intents if i.attendant_id == attendant_id),
            None,
        )
        if intent:
            payout_state = intent.state
            payout_amount = f"KES {format_kes_from_minor(intent.amount_minor_units)}"
            payments_payout_id = intent.payments_payout_id
            payout_locked = intent.state in {"submitted", "completed"}
    except CommissionUnavailableError as exc:
        close_status = f"unavailable ({exc})"

    attendants = [
        {"id": aid, "name": name}
        for aid, name in sorted(attendants_map.items(), key=lambda x: x[1].lower())
    ]
    return _render(
        request,
        "commission.html",
        attendants=attendants,
        day={
            "period": day.isoformat(),
            "attendant_id": attendant_id,
            "attendant_name": attendants_map.get(attendant_id, "Attendant"),
            "rate_display": rate_display,
            "paid_count": len(paid_sales),
            "gmv_kes": to_whole_kes(gmv_minor),
            "estimated_commission": format_kes_from_minor(estimated_minor),
            "close_status": close_status,
            "ledgered_commission": ledgered_commission,
            "payout_state": payout_state,
            "payout_amount": payout_amount,
            "payments_payout_id": payments_payout_id,
            "payout_locked": payout_locked,
            "next_payout_period": next_payout_period,
            "paid_sales": paid_sales,
        },
    )


def _flash_redirect(url: str, *, kind: str, message: str) -> RedirectResponse:
    """Redirect with a one-shot flash cookie (ASCII-only; Set-Cookie is latin-1)."""
    safe = (
        message.replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .encode("ascii", "replace")
        .decode("ascii")
    )
    response = RedirectResponse(_public_path(url), status_code=303)
    response.set_cookie(
        "tillflow_flash",
        f"{kind}|{safe[:180]}",
        max_age=30,
        httponly=True,
        samesite="lax",
        path=cookie_path(),
    )
    return response


@app.post("/commission/close")
async def commission_close(
    request: Request,
    csrf_token: str = Form(...),
    period: str = Form(...),
    attendant_id: str = Form(...),
):
    session = load_session(request)
    if not session.get("tenant_id"):
        return RedirectResponse(_public_path("/"), status_code=303)
    if not verify_csrf(request, csrf_token):
        return RedirectResponse(_public_path("/commission"), status_code=303)
    try:
        day = date.fromisoformat(period)
    except ValueError:
        day = today_eat()
    try:
        result = await get_commission_client().run_close(payout_period=day)
        message = (
            f"Close {result.get('status')} - "
            f"{result.get('ledger_lines_written', 0)} ledger lines, "
            f"{result.get('intents_enqueued', 0)} payout intents."
        )
        kind = "ok"
    except CommissionUnavailableError as exc:
        message = f"Commission unavailable: {exc}"
        kind = "error"
    return _flash_redirect(
        f"/commission?period={day.isoformat()}&attendant_id={attendant_id}",
        kind=kind,
        message=message,
    )


@app.post("/commission/payout")
async def commission_payout(
    request: Request,
    csrf_token: str = Form(...),
    period: str = Form(...),
    attendant_id: str = Form(...),
):
    session = load_session(request)
    if not session.get("tenant_id"):
        return RedirectResponse(_public_path("/"), status_code=303)
    if not verify_csrf(request, csrf_token):
        return RedirectResponse(_public_path("/commission"), status_code=303)
    try:
        day = date.fromisoformat(period)
    except ValueError:
        day = today_eat()
    try:
        result = await get_commission_client().run_payout(
            tenant_id=session["tenant_id"],
            payout_period=day,
            attendant_id=attendant_id,
        )
        amount = format_kes_from_minor(int(result.get("amount_minor_units") or 0))
        next_period = result.get("next_payout_period") or (day + timedelta(days=1)).isoformat()
        if isinstance(next_period, date):
            next_period = next_period.isoformat()
        if result.get("already_requested"):
            message = (
                f"Already paid for {day.isoformat()} (KES {amount}). "
                f"Next payout after close on {next_period}."
            )
        else:
            message = (
                f"Payout {result.get('state')} - KES {amount}. "
                f"Next payout after close on {next_period}."
            )
        kind = "ok"
    except CommissionUnavailableError as exc:
        message = f"Commission unavailable: {exc}"
        kind = "error"
    return _flash_redirect(
        f"/commission?period={day.isoformat()}&attendant_id={attendant_id}",
        kind=kind,
        message=message,
    )


PAYOUT_STATES = ("pending", "submitted", "completed", "failed")


@app.get("/payouts", response_class=HTMLResponse)
async def payouts_list(
    request: Request,
    attendant_id: str | None = None,
    state: str | None = None,
) -> HTMLResponse:
    session = load_session(request)
    if not session.get("tenant_id"):
        return RedirectResponse(_public_path("/"), status_code=303)

    attendant_id = (attendant_id or "").strip() or None
    state = (state or "").strip() or None
    if state and state not in PAYOUT_STATES:
        state = None

    attendants = []
    session_attendant_id = session.get("attendant_id")
    session_attendant_name = session.get("attendant_name") or "Attendant"
    if session_attendant_id:
        attendants.append({"id": session_attendant_id, "name": session_attendant_name})

    payout_rows = []
    error_flash = None
    try:
        raw = await get_commission_client().list_payouts(
            tenant_id=session["tenant_id"],
            attendant_id=attendant_id,
            state=state,
        )
    except CommissionUnavailableError as exc:
        error_flash = {"kind": "error", "message": f"Commission unavailable: {exc}"}
        raw = []

    name_by_id = {a["id"]: a["name"] for a in attendants}
    for row in raw:
        aid = row.attendant_id
        if aid and aid not in name_by_id:
            name_by_id[aid] = aid[:8] + "…"
            attendants.append({"id": aid, "name": name_by_id[aid]})
        payout_rows.append(
            {
                "payout_period": row.payout_period,
                "updated_at": _format_when(row.updated_at),
                "attendant_id": aid,
                "attendant_name": name_by_id.get(aid, aid[:8] + "…" if aid else "—"),
                "phone_number": row.phone_number or "—",
                "amount_kes": format_kes_from_minor(row.amount_minor_units),
                "state": row.state,
                "payments_payout_id": (
                    (row.payments_payout_id[:8] + "…")
                    if row.payments_payout_id and len(row.payments_payout_id) > 12
                    else (row.payments_payout_id or "—")
                ),
            }
        )

    return _render(
        request,
        "payouts.html",
        flash=error_flash,
        attendants=attendants,
        states=PAYOUT_STATES,
        filters={"attendant_id": attendant_id or "", "state": state or ""},
        payouts=payout_rows,
    )


@app.get("/sales/{sale_id}", response_class=HTMLResponse)
async def sale_status(request: Request, sale_id: str) -> HTMLResponse:
    session = load_session(request)
    if not session.get("tenant_id"):
        return RedirectResponse(_public_path("/"), status_code=303)
    try:
        sale = await get_pos_client().get_sale(
            tenant_id=session["tenant_id"], sale_id=sale_id
        )
    except PosUnavailableError as exc:
        return _render(
            request,
            "home.html",
            status_code=502,
            flash={"kind": "error", "message": f"POS unavailable: {exc}"},
        )
    return _render(
        request,
        "sale_status.html",
        sale={
            "sale_id": sale.sale_id,
            "status": sale.status,
            "total_kes": to_whole_kes(sale.total_minor),
            "payment_id": sale.payment_id,
            "payment_state": sale.payment_state,
        },
    )
