from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from rentsmart.contracts import ProviderError, QuotaExceeded
from rentsmart.core.engine import build_brief
from rentsmart.core.facts import OwnerFacts
from rentsmart.providers.cache import CacheMiss, ResponseCache, UsageLog
from rentsmart.providers.rentcast import PROPERTIES_PATH, RentCastProvider
from tests.conftest import ADDRESS, TODAY, route_fixtures


def _provider(tmp_path: Path, *, offline: bool) -> RentCastProvider:
    return RentCastProvider(
        "test-key",
        cache=ResponseCache(tmp_path / "c", timedelta(days=7)),
        offline=offline,
        usage=UsageLog(tmp_path / "c", today=lambda: TODAY),
    )


def test_offline_miss_makes_no_request(no_live_http: respx.MockRouter, tmp_path: Path) -> None:
    route_fixtures(no_live_http)
    with pytest.raises(CacheMiss) as err:
        _provider(tmp_path, offline=True).resolve_address(ADDRESS)
    assert err.value.path == PROPERTIES_PATH
    assert no_live_http.calls.call_count == 0


def test_offline_brief_after_online_fetch(no_live_http: respx.MockRouter, tmp_path: Path) -> None:
    route_fixtures(no_live_http)
    online = build_brief(ADDRESS, OwnerFacts(), _provider(tmp_path, offline=False), today=TODAY)
    calls = no_live_http.calls.call_count
    offline = build_brief(ADDRESS, OwnerFacts(), _provider(tmp_path, offline=True), today=TODAY)
    assert no_live_http.calls.call_count == calls
    assert offline.rent_estimate == online.rent_estimate


def test_usage_counts_live_responses_only(no_live_http: respx.MockRouter, tmp_path: Path) -> None:
    route_fixtures(no_live_http)
    log = UsageLog(tmp_path / "c", today=lambda: TODAY)
    build_brief(ADDRESS, OwnerFacts(), _provider(tmp_path, offline=False), today=TODAY)
    assert log.this_month() == 3
    build_brief(ADDRESS, OwnerFacts(), _provider(tmp_path, offline=False), today=TODAY)  # cached
    assert log.this_month() == 3


def test_usage_counts_quota_errors_not_network_errors(
    no_live_http: respx.MockRouter, tmp_path: Path
) -> None:
    log = UsageLog(tmp_path / "c", today=lambda: TODAY)
    no_live_http.get(PROPERTIES_PATH).mock(return_value=httpx.Response(429))
    with pytest.raises(QuotaExceeded):
        _provider(tmp_path, offline=False).resolve_address(ADDRESS)
    assert log.this_month() == 1
    no_live_http.get(PROPERTIES_PATH).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(ProviderError, match="Could not reach"):
        _provider(tmp_path, offline=False).resolve_address(ADDRESS)
    assert log.this_month() == 1


def test_usage_is_per_month_and_survives_corrupt_file(tmp_path: Path) -> None:
    (tmp_path / "usage.json").write_text("not json")
    log = UsageLog(tmp_path, today=lambda: date(2026, 10, 31))
    assert log.this_month() == 0
    log.record()
    assert log.this_month() == 1
    assert UsageLog(tmp_path, today=lambda: date(2026, 11, 1)).this_month() == 0
    assert "test-key" not in (tmp_path / "usage.json").read_text()
