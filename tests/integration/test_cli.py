"""End to end through the CLI and the RentCast adapter, replaying recorded responses."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from rentsmart import cli
from rentsmart.contracts import Brief, ExitCode
from rentsmart.providers.cache import ResponseCache, default_cache_dir
from rentsmart.providers.rentcast import PROPERTIES_PATH, RENT_AVM_PATH
from tests.conftest import ADDRESS, TODAY, ZORI_SAMPLE, load_fixture, route_fixtures

runner = CliRunner()


@pytest.fixture(autouse=True)
def cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENTCAST_API_KEY", "test-key")
    monkeypatch.setattr(cli, "_today", lambda: TODAY)


def test_readable_brief(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    result = runner.invoke(cli.app, [ADDRESS, "--roof-year", "2019"])
    assert result.exit_code == ExitCode.OK, result.output
    for heading in (
        "PROPERTY",
        "RENT ESTIMATE",
        "RENTAL COMPS",
        "MARKET SPEED",
        "PROPERTY TAX",
        "PRICING SCENARIOS",
        "SUGGESTIONS TO RENT FASTER",
        "QUESTIONS TO ASK YOUR AGENT",
        "Not an appraisal",
    ):
        assert heading in result.output
    assert "$1,850 - $2,250" in result.output


def test_json_is_the_full_brief(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    result = runner.invoke(cli.app, [ADDRESS, "--json"])
    assert result.exit_code == ExitCode.OK
    brief = Brief.model_validate_json(result.stdout)
    assert brief.rent_estimate is not None and brief.rent_estimate.low == 1850


def test_no_personal_data_in_output(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    result = runner.invoke(cli.app, [ADDRESS, "--json"])
    assert "SYNTHETIC OWNER" not in result.output


def test_api_key_sent_as_header(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    runner.invoke(cli.app, [ADDRESS])
    request = no_live_http.calls[0].request
    assert request.headers["X-Api-Key"] == "test-key"
    assert "test-key" not in str(request.url)


def test_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RENTCAST_API_KEY")
    result = runner.invoke(cli.app, [ADDRESS])
    assert result.exit_code == ExitCode.CONFIG_ERROR
    assert "RENTCAST_API_KEY" in result.output


def test_address_not_found(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http, properties=[])
    result = runner.invoke(cli.app, ["nowhere"])
    assert result.exit_code == ExitCode.ADDRESS_NOT_FOUND
    assert "Check the format" in result.output


def test_address_404_is_not_found(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    no_live_http.get(PROPERTIES_PATH).mock(return_value=httpx.Response(404))
    result = runner.invoke(cli.app, ["nowhere"])
    assert result.exit_code == ExitCode.ADDRESS_NOT_FOUND


def test_ambiguous_address(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http, properties=load_fixture("synthetic-ambiguous", "properties.json"))
    result = runner.invoke(cli.app, ["500 Sample Blvd, Gainesville, FL", "--json"])
    assert result.exit_code == ExitCode.AMBIGUOUS_ADDRESS
    assert len(json.loads(result.stdout)["candidates"]) == 2
    assert not no_live_http.routes[1].called  # stopped before pricing


def test_too_few_comps(no_live_http: respx.MockRouter) -> None:
    rent = load_fixture("synthetic-gainesville", "rent_long_term.json")
    rent["comparables"] = rent["comparables"][:1]
    route_fixtures(no_live_http, rent=rent)
    result = runner.invoke(cli.app, [ADDRESS])
    assert result.exit_code == ExitCode.TOO_FEW_COMPS
    assert "No reliable range" in result.output
    assert "140 Sample Ave" in result.output


def test_stale_data(no_live_http: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    route_fixtures(no_live_http)
    monkeypatch.setattr(cli, "_today", lambda: date(2027, 6, 1))
    result = runner.invoke(cli.app, [ADDRESS])
    assert result.exit_code == ExitCode.STALE_DATA
    assert "STALE DATA" in result.output


def test_quota_exceeded_returns_nothing_partial(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    no_live_http.get(RENT_AVM_PATH).mock(return_value=httpx.Response(429))
    result = runner.invoke(cli.app, [ADDRESS])
    assert result.exit_code == ExitCode.QUOTA_EXCEEDED
    assert "quota" in result.output
    assert "RENT ESTIMATE" not in result.output


def test_inactive_subscription_explains_why(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    body = {
        "status": 403,
        "error": "billing/subscription-inactive",
        "message": "The provided API key is not associated with an active API subscription.",
    }
    no_live_http.get(PROPERTIES_PATH).mock(return_value=httpx.Response(403, json=body))
    result = runner.invoke(cli.app, [ADDRESS])
    assert result.exit_code == ExitCode.PROVIDER_ERROR
    assert "not associated with an active API subscription" in result.output
    assert "test-key" not in result.output


def test_recorded_address(no_live_http: respx.MockRouter) -> None:
    """Replays real RentCast responses recorded 2026-10-20."""
    route_fixtures(no_live_http, slug="synthetic-austin")
    result = runner.invoke(cli.app, ["4120 Sample Dr, Austin, TX 78729", "--json"])
    assert result.exit_code == ExitCode.OK, result.output
    brief = Brief.model_validate_json(result.stdout)
    assert brief.facts.address.value == "4120 Sample Dr, Austin, TX 78729"
    assert brief.facts.match_confidence.value == 1.0
    assert brief.rent_estimate is not None
    assert (brief.rent_estimate.low, brief.rent_estimate.high) == (2040, 2480)
    assert len(brief.comps) == 10
    assert {c.value.basis for c in brief.comps if c.value} == {"asking"}
    assert brief.market.median_days_on_market is not None
    assert brief.property_tax is not None and brief.property_tax.value == 7770


def test_real_address_recent_support_and_gap_question(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http, slug="synthetic-austin")
    result = runner.invoke(cli.app, ["4120 Sample Dr, Austin, TX 78729", "--json"])
    brief = Brief.model_validate_json(result.stdout)
    assert brief.recent_comps is not None
    assert brief.recent_comps.value == 2100
    assert "7 of 10 comps" in brief.recent_comps.evidence[0]
    dates = [c.as_of for c in brief.comps]
    assert dates == sorted(dates, reverse=True)
    assert any("7% below" in (q.value or "") for q in brief.agent_questions)


def test_recorded_address_with_asking(no_live_http: respx.MockRouter) -> None:
    """A listing at $2,350 since 2026-09-08 (synthetic subject, recorded neighborhood)."""
    route_fixtures(no_live_http, slug="synthetic-austin")
    args = ["4120 Sample Dr, Austin, TX 78729", "--asking", "2350", "--listed", "2026-09-08"]
    brief = Brief.model_validate_json(runner.invoke(cli.app, [*args, "--json"]).stdout)
    listing = brief.listing
    assert listing is not None
    assert listing.range_position is not None and listing.range_position.value == "upper half"
    assert listing.vs_recent_comps is not None and listing.vs_recent_comps.value == 0.119
    assert listing.days_listed is not None and listing.days_listed.value == 42
    suggestions = " ".join(s.value or "" for s in brief.suggestions)
    assert "12702 Margit Dr" in suggestions
    assert "up longer than the zip median" in suggestions
    assert "Days on market in 78729 are rising" not in suggestions  # superseded
    questions = " ".join(q.value or "" for q in brief.agent_questions)
    assert "Your $2,350 asks 12% above" in questions
    assert "mid estimate" not in questions  # superseded


def test_listed_requires_asking(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    result = runner.invoke(cli.app, [ADDRESS, "--listed", "2026-09-04"])
    assert result.exit_code == 2
    assert "--asking" in result.output
    assert not no_live_http.calls  # rejected before any API call


def test_listed_cannot_be_future(no_live_http: respx.MockRouter) -> None:
    result = runner.invoke(cli.app, [ADDRESS, "--asking", "2000", "--listed", "2026-12-01"])
    assert result.exit_code == 2
    assert not no_live_http.calls


def test_gainesville_slow_listing(no_live_http: respx.MockRouter) -> None:
    """Real listing: $2,995 since 2026-05-21, after price cuts from $3,200."""
    route_fixtures(no_live_http, slug="gainesville-sw73rd")
    args = ["8184 SW 73rd Ln, Gainesville, FL 32608", "--asking", "2995", "--listed", "2026-05-21"]
    brief = Brief.model_validate_json(runner.invoke(cli.app, [*args, "--json"]).stdout)
    assert not any("more likely to rent quickly" in (s.value or "") for s in brief.suggestions)
    questions = " ".join(q.value or "" for q in brief.agent_questions)
    assert "up 152 days, 113 longer than the zip median" in questions
    assert "lower half of the estimated range" in questions


# --- Response cache --------------------------------------------------------------------


def test_second_run_uses_cache(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    assert runner.invoke(cli.app, [ADDRESS]).exit_code == ExitCode.OK
    assert len(no_live_http.calls) == 3
    result = runner.invoke(cli.app, [ADDRESS.upper()])
    assert result.exit_code == ExitCode.OK
    assert len(no_live_http.calls) == 3  # no new API calls


def test_refresh_fetches_again(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    runner.invoke(cli.app, [ADDRESS])
    runner.invoke(cli.app, [ADDRESS, "--refresh"])
    assert len(no_live_http.calls) == 6


def test_owner_overrides_change_only_the_rent_call(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    runner.invoke(cli.app, [ADDRESS])
    runner.invoke(cli.app, [ADDRESS, "--beds", "4"])
    assert len(no_live_http.calls) == 4  # rent AVM depends on beds; the rest is cached


def test_cached_data_shows_its_real_date(
    no_live_http: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The cache stamps entries with its own clock; pin it so the test doesn't depend on today.
    clock = [datetime(2026, 10, 20, 12, tzinfo=UTC)]
    monkeypatch.setattr(
        cli,
        "response_cache",
        lambda refresh: ResponseCache(
            default_cache_dir(), timedelta(days=7), read=not refresh, now=lambda: clock[0]
        ),
    )
    route_fixtures(no_live_http)
    runner.invoke(cli.app, [ADDRESS])
    clock[0] += timedelta(days=3)
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 10, 23))
    brief = Brief.model_validate_json(runner.invoke(cli.app, [ADDRESS, "--json"]).stdout)
    assert brief.facts.beds is not None and brief.facts.beds.as_of == date(2026, 10, 20)
    assert brief.rent_estimate is not None and brief.rent_estimate.as_of == date(2026, 10, 20)
    assert any("retrieved on 2026-10-20 (3 days ago)" in n for n in brief.notices)


def test_errors_are_not_cached(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    no_live_http.get(RENT_AVM_PATH).mock(return_value=httpx.Response(429))
    assert runner.invoke(cli.app, [ADDRESS]).exit_code == ExitCode.QUOTA_EXCEEDED
    route_fixtures(no_live_http)
    assert runner.invoke(cli.app, [ADDRESS]).exit_code == ExitCode.OK


def test_cache_can_be_disabled(
    no_live_http: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RENTSMART_CACHE_DAYS", "0")
    route_fixtures(no_live_http)
    runner.invoke(cli.app, [ADDRESS])
    runner.invoke(cli.app, [ADDRESS])
    assert len(no_live_http.calls) == 6


def test_html_written_beside_text_output(no_live_http: respx.MockRouter, tmp_path: Path) -> None:
    route_fixtures(no_live_http)
    out = tmp_path / "brief.html"
    result = runner.invoke(cli.app, [ADDRESS, "--asking", "2200", "--html", str(out)])
    assert result.exit_code == ExitCode.OK, result.output
    assert "RENT ESTIMATE" in result.stdout
    page = out.read_text()
    assert page.startswith("<!doctype html>") and "123 Example St" in page
    assert "<script src" not in page


def test_html_with_json(no_live_http: respx.MockRouter, tmp_path: Path) -> None:
    route_fixtures(no_live_http)
    out = tmp_path / "brief.html"
    result = runner.invoke(cli.app, [ADDRESS, "--json", "--html", str(out)])
    assert json.loads(result.stdout)["provider"] == "RentCast"
    assert out.exists()


def test_html_unwritable_path(no_live_http: respx.MockRouter, tmp_path: Path) -> None:
    route_fixtures(no_live_http)
    out = tmp_path / "missing-dir" / "brief.html"
    result = runner.invoke(cli.app, [ADDRESS, "--html", str(out)])
    assert result.exit_code == 1
    assert "Could not write" in result.output and "Traceback" not in result.output
    assert not out.exists()


def test_no_html_file_on_failure(no_live_http: respx.MockRouter, tmp_path: Path) -> None:
    route_fixtures(no_live_http, properties=[])
    out = tmp_path / "brief.html"
    result = runner.invoke(cli.app, [ADDRESS, "--html", str(out)])
    assert result.exit_code == ExitCode.ADDRESS_NOT_FOUND
    assert not out.exists()


def test_zip_rent_trend_from_zori_file(
    no_live_http: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    route_fixtures(no_live_http, slug="synthetic-austin")
    monkeypatch.setenv("RENTSMART_ZORI_CSV", str(ZORI_SAMPLE))
    result = runner.invoke(cli.app, ["4120 Sample Dr, Austin, TX 78729"])
    assert "ZIP RENT TREND (zip 78729)" in result.output
    assert "-2.4% over 12 months" in result.output and "Zillow" in result.output
    as_json = runner.invoke(cli.app, ["4120 Sample Dr, Austin, TX 78729", "--json"])
    assert Brief.model_validate_json(as_json.stdout).zip_rent_change is not None


def test_zip_rent_trend_absent_without_file(no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http, slug="synthetic-austin")
    result = runner.invoke(cli.app, ["4120 Sample Dr, Austin, TX 78729"])
    assert "ZIP RENT TREND" not in result.output


def test_bad_zori_path_is_a_config_error(
    no_live_http: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    route_fixtures(no_live_http, slug="synthetic-austin")
    monkeypatch.setenv("RENTSMART_ZORI_CSV", str(tmp_path / "missing.csv"))
    result = runner.invoke(cli.app, ["4120 Sample Dr, Austin, TX 78729"])
    assert result.exit_code == ExitCode.CONFIG_ERROR
    assert no_live_http.calls.call_count == 0  # checked before any paid call


def test_bad_zori_row_fails_before_any_call(
    no_live_http: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    route_fixtures(no_live_http, slug="synthetic-austin")
    bad = tmp_path / "zori.csv"
    bad.write_text(ZORI_SAMPLE.read_text().replace("1944.00", "N/A"))
    monkeypatch.setenv("RENTSMART_ZORI_CSV", str(bad))
    result = runner.invoke(cli.app, ["4120 Sample Dr, Austin, TX 78729"])
    assert result.exit_code == ExitCode.CONFIG_ERROR and "isn't a number" in result.output
    assert no_live_http.calls.call_count == 0
