"""Output contract: the envelope, the brief, and named failures (problem statement §5-§6)."""

from datetime import date, datetime
from enum import IntEnum, StrEnum
from typing import Any, ClassVar, Generic, Literal, Self, TypeVar

from pydantic import BaseModel, Field, model_validator

T = TypeVar("T")


class Kind(StrEnum):
    """How a value was produced (§5.2)."""

    FETCHED = "fetched"
    ESTIMATED = "estimated"
    COMPUTED = "computed"
    MODELED = "modeled"
    PREDICTED = "predicted"
    ADVISED = "advised"
    USER_SUPPLIED = "user_supplied"


NEEDS_LIMITATION = frozenset({Kind.ESTIMATED, Kind.MODELED, Kind.PREDICTED, Kind.ADVISED})


class Envelope(BaseModel, Generic[T]):  # noqa: UP046 - explicit Generic keeps Pydantic generics predictable
    """Every value in the brief travels in this envelope (§5.1)."""

    value: T | None = None
    low: float | None = None
    high: float | None = None
    kind: Kind
    source: str = Field(min_length=1)
    as_of: date
    evidence: list[str] = Field(default_factory=list[str])
    limitations: list[str] = Field(default_factory=list[str])
    stale: bool = False

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError(f"low ({self.low}) must be <= high ({self.high})")
        value: object = self.value
        if isinstance(value, int | float) and not isinstance(value, bool):
            if self.low is not None and value < self.low:
                raise ValueError(f"value ({value}) must be >= low ({self.low})")
            if self.high is not None and value > self.high:
                raise ValueError(f"value ({value}) must be <= high ({self.high})")
        if self.kind in NEEDS_LIMITATION and not self.limitations:
            raise ValueError(f"{self.kind} values need at least one limitation")
        return self


class Comp(BaseModel):
    """One rental comparable. `basis` says whether the price is asking or a signed lease."""

    address: str
    distance_miles: float | None = None
    beds: float | None = None
    baths: float | None = None
    sqft: int | None = None
    price: float
    listed_date: date | None = None
    last_seen_date: date | None = None
    status: str
    basis: Literal["asking", "leased"]
    # Marked active by the vendor but not seen recently: may have rented or been withdrawn.
    unconfirmed: bool = False


class PropertyFacts(BaseModel):
    address: Envelope[str]
    match_confidence: Envelope[float]
    property_type: Envelope[str] | None = None
    beds: Envelope[float] | None = None
    baths: Envelope[float] | None = None
    sqft: Envelope[int] | None = None
    year_built: Envelope[int] | None = None
    roof_year: Envelope[int] | None = None
    hvac_year: Envelope[int] | None = None


class MarketSpeed(BaseModel):
    """Zip-level market speed. Never property-level (§5.4 rule 3)."""

    zip_code: str
    median_days_on_market: Envelope[float] | None = None
    trend: Envelope[Literal["rising", "falling", "flat"]] | None = None


class Scenario(BaseModel):
    label: Literal["low", "mid", "high"]
    asking_rent: float
    speed: str


class ListingCheck(BaseModel):
    """The owner's current asking rent, checked against the brief's evidence."""

    asking_rent: Envelope[float]
    days_listed: Envelope[int] | None = None
    range_position: (
        Envelope[Literal["below range", "lower half", "upper half", "above range"]] | None
    ) = None
    # Fraction above (+) or below (-) the recent comp median, e.g. 0.12 = 12% above.
    vs_recent_comps: Envelope[float] | None = None
    # Days listed minus the zip median days on market.
    vs_zip_median_days: Envelope[float] | None = None


class ExitCode(IntEnum):
    """Distinct exit codes per named failure (§6). 1 and 2 are left to Python and Typer."""

    OK = 0
    ADDRESS_NOT_FOUND = 10
    AMBIGUOUS_ADDRESS = 11
    TOO_FEW_COMPS = 12
    STALE_DATA = 13
    QUOTA_EXCEEDED = 14
    CONFIG_ERROR = 15
    PROVIDER_ERROR = 16
    SIMILAR_ADDRESS = 17


class Brief(BaseModel):
    input_address: str
    generated_at: datetime
    provider: str
    facts: PropertyFacts
    rent_estimate: Envelope[float] | None
    # Median asking price of comps seen within the freshness window, beside the vendor range.
    recent_comps: Envelope[float] | None = None
    listing: ListingCheck | None = None
    comps: list[Envelope[Comp]]
    market: MarketSpeed
    property_tax: Envelope[float] | None
    scenarios: list[Envelope[Scenario]]
    suggestions: list[Envelope[str]]
    agent_questions: list[Envelope[str]]
    notices: list[str]
    too_few_comps: bool
    stale: bool

    @property
    def exit_code(self) -> ExitCode:
        if self.too_few_comps:
            return ExitCode.TOO_FEW_COMPS
        if self.stale:
            return ExitCode.STALE_DATA
        return ExitCode.OK


class RentsmartError(Exception):
    """A named failure: no brief is produced."""

    exit_code: ClassVar[ExitCode] = ExitCode.PROVIDER_ERROR

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": type(self).__name__,
            "exit_code": int(self.exit_code),
            "message": self.message,
        }


class AddressNotFound(RentsmartError):
    exit_code = ExitCode.ADDRESS_NOT_FOUND

    def __init__(self, address: str) -> None:
        super().__init__(
            f'No property found for "{address}". Check the format: street, city, state, ZIP '
            '(e.g. "123 Main St, Gainesville, FL 32601").'
        )


class AmbiguousAddress(RentsmartError):
    exit_code = ExitCode.AMBIGUOUS_ADDRESS

    def __init__(self, address: str, candidates: list[str]) -> None:
        lines = "\n".join(f"  - {c}" for c in candidates)
        super().__init__(
            f'"{address}" matches more than one property. Rerun with one of these:\n{lines}'
        )
        self.candidates = candidates

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "candidates": self.candidates}


class SimilarAddress(RentsmartError):
    """Not looked up yet, but close to addresses that were. Nothing was fetched."""

    exit_code = ExitCode.SIMILAR_ADDRESS

    def __init__(self, address: str, candidates: list[tuple[str, date]]) -> None:
        lines = "\n".join(f"  - {c} (looked up {d.isoformat()})" for c, d in candidates)
        super().__init__(
            f'"{address}" hasn\'t been looked up, but similar addresses have. '
            f"No API calls were made. Did you mean:\n{lines}\n"
            "Rerun with one of these, or add --run-anyway to look it up as typed."
        )
        self.candidates = candidates

    def to_dict(self) -> dict[str, Any]:
        found = [{"address": c, "looked_up": d.isoformat()} for c, d in self.candidates]
        return {**super().to_dict(), "candidates": found}


class QuotaExceeded(RentsmartError):
    exit_code = ExitCode.QUOTA_EXCEEDED

    def __init__(self, provider: str) -> None:
        super().__init__(
            f"The {provider} request quota is used up. No brief was produced. "
            "Try again after the quota resets."
        )


class ConfigError(RentsmartError):
    exit_code = ExitCode.CONFIG_ERROR


class ProviderError(RentsmartError):
    exit_code = ExitCode.PROVIDER_ERROR
