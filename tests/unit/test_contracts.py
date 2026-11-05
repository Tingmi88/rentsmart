from datetime import date

import pytest
from pydantic import ValidationError

from rentsmart.contracts import (
    NEEDS_LIMITATION,
    AmbiguousAddress,
    Envelope,
    ExitCode,
    Kind,
)

AS_OF = date(2026, 10, 1)


def test_valid_envelope() -> None:
    env = Envelope[float](
        value=2000,
        low=1800,
        high=2200,
        kind=Kind.ESTIMATED,
        source="x",
        as_of=AS_OF,
        limitations=["asking prices"],
    )
    assert env.low == 1800


@pytest.mark.parametrize(
    ("value", "low", "high"),
    [(2000, 2100, 2200), (2300, 1800, 2200), (None, 2200, 1800)],
)
def test_low_value_high_ordering_enforced(value: float | None, low: float, high: float) -> None:
    with pytest.raises(ValidationError):
        Envelope[float](value=value, low=low, high=high, kind=Kind.FETCHED, source="x", as_of=AS_OF)


def test_value_on_range_edge_is_allowed() -> None:
    Envelope[float](value=1800, low=1800, high=1800, kind=Kind.FETCHED, source="x", as_of=AS_OF)


def test_source_required() -> None:
    with pytest.raises(ValidationError):
        Envelope[float](value=1, kind=Kind.FETCHED, source="", as_of=AS_OF)


def test_as_of_required() -> None:
    with pytest.raises(ValidationError):
        Envelope[float].model_validate({"value": 1, "kind": "fetched", "source": "x"})


@pytest.mark.parametrize("kind", sorted(NEEDS_LIMITATION))
def test_uncertain_kinds_need_a_limitation(kind: Kind) -> None:
    with pytest.raises(ValidationError, match="limitation"):
        Envelope[str](value="x", kind=kind, source="x", as_of=AS_OF)


@pytest.mark.parametrize("kind", [Kind.FETCHED, Kind.COMPUTED, Kind.USER_SUPPLIED])
def test_certain_kinds_need_no_limitation(kind: Kind) -> None:
    Envelope[str](value="x", kind=kind, source="x", as_of=AS_OF)


def test_needs_limitation_matches_spec() -> None:
    assert {Kind.ESTIMATED, Kind.MODELED, Kind.PREDICTED, Kind.ADVISED} == NEEDS_LIMITATION


def test_exit_codes_are_distinct() -> None:
    codes = [c.value for c in ExitCode]
    assert len(codes) == len(set(codes))
    assert 1 not in codes and 2 not in codes


def test_ambiguous_lists_candidates() -> None:
    err = AmbiguousAddress("500 Sample Blvd", ["Apt 1", "Apt 2"])
    assert err.to_dict()["candidates"] == ["Apt 1", "Apt 2"]
    assert "Apt 2" in err.message
