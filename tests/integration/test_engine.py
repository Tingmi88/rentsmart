"""The whole brief, driven by a FakeProvider: no vendor code involved (Phase 2)."""

from datetime import date

import pytest

from rentsmart.contracts import (
    NEEDS_LIMITATION,
    AddressNotFound,
    AmbiguousAddress,
    Brief,
    Envelope,
    ExitCode,
    Kind,
)
from rentsmart.core.engine import build_brief
from rentsmart.core.facts import OwnerFacts
from rentsmart.core.listing import CurrentListing
from rentsmart.providers.base import PropertyRecord, RentEstimateRecord
from rentsmart.providers.fake import FakeProvider
from tests.conftest import ADDRESS, TODAY


def _all_envelopes(fake: FakeProvider) -> list[Envelope[object]]:
    brief = build_brief(ADDRESS, OwnerFacts(), fake, today=TODAY)
    facts = [getattr(brief.facts, name) for name in type(brief.facts).model_fields]
    singles = [
        brief.rent_estimate,
        brief.property_tax,
        brief.market.median_days_on_market,
        brief.market.trend,
    ]
    lists = [*brief.comps, *brief.scenarios, *brief.suggestions, *brief.agent_questions]
    return [e for e in [*facts, *singles, *lists] if e is not None]


def test_every_section_present(fake_provider: FakeProvider) -> None:
    brief = build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY)
    assert brief.exit_code == ExitCode.OK
    assert brief.facts.address.value == ADDRESS
    assert brief.facts.match_confidence.value == 1.0
    assert brief.rent_estimate is not None
    assert len(brief.comps) == 5
    assert brief.market.median_days_on_market is not None
    assert brief.market.trend is not None
    assert brief.property_tax is not None and brief.property_tax.value == 3785
    assert len(brief.scenarios) == 3
    assert brief.suggestions
    assert brief.agent_questions


def test_every_envelope_honors_contract(fake_provider: FakeProvider) -> None:
    for env in _all_envelopes(fake_provider):
        assert env.source and env.as_of
        if env.kind in NEEDS_LIMITATION:
            assert env.limitations


def test_every_comp_is_labeled_asking(fake_provider: FakeProvider) -> None:
    brief = build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY)
    assert {c.value.basis for c in brief.comps if c.value} == {"asking"}


def test_owner_facts_override_vendor(fake_provider: FakeProvider) -> None:
    brief = build_brief(ADDRESS, OwnerFacts(beds=4, roof_year=2019), fake_provider, today=TODAY)
    assert brief.facts.beds is not None
    assert brief.facts.beds.value == 4 and brief.facts.beds.kind == Kind.USER_SUPPLIED
    assert brief.facts.baths is not None and brief.facts.baths.kind == Kind.FETCHED
    assert fake_provider.queries[-1].beds == 4
    assert any("roof (2019)" in (s.value or "") for s in brief.suggestions)


def test_advice_cites_evidence(fake_provider: FakeProvider) -> None:
    brief = build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY)
    for advice in [*brief.suggestions, *brief.agent_questions]:
        assert advice.kind == Kind.ADVISED
        assert advice.evidence


def test_no_system_advice_without_owner_facts(fake_provider: FakeProvider) -> None:
    brief = build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY)
    assert not any("roof" in (s.value or "") for s in brief.suggestions)


def test_address_not_found(fake_provider: FakeProvider) -> None:
    fake_provider.properties = []
    with pytest.raises(AddressNotFound):
        build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY)


def test_ambiguous_address_never_guesses(fake_provider: FakeProvider) -> None:
    fake_provider.properties = [
        PropertyRecord(formatted_address="1 A St, Apt 1", zip_code="1"),
        PropertyRecord(formatted_address="1 A St, Apt 2", zip_code="1"),
    ]
    with pytest.raises(AmbiguousAddress) as err:
        build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY)
    assert err.value.candidates == ["1 A St, Apt 1", "1 A St, Apt 2"]
    assert fake_provider.queries == []


def test_too_few_comps_shows_what_exists(fake_provider: FakeProvider) -> None:
    fake_provider.rent = RentEstimateRecord(
        rent=2000, low=1800, high=2200, comps=fake_provider.rent.comps[:2]
    )
    brief = build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY)
    assert brief.exit_code == ExitCode.TOO_FEW_COMPS
    assert brief.rent_estimate is None
    assert brief.scenarios == []
    assert len(brief.comps) == 2


def test_stale_data_flagged(fake_provider: FakeProvider) -> None:
    brief = build_brief(ADDRESS, OwnerFacts(), fake_provider, today=date(2027, 6, 1))
    assert brief.exit_code == ExitCode.STALE_DATA
    assert brief.market.median_days_on_market is not None
    assert brief.market.median_days_on_market.stale


def test_unconfirmed_actives_dont_count_as_competition(fake_provider: FakeProvider) -> None:
    # Synthetic fixture has 3 active comps within a mile, seen 2026-10-18.
    fresh = build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY)
    assert any("still active" in (s.value or "") for s in fresh.suggestions)
    later = build_brief(ADDRESS, OwnerFacts(), fake_provider, today=date(2026, 11, 20))
    assert all(c.value.unconfirmed for c in later.comps if c.value and c.value.status == "active")
    assert not any("still active" in (s.value or "") for s in later.suggestions)


# --- --asking: the owner's current listing ---------------------------------------------


def _with_listing(fake: FakeProvider, asking: float, listed: date | None = None) -> Brief:
    return build_brief(
        ADDRESS,
        OwnerFacts(),
        fake,
        today=TODAY,
        listing=CurrentListing(asking_rent=asking, listed_date=listed),
    )


def test_no_listing_section_without_asking(fake_provider: FakeProvider) -> None:
    assert build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY).listing is None


def test_listing_position_in_range(fake_provider: FakeProvider) -> None:
    # Synthetic range is $1,850-$2,250.
    cases = {1800: "below range", 1900: "lower half", 2200: "upper half", 2300: "above range"}
    for asking, expected in cases.items():
        listing = _with_listing(fake_provider, asking).listing
        assert listing is not None and listing.range_position is not None
        assert listing.range_position.value == expected
        assert listing.asking_rent.kind == Kind.USER_SUPPLIED


def test_listing_days_vs_zip_median(fake_provider: FakeProvider) -> None:
    listing = _with_listing(fake_provider, 2000, date(2026, 9, 10)).listing
    assert listing is not None and listing.days_listed is not None
    assert listing.days_listed.value == 40
    assert listing.vs_zip_median_days is not None
    assert listing.vs_zip_median_days.value == 40 - 31


def test_cheaper_similar_listing_cited(fake_provider: FakeProvider) -> None:
    # Similar (3bd/2ba, sqft within 10% of 1,450): 88 Fixture Rd $1,995, 140 Sample Ave $2,100.
    brief = _with_listing(fake_provider, 2150)
    hits = [
        s for s in brief.suggestions if "similar home is still listed for less" in (s.value or "")
    ]
    assert len(hits) == 1
    assert "88 Fixture Rd" in (hits[0].value or "")  # cheapest is named
    evidence = " ".join(hits[0].evidence)
    assert "88 Fixture Rd" in evidence and "140 Sample Ave" in evidence
    assert "17 Mock Ln" not in evidence  # 4 beds: not similar


def test_no_cheaper_listing_advice_when_owner_is_cheapest(fake_provider: FakeProvider) -> None:
    brief = _with_listing(fake_provider, 1900)
    assert not any("listed for less" in (s.value or "") for s in brief.suggestions)
    assert not any("Your $1,900" in (q.value or "") for q in brief.agent_questions)


def test_subject_never_its_own_comp(fake_provider: FakeProvider) -> None:
    own = fake_provider.rent.comps[0].model_copy(update={"address": ADDRESS})
    fake_provider.rent = fake_provider.rent.model_copy(
        update={"comps": [own, *fake_provider.rent.comps[1:]]}
    )
    brief = build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY)
    assert all(c.value and c.value.address != ADDRESS for c in brief.comps)


def test_no_generic_price_advice_when_already_at_or_below_mid(fake_provider: FakeProvider) -> None:
    # Synthetic mid is $2,050.
    below = _with_listing(fake_provider, 2000)
    assert not any("more likely to rent quickly" in (s.value or "") for s in below.suggestions)
    above = _with_listing(fake_provider, 2200)
    assert any("more likely to rent quickly" in (s.value or "") for s in above.suggestions)


def test_slow_listing_not_overpriced_gets_a_question(fake_provider: FakeProvider) -> None:
    # Zip median 31 days: 70 days listed is more than twice that.
    slow = _with_listing(fake_provider, 2000, date(2026, 8, 11))
    hits = [q for q in slow.agent_questions if "besides price" in (q.value or "")]
    assert len(hits) == 1
    assert "up 70 days, 39 longer than the zip median" in (hits[0].value or "")
    assert "lower half" in (hits[0].value or "")


@pytest.mark.parametrize(
    ("asking", "listed"),
    [
        (2000, date(2026, 9, 30)),  # 20 days: not slow
        (2200, date(2026, 8, 11)),  # slow, but above the mid: price is the obvious suspect
        (2000, None),  # no listing date
    ],
)
def test_slow_listing_question_stays_silent(
    fake_provider: FakeProvider, asking: float, listed: date | None
) -> None:
    brief = _with_listing(fake_provider, asking, listed)
    assert not any("besides price" in (q.value or "") for q in brief.agent_questions)
