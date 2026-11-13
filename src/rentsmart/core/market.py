"""Zip-level market speed. Never a property-level day count (§5.4 rule 3)."""

from datetime import date
from typing import Literal

from rentsmart.contracts import Envelope, Kind, MarketSpeed
from rentsmart.providers.base import MarketRecord, RentIndexRecord

ZIP_ONLY = "Zip-level figure; not specific to this property."
TREND_THRESHOLD = 0.10
MIN_TREND_POINTS = 3

Trend = Literal["rising", "falling", "flat"]


def _trend(history: list[tuple[date, float]]) -> Trend | None:
    if len(history) < MIN_TREND_POINTS:
        return None
    early = sum(v for _, v in history[:2]) / 2
    late = sum(v for _, v in history[-2:]) / 2
    if early <= 0:
        return None
    change = (late - early) / early
    if change > TREND_THRESHOLD:
        return "rising"
    if change < -TREND_THRESHOLD:
        return "falling"
    return "flat"


def build_market(record: MarketRecord, provider: str, today: date) -> MarketSpeed:
    as_of = record.as_of or today
    median = None
    if record.median_days_on_market is not None:
        median = Envelope[float](
            value=record.median_days_on_market,
            kind=Kind.FETCHED,
            source=f"{provider} market statistics",
            as_of=as_of,
            evidence=[f"Zip {record.zip_code}, rental listings"],
            limitations=[ZIP_ONLY, "Days on market for listings, not time to signed lease."],
        )
    trend = None
    direction = _trend(record.history)
    if direction is not None:
        trend = Envelope[Trend](
            value=direction,
            kind=Kind.COMPUTED,
            source="computed",
            as_of=as_of,
            evidence=[f"{month:%Y-%m}: median {v:g}" for month, v in record.history],
            limitations=[ZIP_ONLY, "Compares the first two and last two months of history."],
        )
    return MarketSpeed(zip_code=record.zip_code, median_days_on_market=median, trend=trend)


def build_rent_change(record: RentIndexRecord | None) -> Envelope[float] | None:
    """Zip rent index change over the 12 months to its latest month. Trend context, not a price."""
    if record is None or not record.history:
        return None
    month, latest = record.history[-1]
    year_ago = {(m.year, m.month): v for m, v in record.history}.get((month.year - 1, month.month))
    if not year_ago:
        return None
    return Envelope[float](
        value=round(latest / year_ago - 1, 3),
        kind=Kind.COMPUTED,
        source=f"computed from {record.source}",
        as_of=month,
        evidence=[
            f"{month:%Y-%m}: ${latest:,.0f}",
            f"{month.year - 1}-{month:%m}: ${year_ago:,.0f}",
        ],
        limitations=[
            "Zip-level rent index; not a price for this property.",
            *record.limitations,
        ],
    )
