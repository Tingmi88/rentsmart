"""Phase 4: every way the provider can fail ends in a named failure, never a traceback."""

import httpx
import pytest
import respx
from typer.testing import CliRunner

from rentsmart import cli
from rentsmart.contracts import ExitCode
from rentsmart.providers.rentcast import MARKETS_PATH, PROPERTIES_PATH, RENT_AVM_PATH
from tests.conftest import ADDRESS, TODAY, route_fixtures

runner = CliRunner()


@pytest.fixture(autouse=True)
def cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENTCAST_API_KEY", "test-key")
    monkeypatch.setattr(cli, "_today", lambda: TODAY)


def _run(router: respx.MockRouter, path: str, **mock: object) -> tuple[int, str]:
    route_fixtures(router)
    router.get(path).mock(**mock)  # pyright: ignore[reportArgumentType]
    result = runner.invoke(cli.app, [ADDRESS])
    assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
    return result.exit_code, result.output


@pytest.mark.parametrize("path", [PROPERTIES_PATH, RENT_AVM_PATH, MARKETS_PATH])
def test_network_failure(no_live_http: respx.MockRouter, path: str) -> None:
    code, output = _run(no_live_http, path, side_effect=httpx.ConnectError("connection refused"))
    assert code == ExitCode.PROVIDER_ERROR
    assert "Could not reach RentCast" in output


def test_timeout(no_live_http: respx.MockRouter) -> None:
    code, output = _run(no_live_http, RENT_AVM_PATH, side_effect=httpx.ReadTimeout("slow"))
    assert code == ExitCode.PROVIDER_ERROR
    assert "Could not reach RentCast" in output


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_error(no_live_http: respx.MockRouter, status: int) -> None:
    code, output = _run(no_live_http, MARKETS_PATH, return_value=httpx.Response(status))
    assert code == ExitCode.PROVIDER_ERROR
    assert f"HTTP {status}" in output


def test_quota_on_first_call(no_live_http: respx.MockRouter) -> None:
    code, output = _run(no_live_http, PROPERTIES_PATH, return_value=httpx.Response(429))
    assert code == ExitCode.QUOTA_EXCEEDED
    assert "PROPERTY" not in output


def test_response_not_json(no_live_http: respx.MockRouter) -> None:
    code, output = _run(
        no_live_http, RENT_AVM_PATH, return_value=httpx.Response(200, text="<html>oops</html>")
    )
    assert code == ExitCode.PROVIDER_ERROR
    assert "isn't JSON" in output


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (PROPERTIES_PATH, [{"zipCode": "32601"}]),  # no formattedAddress
        (PROPERTIES_PATH, ["not an object"]),
        (RENT_AVM_PATH, [1, 2, 3]),  # list where an object is expected
        (RENT_AVM_PATH, {"rent": 2000, "comparables": [{"formattedAddress": "x"}]}),  # no price
        (MARKETS_PATH, {"rentalData": {"history": {"2026-13": {"medianDaysOnMarket": 5}}}}),
    ],
)
def test_unexpected_shape(no_live_http: respx.MockRouter, path: str, body: object) -> None:
    code, output = _run(no_live_http, path, return_value=httpx.Response(200, json=body))
    assert code == ExitCode.PROVIDER_ERROR
    assert "unexpected response" in output


def test_bad_stale_threshold(
    no_live_http: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RENTSMART_STALE_AFTER_DAYS", "ninety")
    route_fixtures(no_live_http)
    result = runner.invoke(cli.app, [ADDRESS])
    assert result.exit_code == ExitCode.CONFIG_ERROR
    assert not no_live_http.calls
