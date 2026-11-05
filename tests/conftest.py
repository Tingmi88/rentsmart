import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from rentsmart.contracts import Brief
from rentsmart.core.engine import build_brief
from rentsmart.core.facts import OwnerFacts
from rentsmart.core.listing import CurrentListing
from rentsmart.providers.base import SubjectQuery
from rentsmart.providers.fake import FakeProvider
from rentsmart.providers.rentcast import (
    BASE_URL,
    MARKETS_PATH,
    PROPERTIES_PATH,
    RENT_AVM_PATH,
    RentCastProvider,
)
from rentsmart.providers.replay import replay_provider

FIXTURES = Path(__file__).parent / "fixtures" / "rentcast"
TODAY = date(2026, 10, 20)
ADDRESS = "123 Example St, Gainesville, FL 32601"
AUSTIN = "4120 Sample Dr, Austin, TX 78729"


def load_fixture(slug: str, name: str) -> Any:
    return json.loads((FIXTURES / slug / name).read_text())


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[respx.MockRouter]:
    """Every test runs with HTTP mocked and no API key: unmocked requests fail."""
    # Each test gets its own empty response cache, never the user's.
    monkeypatch.setenv("RENTSMART_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("RENTSMART_CACHE_DAYS", raising=False)
    monkeypatch.delenv("RENTCAST_API_KEY", raising=False)
    monkeypatch.delenv("RENTSMART_STALE_AFTER_DAYS", raising=False)
    # Plain, unwrapped CLI output everywhere (CI forces Rich color and box drawing).
    for var in ("FORCE_COLOR", "GITHUB_ACTIONS", "TTY_COMPATIBLE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "200")
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


def route_fixtures(
    router: respx.MockRouter,
    slug: str = "synthetic-gainesville",
    properties: Any = None,
    rent: Any = None,
) -> None:
    """Replay recorded responses. `properties` / `rent` override the fixture file."""

    def reply(data: Any) -> httpx.Response:
        return httpx.Response(404) if data is None else httpx.Response(200, json=data)

    router.get(PROPERTIES_PATH).mock(
        return_value=reply(
            properties if properties is not None else load_fixture(slug, "properties.json")
        )
    )
    router.get(RENT_AVM_PATH).mock(
        return_value=reply(rent if rent is not None else load_fixture(slug, "rent_long_term.json"))
    )
    router.get(MARKETS_PATH).mock(return_value=reply(load_fixture(slug, "markets.json")))


@pytest.fixture
def rentcast(no_live_http: respx.MockRouter) -> RentCastProvider:
    route_fixtures(no_live_http)
    return RentCastProvider("test-key")


@pytest.fixture
def fake_provider(rentcast: RentCastProvider) -> FakeProvider:
    """A FakeProvider loaded with the synthetic records, parsed once through the adapter."""
    record = rentcast.resolve_address(ADDRESS)
    return FakeProvider(
        properties=record,
        rent=rentcast.rent_estimate(SubjectQuery(address=record[0].formatted_address)),
        market=rentcast.market_stats(record[0].zip_code),
    )


def austin_brief(asking: float | None = 2350) -> Brief:
    """The synthetic-austin brief as of its recording day. No network."""
    listing = CurrentListing(asking_rent=asking, listed_date=date(2026, 9, 8)) if asking else None
    return build_brief(
        AUSTIN,
        OwnerFacts(),
        replay_provider(FIXTURES / "synthetic-austin", lambda: TODAY),
        today=TODAY,
        listing=listing,
    )
