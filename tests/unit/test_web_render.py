import re
from datetime import date

from rentsmart.contracts import AmbiguousAddress
from rentsmart.web.render import (
    render_error,
    render_index,
    render_live,
    render_not_cached,
    render_page,
)
from tests.conftest import austin_brief

SECTIONS = ("panel-advice", "panel-comps", "panel-market", "panel-scenarios", "panel-details")


def test_file_page_has_every_section_and_no_external_assets() -> None:
    html = render_page(austin_brief())
    for section in SECTIONS:
        assert f'id="{section}"' in html
    assert "<script src" not in html and "<link" not in html
    assert re.search(r'src="https?://', html) is None  # outbound <a> links are fine
    assert "Not an appraisal" in html
    assert "<form" not in html  # static file has no editable control


def test_page_shows_badges_divider_and_chips() -> None:
    html = render_page(austin_brief())
    assert "Older than 90 days" in html and "STALE" in html
    assert "+11.9% vs recent comps" in html and 'class="chip warn"' in html
    assert "12702 Margit Dr" in html


def test_unconfirmed_badge() -> None:
    brief = austin_brief()
    first = brief.comps[0]
    assert first.value is not None
    comp = first.model_copy(update={"value": first.value.model_copy(update={"unconfirmed": True})})
    html = render_page(brief.model_copy(update={"comps": [comp, *brief.comps[1:]]}))
    assert "UNCONFIRMED" in html


def test_app_page_links_assets_and_has_control() -> None:
    html = render_page(austin_brief(), app=True, entered=2350)
    assert '<script src="/static/app.js"' in html and "data-whatif" in html
    assert 'name="entered" value="2350"' in html


def test_what_if_label_only_when_changed() -> None:
    assert "What-if $2,250 (entered $2,350)" in render_live(austin_brief(2250), entered=2350)
    assert "What-if" not in render_live(austin_brief(2350), entered=2350)


def test_vendor_strings_are_escaped() -> None:
    brief = austin_brief()
    addr = brief.facts.address.model_copy(update={"value": "<script>alert(1)</script>"})
    facts = brief.facts.model_copy(update={"address": addr})
    html = render_page(brief.model_copy(update={"facts": facts}))
    assert "<script>alert(1)" not in html and "&lt;script&gt;alert(1)" in html


def test_no_range_brief_renders_banner_without_line() -> None:
    bare = austin_brief().model_copy(
        update={"rent_estimate": None, "comps": [], "too_few_comps": True}
    )
    html = render_page(bare, app=True)
    assert "Too few comps" in html and 'class="pl"' not in html and 'type="range"' not in html


def test_index_not_cached_and_error_pages() -> None:
    assert "18 used this month on this machine" in render_index(usage=18)
    page = render_not_cached("1 A St", {"address": "1 A St", "asking": "2000"}, usage=18)
    assert 'method="post"' in page and "up to 3 RentCast calls" in page
    assert 'name="asking" value="2000"' in page and "Did you mean" not in page
    similar = [("<b>1 A Street</b>", date(2026, 10, 26), "/brief?x")]
    page = render_not_cached("1 A St", {"address": "1 A St"}, usage=18, similar=similar)
    assert "Did you mean" in page and "looked up Oct 26, 2026" in page
    assert "&lt;b&gt;1 A Street" in page and "Run as entered" in page
    err = AmbiguousAddress("1 A St", ["1 A St #1", "<b>1 A St #2</b>"])
    html = render_error(err, address="1 A St", links=[(c, "/brief?x") for c in err.candidates])
    assert "&lt;b&gt;1 A St #2" in html and 'href="/brief?x"' in html


def test_empty_envelope_values_render() -> None:
    brief = austin_brief()
    market = brief.market
    assert market.median_days_on_market is not None and brief.recent_comps is not None
    empty_dom = market.median_days_on_market.model_copy(update={"value": None})
    scenario = brief.scenarios[0].model_copy(update={"value": None})
    recent = brief.recent_comps.model_copy(update={"evidence": []})
    match = brief.facts.match_confidence.model_copy(update={"value": None})
    brief = brief.model_copy(
        update={
            "market": market.model_copy(update={"median_days_on_market": empty_dom}),
            "scenarios": [scenario, *brief.scenarios[1:]],
            "recent_comps": recent,
            "facts": brief.facts.model_copy(update={"match_confidence": match}),
        }
    )
    html = render_page(brief, app=True)
    assert 'id="panel-market"' in html and "No market statistics." in html


def test_comp_rows_link_to_search_and_zillow() -> None:
    html = render_page(austin_brief())
    first = austin_brief().comps[0].value
    assert first is not None
    count = len(austin_brief().comps)
    assert html.count('href="https://www.google.com/search?q=') == count
    assert html.count('href="https://www.zillow.com/homes/') == count
    assert html.count('rel="noopener noreferrer"') == 2 * count
    assert f'aria-label="Search the web for {first.address}"' in html


def test_index_form_remembers_last_entry() -> None:
    html = render_index(usage=0)
    assert "data-remember" in html and "data-clear" in html


def test_market_panel_shows_zip_rent_trend() -> None:
    from rentsmart.core.market import build_rent_change
    from rentsmart.providers.zori import ZoriFile
    from tests.conftest import ZORI_SAMPLE

    change = build_rent_change(ZoriFile(ZORI_SAMPLE).rent_index("78729"))
    html = render_page(austin_brief().model_copy(update={"zip_rent_change": change}))
    assert "Zip rent trend" in html and "-2.4%" in html and "Zillow" in html
    assert "Zip rent trend" not in render_page(austin_brief())
