"""Rent estimate, rental comps, and property tax sections."""

from datetime import date
from statistics import median

from rentsmart.contracts import Comp, Envelope, Kind
from rentsmart.providers.base import CompRecord, RentEstimateRecord, TaxRecord

MIN_COMPS = 3
UNCONFIRMED_AFTER_DAYS = 14
ASKING_BASIS = "Based on asking prices from rental listings, not signed lease prices."
NO_MLS = "Does not include MLS listings; your agent may see newer listings."


def _comp(record: CompRecord, provider: str, today: date) -> Envelope[Comp]:
    as_of = record.last_seen_date or record.listed_date or today
    unseen_days = (today - as_of).days
    unconfirmed = record.status == "active" and unseen_days > UNCONFIRMED_AFTER_DAYS
    limitations = ["Asking price, not a signed lease price."]
    if unconfirmed:
        limitations.append(
            f"Marked active but not seen for {unseen_days} days; may have rented or been withdrawn."
        )
    return Envelope[Comp](
        value=Comp(**record.model_dump(), basis="asking", unconfirmed=unconfirmed),
        kind=Kind.FETCHED,
        source=f"{provider} rental listings",
        as_of=as_of,
        evidence=[f"Listing status: {record.status}"],
        limitations=limitations,
    )


def build_comps(record: RentEstimateRecord, provider: str, today: date) -> list[Envelope[Comp]]:
    """Newest first, so the comps that best reflect today's market lead."""
    comps = [_comp(c, provider, today) for c in record.comps]
    return sorted(comps, key=lambda c: c.as_of, reverse=True)


def build_recent_support(
    comps: list[Envelope[Comp]], window_days: int, today: date
) -> Envelope[float] | None:
    """Median asking price of the comps not flagged stale. Expects comps already flagged."""
    recent = [c for c in comps if not c.stale and c.value is not None]
    if len(recent) < MIN_COMPS:
        return None
    prices = [c.value.price for c in recent if c.value is not None]
    return Envelope[float](
        value=median(prices),
        low=min(prices),
        high=max(prices),
        kind=Kind.COMPUTED,
        source="computed",
        as_of=max((c.as_of for c in recent), default=today),
        evidence=[
            f"{len(recent)} of {len(comps)} comps seen in the last {window_days} days",
            "Asking prices: " + ", ".join(f"${p:,.0f}" for p in sorted(prices)),
        ],
        limitations=[
            ASKING_BASIS,
            "Plain median; not adjusted for size, distance, or condition.",
        ],
    )


def has_enough_comps(record: RentEstimateRecord) -> bool:
    return len(record.comps) >= MIN_COMPS


def build_rent_estimate(
    record: RentEstimateRecord, provider: str, today: date
) -> Envelope[float] | None:
    """Return None when no reliable range is possible (too few comps or no vendor range)."""
    if not has_enough_comps(record) or record.low is None or record.high is None:
        return None
    low, high = sorted((record.low, record.high))
    limitations = [
        ASKING_BASIS,
        NO_MLS,
        "Does not account for condition, upgrades, furnishings, or lease terms "
        "beyond the facts listed.",
    ]
    value = record.rent
    if value is not None and not low <= value <= high:
        value = None
        limitations.append("Vendor point estimate fell outside its own range and was omitted.")
    return Envelope[float](
        value=value,
        low=low,
        high=high,
        kind=Kind.ESTIMATED,
        source=f"{provider} rent AVM",
        as_of=record.as_of or today,
        evidence=[f"{c.address}: ${c.price:,.0f}/mo asking ({c.status})" for c in record.comps],
        limitations=limitations,
    )


def build_tax(record: TaxRecord | None, provider: str, today: date) -> Envelope[float] | None:
    if record is None:
        return None
    evidence = [f"Tax year {record.year}"]
    if record.assessed_value is not None:
        evidence.append(f"Assessed value ${record.assessed_value:,.0f}")
    return Envelope[float](
        value=record.amount,
        kind=Kind.FETCHED,
        source=f"{provider} tax record",
        as_of=min(date(record.year, 12, 31), today),
        evidence=evidence,
        limitations=[
            "Most recent bill on record; the current year may differ.",
            "An owner cost that lowers net rental income; it does not set market rent.",
        ],
    )
