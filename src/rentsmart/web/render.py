"""Brief -> HTML. One set of templates serves the shareable file and the local app."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from importlib.resources import files
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from rentsmart.contracts import Brief, RentsmartError
from rentsmart.web import view

_env = Environment(
    loader=PackageLoader("rentsmart.web", "templates"),
    autoescape=select_autoescape(default=True, default_for_string=True),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["money"] = view.money  # pyright: ignore[reportUnknownMemberType]
_env.filters["search_url"] = view.search_url  # pyright: ignore[reportUnknownMemberType]
_env.filters["zillow_url"] = view.zillow_url  # pyright: ignore[reportUnknownMemberType]


def static_text(name: str) -> str:
    return files("rentsmart.web").joinpath("static", name).read_text(encoding="utf-8")


@dataclass(frozen=True)
class WhatIf:
    asking: float
    entered: float


def _layout(app: bool) -> dict[str, Any]:
    if app:
        return {"inline": False, "css": "", "js": ""}
    return {"inline": True, "css": static_text("app.css"), "js": static_text("app.js")}


def _live_context(brief: Brief, entered: float | None) -> dict[str, Any]:
    asking = brief.listing.asking_rent.value if brief.listing else None
    whatif = (
        WhatIf(asking, entered)
        if asking is not None and entered is not None and asking != entered
        else None
    )
    return {
        "brief": brief,
        "line": view.price_line(brief),
        "chips": view.checks(brief),
        "spark": view.sparkline(view.market_history(brief)),
        "comps": view.comp_rows(brief),
        "details": view.detail_rows(brief),
        "whatif": whatif,
    }


@dataclass(frozen=True)
class Refresh:
    """Saved data older than the reuse window: its oldest fetch date, and calls to refetch."""

    saved_on: date
    days_old: int
    calls: int


def render_page(
    brief: Brief,
    *,
    app: bool = False,
    entered: float | None = None,
    listed: date | None = None,
    today: date | None = None,
    notice: str | None = None,
    refresh: Refresh | None = None,
    query: Mapping[str, str] | None = None,
) -> str:
    """`refresh` offers a paid refetch, posting `query` back to /brief."""
    asking = brief.listing.asking_rent.value if brief.listing else None

    return _env.get_template("brief.html").render(
        **_layout(app),
        **_live_context(brief, entered),
        app=app,
        street=(brief.facts.address.value or "").split(",")[0],
        fact_line=view.fact_line(brief),
        slider=view.slider(brief),
        asking_value=f"{asking:g}" if asking is not None else "",
        entered=f"{entered:g}" if entered is not None else None,
        listed=listed.isoformat() if listed else "",
        today=(today or date.today()).isoformat(),
        notice=notice,
        refresh=refresh,
        query=dict(query or {}),
    )


def render_live(brief: Brief, *, entered: float | None = None) -> str:
    return _env.get_template("_live.html").render(**_live_context(brief, entered))


def render_index(
    *, usage: int, error: str | None = None, values: Mapping[str, str] | None = None
) -> str:
    return _env.get_template("index.html").render(
        **_layout(True), usage=usage, error=error, values=dict(values or {})
    )


def render_not_cached(
    address: str,
    query: Mapping[str, str],
    *,
    usage: int,
    similar: Sequence[tuple[str, date, str]] = (),
) -> str:
    """`similar`: (address, date it was looked up, link) for saved look-alikes."""
    return _env.get_template("not_cached.html").render(
        **_layout(True), address=address, query=dict(query), usage=usage, similar=list(similar)
    )


def render_error(
    err: RentsmartError, *, address: str, links: Sequence[tuple[str, str]] = ()
) -> str:
    return _env.get_template("error.html").render(
        **_layout(True), err=err, address=address, links=list(links)
    )


def render_notice(message: str, *, link: str | None = None) -> str:
    return _env.get_template("notice.html").render(message=message, link=link)
