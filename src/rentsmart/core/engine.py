"""The one engine: address in, brief out. Front doors (CLI, later web) wrap this."""

from datetime import UTC, date, datetime

from rentsmart.contracts import AddressNotFound, AmbiguousAddress, Brief, MarketSpeed
from rentsmart.core.facts import OwnerFacts, build_facts
from rentsmart.core.freshness import DEFAULT_STALE_AFTER_DAYS, TAX_STALE_AFTER_DAYS, flag_stale
from rentsmart.core.listing import CurrentListing, build_listing_check
from rentsmart.core.market import build_market
from rentsmart.core.pricing import (
    MIN_COMPS,
    NO_MLS,
    build_comps,
    build_recent_support,
    build_rent_estimate,
    build_tax,
    has_enough_comps,
)
from rentsmart.core.rules import QUESTION_RULES, SUGGESTION_RULES, run_rules
from rentsmart.core.scenarios import build_scenarios
from rentsmart.providers.base import Provider, SubjectQuery

DISCLAIMER = "Not an appraisal; not financial, legal, or tax advice."
LOW_MATCH_CONFIDENCE = 0.8


def build_brief(
    address: str,
    owner: OwnerFacts,
    provider: Provider,
    *,
    today: date | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    listing: CurrentListing | None = None,
) -> Brief:
    today = today or date.today()

    candidates = provider.resolve_address(address)
    if not candidates:
        raise AddressNotFound(address)
    if len(candidates) > 1:
        raise AmbiguousAddress(address, [c.formatted_address for c in candidates])
    record = candidates[0]

    facts = build_facts(address, record, owner, provider.name, today)
    subject = SubjectQuery(
        address=record.formatted_address,
        property_type=record.property_type,
        beds=facts.beds.value if facts.beds else None,
        baths=facts.baths.value if facts.baths else None,
        sqft=facts.sqft.value if facts.sqft else None,
    )
    rent_record = provider.rent_estimate(subject)
    market_record = provider.market_stats(record.zip_code)

    # The subject never counts as its own comp (e.g. its live listing).
    comps = [
        flag_stale(c, today, stale_after_days)
        for c in build_comps(rent_record, provider.name, today)
        if c.value is None or c.value.address != record.formatted_address
    ]
    rent = build_rent_estimate(rent_record, provider.name, today)
    rent = rent and flag_stale(rent, today, stale_after_days)
    recent = build_recent_support(comps, stale_after_days, today)
    market = build_market(market_record, provider.name, today)
    if market.median_days_on_market is not None:
        market = MarketSpeed(
            zip_code=market.zip_code,
            median_days_on_market=flag_stale(market.median_days_on_market, today, stale_after_days),
            trend=market.trend,
        )
    tax = build_tax(record.tax, provider.name, today)
    tax = tax and flag_stale(tax, today, TAX_STALE_AFTER_DAYS)

    too_few_comps = not has_enough_comps(rent_record)
    notices = [DISCLAIMER, NO_MLS]
    if too_few_comps:
        notices.append(
            f"No reliable rent range: {len(comps)} comparable rentals found, "
            f"at least {MIN_COMPS} needed. Comps found are shown below."
        )
    retrieved = min(d for d in (record.retrieved_on, rent_record.as_of, today) if d is not None)
    if retrieved < today:
        notices.append(
            f"Using {provider.name} data retrieved on {retrieved} "
            f"({(today - retrieved).days} days ago)."
        )
    confidence = facts.match_confidence.value or 0.0
    if confidence < LOW_MATCH_CONFIDENCE:
        notices.append(
            f"Resolved address only partly matches your input (confidence {confidence:.2f}). "
            "Check it is your property."
        )

    brief = Brief(
        input_address=address,
        generated_at=datetime.combine(today, datetime.now(UTC).time(), tzinfo=UTC),
        provider=provider.name,
        facts=facts,
        rent_estimate=rent,
        recent_comps=recent,
        listing=listing and build_listing_check(listing, rent, recent, market, comps, today),
        comps=comps,
        market=market,
        property_tax=tax,
        scenarios=build_scenarios(rent, market),
        suggestions=[],
        agent_questions=[],
        notices=notices,
        too_few_comps=too_few_comps,
        stale=any(e is not None and e.stale for e in (rent, market.median_days_on_market, tax)),
    )
    return brief.model_copy(
        update={
            "suggestions": run_rules(SUGGESTION_RULES, brief),
            "agent_questions": run_rules(QUESTION_RULES, brief),
        }
    )
