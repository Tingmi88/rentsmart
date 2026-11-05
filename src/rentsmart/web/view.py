"""Display data for the HTML brief. Restates values already in the brief; adds no advice."""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from rentsmart.contracts import Brief, Comp, Envelope
from rentsmart.core.rules import RECENT_GAP

SLIDER_SPAN = 0.15
SLIDER_STEP = 25
LABEL_MIN, LABEL_MAX = 18.0, 82.0  # keep centred labels inside the line on phones
_HISTORY = re.compile(r"^(\d{4}-\d{2}): median (\d+(?:\.\d+)?)$")
_OUTSIDE = ("above range", "below range")


def money(amount: float | None) -> str:
    return "n/a" if amount is None else f"${amount:,.0f}"


def _num(value: float | None) -> str:
    return "?" if value is None else f"{value:g}"


@dataclass(frozen=True)
class Chip:
    label: str
    detail: str
    warn: bool


def checks(brief: Brief) -> list[Chip]:
    lst = brief.listing
    if lst is None:
        return []
    chips: list[Chip] = []
    if lst.range_position is not None and (pos := lst.range_position.value) is not None:
        outside = pos in _OUTSIDE
        chips.append(Chip("Outside range" if outside else "In range", pos, outside))
    recent = brief.recent_comps.value if brief.recent_comps else None
    gap = lst.vs_recent_comps.value if lst.vs_recent_comps else None
    if gap is not None and recent is not None:
        label = f"{gap * 100:+.1f}% vs recent comps"
        chips.append(Chip(label, f"median {money(recent)}", abs(gap) >= RECENT_GAP))
    days = lst.days_listed.value if lst.days_listed else None
    median = brief.market.median_days_on_market
    zip_days = median.value if median else None
    if days is not None and zip_days is not None:
        chips.append(Chip(f"{days} days listed", f"zip median {zip_days:.0f}", days > zip_days))
    return chips


@dataclass(frozen=True)
class Mark:
    kind: str  # comp, comp-active, comp-old, mid, asking, recent
    pct: float
    row: int
    title: str


@dataclass(frozen=True)
class Label:
    kind: str  # asking, mid, recent
    pct: float
    text: str


@dataclass(frozen=True)
class PriceLine:
    low_pct: float
    high_pct: float
    marks: list[Mark]
    labels: list[Label]


def _asking(brief: Brief) -> float | None:
    return brief.listing.asking_rent.value if brief.listing else None


def _comps(brief: Brief) -> list[tuple[Comp, bool]]:
    """Comps with their stale flag, skipping any envelope without a value."""
    return [(env.value, env.stale) for env in brief.comps if env.value is not None]


def price_line(brief: Brief) -> PriceLine | None:
    est = brief.rent_estimate
    if est is None or est.value is None or est.low is None or est.high is None:
        return None
    mid, asking = est.value, _asking(brief)
    recent = brief.recent_comps.value if brief.recent_comps else None
    comps = _comps(brief)
    prices = [c.price for c, _ in comps] + [est.low, est.high]
    prices += [p for p in (asking, recent) if p is not None]
    lo, hi = min(prices), max(prices)
    pad = (hi - lo) * 0.05 or 50.0
    lo, hi = lo - pad, hi + pad

    def pct(price: float) -> float:
        return round((price - lo) / (hi - lo) * 100, 2)

    def label_pct(price: float) -> float:
        return min(max(pct(price), LABEL_MIN), LABEL_MAX)

    marks: list[Mark] = []
    stacked: dict[float, int] = {}
    for comp, stale in comps:
        row = stacked.get(comp.price, 0)
        stacked[comp.price] = row + 1
        kind = "comp-old" if stale else ("comp-active" if comp.status == "active" else "comp")
        title = f"{comp.address}: {money(comp.price)} ({comp.status})"
        marks.append(Mark(kind, pct(comp.price), row, title))
    marks.append(Mark("mid", pct(mid), 0, f"Estimate mid {money(mid)}"))
    # The range itself is printed above the line; labelling its ends here collides on phones.
    labels = [Label("mid", label_pct(mid), f"mid {money(mid)}")]
    if recent is not None:
        marks.append(Mark("recent", pct(recent), 0, f"Recent comp median {money(recent)}"))
        labels.append(Label("recent", label_pct(recent), f"recent median {money(recent)}"))
    if asking is not None:
        marks.append(Mark("asking", pct(asking), 0, f"Your asking {money(asking)}"))
        labels.append(Label("asking", label_pct(asking), f"your asking {money(asking)}"))
    return PriceLine(pct(est.low), pct(est.high), marks, labels)


@dataclass(frozen=True)
class Slider:
    min: int
    max: int
    step: int
    mid: int


def slider(brief: Brief) -> Slider | None:
    est = brief.rent_estimate
    if est is None or est.value is None or est.low is None or est.high is None:
        return None
    low = math.floor(est.low * (1 - SLIDER_SPAN) / SLIDER_STEP) * SLIDER_STEP
    high = math.ceil(est.high * (1 + SLIDER_SPAN) / SLIDER_STEP) * SLIDER_STEP
    asking = _asking(brief)
    if asking is not None:
        low = min(low, math.floor(asking / SLIDER_STEP) * SLIDER_STEP)
        high = max(high, math.ceil(asking / SLIDER_STEP) * SLIDER_STEP)
    mid = round(est.value / SLIDER_STEP) * SLIDER_STEP
    return Slider(low, high, SLIDER_STEP, mid)


def market_history(brief: Brief) -> list[tuple[str, float]]:
    """Monthly medians, read back from the trend's evidence lines ("2026-05: median 28")."""
    trend = brief.market.trend
    if trend is None:
        return []
    points: list[tuple[str, float]] = []
    for line in trend.evidence:
        if match := _HISTORY.match(line):
            points.append((match.group(1), float(match.group(2))))
    return points


@dataclass(frozen=True)
class Spark:
    points: str  # SVG polyline points in a 260x60 box
    first: str
    last: str
    last_value: float


def sparkline(history: list[tuple[str, float]]) -> Spark | None:
    if len(history) < 2:
        return None
    width, height, pad = 260, 60, 6
    top = max(v for _, v in history) * 1.15 or 1.0
    step = (width - 2 * pad) / (len(history) - 1)
    coords = [
        f"{pad + i * step:.1f},{height - pad - v / top * (height - 2 * pad):.1f}"
        for i, (_, v) in enumerate(history)
    ]
    return Spark(" ".join(coords), history[0][0], history[-1][0], history[-1][1])


@dataclass(frozen=True)
class CompRow:
    comp: Comp
    stale: bool
    divider_before: bool


def search_url(address: str) -> str:
    return "https://www.google.com/search?" + urlencode({"q": address})


def zillow_url(address: str) -> str:
    """Zillow's address-search link, opened in the user's browser. The app never fetches it."""
    slug = "-".join(address.split())
    return f"https://www.zillow.com/homes/{quote(slug, safe=',-')}_rb/"


def comp_rows(brief: Brief) -> list[CompRow]:
    rows: list[CompRow] = []
    divided = False
    for comp, stale in _comps(brief):
        rows.append(CompRow(comp, stale, stale and not divided))
        divided = divided or stale
    return rows


def fact_line(brief: Brief) -> str:
    f = brief.facts
    parts: list[str] = []
    if f.property_type and f.property_type.value:
        parts.append(f.property_type.value)
    if f.beds and f.beds.value is not None:
        parts.append(f"{_num(f.beds.value)} bd")
    if f.baths and f.baths.value is not None:
        parts.append(f"{_num(f.baths.value)} ba")
    if f.sqft and f.sqft.value is not None:
        parts.append(f"{f.sqft.value:,} sqft")
    if f.year_built and f.year_built.value is not None:
        parts.append(f"built {f.year_built.value}")
    return " · ".join(parts)


@dataclass(frozen=True)
class DetailRow:
    label: str
    value: str
    env: Envelope[Any]


def _pct(value: float | None) -> str:
    return "?" if value is None else f"{value * 100:+.1f}%"


def detail_rows(brief: Brief) -> list[DetailRow]:
    f = brief.facts
    rows: list[DetailRow] = []

    def add(label: str, env: Envelope[Any] | None, show: Callable[[Any], str] = str) -> None:
        if env is not None:
            text = "?" if env.value is None else show(env.value)
            rows.append(DetailRow(label, text, env))

    add("Address", f.address)
    add("Match confidence", f.match_confidence, lambda v: f"{v:.0%}")
    add("Property type", f.property_type)
    add("Beds", f.beds, _num)
    add("Baths", f.baths, _num)
    add("Sqft", f.sqft, lambda v: f"{v:,}")
    add("Year built", f.year_built)
    add("Roof year", f.roof_year)
    add("HVAC year", f.hvac_year)
    est = brief.rent_estimate
    if est is not None:
        span = f"{money(est.low)} to {money(est.high)}, " if est.low and est.high else ""
        add("Rent estimate", est, lambda v: f"{span}mid {money(v)}")
    add("Recent comp median", brief.recent_comps, money)
    if lst := brief.listing:
        add("Asking rent", lst.asking_rent, money)
        add("Days listed", lst.days_listed)
        add("Range position", lst.range_position)
        add("vs recent comps", lst.vs_recent_comps, _pct)
        add("vs zip median days", lst.vs_zip_median_days, lambda v: f"{v:+.0f} days")
    add("Zip median days on market", brief.market.median_days_on_market, lambda v: f"{v:.0f}")
    add("Market trend", brief.market.trend)
    add("Property tax", brief.property_tax, lambda v: f"{money(v)} / year")
    return rows
