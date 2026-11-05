"""Similar saved addresses are offered before any paid lookup (CLI, provider, and local UI)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from rentsmart import cli
from rentsmart.contracts import ExitCode, SimilarAddress
from rentsmart.providers.cache import ResponseCache
from rentsmart.providers.rentcast import PROPERTIES_PATH, RentCastProvider
from rentsmart.web.app import create_app
from tests.conftest import AUSTIN, TODAY, load_fixture, route_fixtures

TYPO = "4120 sample dr Austin TX, 78279"
PORT = 8765
ORIGIN = f"http://127.0.0.1:{PORT}"
runner = CliRunner()


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENTCAST_API_KEY", "test-key")
    monkeypatch.setattr(cli, "_today", lambda: TODAY)


def _provider(tmp_path: Path, *, check: bool = True, read: bool = True) -> RentCastProvider:
    cache = ResponseCache(tmp_path / "c", timedelta(days=7), read=read)
    return RentCastProvider("test-key", cache=cache, check_similar=check)


def _seed(router: respx.MockRouter, tmp_path: Path) -> int:
    route_fixtures(router, "synthetic-austin")
    _provider(tmp_path, check=False).resolve_address(AUSTIN)
    return router.calls.call_count


def test_typo_raises_similar_without_a_call(no_live_http: respx.MockRouter, tmp_path: Path) -> None:
    calls = _seed(no_live_http, tmp_path)
    with pytest.raises(SimilarAddress) as err:
        _provider(tmp_path).resolve_address(TYPO)
    assert [c for c, _ in err.value.candidates] == [AUSTIN]
    assert err.value.exit_code == ExitCode.SIMILAR_ADDRESS
    assert no_live_http.calls.call_count == calls


def test_same_address_other_wording_reuses_saved_lookup(
    no_live_http: respx.MockRouter, tmp_path: Path
) -> None:
    calls = _seed(no_live_http, tmp_path)
    records = _provider(tmp_path).resolve_address("4120 sample drive, austin tx 78729")
    assert [r.formatted_address for r in records] == [AUSTIN]
    assert no_live_http.calls.call_count == calls


def test_check_off_looks_up_as_typed(no_live_http: respx.MockRouter, tmp_path: Path) -> None:
    calls = _seed(no_live_http, tmp_path)
    _provider(tmp_path, check=False).resolve_address(TYPO)
    assert no_live_http.calls.call_count == calls + 1


def test_refresh_never_reuses_saved_lookup(no_live_http: respx.MockRouter, tmp_path: Path) -> None:
    calls = _seed(no_live_http, tmp_path)
    refresh = _provider(tmp_path, check=False, read=False)
    refresh.resolve_address("4120 sample drive austin tx 78729")
    assert no_live_http.calls.call_count == calls + 1


def test_unrelated_address_is_not_blocked(no_live_http: respx.MockRouter, tmp_path: Path) -> None:
    calls = _seed(no_live_http, tmp_path)
    _provider(tmp_path).resolve_address("12 Other Rd, Austin, TX 78729")
    assert no_live_http.calls.call_count == calls + 1


def test_cli_suggests_and_spends_nothing(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http, "synthetic-austin")
    assert runner.invoke(cli.app, [AUSTIN]).exit_code == ExitCode.OK
    calls = no_live_http.calls.call_count
    result = runner.invoke(cli.app, [TYPO])
    assert result.exit_code == ExitCode.SIMILAR_ADDRESS
    assert AUSTIN in result.output and "--run-anyway" in result.output
    as_json = json.loads(runner.invoke(cli.app, [TYPO, "--json"]).output)
    assert as_json["candidates"][0]["address"] == AUSTIN
    assert no_live_http.calls.call_count == calls
    assert runner.invoke(cli.app, [TYPO, "--run-anyway"]).exit_code == ExitCode.OK
    assert no_live_http.calls.call_count == calls + 1  # rent and market data were cached


def _client() -> TestClient:
    return TestClient(create_app(PORT, today=lambda: TODAY), base_url=ORIGIN)


def test_ui_did_you_mean_links_split_fields(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http, "synthetic-austin")
    assert runner.invoke(cli.app, [AUSTIN]).exit_code == ExitCode.OK
    calls = no_live_http.calls.call_count
    client = _client()
    fields = {"street": "4120 sample dr", "city": "Austin", "state": "TX", "zip": "78279"}
    page = client.get("/brief", params={**fields, "asking": "2350"})
    assert page.status_code == 200 and "Did you mean" in page.text
    assert "street=4120+Sample+Dr&amp;city=Austin&amp;state=TX&amp;zip=78729" in page.text
    assert "asking=2350" in page.text and "Run as entered" in page.text
    picked = client.get(
        "/brief",
        params={"street": "4120 Sample Dr", "city": "Austin", "state": "TX", "zip": "78729"},
    )
    assert picked.status_code == 200 and 'id="panel-advice"' in picked.text
    assert no_live_http.calls.call_count == calls


def test_ui_run_as_entered_skips_the_check(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http, "synthetic-austin")
    assert runner.invoke(cli.app, [AUSTIN]).exit_code == ExitCode.OK
    calls = no_live_http.calls.call_count
    fields = {"street": "4120 sample dr", "city": "Austin", "state": "TX", "zip": "78279"}
    resp = _client().post("/brief", data=fields, headers={"origin": ORIGIN}, follow_redirects=False)
    assert resp.status_code == 303
    assert no_live_http.calls.call_count == calls + 1


def test_freshest_saved_lookup_wins_over_older_exact_text(tmp_path: Path) -> None:
    root = tmp_path / "c"
    data = load_fixture("synthetic-austin", "properties.json")
    now = datetime.now(UTC)
    old = ResponseCache(root, timedelta(days=7), now=lambda: now - timedelta(days=10))
    old.put(PROPERTIES_PATH, {"address": AUSTIN}, data)
    ResponseCache(root, timedelta(days=7)).put(
        PROPERTIES_PATH, {"address": "4120 Sample Drive, Austin, TX 78729"}, data
    )
    provider = RentCastProvider(
        "test-key", cache=ResponseCache(root, timedelta.max), offline=True, check_similar=True
    )
    provider.resolve_address(AUSTIN)
    assert now - provider.saved_at[PROPERTIES_PATH] < timedelta(minutes=1)


def test_exact_text_never_asks_did_you_mean(tmp_path: Path) -> None:
    root = tmp_path / "c"
    data = load_fixture("synthetic-austin", "properties.json")
    ResponseCache(root, timedelta(days=7)).put(PROPERTIES_PATH, {"address": "4120 sample Dr"}, data)
    provider = RentCastProvider(
        "test-key", cache=ResponseCache(root, timedelta(days=7)), offline=True, check_similar=True
    )
    assert [r.formatted_address for r in provider.resolve_address("4120 sample Dr")] == [AUSTIN]
