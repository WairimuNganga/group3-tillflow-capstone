import pytest

from tillflow_shared.money.kes import from_whole_kes, to_whole_kes


@pytest.mark.parametrize(
    ("minor_units", "whole_kes"),
    [
        (0, 0),
        (1, 0),
        (49, 0),
        (50, 1),
        (99, 1),
        (100, 1),
        (149, 1),
        (150, 2),
        (199, 2),
        (200, 2),
        (10_000, 100),
    ],
)
def test_to_whole_kes_rounds_half_up(minor_units: int, whole_kes: int) -> None:
    assert to_whole_kes(minor_units) == whole_kes


@pytest.mark.parametrize("whole_kes", [0, 1, 10, 999])
def test_from_whole_kes_reconstructs_minor_units(whole_kes: int) -> None:
    assert from_whole_kes(whole_kes) == whole_kes * 100


def test_round_trip_for_representable_amounts() -> None:
    for whole in range(0, 500):
        assert to_whole_kes(from_whole_kes(whole)) == whole


def test_negative_minor_units_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        to_whole_kes(-1)


def test_negative_whole_kes_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        from_whole_kes(-1)
