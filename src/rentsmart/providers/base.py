"""Provider interface. The core depends on this module only, never on a vendor."""

from datetime import date
from typing import Protocol

from pydantic import BaseModel, Field


class TaxRecord(BaseModel):
    year: int
    amount: float
    assessed_value: float | None = None


class PropertyRecord(BaseModel):
    formatted_address: str
    zip_code: str
    property_type: str | None = None
    beds: float | None = None
    baths: float | None = None
    sqft: int | None = None
    year_built: int | None = None
    tax: TaxRecord | None = None
    # When the provider fetched this record (earlier than today if served from a cache).
    retrieved_on: date | None = None


class CompRecord(BaseModel):
    address: str
    distance_miles: float | None = None
    beds: float | None = None
    baths: float | None = None
    sqft: int | None = None
    price: float
    listed_date: date | None = None
    last_seen_date: date | None = None
    status: str


class RentEstimateRecord(BaseModel):
    """A vendor rent AVM result. Comps come from listings, so their prices are asking prices."""

    rent: float | None = None
    low: float | None = None
    high: float | None = None
    comps: list[CompRecord] = Field(default_factory=list[CompRecord])
    as_of: date | None = None


class MarketRecord(BaseModel):
    zip_code: str
    median_days_on_market: float | None = None
    # (month, median days on market), oldest first.
    history: list[tuple[date, float]] = Field(default_factory=list[tuple[date, float]])
    as_of: date | None = None


class SubjectQuery(BaseModel):
    """The property to price, after owner-supplied facts override vendor facts."""

    address: str
    property_type: str | None = None
    beds: float | None = None
    baths: float | None = None
    sqft: int | None = None


class Provider(Protocol):
    name: str

    def resolve_address(self, address: str) -> list[PropertyRecord]:
        """Return every property that plausibly matches; the core decides on ambiguity."""
        ...

    def rent_estimate(self, subject: SubjectQuery) -> RentEstimateRecord: ...

    def market_stats(self, zip_code: str) -> MarketRecord: ...
