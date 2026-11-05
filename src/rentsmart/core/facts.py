"""Resolved address and property facts. Owner-supplied facts override vendor facts."""

import re
from datetime import date

from pydantic import BaseModel, Field

from rentsmart.contracts import Envelope, Kind, PropertyFacts
from rentsmart.providers.base import PropertyRecord

OWNER_SOURCE = "owner (CLI flag)"
RECORD_DATE_UNKNOWN = "Vendor record has no update date; shown as the retrieval date."

_ABBREVIATIONS = {
    "street": "st",
    "avenue": "ave",
    "road": "rd",
    "drive": "dr",
    "boulevard": "blvd",
    "lane": "ln",
    "court": "ct",
    "place": "pl",
    "terrace": "ter",
    "circle": "cir",
    "parkway": "pkwy",
    "highway": "hwy",
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
    "northeast": "ne",
    "northwest": "nw",
    "southeast": "se",
    "southwest": "sw",
    "apartment": "apt",
    "unit": "apt",
}


class OwnerFacts(BaseModel):
    beds: float | None = Field(default=None, ge=0)
    baths: float | None = Field(default=None, ge=0)
    sqft: int | None = Field(default=None, gt=0)
    roof_year: int | None = None
    hvac_year: int | None = None


def _tokens(address: str) -> set[str]:
    words: list[str] = re.findall(r"[a-z0-9]+", address.lower())
    return {_ABBREVIATIONS.get(w, w) for w in words}


def match_confidence(input_address: str, resolved_address: str) -> float:
    """Share of the owner's address tokens found in the resolved address (0-1)."""
    wanted = _tokens(input_address)
    if not wanted:
        return 0.0
    return round(len(wanted & _tokens(resolved_address)) / len(wanted), 2)


def _fetched[V](value: V | None, source: str, today: date) -> Envelope[V] | None:
    if value is None:
        return None
    return Envelope[V](
        value=value,
        kind=Kind.FETCHED,
        source=source,
        as_of=today,
        limitations=[RECORD_DATE_UNKNOWN],
    )


def _fact[V](
    owner_value: V | None,
    vendor_value: V | None,
    flag: str,
    source: str,
    today: date,
    retrieved: date | None = None,
) -> Envelope[V] | None:
    if owner_value is not None:
        return Envelope[V](
            value=owner_value,
            kind=Kind.USER_SUPPLIED,
            source=OWNER_SOURCE,
            as_of=today,
            evidence=[f"{flag} {owner_value}"],
        )
    return _fetched(vendor_value, source, retrieved or today)


def build_facts(
    input_address: str, record: PropertyRecord, owner: OwnerFacts, provider: str, today: date
) -> PropertyFacts:
    source = f"{provider} property record"
    retrieved = record.retrieved_on or today
    confidence = match_confidence(input_address, record.formatted_address)
    return PropertyFacts(
        address=Envelope[str](
            value=record.formatted_address,
            kind=Kind.FETCHED,
            source=source,
            as_of=retrieved,
            evidence=[f"Input: {input_address}"],
        ),
        match_confidence=Envelope[float](
            value=confidence,
            low=0.0,
            high=1.0,
            kind=Kind.COMPUTED,
            source="computed",
            as_of=today,
            evidence=[f"Input: {input_address}", f"Resolved: {record.formatted_address}"],
            limitations=["Token overlap only; does not verify the property on a map."],
        ),
        property_type=_fetched(record.property_type, source, retrieved),
        beds=_fact(owner.beds, record.beds, "--beds", source, today, retrieved),
        baths=_fact(owner.baths, record.baths, "--baths", source, today, retrieved),
        sqft=_fact(owner.sqft, record.sqft, "--sqft", source, today, retrieved),
        year_built=_fetched(record.year_built, source, retrieved),
        roof_year=_fact(owner.roof_year, None, "--roof-year", source, today),
        hvac_year=_fact(owner.hvac_year, None, "--hvac-year", source, today),
    )
