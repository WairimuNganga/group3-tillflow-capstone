from __future__ import annotations

import asyncio
import logging
from datetime import date

from typing import Any

from commission.services.close_service import CloseService
from commission.services.payout_service import PayoutService
from commission.timeutil import today_eat
from commission.worker.queue import PayoutQueue

_log = logging.getLogger(__name__)


class WorkerLoop:
    """Dispatch SQS / in-memory payout queue messages."""

    def __init__(
        self,
        *,
        queue: PayoutQueue,
        close_service: CloseService,
        payout_service: PayoutService,
    ) -> None:
        self._queue = queue
        self._close = close_service
        self._payout = payout_service
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        _log.info("commission worker started")
        while not self._stop.is_set():
            try:
                messages = await self._queue.receive(max_messages=5, wait_seconds=5)
            except Exception:
                _log.exception("queue receive failed")
                await asyncio.sleep(2)
                continue
            if not messages:
                await asyncio.sleep(0.1)
                continue
            for msg in messages:
                try:
                    await self.handle(msg.body)
                    await self._queue.delete(msg.receipt_handle)
                except Exception:
                    _log.exception("message handling failed body=%s", msg.body)
                    # Leave message for retry / DLQ via SQS redrive.

    async def handle(self, body: dict[str, Any]) -> None:
        event = body.get("event") or body.get("detail-type")
        # EventBridge schedule payload uses detail.event
        if isinstance(body.get("detail"), dict):
            event = body["detail"].get("event", event)

        if event in {
            "commission.daily_close.requested",
            "Scheduled Event",
        } or body.get("event") == "commission.daily_close.requested":
            period_raw = body.get("payout_period")
            if not period_raw and isinstance(body.get("detail"), dict):
                period_raw = body["detail"].get("payout_period")
            payout_period = (
                date.fromisoformat(str(period_raw))
                if period_raw
                else today_eat()
            )
            # Prefer yesterday EAT close for nightly schedule when period omitted —
            # for local/tests the body should include payout_period.
            await self._close.run(payout_period)
            return

        if event == "commission.attendant_payout.requested":
            await self._payout.submit(
                tenant_id=str(body["tenant_id"]),
                payout_period=date.fromisoformat(str(body["payout_period"])),
                attendant_id=str(body["attendant_id"]),
            )
            return

        _log.warning("unknown queue event: %s", event)
