"""Demo UI clock — East Africa Time (GMT+3 / Africa/Nairobi)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

EAT = ZoneInfo("Africa/Nairobi")


def today_eat() -> date:
    return datetime.now(EAT).date()


def format_when_eat(created_at: str | None) -> str:
    """Format an ISO timestamp for display in GMT+3."""
    if not created_at:
        return "—"
    raw = created_at.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return created_at.replace("T", " ")[:19] or "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    local = dt.astimezone(EAT)
    return local.strftime("%Y-%m-%d %H:%M:%S")


def sale_date_eat(created_at: str | None) -> date | None:
    if not created_at:
        return None
    raw = created_at.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        if len(created_at) >= 10:
            try:
                return date.fromisoformat(created_at[:10])
            except ValueError:
                return None
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(EAT).date()
