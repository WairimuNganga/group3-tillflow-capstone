from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from payments.domain.state import is_payment_terminal
from payments.outbox import InMemoryOutbox
from payments.repositories.memory import InMemoryPaymentRepository
from payments.repositories.memory_settlement import InMemoryLedgerRepository
from payments.repositories.postgres import PostgresPaymentRepository
from payments.repositories.postgres_settlement import PostgresLedgerRepository
from payments.services.settlement import SettlementResult, settle_failure, settle_success
from tillflow_shared.mpesa.adapter import MpesaAdapter
from tillflow_shared.mpesa.types import TransactionQueryRequest
from tillflow_shared.otel import business_counter
from tillflow_shared.otel.middleware import traced

reconcile_processed = business_counter(
    "payments_reconciliation_processed_total",
    "Reconciliation worker outcomes.",
)

PaymentRepository = InMemoryPaymentRepository | PostgresPaymentRepository
LedgerRepository = InMemoryLedgerRepository | PostgresLedgerRepository


@dataclass(frozen=True)
class ReconcileResult:
    reason: str
    payment_id: UUID
    state: str
    ledger_written: bool = False


class ReconciliationService:
    """Resolve stuck payments via STK Query ([ADR-004])."""

    def __init__(
        self,
        *,
        payments: PaymentRepository,
        ledger: LedgerRepository,
        adapter: MpesaAdapter,
        outbox: InMemoryOutbox,
    ) -> None:
        self._payments = payments
        self._ledger = ledger
        self._adapter = adapter
        self._outbox = outbox

    async def reconcile_payment(self, payment_id: UUID) -> ReconcileResult:
        with traced("payments.reconcile", payment_id=str(payment_id)):
            return await self._reconcile(payment_id)

    async def process_outbox(self) -> list[ReconcileResult]:
        """Drain unpublished reconciliation jobs (local stand-in for SQS worker)."""
        results: list[ReconcileResult] = []
        for message in await self._outbox.list_unpublished():
            result = await self.reconcile_payment(message.payment_id)
            await self._outbox.mark_published(message.id)
            results.append(result)
        return results

    async def _reconcile(self, payment_id: UUID) -> ReconcileResult:
        payment = await self._payments.get_by_id(payment_id)
        if payment is None:
            reconcile_processed.add(1, {"result": "not_found"})
            return ReconcileResult(
                reason="not_found",
                payment_id=payment_id,
                state="unknown",
            )

        if is_payment_terminal(payment.payment_state):
            reconcile_processed.add(1, {"result": "already_terminal"})
            return ReconcileResult(
                reason="already_terminal",
                payment_id=payment.id,
                state=payment.state,
            )

        if not payment.checkout_request_id:
            reconcile_processed.add(1, {"result": "missing_checkout_id"})
            return ReconcileResult(
                reason="missing_checkout_id",
                payment_id=payment.id,
                state=payment.state,
            )

        query = await self._adapter.query_transaction_status(
            TransactionQueryRequest(
                tenant_id=payment.tenant_id,
                idempotency_key=payment.idempotency_key,
                checkout_request_id=payment.checkout_request_id,
            )
        )

        settled: SettlementResult
        if query.result_code == "0":
            settled = await settle_success(
                payments=self._payments,
                ledger=self._ledger,
                payment=payment,
                amount_whole=query.amount_whole_kes,
                receipt=query.mpesa_receipt_number,
            )
        else:
            settled = await settle_failure(
                payments=self._payments,
                payment=payment,
                result_desc=query.result_desc,
            )

        reconcile_processed.add(1, {"result": settled.reason})
        return ReconcileResult(
            reason=settled.reason,
            payment_id=settled.payment.id,
            state=settled.payment.state,
            ledger_written=settled.ledger_written,
        )
