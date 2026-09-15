from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from payments.deps import get_callback_service
from payments.services.callback_service import CallbackAuthError, CallbackService
from tillflow_shared.otel.middleware import traced

router = APIRouter(prefix="/callbacks/mpesa", tags=["callbacks"])


@router.post("/{callback_secret}")
async def mpesa_stk_callback(
    callback_secret: str,
    payload: dict[str, Any],
    service: CallbackService = Depends(get_callback_service),
) -> JSONResponse:
    """Public Daraja STK callback endpoint.

    Authenticity is the unguessable path secret ([ADR-007]). Processing is
    idempotent and order-independent ([ADR-004]).
    """
    with traced("payments.callback_http"):
        try:
            result = await service.handle(callback_secret=callback_secret, payload=payload)
        except CallbackAuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "accepted": result.accepted,
            "reason": result.reason,
            "payment_id": str(result.payment_id) if result.payment_id else None,
            "state": result.state,
            "ledger_written": result.ledger_written,
        },
    )
