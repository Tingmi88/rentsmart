import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from rentsmart.providers.cache import default_cache_dir
from rentsmart.providers.rentcast import MARKETS_PATH, PROPERTIES_PATH, RENT_AVM_PATH
from rentsmart.web import app as web_app
from rentsmart.web.app import create_app
from tests.conftest import ADDRESS, TODAY, load_fixture, route_fixtures

PORT = 8765
ORIGIN = f"http://127.0.0.1:{PORT}"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("RENTCAST_API_KEY", "test-key-SECRET")
    return TestClient(create_app(PORT, today=lambda: TODAY), base_url=ORIGIN)


def _run(client: TestClient, **fields: str) -> None:
    resp = client.post(
        "/brief",
        data={"address": ADDRESS, **fields},
        headers={"origin": ORIGIN},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def test_index(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200 and "0 used this month on this machine" in resp.text


def test_uncached_get_offers_run_and_spends_nothing(
    client: TestClient, no_live_http: respx.MockRouter
) -> None:
    route_fixtures(no_live_http)
    resp = client.get("/brief", params={"address": ADDRESS, "asking": "2200"})
    assert resp.status_code == 200 and "up to 3 RentCast calls" in resp.text
    assert no_live_http.calls.call_count == 0


def test_post_fetches_then_gets_and_whatifs_are_free(
    client: TestClient, no_live_http: respx.MockRouter
) -> None:
    route_fixtures(no_live_http)
    _run(client, asking="2200")
    calls = no_live_http.calls.call_count
    assert calls == 3
    page = client.get("/brief", params={"address": ADDRESS, "asking": "2200"})
    assert (
        page.status_code == 200 and 'id="panel-advice"' in page.text and "data-whatif" in page.text
    )
    live = client.get(
        "/brief/sections", params={"address": ADDRESS, "asking": "1900", "entered": "2200"}
    )
    assert live.status_code == 200 and "What-if $1,900 (entered $2,200)" in live.text
    assert no_live_http.calls.call_count == calls
    assert "3 used this month" in client.get("/").text


def test_redirect_keeps_query(client: TestClient, no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    resp = client.post(
        "/brief",
        data={"address": ADDRESS, "asking": "2200", "listed": "2026-09-01"},
        headers={"origin": ORIGIN},
        follow_redirects=False,
    )
    assert resp.headers["location"].startswith("/brief?address=")
    assert (
        "asking=2200" in resp.headers["location"]
        and "listed=2026-09-01" in resp.headers["location"]
    )


@pytest.mark.parametrize("host", ["evil.example:8765", "127.0.0.1:9999", "localhost"])
def test_foreign_host_refused(client: TestClient, host: str) -> None:
    assert client.get("/", headers={"host": host}).status_code == 400


@pytest.mark.parametrize("origin", ["https://evil.example", "http://127.0.0.1:9999", ""])
def test_cross_site_post_refused(
    client: TestClient, no_live_http: respx.MockRouter, origin: str
) -> None:
    route_fixtures(no_live_http)
    headers = {"origin": origin} if origin else {}
    resp = client.post("/brief", data={"address": ADDRESS}, headers=headers)
    assert resp.status_code == 403
    assert no_live_http.calls.call_count == 0


def test_referer_accepted_when_origin_missing(
    client: TestClient, no_live_http: respx.MockRouter
) -> None:
    route_fixtures(no_live_http)
    resp = client.post(
        "/brief",
        data={"address": ADDRESS},
        headers={"referer": f"{ORIGIN}/brief?x=1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


@pytest.mark.parametrize("asking", ["nan", "inf", "-5", "abc", "1e9", "0"])
def test_bad_asking_is_422(client: TestClient, no_live_http: respx.MockRouter, asking: str) -> None:
    resp = client.get("/brief", params={"address": ADDRESS, "asking": asking})
    assert resp.status_code == 422 and "Asking rent" in resp.text
    assert no_live_http.calls.call_count == 0


def test_listed_rules(client: TestClient) -> None:
    no_asking = client.get("/brief", params={"address": ADDRESS, "listed": "2026-09-01"})
    assert no_asking.status_code == 422 and "needs an asking rent" in no_asking.text
    future = client.get(
        "/brief", params={"address": ADDRESS, "asking": "2000", "listed": "2026-12-01"}
    )
    assert future.status_code == 422 and "be in the future" in future.text


def test_cache_disabled_explains(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENTSMART_CACHE_DAYS", "0")
    resp = client.get("/brief", params={"address": ADDRESS})
    assert resp.status_code == 500 and "needs the response cache" in resp.text


def test_named_failures(client: TestClient, no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http, properties=[])
    resp = client.post(
        "/brief", data={"address": ADDRESS}, headers={"origin": ORIGIN}, follow_redirects=False
    )
    assert resp.status_code == 404 and "exit 10" in resp.text


def test_ambiguous_links_are_escaped(client: TestClient, no_live_http: respx.MockRouter) -> None:
    records = load_fixture("synthetic-ambiguous", "properties.json")
    records[0]["formattedAddress"] = "<b>1 Evil St</b>, Gainesville, FL 32601"
    route_fixtures(no_live_http, properties=records)
    resp = client.post(
        "/brief", data={"address": ADDRESS}, headers={"origin": ORIGIN}, follow_redirects=False
    )
    assert resp.status_code == 409
    assert "<b>1 Evil St" not in resp.text and "&lt;b&gt;1 Evil St" in resp.text
    assert 'href="/brief?street=' in resp.text  # candidates link to the split fields


def test_quota_and_missing_key(
    client: TestClient, no_live_http: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_live_http.get(PROPERTIES_PATH).mock(return_value=httpx.Response(429))
    resp = client.post(
        "/brief", data={"address": ADDRESS}, headers={"origin": ORIGIN}, follow_redirects=False
    )
    assert resp.status_code == 429 and 'method="post"' not in resp.text
    monkeypatch.delenv("RENTCAST_API_KEY")
    resp = client.get("/brief", params={"address": ADDRESS})
    assert resp.status_code == 500 and "RENTCAST_API_KEY" in resp.text


def test_key_never_in_any_response(client: TestClient, no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    _run(client, asking="2200")
    bodies = [
        client.get("/").text,
        client.get("/brief", params={"address": ADDRESS, "asking": "2200"}).text,
        client.get("/brief/sections", params={"address": ADDRESS, "asking": "2000"}).text,
        client.get("/static/app.js").text,
    ]
    assert all("SECRET" not in b for b in bodies)


def test_whatif_after_expiry_does_not_fetch(
    client: TestClient, no_live_http: respx.MockRouter
) -> None:
    route_fixtures(no_live_http)
    resp = client.get("/brief/sections", params={"address": ADDRESS, "asking": "2000"})
    assert resp.status_code == 409 and "Data expired" in resp.text
    assert no_live_http.calls.call_count == 0


def test_static_whitelist(client: TestClient) -> None:
    assert client.get("/static/app.css").headers["content-type"].startswith("text/css")
    assert client.get("/static/../app.py").status_code == 404
    assert client.get("/static/render.py").status_code == 404


def test_ui_binds_localhost_only(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(web_app.uvicorn, "run", lambda app, **kw: seen.update(kw))
    monkeypatch.setattr(web_app.webbrowser, "open", lambda url: seen.update(url=url))
    result = CliRunner().invoke(web_app.cli, ["--port", "9999", "--no-open"])
    assert result.exit_code == 0, result.output
    assert seen["host"] == "127.0.0.1" and seen["port"] == 9999
    assert "url" not in seen
    assert "http://127.0.0.1:9999/" in result.output


def test_unwritable_cache_shows_fetched_brief_instead_of_looping(
    client: TestClient,
    no_live_http: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the cache dir should be")
    monkeypatch.setenv("RENTSMART_CACHE_DIR", str(blocker / "cache"))
    route_fixtures(no_live_http)
    resp = client.post(
        "/brief", data={"address": ADDRESS}, headers={"origin": ORIGIN}, follow_redirects=False
    )
    assert resp.status_code == 200 and 'id="panel-advice"' in resp.text
    assert "be saved to the cache" in resp.text
    assert no_live_http.calls.call_count == 3


def test_concurrent_runs_fetch_once(client: TestClient, no_live_http: respx.MockRouter) -> None:
    route_fixtures(no_live_http)
    reply = load_fixture("synthetic-gainesville", "properties.json")

    def slow(request: httpx.Request) -> httpx.Response:
        time.sleep(0.2)  # both requests are in flight before either caches
        return httpx.Response(200, json=reply)

    no_live_http.get(PROPERTIES_PATH).mock(side_effect=slow)

    def run() -> int:
        return client.post(
            "/brief",
            data={"address": ADDRESS},
            headers={"origin": ORIGIN},
            follow_redirects=False,
        ).status_code

    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(lambda _: run(), range(2))) == [303, 303]
    assert no_live_http.calls.call_count == 3


FIELDS = {"street": "123 Example St", "city": "Gainesville", "state": "fl", "zip": "32601"}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"street": ""}, "Enter the street address"),
        ({"city": " "}, "Enter the city"),
        ({"state": "Florida"}, "State must be a 2-letter code"),
        ({"state": "XX"}, "State must be a 2-letter code"),
        ({"zip": "3260"}, "ZIP must be 5 digits"),
        ({"zip": "32601-12"}, "ZIP must be 5 digits"),
    ],
)
def test_split_fields_are_checked(
    client: TestClient, no_live_http: respx.MockRouter, change: dict[str, str], message: str
) -> None:
    resp = client.get("/brief", params={**FIELDS, **change})
    assert resp.status_code == 422 and message in resp.text
    assert 'value="123 Example St"' in resp.text or change == {"street": ""}  # refilled
    assert no_live_http.calls.call_count == 0


def test_split_fields_join_into_one_address(
    client: TestClient, no_live_http: respx.MockRouter
) -> None:
    route_fixtures(no_live_http)
    resp = client.post("/brief", data=FIELDS, headers={"origin": ORIGIN}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == (
        "/brief?street=123+Example+St&city=Gainesville&state=FL&zip=32601"
    )
    assert no_live_http.calls[0].request.url.params["address"] == ADDRESS
    page = client.get(resp.headers["location"])
    assert page.status_code == 200 and 'id="panel-advice"' in page.text


def test_index_splits_a_one_line_address(client: TestClient) -> None:
    page = client.get("/", params={"address": ADDRESS}).text
    assert 'value="123 Example St"' in page and 'value="Gainesville"' in page
    assert 'value="FL"' in page and 'value="32601"' in page


def _age_cache(days: int, *paths: str) -> None:
    """Backdate saved responses (all of them, or only those for `paths`)."""
    for file in default_cache_dir().glob("*.json"):
        entry = json.loads(file.read_text())
        if "path" in entry and (not paths or entry["path"] in paths):
            entry["fetched_at"] = (datetime.now(UTC) - timedelta(days=days)).isoformat()
            file.write_text(json.dumps(entry))


def test_old_saved_data_opens_with_refresh_offer(
    client: TestClient, no_live_http: respx.MockRouter
) -> None:
    route_fixtures(no_live_http)
    _run(client, asking="2200")
    calls = no_live_http.calls.call_count
    _age_cache(10)
    page = client.get("/brief", params={"address": ADDRESS, "asking": "2200"})
    assert page.status_code == 200 and 'id="panel-advice"' in page.text
    assert "10 days old" in page.text and "Refresh (about 3 calls)" in page.text
    live = client.get(
        "/brief/sections", params={"address": ADDRESS, "asking": "1900", "entered": "2200"}
    )
    assert live.status_code == 200 and "What-if $1,900" in live.text
    assert no_live_http.calls.call_count == calls


def test_refresh_counts_only_expired_parts(
    client: TestClient, no_live_http: respx.MockRouter
) -> None:
    route_fixtures(no_live_http)
    _run(client)
    _age_cache(10, RENT_AVM_PATH, MARKETS_PATH)
    page = client.get("/brief", params={"address": ADDRESS})
    assert "Refresh (about 2 calls)" in page.text
    calls = no_live_http.calls.call_count
    resp = client.post(
        "/brief", data={"address": ADDRESS}, headers={"origin": ORIGIN}, follow_redirects=False
    )
    assert resp.status_code == 303 and no_live_http.calls.call_count == calls + 2
    assert "Refresh (" not in client.get("/brief", params={"address": ADDRESS}).text


def test_fresh_data_has_no_refresh_offer(
    client: TestClient, no_live_http: respx.MockRouter
) -> None:
    route_fixtures(no_live_http)
    _run(client)
    assert "Refresh (" not in client.get("/brief", params={"address": ADDRESS}).text
