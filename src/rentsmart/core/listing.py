"""The owner's current listing, checked against the evidence in the brief."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from rentsmart.contracts import Comp, Envelope, Kind, ListingCheck, MarketSpeed

OWNER_SOURCE = "owner (CLI flag)"


class CurrentListing(BaseModel):
    asking_rent: float = Field(gt=0)
    listed_date: date | None = None


Position = Literal["below range", "lower half", "upper half", "above range"]


def _range_position(asking: float, rent: Envelope[float], today: date) -> Envelope[Position] | None:
    if rent.low is None or rent.high is None:
        return None
    low, high = rent.low, rent.high
    label: Position
    if asking < low:
        label, detail = "below range", f"${low - asking:,.0f} below the range"
    elif asking > high:
        label, detail = "above range", f"${asking - high:,.0f} above the range"
    else:
        share = (asking - low) / (high - low) if high > low else 0.5
        label = "lower half" if share < 0.5 else "upper half"
        detail = f"{share:.0%} of the way from ${low:,.0f} to ${high:,.0f}"
    return Envelope[Position](
        value=label,
        kind=Kind.COMPUTED,
        source="computed",
        as_of=today,
        evidence=[f"Asking ${asking:,.0f} is {detail}"],
        limitations=["Range is the vendor's estimate from asking prices."],
    )


def _vs_recent(
    asking: float, recent: Envelope[float], comps: list[Envelope[Comp]], today: date
) -> Envelope[float] | None:
    if recent.value is None:
        return None
    prices = [c.value.price for c in comps if not c.stale and c.value is not None]
    more = sum(p > asking for p in prices)
    less = sum(p < asking for p in prices)
    return Envelope[float](
        value=round((asking - recent.value) / recent.value, 3),
        kind=Kind.COMPUTED,
        source="computed",
        as_of=today,
        evidence=[
            f"Recent comp median ${recent.value:,.0f}",
            f"{more} of {len(prices)} recent comps ask more; {less} ask less",
        ],
        limitations=["Compares asking prices only; not adjusted for size or condition."],
    )


def build_listing_check(
    listing: CurrentListing,
    rent: Envelope[float] | None,
    recent: Envelope[float] | None,
    market: MarketSpeed,
    comps: list[Envelope[Comp]],
    today: date,
) -> ListingCheck:
    asking = listing.asking_rent
    days_listed = None
    vs_zip = None
    if listing.listed_date is not None:
        days = (today - listing.listed_date).days
        days_listed = Envelope[int](
            value=days,
            kind=Kind.COMPUTED,
            source="computed",
            as_of=today,
            evidence=[f"Listed {listing.listed_date} (--listed)"],
        )
        median = market.median_days_on_market
        if median is not None and median.value is not None:
            vs_zip = Envelope[float](
                value=days - median.value,
                kind=Kind.COMPUTED,
                source="computed",
                as_of=today,
                evidence=[f"{days} days listed", f"Zip median {median.value:g} days"],
                limitations=["Zip median is for all rental listings, not this property type."],
            )
    return ListingCheck(
        asking_rent=Envelope[float](
            value=asking,
            kind=Kind.USER_SUPPLIED,
            source=OWNER_SOURCE,
            as_of=today,
            evidence=[f"--asking {asking:g}"],
        ),
        days_listed=days_listed,
        range_position=_range_position(asking, rent, today) if rent else None,
        vs_recent_comps=_vs_recent(asking, recent, comps, today) if recent else None,
        vs_zip_median_days=vs_zip,
    )
