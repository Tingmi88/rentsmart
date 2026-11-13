"""Typer front door. Thin: parse flags, call the engine, print, exit with the right code."""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from rentsmart.contracts import RentsmartError
from rentsmart.core.engine import build_brief
from rentsmart.core.facts import OwnerFacts
from rentsmart.core.listing import CurrentListing
from rentsmart.providers.rentcast import RentCastProvider
from rentsmart.render import render
from rentsmart.settings import rent_index, response_cache, stale_after_days, usage_log
from rentsmart.web.render import render_page

app = typer.Typer(
    add_completion=False,
    help="Independent rental pricing brief for a US address. "
    "Not an appraisal; not financial, legal, or tax advice.",
)


def _today() -> date:
    return date.today()


@app.command()
def main(
    address: Annotated[
        str,
        typer.Argument(help='Full US street address, e.g. "123 Main St, Gainesville, FL 32601".'),
    ],
    beds: Annotated[
        float | None, typer.Option(min=0, help="Bedrooms (overrides vendor data).")
    ] = None,
    baths: Annotated[
        float | None, typer.Option(min=0, help="Bathrooms (overrides vendor data).")
    ] = None,
    sqft: Annotated[int | None, typer.Option(min=1, help="Living area in sqft.")] = None,
    roof_year: Annotated[
        int | None, typer.Option(min=1800, max=2100, help="Year roof replaced.")
    ] = None,
    hvac_year: Annotated[
        int | None, typer.Option(min=1800, max=2100, help="Year HVAC replaced.")
    ] = None,
    asking: Annotated[
        float | None, typer.Option(min=1, help="Your current asking rent, to check it.")
    ] = None,
    listed: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Date your listing went live (YYYY-MM-DD)."),
    ] = None,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Ignore cached responses and fetch fresh data.")
    ] = False,
    run_anyway: Annotated[
        bool,
        typer.Option(
            "--run-anyway",
            help="Look the address up as typed, even if a similar address was looked up before.",
        ),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full brief as JSON.")] = False,
    html_path: Annotated[
        Path | None,
        typer.Option("--html", dir_okay=False, help="Also write the brief as one HTML file."),
    ] = None,
) -> None:
    owner = OwnerFacts(beds=beds, baths=baths, sqft=sqft, roof_year=roof_year, hvac_year=hvac_year)
    today = _today()
    if listed is not None and asking is None:
        raise typer.BadParameter("--listed needs --asking.", param_hint="--listed")
    if listed is not None and listed.date() > today:
        raise typer.BadParameter("can't be in the future.", param_hint="--listed")
    listing = (
        CurrentListing(asking_rent=asking, listed_date=listed and listed.date())
        if asking is not None
        else None
    )
    try:
        brief = build_brief(
            address,
            owner,
            RentCastProvider.from_env(
                cache=response_cache(refresh),
                today=lambda: today,
                usage=usage_log(),
                check_similar=not run_anyway,
            ),
            today=today,
            stale_after_days=stale_after_days(),
            listing=listing,
            rent_index=rent_index(),
        )
    except RentsmartError as err:
        if as_json:
            typer.echo(json.dumps(err.to_dict(), indent=2))
        else:
            typer.echo(err.message, err=True)
        raise typer.Exit(int(err.exit_code)) from None

    if html_path is not None:
        try:
            html_path.write_text(render_page(brief, entered=asking), encoding="utf-8")
        except OSError as err:
            typer.echo(f"Could not write {html_path}: {err.strerror}", err=True)
            raise typer.Exit(1) from None

    typer.echo(brief.model_dump_json(indent=2) if as_json else render(brief))
    raise typer.Exit(int(brief.exit_code))
