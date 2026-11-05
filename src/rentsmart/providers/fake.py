"""In-memory provider. Drives the whole brief in tests without any vendor."""

from dataclasses import dataclass, field

from rentsmart.providers.base import MarketRecord, PropertyRecord, RentEstimateRecord, SubjectQuery


@dataclass
class FakeProvider:
    properties: list[PropertyRecord]
    rent: RentEstimateRecord
    market: MarketRecord
    name: str = "Fake"
    queries: list[SubjectQuery] = field(default_factory=list[SubjectQuery])

    def resolve_address(self, address: str) -> list[PropertyRecord]:
        return list(self.properties)

    def rent_estimate(self, subject: SubjectQuery) -> RentEstimateRecord:
        self.queries.append(subject)
        return self.rent

    def market_stats(self, zip_code: str) -> MarketRecord:
        return self.market
