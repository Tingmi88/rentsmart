"""Local web UI over the same engine. Listens on 127.0.0.1; only POST /brief spends API calls."""

import math
import re
import threading
import webbrowser
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Annotated
from urllib.parse import parse_qs, urlencode, urlsplit

import typer
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from rentsmart.contracts import (
    AddressNotFound,
    AmbiguousAddress,
    Brief,
    ConfigError,
    QuotaExceeded,
    RentsmartError,
    SimilarAddress,
)
from rentsmart.core.address import STATES, join, split_formatted
from rentsmart.core.engine import build_brief
from rentsmart.core.facts import OwnerFacts
from rentsmart.core.listing import CurrentListing
from rentsmart.providers.cache import CacheMiss, default_cache_dir
from rentsmart.providers.rentcast import RentCastProvider
from rentsmart.settings import rent_index, response_cache, stale_after_days, usage_log
from rentsmart.web import render

DEFAULT_PORT = 8765
# One live fetch at a time: a double-clicked Run waits, then reads the first run's cache.
_FETCH_LOCK = threading.Lock()
MAX_ADDRESS = 200
ADDRESS_FIELDS: tuple[str, ...] = ("street", "city", "state", "zip")
ZIP = re.compile(r"\d{5}(-\d{4})?")
MAX_RENT = 1_000_000
STATIC = {"app.css": "text/css", "app.js": "text/javascript"}
ERROR_STATUS: dict[type[RentsmartError], int] = {
    AddressNotFound: 404,
    AmbiguousAddress: 409,
    QuotaExceeded: 429,
    ConfigError: 500,
}
NO_CACHE = (
    "The local UI needs the response cache, but RENTSMART_CACHE_DAYS is 0. "
    "Unset it or set it to a number of days."
)


class InputError(ValueError):
    """Form input the CLI would also reject."""


@dataclass(frozen=True)
class BriefRequest:
    address: str
    asking: float | None = None
    listed: date | None = None
    entered: float | None = None
    # (street, city, state, zip) when entered in separate fields; None for a one-line address.
    parts: tuple[str, str, str, str] | None = None

    def at(self, formatted: str) -> "BriefRequest":
        """The same request for another address, split into fields when it can be."""
        return replace(self, address=formatted, parts=split_formatted(formatted))

    def query(self) -> dict[str, str]:
        q = dict(zip(ADDRESS_FIELDS, self.parts, strict=True)) if self.parts else {}
        if not q:
            q["address"] = self.address
        if self.asking is not None:
            q["asking"] = f"{self.asking:g}"
        if self.listed is not None:
            q["listed"] = self.listed.isoformat()
        if self.entered is not None:
            q["entered"] = f"{self.entered:g}"
        return q


def _rent(fields: Mapping[str, str], name: str, label: str) -> float | None:
    raw = fields.get(name, "").strip().replace(",", "").removeprefix("$")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise InputError(f"{label} must be a number of dollars, got {raw!r}.") from None
    if not math.isfinite(value) or not 1 <= value <= MAX_RENT:
        raise InputError(f"{label} must be between $1 and ${MAX_RENT:,}.")
    return value


def _address(fields: Mapping[str, str]) -> tuple[str, tuple[str, str, str, str] | None]:
    street, city, state, zip_code = (" ".join(fields.get(n, "").split()) for n in ADDRESS_FIELDS)
    if not (street or city or state or zip_code):
        # One-line address: older links, and ambiguous-match candidates that won't split.
        address = " ".join(fields.get("address", "").split())
        if not address:
            raise InputError("Enter an address.")
        return address, None
    state = state.upper()
    if not street:
        raise InputError("Enter the street address, e.g. 123 Main St.")
    if not city:
        raise InputError("Enter the city.")
    if state not in STATES:
        raise InputError("State must be a 2-letter code, e.g. TX.")
    if not ZIP.fullmatch(zip_code):
        raise InputError("ZIP must be 5 digits, e.g. 78729.")
    return join(street, city, state, zip_code), (street, city, state, zip_code)


def form_values(fields: Mapping[str, str]) -> dict[str, str]:
    """Form fields to refill, splitting a one-line address into the separate fields."""
    values = dict(fields)
    if not any(values.get(n) for n in ADDRESS_FIELDS) and (
        parts := split_formatted(values.get("address", ""))
    ):
        values.update(zip(ADDRESS_FIELDS, parts, strict=True))
    return values


def parse_request(fields: Mapping[str, str], today: date) -> BriefRequest:
    address, parts = _address(fields)
    if len(address) > MAX_ADDRESS:
        raise InputError(f"Address is longer than {MAX_ADDRESS} characters.")
    asking = _rent(fields, "asking", "Asking rent")
    entered = _rent(fields, "entered", "Entered asking rent")
    listed: date | None = None
    if raw := fields.get("listed", "").strip():
        try:
            listed = date.fromisoformat(raw)
        except ValueError:
            raise InputError(f"Listed date must be YYYY-MM-DD, got {raw!r}.") from None
        if asking is None:
            raise InputError("A listed date needs an asking rent.")
        if listed > today:
            raise InputError("Listed date can't be in the future.")
    return BriefRequest(address, asking, listed, entered, parts)


def create_app(port: int = DEFAULT_PORT, today: Callable[[], date] = date.today) -> FastAPI:
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def build(
        req: BriefRequest, *, offline: bool, check_similar: bool = False, any_age: bool = False
    ) -> tuple[Brief, list[datetime]]:
        """The brief, plus when each saved response older than the reuse window was fetched."""
        cache, window = response_cache(any_age=any_age), response_cache()
        if cache is None or window is None:
            raise ConfigError(NO_CACHE)
        day = today()
        provider = RentCastProvider.from_env(
            cache=cache,
            today=lambda: day,
            offline=offline,
            usage=usage_log(),
            check_similar=check_similar,
        )
        listing = (
            CurrentListing(asking_rent=req.asking, listed_date=req.listed)
            if req.asking is not None
            else None
        )
        brief = build_brief(
            req.address,
            OwnerFacts(),
            provider,
            today=day,
            stale_after_days=stale_after_days(),
            listing=listing,
            rent_index=rent_index(),
        )
        return brief, [at for at in provider.saved_at.values() if not window.is_fresh(at)]

    def fetch(req: BriefRequest) -> tuple[Brief, bool]:
        """Live build, plus whether the cache can now serve it (False: it couldn't be saved)."""
        with _FETCH_LOCK:
            brief, _ = build(req, offline=False)
            try:
                build(req, offline=True)
            except CacheMiss:
                return brief, False
            return brief, True

    def failure(err: RentsmartError, req: BriefRequest) -> HTMLResponse:
        links: list[tuple[str, str]] = []
        if isinstance(err, AmbiguousAddress):
            links = [(c, "/brief?" + urlencode(req.at(c).query())) for c in err.candidates]
        return HTMLResponse(
            render.render_error(err, address=req.address, links=links),
            status_code=ERROR_STATUS.get(type(err), 502),
        )

    def bad_input(err: InputError, fields: Mapping[str, str]) -> HTMLResponse:
        page = render.render_index(
            usage=usage_log().this_month(), error=str(err), values=form_values(fields)
        )
        return HTMLResponse(page, status_code=422)

    @app.middleware("http")
    async def local_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.headers.get("host") not in hosts:
            return Response("Local use only.", status_code=400, media_type="text/plain")
        if request.method == "POST":
            source = request.headers.get("origin") or request.headers.get("referer") or ""
            parts = urlsplit(source)
            if parts.scheme != "http" or parts.netloc not in hosts:
                return Response(
                    "Cross-site request refused.", status_code=403, media_type="text/plain"
                )
        return await call_next(request)

    @app.get("/")
    def index(request: Request) -> HTMLResponse:
        values = form_values(request.query_params)
        return HTMLResponse(render.render_index(usage=usage_log().this_month(), values=values))

    @app.get("/brief")
    def brief_page(request: Request) -> HTMLResponse:
        fields = dict(request.query_params)
        try:
            req = parse_request(fields, today())
        except InputError as err:
            return bad_input(err, fields)
        try:
            brief, expired = build(req, offline=True, check_similar=True, any_age=True)
        except (CacheMiss, SimilarAddress) as err:
            # Nothing fetched. Offer saved look-alikes first, then a paid run as entered.
            similar = err.candidates if isinstance(err, SimilarAddress) else []
            links = [(c, saved, "/brief?" + urlencode(req.at(c).query())) for c, saved in similar]
            page = render.render_not_cached(
                req.address, req.query(), usage=usage_log().this_month(), similar=links
            )
            return HTMLResponse(page)
        except RentsmartError as err:
            return failure(err, req)
        entered = req.entered if req.entered is not None else req.asking
        refresh = None
        if expired:
            # Shown anyway, dated; refetching only the expired parts is the user's call.
            oldest = min(expired)
            refresh = render.Refresh(
                saved_on=oldest.astimezone().date(),
                days_old=(datetime.now(UTC) - oldest).days,  # the cache's clock, not today()
                calls=len(expired),
            )
        page = render.render_page(
            brief,
            app=True,
            entered=entered,
            listed=req.listed,
            today=today(),
            refresh=refresh,
            query=req.query(),
        )
        return HTMLResponse(page)

    @app.post("/brief")
    async def run_brief(request: Request) -> Response:
        body = (await request.body()).decode("utf-8", "replace")
        fields = {k: v[0] for k, v in parse_qs(body).items()}
        try:
            req = parse_request(fields, today())
        except InputError as err:
            return bad_input(err, fields)
        try:
            brief, cached = await run_in_threadpool(fetch, req)
        except RentsmartError as err:
            return failure(err, req)
        if not cached:
            # Redirecting would land on "Not cached" and invite another paid run.
            notice = (
                f"RentCast data was fetched but couldn't be saved to the cache at "
                f"{default_cache_dir()}, so reloads and asking-price changes won't work. "
                "Check that folder's permissions."
            )
            page = render.render_page(
                brief,
                app=True,
                entered=req.asking,
                listed=req.listed,
                today=today(),
                notice=notice,
            )
            return HTMLResponse(page)
        return RedirectResponse("/brief?" + urlencode(req.query()), status_code=303)

    @app.get("/brief/sections")
    def sections(request: Request) -> HTMLResponse:
        try:
            req = parse_request(dict(request.query_params), today())
        except InputError as err:
            return HTMLResponse(render.render_notice(str(err)), status_code=422)
        try:
            brief, _ = build(req, offline=True, any_age=True)
        except CacheMiss:
            notice = render.render_notice(
                "Data expired.",
                link="/brief?" + urlencode(replace(req, asking=req.entered).query()),
            )
            return HTMLResponse(notice, status_code=409)
        except RentsmartError as err:
            status = ERROR_STATUS.get(type(err), 502)
            return HTMLResponse(render.render_notice(err.message), status_code=status)
        return HTMLResponse(render.render_live(brief, entered=req.entered))

    @app.get("/static/{name}")
    def static(name: str) -> Response:
        if name not in STATIC:
            return Response(status_code=404)
        return Response(render.static_text(name), media_type=STATIC[name])

    return app


cli = typer.Typer(
    add_completion=False,
    help="Local rentsmart UI on 127.0.0.1 (this machine only). Ctrl+C to stop.",
)


@cli.command()
def main(
    port: Annotated[int, typer.Option(min=1024, max=65535, help="Local port.")] = DEFAULT_PORT,
    no_open: Annotated[bool, typer.Option("--no-open", help="Don't open the browser.")] = False,
) -> None:
    url = f"http://127.0.0.1:{port}/"
    typer.echo(f"rentsmart UI on {url} (Ctrl+C to stop)")
    if not no_open:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(port), host="127.0.0.1", port=port, log_level="warning")
