from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from payments.domain.models import Payment, PaymentLedgerEntry
from payments.domain.state import PaymentState, assert_payment_transition
from payments.repositories.memory import InMemoryPaymentRepository
from payments.repositories.memory_settlement import InMemoryLedgerRepository
from payments.repositories.postgres import PostgresPaymentRepository
from payments.repositories.postgres_settlement import PostgresLedgerRepository
from tillflow_shared.money import from_whole_kes

PaymentRepository = InMemoryPaymentRepository | PostgresPaymentRepository
LedgerRepository = InMemoryLedgerRepository | PostgresLedgerRepository

LEDGER_CHARGE_CONFIRMED = "charge_confirmed"


@dataclass(frozen=True)
class SettlementResult:
    reason: str
    payment: Payment
    ledger_written: bool = False


async def settle_success(
    *,
    payments: PaymentRepository,
    ledger: LedgerRepository,
    payment: Payment,
    amount_whole: int | None,
    receipt: str | None,
) -> SettlementResult:
    """Apply a successful provider result (callback or STK Query)."""
    current = payment.payment_state
    if current is PaymentState.PAID:
        return SettlementResult(reason="already_paid", payment=payment)

    if amount_whole is not None and amount_whole != payment.amount_whole_kes:
        return SettlementResult(reason="amount_mismatch", payment=payment)

    assert_payment_transition(current, PaymentState.PAID)
    now = datetime.now(UTC)
    payment.state = PaymentState.PAID.value
    payment.mpesa_receipt_number = receipt
    payment.settled_at = now
    payment.updated_at = now
    payment = await payments.update(payment)

    ledger_written = False
    if await ledger.count_for_payment(payment.id, LEDGER_CHARGE_CONFIRMED) == 0:
        await ledger.append(
            PaymentLedgerEntry(
                tenant_id=payment.tenant_id,
                payment_id=payment.id,
                payout_id=None,
                entry_type=LEDGER_CHARGE_CONFIRMED,
                amount_minor_units=from_whole_kes(payment.amount_whole_kes),
                created_at=now,
            )
        )
        ledger_written = True

    return SettlementResult(
        reason="settled_paid",
        payment=payment,
        ledger_written=ledger_written,
    )


async def settle_failure(
    *,
    payments: PaymentRepository,
    payment: Payment,
    result_desc: Any,
) -> SettlementResult:
    """Apply a failed provider result (callback or STK Query)."""
    current = payment.payment_state
    if current is PaymentState.PAID:
        return SettlementResult(reason="ignored_failure_after_paid", payment=payment)
    if current is PaymentState.FAILED:
        return SettlementResult(reason="already_failed", payment=payment)

    assert_payment_transition(current, PaymentState.FAILED)
    payment.state = PaymentState.FAILED.value
    payment.failure_reason = str(result_desc) if result_desc is not None else "stk_failed"
    payment.updated_at = datetime.now(UTC)
    payment = await payments.update(payment)
    return SettlementResult(reason="settled_failed", payment=payment)
