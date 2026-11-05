"""Advice rules (§5.4 rule 4).

Each rule reads facts already in the brief and either returns one piece of advice citing
them as evidence, or None. If the evidence isn't there, the advice isn't made.
"""

from collections.abc import Callable
from datetime import date

from rentsmart.contracts import Brief, Envelope, Kind

Rule = Callable[[Brief], Envelope[str] | None]

RECENT_SYSTEM_YEARS = 10
NEARBY_MILES = 1.0
MIN_ACTIVE_NEARBY = 3
RECENT_GAP = 0.05
SIMILAR_SQFT = 0.10
# A listing up this many times the zip median days on market is unusually slow.
SLOW_LISTING_FACTOR = 2.0
RULE_LIMITATION = "Rule-based advice from the evidence in this brief; not a guarantee."


def _advice(text: str, evidence: list[str], as_of: date) -> Envelope[str]:
    return Envelope[str](
        value=text,
        kind=Kind.ADVISED,
        source="rentsmart rules",
        as_of=as_of,
        evidence=evidence,
        limitations=[RULE_LIMITATION],
    )


def _range(rent: Envelope[float]) -> str:
    return f"${rent.low:,.0f}-${rent.high:,.0f}"


def _mid(rent: Envelope[float]) -> float:
    if rent.value is not None:
        return rent.value
    assert rent.low is not None and rent.high is not None
    return (rent.low + rent.high) / 2


def _asking_at_or_below_mid(brief: Brief) -> bool:
    listing, rent = brief.listing, brief.rent_estimate
    return (
        listing is not None
        and listing.asking_rent.value is not None
        and rent is not None
        and listing.asking_rent.value <= _mid(rent)
    )


def _is_rising(brief: Brief) -> bool:
    trend = brief.market.trend
    return trend is not None and trend.value == "rising"


# --- Suggestions to rent faster -------------------------------------------------------


def price_for_speed(brief: Brief) -> Envelope[str] | None:
    rent = brief.rent_estimate
    if rent is None or listing_slower_than_zip(brief) is not None:
        return None  # the listing-specific advice says it better
    if _asking_at_or_below_mid(brief):
        return None  # the owner is already in the band this would suggest
    evidence = [f"Rent estimate {_range(rent)}"]
    if _is_rising(brief):
        evidence.append(f"Zip {brief.market.zip_code} days-on-market trend: rising")
        text = (
            f"Days on market in {brief.market.zip_code} are rising. Asking between "
            f"${rent.low:,.0f} and ${_mid(rent):,.0f} is more likely to rent quickly."
        )
    else:
        text = (
            f"To rent faster, ask at or below the mid estimate of ${_mid(rent):,.0f}; "
            f"asking near ${rent.high:,.0f} is likely slower."
        )
    return _advice(text, evidence, brief.generated_at.date())


def highlight_recent_systems(brief: Brief) -> Envelope[str] | None:
    cutoff = brief.generated_at.year - RECENT_SYSTEM_YEARS
    recent: list[str] = []
    evidence: list[str] = []
    for label, fact in (("roof", brief.facts.roof_year), ("HVAC", brief.facts.hvac_year)):
        if fact is not None and fact.value is not None and fact.value >= cutoff:
            recent.append(f"{label} ({fact.value})")
            evidence.append(f"{label} year {fact.value} ({fact.kind})")
    if not recent:
        return None
    text = (
        f"Mention the newer {' and '.join(recent)} in your listing; "
        "listing comps don't show system ages."
    )
    return _advice(text, evidence, brief.generated_at.date())


def stand_out_from_active_comps(brief: Brief) -> Envelope[str] | None:
    active = [
        c.value
        for c in brief.comps
        if c.value is not None
        and c.value.status == "active"
        and not c.value.unconfirmed
        and c.value.distance_miles is not None
        and c.value.distance_miles <= NEARBY_MILES
    ]
    if len(active) < MIN_ACTIVE_NEARBY:
        return None
    text = (
        f"{len(active)} comparable listings within {NEARBY_MILES:g} mile are still active. "
        "Strong photos, flexible move-in dates, or a small move-in incentive can help yours "
        "stand out."
    )
    evidence = [f"Active comp: {c.address} ({c.distance_miles:.1f} mi)" for c in active]
    return _advice(text, evidence, brief.generated_at.date())


def cheaper_equivalent_listings(brief: Brief) -> Envelope[str] | None:
    """Active, confirmed comps like the subject that ask less than the owner does."""
    listing = brief.listing
    if listing is None or listing.asking_rent.value is None:
        return None
    asking = listing.asking_rent.value
    facts = brief.facts
    beds = facts.beds.value if facts.beds else None
    baths = facts.baths.value if facts.baths else None
    sqft = facts.sqft.value if facts.sqft else None
    rivals = [
        c
        for c in (env.value for env in brief.comps)
        if c is not None
        and c.status == "active"
        and not c.unconfirmed
        and c.price < asking
        and (beds is None or c.beds == beds)
        and (baths is None or c.baths is None or c.baths == baths)
        and (sqft is None or c.sqft is None or abs(c.sqft - sqft) <= sqft * SIMILAR_SQFT)
    ]
    if not rivals:
        return None
    rivals.sort(key=lambda c: c.price)
    first = rivals[0]
    since = f", listed since {first.listed_date}" if first.listed_date else ""
    more = f" ({len(rivals)} such listings in all)" if len(rivals) > 1 else ""
    text = (
        f"A similar home is still listed for less: {first.address} at ${first.price:,.0f}"
        f"{since}, ${asking - first.price:,.0f} below your ${asking:,.0f}{more}. Renters "
        "comparing the two may pick the cheaper one unless yours offers more."
    )
    evidence = [
        f"Active comp: {c.address}, ${c.price:,.0f}, {c.beds:g}bd/{c.baths:g}ba, "
        f"{c.sqft or '?'} sqft"
        for c in rivals
        if c.beds is not None and c.baths is not None
    ] or [f"Active comp: {c.address}, ${c.price:,.0f}" for c in rivals]
    return _advice(text, evidence, brief.generated_at.date())


def listing_slower_than_zip(brief: Brief) -> Envelope[str] | None:
    listing, rent, recent = brief.listing, brief.rent_estimate, brief.recent_comps
    if listing is None or rent is None or recent is None or recent.value is None:
        return None
    vs_zip, vs_recent = listing.vs_zip_median_days, listing.vs_recent_comps
    if vs_zip is None or vs_recent is None or vs_zip.value is None or vs_recent.value is None:
        return None
    if vs_zip.value <= 0 or vs_recent.value < RECENT_GAP:
        return None
    text = (
        f"Your listing has been up longer than the zip median and asks {vs_recent.value:.0%} "
        f"above recent comps. Asking nearer ${recent.value:,.0f}-${_mid(rent):,.0f} is more "
        "likely to rent faster."
    )
    evidence = [*vs_zip.evidence, *vs_recent.evidence, f"Rent estimate mid ${_mid(rent):,.0f}"]
    return _advice(text, evidence, brief.generated_at.date())


# --- Questions to ask your agent ------------------------------------------------------


def ask_outside_range(brief: Brief) -> Envelope[str] | None:
    rent = brief.rent_estimate
    if rent is None:
        return None
    text = (
        f"If you're advised to ask outside {_range(rent)}, ask which signed leases "
        "(not asking prices) support that number."
    )
    return _advice(text, [f"Rent estimate {_range(rent)}"], brief.generated_at.date())


def ask_about_mls(brief: Brief) -> Envelope[str] | None:
    text = (
        "Ask whether MLS listings or recently signed leases not in this brief point to a "
        "different price, and to see them."
    )
    return _advice(
        text,
        ["This brief uses public listing data only; no MLS access."],
        brief.generated_at.date(),
    )


def ask_for_comps(brief: Brief) -> Envelope[str] | None:
    if not brief.too_few_comps:
        return None
    text = "Public data has too few comparable rentals here. Ask for the comps behind any price."
    evidence = [f"{len(brief.comps)} comparable rentals found"]
    return _advice(text, evidence, brief.generated_at.date())


def ask_about_recent_gap(brief: Brief) -> Envelope[str] | None:
    rent, recent = brief.rent_estimate, brief.recent_comps
    if rent is None or recent is None or recent.value is None:
        return None
    if ask_about_listing_price(brief) is not None:
        return None  # the owner's own price is the more useful comparison
    mid = _mid(rent)
    gap = (recent.value - mid) / mid
    if abs(gap) < RECENT_GAP:
        return None
    direction = "below" if gap < 0 else "above"
    text = (
        f"Recent comps ask a median ${recent.value:,.0f}, {abs(gap):.0%} {direction} the "
        f"${mid:,.0f} mid estimate. Ask what supports pricing near ${mid:,.0f}."
    )
    evidence = [*recent.evidence, f"Rent estimate mid ${mid:,.0f}"]
    return _advice(text, evidence, brief.generated_at.date())


def ask_about_listing_price(brief: Brief) -> Envelope[str] | None:
    listing = brief.listing
    if listing is None or listing.asking_rent.value is None:
        return None
    vs_recent, position = listing.vs_recent_comps, listing.range_position
    above_recent = (
        vs_recent is not None and vs_recent.value is not None and vs_recent.value >= RECENT_GAP
    )
    above_range = position is not None and position.value == "above range"
    if not (above_recent or above_range):
        return None
    reasons: list[str] = []
    evidence: list[str] = []
    if above_recent and vs_recent is not None and vs_recent.value is not None:
        reasons.append(f"{vs_recent.value:.0%} above the recent comp median")
        evidence.extend(vs_recent.evidence)
    if above_range and position is not None:
        reasons.append("above the estimated range")
        evidence.extend(position.evidence)
    text = (
        f"Your ${listing.asking_rent.value:,.0f} asks {' and '.join(reasons)}. "
        "Ask which signed leases support it."
    )
    return _advice(text, evidence, brief.generated_at.date())


def ask_why_listing_is_slow(brief: Brief) -> Envelope[str] | None:
    """Listed far longer than the zip median while not overpriced: price isn't the obvious cause."""
    listing, rent = brief.listing, brief.rent_estimate
    median = brief.market.median_days_on_market
    if listing is None or rent is None or listing.days_listed is None:
        return None
    if median is None or median.value is None or listing.days_listed.value is None:
        return None
    days, zip_median = listing.days_listed.value, median.value
    if days < zip_median * SLOW_LISTING_FACTOR or not _asking_at_or_below_mid(brief):
        return None
    position = listing.range_position
    where = (
        f"in the {position.value} of the estimated range"
        if position is not None and position.value in ("lower half", "upper half")
        else f"at or below the ${_mid(rent):,.0f} mid estimate"
    )
    text = (
        f"Your listing has been up {days} days, {days - zip_median:g} longer than the zip "
        f"median, while asking {where}. Ask what besides price may be holding it back."
    )
    evidence = [
        *listing.days_listed.evidence,
        f"{days} days listed",
        f"Zip median {zip_median:g} days",
        f"Rent estimate mid ${_mid(rent):,.0f}",
    ]
    if position is not None:
        evidence.extend(position.evidence)
    return _advice(text, evidence, brief.generated_at.date())


def ask_about_slowing_market(brief: Brief) -> Envelope[str] | None:
    if not _is_rising(brief):
        return None
    zip_code = brief.market.zip_code
    text = f"Days on market in {zip_code} are rising. Ask how the suggested price accounts for it."
    evidence = [f"Zip {zip_code} days-on-market trend: rising"]
    return _advice(text, evidence, brief.generated_at.date())


SUGGESTION_RULES: list[Rule] = [
    price_for_speed,
    highlight_recent_systems,
    stand_out_from_active_comps,
    cheaper_equivalent_listings,
    listing_slower_than_zip,
]
QUESTION_RULES: list[Rule] = [
    ask_outside_range,
    ask_about_mls,
    ask_for_comps,
    ask_about_recent_gap,
    ask_about_listing_price,
    ask_why_listing_is_slow,
    ask_about_slowing_market,
]


def run_rules(rules: list[Rule], brief: Brief) -> list[Envelope[str]]:
    return [advice for rule in rules if (advice := rule(brief)) is not None]
