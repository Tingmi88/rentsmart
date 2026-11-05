from rentsmart.contracts import Brief
from rentsmart.web import view
from tests.conftest import austin_brief


def _with_gap(brief: Brief, gap: float) -> Brief:
    lst = brief.listing
    assert lst is not None and lst.vs_recent_comps is not None
    env = lst.vs_recent_comps.model_copy(update={"value": gap})
    return brief.model_copy(update={"listing": lst.model_copy(update={"vs_recent_comps": env})})


def test_chips_restate_listing_checks() -> None:
    chips = view.checks(austin_brief())
    assert [c.label for c in chips] == ["In range", "+11.9% vs recent comps", "42 days listed"]
    assert [c.warn for c in chips] == [False, True, True]
    assert chips[2].detail == "zip median 41"


def test_gap_chip_flips_exactly_at_recent_gap() -> None:
    assert view.checks(_with_gap(austin_brief(), 0.05))[1].warn
    assert not view.checks(_with_gap(austin_brief(), 0.0499))[1].warn
    assert view.checks(_with_gap(austin_brief(), -0.05))[1].warn


def test_no_asking_no_chips() -> None:
    assert view.checks(austin_brief(asking=None)) == []


def test_price_line_marks_and_stacking() -> None:
    line = view.price_line(austin_brief())
    assert line is not None
    kinds = [m.kind for m in line.marks]
    assert kinds.count("mid") == 1 and kinds.count("asking") == 1 and kinds.count("recent") == 1
    assert sum(k.startswith("comp") for k in kinds) == 10
    assert sorted(m.row for m in line.marks if m.title.endswith("$2,100 (inactive)")) == [0, 1, 2]
    assert all(0 <= m.pct <= 100 for m in line.marks)
    assert all(18 <= lb.pct <= 82 for lb in line.labels)
    assert 0 < line.low_pct < line.high_pct < 100


def test_slider_bounds() -> None:
    s = view.slider(austin_brief())
    assert s == view.Slider(min=1725, max=2875, step=25, mid=2250)


def test_slider_stretches_to_include_asking() -> None:
    s = view.slider(austin_brief(asking=4000))
    assert s is not None and s.max >= 4000


def test_market_history_and_sparkline() -> None:
    history = view.market_history(austin_brief())
    assert history[0] == ("2026-05", 28.0) and history[-1] == ("2026-10", 41.0)
    spark = view.sparkline(history)
    assert spark is not None and spark.first == "2026-05" and spark.last_value == 41.0
    assert len(spark.points.split()) == 6
    assert view.sparkline(history[:1]) is None


def test_comp_rows_divider_before_first_stale() -> None:
    rows = view.comp_rows(austin_brief())
    assert [r.divider_before for r in rows].count(True) == 1
    first_stale = next(i for i, r in enumerate(rows) if r.stale)
    assert rows[first_stale].divider_before


def test_no_range_means_no_line_or_slider() -> None:
    bare = austin_brief().model_copy(
        update={"rent_estimate": None, "comps": [], "too_few_comps": True}
    )
    assert view.price_line(bare) is None
    assert view.slider(bare) is None


def test_fact_line_and_details() -> None:
    brief = austin_brief()
    assert view.fact_line(brief) == "Single Family · 4 bd · 2.5 ba · 1,880 sqft · built 1996"
    labels = [r.label for r in view.detail_rows(brief)]
    assert "Rent estimate" in labels and "Asking rent" in labels and "Property tax" in labels
    assert view.money(2350) == "$2,350"


def test_search_url_encodes_full_address() -> None:
    url = view.search_url("123 Main St # 2, Gainesville, FL 32601")
    assert url == "https://www.google.com/search?q=123+Main+St+%23+2%2C+Gainesville%2C+FL+32601"


def test_zillow_url_uses_address_search_slug() -> None:
    url = view.zillow_url("1204 Tomanet Trl, Austin, TX 78748")
    assert url == "https://www.zillow.com/homes/1204-Tomanet-Trl,-Austin,-TX-78748_rb/"


def test_zillow_url_encodes_unit_and_slash() -> None:
    url = view.zillow_url("12 1/2 Oak  Ave # 4B, Austin, TX 78748")
    assert url == "https://www.zillow.com/homes/12-1%2F2-Oak-Ave-%23-4B,-Austin,-TX-78748_rb/"
