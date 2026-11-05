import re

import pytest
import respx
from playwright.sync_api import Page, expect

from tests.conftest import route_fixtures

pytestmark = pytest.mark.ui

ENTRY = {
    "street": "123 Example St",
    "city": "Gainesville",
    "state": "FL",
    "zip": "32601",
    "asking": "2200",
}


def _fill(page: Page, entry: dict[str, str]) -> None:
    for name, value in entry.items():
        page.locator(f'input[name="{name}"]').fill(value)


def _expect_form(page: Page, entry: dict[str, str]) -> None:
    for name, value in entry.items():
        expect(page.locator(f'input[name="{name}"]')).to_have_value(value)


def test_form_remembers_last_entry_and_clear_forgets_it(page: Page, app_url: str) -> None:
    page.goto(app_url + "/")
    _fill(page, ENTRY)
    page.get_by_role("button", name="Show brief").click()
    expect(page.get_by_role("heading", name="Not cached")).to_be_visible()

    page.get_by_role("link", name="← New address").click()
    _expect_form(page, ENTRY)

    page.get_by_role("button", name="Clear").click()
    _expect_form(page, dict.fromkeys(ENTRY, ""))
    page.reload()
    _expect_form(page, dict.fromkeys(ENTRY, ""))


def test_server_values_win_over_remembered_entry(page: Page, app_url: str) -> None:
    page.goto(app_url + "/")
    _fill(page, ENTRY)
    page.get_by_role("button", name="Show brief").click()
    expect(page.get_by_role("heading", name="Not cached")).to_be_visible()
    assert page.evaluate("localStorage.getItem('rentsmart:last-entry')") is not None
    page.goto(app_url + "/?street=9+Other+Rd&city=Ocala&state=FL&zip=34470")
    _expect_form(page, {"street": "9 Other Rd", "city": "Ocala", "asking": ""})


def test_run_brief_then_tabs_whatif_and_comp_links(
    page: Page, app_url: str, no_live_http: respx.MockRouter
) -> None:
    route_fixtures(no_live_http)
    page.goto(app_url + "/")
    _fill(page, ENTRY)
    page.get_by_role("button", name="Show brief").click()
    page.get_by_role("button", name=re.compile(r"^Run")).click()
    expect(page.get_by_role("tab", name="Advice")).to_have_attribute("aria-selected", "true")
    assert no_live_http.calls.call_count == 3

    page.get_by_role("tab", name=re.compile(r"^Comps")).click()
    comps = page.locator("#panel-comps")
    expect(comps).to_be_visible()
    search = comps.get_by_role("link", name=re.compile(r"^Search the web for "))
    zillow = comps.get_by_role("link", name=re.compile(r" on Zillow$"))
    expect(search.first).to_have_attribute(
        "href", re.compile(r"^https://www\.google\.com/search\?q=")
    )
    expect(zillow.first).to_have_attribute(
        "href", re.compile(r"^https://www\.zillow\.com/homes/.+_rb/$")
    )
    expect(zillow.first).to_have_attribute("target", "_blank")
    assert search.count() == zillow.count() > 0

    page.locator('form[data-whatif] input[name="asking"]').fill("1900")
    expect(page.locator(".whatif")).to_have_text("What-if $1,900 (entered $2,200)")
    expect(comps).to_be_visible()  # the live update keeps the open tab
    assert no_live_http.calls.call_count == 3  # what-ifs and tab switches spend nothing
