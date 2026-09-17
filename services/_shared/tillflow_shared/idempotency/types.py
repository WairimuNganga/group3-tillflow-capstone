from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class IdempotencyStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True)
class IdempotencyRecord:
    service: str
    tenant_id: str
    key: str
    status: IdempotencyStatus
    status_code: int | None
    response_body: dict[str, Any] | list[Any] | None
    created_at: datetime
    expires_at: datetime

    @property
    def is_replay(self) -> bool:
        return self.status is IdempotencyStatus.COMPLETED
