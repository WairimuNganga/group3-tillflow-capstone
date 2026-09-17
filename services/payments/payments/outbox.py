from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass
class OutboxMessage:
    id: UUID
    payment_id: UUID
    kind: str
    created_at: datetime
    published: bool = False


class InMemoryOutbox:
    """Transactional-outbox stand-in until Postgres outbox + SQS land."""

    def __init__(self) -> None:
        self._messages: dict[UUID, OutboxMessage] = {}
        self._lock = asyncio.Lock()

    async def enqueue_reconciliation(self, payment_id: UUID) -> OutboxMessage:
        async with self._lock:
            # Idempotent: one pending reconciliation job per payment.
            for msg in self._messages.values():
                if (
                    msg.payment_id == payment_id
                    and msg.kind == "payment.reconcile"
                    and not msg.published
                ):
                    return msg
            message = OutboxMessage(
                id=uuid4(),
                payment_id=payment_id,
                kind="payment.reconcile",
                created_at=datetime.now(UTC),
            )
            self._messages[message.id] = message
            return message

    async def list_unpublished(self) -> list[OutboxMessage]:
        async with self._lock:
            return [m for m in self._messages.values() if not m.published]

    async def mark_published(self, message_id: UUID) -> None:
        async with self._lock:
            msg = self._messages[message_id]
            msg.published = True

    def clear(self) -> None:
        self._messages.clear()
