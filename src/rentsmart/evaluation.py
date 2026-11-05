"""Golden-set evaluation (spec §12).

Replays each golden address's recorded responses, builds the brief as of the recording
date, and compares it with the lease that was actually signed. Coverage (how often the
lease falls inside the range) is always reported with range width: a range that is
always right because it is huge is a failure.
"""

import json
import tomllib
from datetime import date
from pathlib import Path
from statistics import median
from typing import Annotated, Literal, Self

import typer
from pydantic import BaseModel, model_validator

from rentsmart.contracts import RentsmartError
from rentsmart.core.engine import build_brief
from rentsmart.core.facts import OwnerFacts
from rentsmart.providers.replay import replay_provider

DEFAULT_GOLDEN = Path("benchmarks/golden.toml")
DEFAULT_BASELINE = Path("benchmarks/baseline.json")
DEFAULT_FIXTURES = Path("tests/fixtures/rentcast")
# How far a metric may move against us before the check fails (absolute fractions).
COVERAGE_TOLERANCE = 0.05
WIDTH_TOLERANCE = 0.05


class GoldenEntry(BaseModel):
    slug: str
    address: str
    recorded: date
    listed: date | None = None
    asking: float | None = None
    status: Literal["pending", "leased"]
    lease_price: float | None = None
    lease_date: date | None = None

    @model_validator(mode="after")
    def _leased_has_price(self) -> Self:
        if self.status == "leased" and self.lease_price is None:
            raise ValueError(f"{self.slug}: leased entries need lease_price")
        return self


class EntryResult(BaseModel):
    slug: str
    lease_price: float
    low: float | None
    high: float | None
    mid: float | None
    covered: bool
    width_pct: float | None
    mid_error_pct: float | None
    recent_median: float | None
    recent_error_pct: float | None


class Metrics(BaseModel):
    n_leased: int
    coverage: float | None = None
    median_width_pct: float | None = None


class Report(Metrics):
    n_pending: int
    n_no_range: int
    median_abs_mid_error_pct: float | None = None
    median_abs_recent_error_pct: float | None = None
    results: list[EntryResult]


class EvaluationError(Exception):
    pass


def load_golden(path: Path) -> list[GoldenEntry]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    return [GoldenEntry.model_validate(e) for e in data.get("entry", [])]


def _pct(value: float, base: float) -> float:
    return round((value - base) / base, 4)


def evaluate_entry(entry: GoldenEntry, fixtures: Path) -> EntryResult:
    assert entry.lease_price is not None
    fixture_dir = fixtures / entry.slug
    if not fixture_dir.is_dir():
        raise EvaluationError(f"{entry.slug}: no recorded fixtures in {fixture_dir}")
    try:
        brief = build_brief(
            entry.address,
            OwnerFacts(),
            replay_provider(fixture_dir, lambda: entry.recorded),
            today=entry.recorded,
        )
    except RentsmartError as err:
        raise EvaluationError(f"{entry.slug}: {err.message}") from err
    lease = entry.lease_price
    rent = brief.rent_estimate
    low = rent.low if rent else None
    high = rent.high if rent else None
    mid = None
    if rent is not None and low is not None and high is not None:
        mid = rent.value if rent.value is not None else (low + high) / 2
    recent = brief.recent_comps.value if brief.recent_comps else None
    return EntryResult(
        slug=entry.slug,
        lease_price=lease,
        low=low,
        high=high,
        mid=mid,
        covered=low is not None and high is not None and low <= lease <= high,
        width_pct=round((high - low) / mid, 4) if low and high and mid else None,
        mid_error_pct=_pct(mid, lease) if mid else None,
        recent_median=recent,
        recent_error_pct=_pct(recent, lease) if recent else None,
    )


def _median_or_none(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def evaluate(entries: list[GoldenEntry], fixtures: Path) -> Report:
    leased = [e for e in entries if e.status == "leased"]
    results = [evaluate_entry(e, fixtures) for e in leased]
    n = len(results)
    return Report(
        n_leased=n,
        n_pending=len(entries) - n,
        # An entry with no range counts as not covered: refusing to answer isn't a hit.
        n_no_range=sum(r.low is None for r in results),
        coverage=round(sum(r.covered for r in results) / n, 4) if n else None,
        median_width_pct=_median_or_none([r.width_pct for r in results if r.width_pct is not None]),
        median_abs_mid_error_pct=_median_or_none(
            [abs(r.mid_error_pct) for r in results if r.mid_error_pct is not None]
        ),
        median_abs_recent_error_pct=_median_or_none(
            [abs(r.recent_error_pct) for r in results if r.recent_error_pct is not None]
        ),
        results=results,
    )


def check(report: Report, baseline: Metrics) -> list[str]:
    """Return the reasons the report regresses against the baseline (empty = pass)."""
    failures: list[str] = []
    if report.n_leased != baseline.n_leased:
        failures.append(
            f"Golden set has {report.n_leased} leased entries but the baseline has "
            f"{baseline.n_leased}. Review the report, then run with --update-baseline."
        )
        return failures
    if (
        report.coverage is not None
        and baseline.coverage is not None
        and report.coverage < baseline.coverage - COVERAGE_TOLERANCE
    ):
        failures.append(f"Coverage fell to {report.coverage:.0%} from {baseline.coverage:.0%}.")
    if (
        report.median_width_pct is not None
        and baseline.median_width_pct is not None
        and report.median_width_pct > baseline.median_width_pct + WIDTH_TOLERANCE
    ):
        failures.append(
            f"Median range width grew to {report.median_width_pct:.0%} "
            f"from {baseline.median_width_pct:.0%}."
        )
    return failures


def _fmt_pct(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1%}" if signed else f"{value:.1%}"


def _fmt_money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.0f}"


def format_report(report: Report) -> str:
    lines = [
        f"Golden set: {report.n_leased} leased, {report.n_pending} pending",
        "",
        f"  Coverage (lease inside range): {_fmt_pct(report.coverage)}",
        f"  Median range width (of mid):   {_fmt_pct(report.median_width_pct)}",
        f"  Median |mid - lease|:          {_fmt_pct(report.median_abs_mid_error_pct)}",
        f"  Median |recent comps - lease|: {_fmt_pct(report.median_abs_recent_error_pct)}",
        f"  Entries with no range:         {report.n_no_range}",
    ]
    if report.results:
        lines += ["", "  slug                      lease      range              mid err  hit"]
        for r in report.results:
            rng = f"{_fmt_money(r.low)}-{_fmt_money(r.high)}" if r.low is not None else "no range"
            lines.append(
                f"  {r.slug:<24}  {_fmt_money(r.lease_price):<9}  {rng:<17}  "
                f"{_fmt_pct(r.mid_error_pct, signed=True):>7}  {'yes' if r.covered else 'NO'}"
            )
    if report.n_leased == 0:
        lines += ["", "  No leased entries yet; nothing to score."]
    return "\n".join(lines)


app = typer.Typer(add_completion=False, help="Score rentsmart against the golden set.")


@app.command()
def main(
    golden: Annotated[Path, typer.Option(help="Golden set TOML.")] = DEFAULT_GOLDEN,
    fixtures: Annotated[Path, typer.Option(help="Recorded fixtures root.")] = DEFAULT_FIXTURES,
    baseline: Annotated[Path, typer.Option(help="Baseline metrics JSON.")] = DEFAULT_BASELINE,
    run_check: Annotated[
        bool, typer.Option("--check", help="Fail if metrics regress against the baseline.")
    ] = False,
    update_baseline: Annotated[
        bool, typer.Option("--update-baseline", help="Write current metrics as the baseline.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full report as JSON.")] = False,
) -> None:
    try:
        report = evaluate(load_golden(golden), fixtures)
    except (EvaluationError, ValueError, OSError) as err:
        typer.echo(f"Evaluation failed: {err}", err=True)
        raise typer.Exit(1) from None
    typer.echo(report.model_dump_json(indent=2) if as_json else format_report(report))

    metrics = Metrics(
        n_leased=report.n_leased,
        coverage=report.coverage,
        median_width_pct=report.median_width_pct,
    )
    if update_baseline:
        baseline.write_text(metrics.model_dump_json(indent=2) + "\n")
        typer.echo(f"\nBaseline written to {baseline}.")
    if run_check:
        failures = check(report, Metrics.model_validate(json.loads(baseline.read_text())))
        for failure in failures:
            typer.echo(f"FAIL: {failure}", err=True)
        if failures:
            raise typer.Exit(1)
        typer.echo("\nCheck passed.")
