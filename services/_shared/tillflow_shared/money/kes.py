"""Minor-units ↔ whole-shilling conversion ([ADR-004]).

This module is the **only** place in the codebase allowed to convert between TillFlow's
internal minor units (1 KES = 100 units) and M-Pesa's whole-shilling amounts.
"""


def to_whole_kes(minor_units: int) -> int:
    """Round minor units to the nearest whole shilling (half-up)."""
    if minor_units < 0:
        raise ValueError("minor_units must be non-negative")
    return (minor_units + 50) // 100


def from_whole_kes(whole_kes: int) -> int:
    """Reconstruct minor units from a whole-shilling amount."""
    if whole_kes < 0:
        raise ValueError("whole_kes must be non-negative")
    return whole_kes * 100
