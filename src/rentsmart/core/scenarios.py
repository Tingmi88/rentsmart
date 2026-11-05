"""Pricing scenarios: asking rent at low/mid/high with direction of speed only (§5.4 rule 3)."""

from rentsmart.contracts import Envelope, Kind, MarketSpeed, Scenario


def build_scenarios(rent: Envelope[float] | None, market: MarketSpeed) -> list[Envelope[Scenario]]:
    if rent is None or rent.low is None or rent.high is None:
        return []
    low, high = rent.low, rent.high
    mid = rent.value if rent.value is not None else (low + high) / 2
    ref = (
        "the zip median days on market"
        if market.median_days_on_market is not None
        else "typical comparable listings"
    )
    rows: list[Scenario] = [
        Scenario(label="low", asking_rent=low, speed=f"likely faster than {ref}"),
        Scenario(label="mid", asking_rent=mid, speed=f"likely near {ref}"),
        Scenario(label="high", asking_rent=high, speed=f"likely slower than {ref}"),
    ]
    return [
        Envelope[Scenario](
            value=row,
            kind=Kind.COMPUTED,
            source="computed",
            as_of=rent.as_of,
            evidence=[f"Rent estimate range ${low:,.0f}-${high:,.0f}"],
            limitations=["Direction only; no specific number of days is predicted."],
        )
        for row in rows
    ]
