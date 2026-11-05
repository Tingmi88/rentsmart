"""Human-readable view, rendered only from the Brief so it can't disagree with --json."""

from typing import Any

from rentsmart.contracts import Brief, Envelope


def _meta(env: Envelope[Any]) -> str:
    stale = " · STALE" if env.stale else ""
    return f"[{env.kind} · {env.source} · as of {env.as_of}{stale}]"


def _money(amount: float | None) -> str:
    return "n/a" if amount is None else f"${amount:,.0f}"


def _num(value: float | None) -> str:
    return "?" if value is None else f"{value:g}"


def _miles(value: float | None) -> str:
    return "? mi" if value is None else f"{value:.1f} mi"


def _limits(env: Envelope[Any], indent: str = "    ") -> list[str]:
    return [f"{indent}- {lim}" for lim in env.limitations]


def render(brief: Brief) -> str:
    out: list[str] = []
    add = out.append
    facts = brief.facts

    add(f"rentsmart brief: {facts.address.value}")
    add(f"Generated {brief.generated_at:%Y-%m-%d} from {brief.provider}.")
    if brief.stale:
        add("")
        add("!! STALE DATA: some values below are older than the freshness threshold.")
    if brief.too_few_comps:
        add("")
        add("!! TOO FEW COMPS: no reliable rent range is possible. See what exists below.")

    add("")
    add("PROPERTY")
    add(f"  Address match confidence: {facts.match_confidence.value:.2f}")
    for label, env in (
        ("Type", facts.property_type),
        ("Beds", facts.beds),
        ("Baths", facts.baths),
        ("Sqft", facts.sqft),
        ("Year built", facts.year_built),
        ("Roof year", facts.roof_year),
        ("HVAC year", facts.hvac_year),
    ):
        if env is not None:
            value = _num(env.value) if isinstance(env.value, float) else env.value
            add(f"  {label}: {value}  {_meta(env)}")

    add("")
    add("RENT ESTIMATE (monthly)")
    rent = brief.rent_estimate
    if rent is None:
        add("  No reliable range: too few comparable rentals.")
    else:
        add(f"  {_money(rent.low)} - {_money(rent.high)}, mid {_money(rent.value)}  {_meta(rent)}")
        add("  Limitations:")
        out.extend(_limits(rent))
    recent = brief.recent_comps
    if recent is not None:
        add(f"  Recent support: median {_money(recent.value)}  {_meta(recent)}")
        add(f"    {'; '.join(recent.evidence)}")

    listing = brief.listing
    if listing is not None:
        add("")
        add("YOUR LISTING")
        add(f"  Asking {_money(listing.asking_rent.value)}/mo  {_meta(listing.asking_rent)}")
        position = listing.range_position
        if position is not None:
            add(f"  Range position: {position.value} ({position.evidence[0]})")
        vs_recent = listing.vs_recent_comps
        if vs_recent is not None and vs_recent.value is not None:
            direction = "above" if vs_recent.value >= 0 else "below"
            add(
                f"  vs recent comps: {abs(vs_recent.value):.1%} {direction} "
                f"({'; '.join(vs_recent.evidence)})"
            )
        if listing.days_listed is not None:
            line = f"  Days listed: {listing.days_listed.value}"
            vs_zip = listing.vs_zip_median_days
            if vs_zip is not None and vs_zip.value is not None:
                direction = "longer" if vs_zip.value > 0 else "shorter"
                line += f" ({abs(vs_zip.value):g} days {direction} than the zip median)"
            add(line)

    add("")
    add("RENTAL COMPS (newest first)")
    if not brief.comps:
        add("  None found.")
    divided = False
    for env in brief.comps:
        c = env.value
        if c is None:
            continue
        if env.stale and not divided:
            add("  -- older than the freshness threshold --")
            divided = True
        sqft = f"{c.sqft:,} sqft" if c.sqft else "? sqft"
        status = f"{c.status}?" if c.unconfirmed else c.status
        flags = ("  UNCONFIRMED" if c.unconfirmed else "") + ("  STALE" if env.stale else "")
        add(
            f"  {_money(c.price)} {c.basis}, {status}  {_num(c.beds)}bd/{_num(c.baths)}ba "
            f"{sqft}  {_miles(c.distance_miles)}  seen {env.as_of}{flags}"
        )
        add(f"    {c.address}")
        if c.unconfirmed:
            add(f"    - {env.limitations[-1]}")

    add("")
    add(f"MARKET SPEED (zip {brief.market.zip_code})")
    median = brief.market.median_days_on_market
    trend = brief.market.trend
    if median is None and trend is None:
        add("  No zip-level market data.")
    if median is not None:
        add(f"  Median days on market: {_num(median.value)}  {_meta(median)}")
    if trend is not None:
        add(f"  Trend: {trend.value}  {_meta(trend)}")

    add("")
    add("PROPERTY TAX (annual)")
    tax = brief.property_tax
    if tax is None:
        add("  No tax record.")
    else:
        add(f"  {_money(tax.value)}  {_meta(tax)}")
        add(f"    {'; '.join(tax.evidence)}")

    add("")
    add("PRICING SCENARIOS")
    if not brief.scenarios:
        add("  None: no rent range to build them from.")
    for env in brief.scenarios:
        s = env.value
        if s is not None:
            add(f"  {s.label:>4}: {_money(s.asking_rent)}/mo, {s.speed}")
    if brief.scenarios:
        out.extend(_limits(brief.scenarios[0], indent="  "))

    for title, items in (
        ("SUGGESTIONS TO RENT FASTER", brief.suggestions),
        ("QUESTIONS TO ASK YOUR AGENT", brief.agent_questions),
    ):
        add("")
        add(title)
        if not items:
            add("  None: the evidence in this brief doesn't support any.")
        for env in items:
            add(f"  * {env.value}")
            add(f"    because: {'; '.join(env.evidence)}")

    add("")
    add("NOTES")
    out.extend(f"  - {n}" for n in brief.notices)
    return "\n".join(out)
