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


class RentIndexRecord(BaseModel):
    """A zip-level rent index from a secondary source, read beside the main provider."""

    zip_code: str
    source: str
    # (month, index level in dollars), oldest first.
    history: list[tuple[date, float]] = Field(default_factory=list[tuple[date, float]])
    # What the source measures and how; shown with any value built from it.
    limitations: list[str] = Field(default_factory=list[str])


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


class RentIndexProvider(Protocol):
    """Optional second source: a zip-level rent index, for trend context only."""

    name: str

    def rent_index(self, zip_code: str) -> RentIndexRecord | None:
        """The zip's series, or None if the source doesn't cover it."""
        ...
