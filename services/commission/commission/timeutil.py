"""Business calendar for commission close / payout periods.

TillFlow payout days are East Africa Time (GMT+3, Africa/Nairobi — no DST).
Timestamps stay stored in UTC; only calendar-day bucketing uses EAT.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

EAT = ZoneInfo("Africa/Nairobi")
BUSINESS_TZ_NAME = "Africa/Nairobi"  # GMT+3


def now_eat() -> datetime:
    return datetime.now(EAT)


def today_eat() -> date:
    return now_eat().date()


def to_eat_date(dt: datetime) -> date:
    """Calendar date of ``dt`` in EAT (assumes UTC if naive)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(EAT).date()
