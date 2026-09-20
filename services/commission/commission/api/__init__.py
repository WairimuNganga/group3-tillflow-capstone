# Re-export router from the close module file — keep a single router module.
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from commission.api.schemas import (
    AttendantPayoutRequest,
    AttendantPayoutResponse,
    CloseRequest,
    CloseResponse,
    LedgerLineSummary,
    PayoutIntentSummary,
    PayoutListItem,
    PayoutListResponse,
    PeriodSummaryResponse,
)
from commission.deps import (
    get_close_service,
    get_db_session,
    get_memory_close_runs,
    get_memory_intents,
    get_memory_ledger,
    get_payout_service,
)
from commission.repositories.postgres import (
    PostgresCloseRunRepository,
    PostgresLedgerRepository,
    PostgresPayoutIntentRepository,
)
from commission.services.close_service import CloseService
from commission.services.payout_service import PayoutService

router = APIRouter(prefix="/internal", tags=["internal"])


def _iso(dt) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@router.get("/summary", response_model=PeriodSummaryResponse)
async def period_summary(
    payout_period: date,
    tenant_id: str,
    session: AsyncSession | None = Depends(get_db_session),
) -> PeriodSummaryResponse:
    """Read-only view of ledger + payout intents for a tenant/period (demo UI)."""
    if session is None:
        close_runs = get_memory_close_runs()
        ledger = get_memory_ledger()
        intents = get_memory_intents()
    else:
        close_runs = PostgresCloseRunRepository(session)
        ledger = PostgresLedgerRepository(session)
        intents = PostgresPayoutIntentRepository(session)

    run = await close_runs.get_by_period(payout_period)
    lines = [
        line
        for line in await ledger.list_for_period(payout_period)
        if line.tenant_id == tenant_id
    ]
    payouts = [
        intent
        for intent in await intents.list_for_period(payout_period)
        if intent.tenant_id == tenant_id
    ]
    return PeriodSummaryResponse(
        payout_period=payout_period,
        tenant_id=tenant_id,
        close_status=run.status if run else None,
        ledger_lines=[
            LedgerLineSummary(
                sale_id=str(line.sale_id),
                attendant_id=line.attendant_id,
                sale_amount_minor_units=line.sale_amount_minor_units,
                rate_bps=line.rate_bps,
                commission_minor_units=line.commission_minor_units,
            )
            for line in lines
        ],
        ledger_commission_minor_units=sum(line.commission_minor_units for line in lines),
        payout_intents=[
            PayoutIntentSummary(
                attendant_id=intent.attendant_id,
                state=intent.state,
                amount_minor_units=intent.amount_minor_units,
                payments_payout_id=(
                    str(intent.payments_payout_id) if intent.payments_payout_id else None
                ),
            )
            for intent in payouts
        ],
    )


@router.get("/payouts", response_model=PayoutListResponse)
async def list_payouts(
    tenant_id: str,
    attendant_id: str | None = None,
    state: str | None = None,
    session: AsyncSession | None = Depends(get_db_session),
) -> PayoutListResponse:
    """List payout intents for a tenant (demo tracking table)."""
    attendant_id = (attendant_id or "").strip() or None
    state = (state or "").strip() or None
    intents = (
        get_memory_intents()
        if session is None
        else PostgresPayoutIntentRepository(session)
    )

    rows = await intents.list_for_tenant(
        tenant_id, attendant_id=attendant_id, state=state
    )
    return PayoutListResponse(
        tenant_id=tenant_id,
        payouts=[
            PayoutListItem(
                tenant_id=intent.tenant_id,
                payout_period=intent.payout_period,
                attendant_id=intent.attendant_id,
                phone_number=intent.phone_number,
                amount_minor_units=intent.amount_minor_units,
                state=intent.state,
                payments_payout_id=(
                    str(intent.payments_payout_id) if intent.payments_payout_id else None
                ),
                failure_reason=intent.failure_reason,
                created_at=_iso(intent.created_at),
                updated_at=_iso(intent.updated_at),
            )
            for intent in rows
        ],
    )


@router.post("/close", response_model=CloseResponse)
async def trigger_close(
    body: CloseRequest,
    service: CloseService = Depends(get_close_service),
) -> CloseResponse:
    result = await service.run(body.payout_period)
    return CloseResponse(
        payout_period=result.payout_period,
        status=result.status,
        ledger_lines_written=result.ledger_lines_written,
        intents_enqueued=result.intents_enqueued,
        skipped_mismatch=result.skipped_mismatch,
        already_completed=result.already_completed,
    )


@router.post("/payout", response_model=AttendantPayoutResponse)
async def trigger_payout(
    body: AttendantPayoutRequest,
    service: PayoutService = Depends(get_payout_service),
) -> AttendantPayoutResponse:
    try:
        result = await service.submit(
            tenant_id=body.tenant_id,
            payout_period=body.payout_period,
            attendant_id=body.attendant_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    intent = result.intent
    return AttendantPayoutResponse(
        tenant_id=intent.tenant_id,
        payout_period=intent.payout_period,
        attendant_id=intent.attendant_id,
        state=intent.state,
        amount_minor_units=intent.amount_minor_units,
        payments_payout_id=(
            str(intent.payments_payout_id) if intent.payments_payout_id else None
        ),
        already_requested=result.already_requested,
        next_payout_period=result.next_payout_period,
    )


__all__ = ["router"]
