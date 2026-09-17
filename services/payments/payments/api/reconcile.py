from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from payments.deps import get_reconciliation_service
from payments.services.reconciliation_service import ReconciliationService

router = APIRouter(prefix="/payments", tags=["reconciliation"])


@router.post("/reconcile/outbox")
async def process_reconciliation_outbox(
    service: ReconciliationService = Depends(get_reconciliation_service),
) -> JSONResponse:
    """Drain pending reconciliation jobs (local / test stand-in for the SQS worker)."""
    results = await service.process_outbox()
    return JSONResponse(
        status_code=200,
        content={
            "processed": len(results),
            "results": [
                {
                    "payment_id": str(r.payment_id),
                    "state": r.state,
                    "reason": r.reason,
                    "ledger_written": r.ledger_written,
                }
                for r in results
            ],
        },
    )


@router.post("/reconcile/{payment_id}")
async def reconcile_one(
    payment_id: UUID,
    service: ReconciliationService = Depends(get_reconciliation_service),
) -> JSONResponse:
    """Reconcile a single payment via STK Query."""
    result = await service.reconcile_payment(payment_id)
    return JSONResponse(
        status_code=200,
        content={
            "payment_id": str(result.payment_id),
            "state": result.state,
            "reason": result.reason,
            "ledger_written": result.ledger_written,
        },
    )
