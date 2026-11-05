import re
from datetime import date

from rentsmart.contracts import Kind, MarketSpeed
from rentsmart.core.facts import match_confidence
from rentsmart.core.freshness import flag_stale
from rentsmart.core.market import build_market
from rentsmart.core.pricing import build_comps, build_recent_support, build_rent_estimate
from rentsmart.core.scenarios import build_scenarios
from rentsmart.providers.base import CompRecord, MarketRecord, RentEstimateRecord

TODAY = date(2026, 10, 20)


def _comps(n: int) -> list[CompRecord]:
    return [CompRecord(address=f"{i} Test St", price=2000, status="active") for i in range(n)]


def test_match_confidence_handles_abbreviations() -> None:
    assert (
        match_confidence(
            "123 Example Street, Gainesville FL", "123 Example St, Gainesville, FL 32601"
        )
        == 1.0
    )


def test_match_confidence_drops_for_different_street() -> None:
    assert match_confidence("9 Other Rd, Gainesville FL", "123 Example St, Gainesville, FL") < 0.8


def test_rent_estimate_withheld_with_too_few_comps() -> None:
    record = RentEstimateRecord(rent=2000, low=1800, high=2200, comps=_comps(2))
    assert build_rent_estimate(record, "X", TODAY) is None


def test_rent_estimate_states_asking_basis() -> None:
    record = RentEstimateRecord(rent=2000, low=1800, high=2200, comps=_comps(3))
    rent = build_rent_estimate(record, "X", TODAY)
    assert rent is not None
    assert rent.kind == Kind.ESTIMATED
    assert any("asking prices" in lim and "not signed lease" in lim for lim in rent.limitations)


def test_vendor_point_outside_range_is_omitted_not_fatal() -> None:
    record = RentEstimateRecord(rent=2500, low=1800, high=2200, comps=_comps(3))
    rent = build_rent_estimate(record, "X", TODAY)
    assert rent is not None and rent.value is None


def test_market_trend_rising() -> None:
    history = [
        (date(2026, m, 1), v)
        for m, v in zip(range(5, 11), [24.0, 25.0, 26.0, 28.0, 30.0, 31.0], strict=True)
    ]
    market = build_market(
        MarketRecord(zip_code="1", median_days_on_market=31, history=history), "X", TODAY
    )
    assert market.trend is not None and market.trend.value == "rising"


def test_market_trend_needs_history() -> None:
    market = build_market(MarketRecord(zip_code="1", history=[(TODAY, 30.0)]), "X", TODAY)
    assert market.trend is None


def test_scenarios_never_state_a_day_count() -> None:
    record = RentEstimateRecord(rent=2000, low=1800, high=2200, comps=_comps(3))
    market = build_market(MarketRecord(zip_code="1", median_days_on_market=31), "X", TODAY)
    scenarios = build_scenarios(build_rent_estimate(record, "X", TODAY), market)
    assert [s.value.label for s in scenarios if s.value] == ["low", "mid", "high"]
    for s in scenarios:
        assert s.value is not None
        assert not re.search(r"\d", s.value.speed)


def test_no_scenarios_without_range() -> None:
    assert build_scenarios(None, MarketSpeed(zip_code="1")) == []


def _dated(price: float, seen: date, status: str = "inactive") -> CompRecord:
    return CompRecord(
        address=f"{price:g} Test St",
        price=price,
        status=status,
        last_seen_date=seen,
        distance_miles=0.5,
    )


def test_comps_sorted_newest_first() -> None:
    record = RentEstimateRecord(
        comps=[
            _dated(1, date(2026, 1, 1)),
            _dated(2, date(2026, 10, 1)),
            _dated(3, date(2026, 5, 1)),
        ]
    )
    assert [c.value.price for c in build_comps(record, "X", TODAY) if c.value] == [2, 3, 1]


def test_active_but_unseen_comp_is_unconfirmed() -> None:
    record = RentEstimateRecord(
        comps=[
            _dated(1, date(2026, 10, 1), status="active"),  # 19 days unseen
            _dated(2, date(2026, 10, 15), status="active"),  # 5 days
            _dated(3, date(2026, 8, 1), status="inactive"),  # old, but delisted: not unconfirmed
        ]
    )
    flags = {c.value.price: c.value.unconfirmed for c in build_comps(record, "X", TODAY) if c.value}
    assert flags == {1: True, 2: False, 3: False}


def test_recent_support_uses_only_fresh_comps() -> None:
    record = RentEstimateRecord(
        comps=[
            _dated(2000, date(2026, 10, 1)),
            _dated(2100, date(2026, 9, 1)),
            _dated(2200, date(2026, 8, 1)),
            _dated(3000, date(2026, 1, 1)),  # stale
        ]
    )
    comps = [flag_stale(c, TODAY, 90) for c in build_comps(record, "X", TODAY)]
    recent = build_recent_support(comps, 90, TODAY)
    assert recent is not None
    assert (recent.value, recent.low, recent.high) == (2100, 2000, 2200)
    assert recent.kind == Kind.COMPUTED
    assert "3 of 4 comps" in recent.evidence[0]


def test_recent_support_needs_enough_fresh_comps() -> None:
    record = RentEstimateRecord(
        comps=[_dated(2000, date(2026, 10, 1)), _dated(2100, date(2026, 1, 1))]
    )
    comps = [flag_stale(c, TODAY, 90) for c in build_comps(record, "X", TODAY)]
    assert build_recent_support(comps, 90, TODAY) is None
