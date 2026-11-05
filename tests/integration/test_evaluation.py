"""Phase 3 harness: scores replayed briefs against known leases, gates regressions."""

from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rentsmart.evaluation import (
    EvaluationError,
    GoldenEntry,
    Metrics,
    app,
    check,
    evaluate,
    load_golden,
)
from rentsmart.providers.replay import replay_provider
from tests.conftest import ADDRESS, FIXTURES

runner = CliRunner()
REPO = Path(__file__).resolve().parents[2]


def _entry(lease: float | None, slug: str = "synthetic-gainesville") -> GoldenEntry:
    return GoldenEntry(
        slug=slug,
        address=ADDRESS,
        recorded=date(2026, 10, 20),
        status="leased" if lease is not None else "pending",
        lease_price=lease,
    )


def test_replay_provider_needs_no_network() -> None:
    provider = replay_provider(FIXTURES / "synthetic-gainesville")
    assert provider.resolve_address(ADDRESS)[0].zip_code == "32601"


def test_scores_coverage_width_and_error() -> None:
    # Synthetic range $1,850-$2,250, mid $2,050, recent comp median $2,100.
    report = evaluate([_entry(2000), _entry(2400), _entry(None)], FIXTURES)
    assert (report.n_leased, report.n_pending) == (2, 1)
    assert report.coverage == 0.5
    hit, miss = report.results
    assert hit.covered and not miss.covered
    assert hit.width_pct == round(400 / 2050, 4)
    assert hit.mid_error_pct == round((2050 - 2000) / 2000, 4)
    assert hit.recent_error_pct == round((2100 - 2000) / 2000, 4)


def test_missing_fixtures_is_an_error() -> None:
    with pytest.raises(EvaluationError, match="no recorded fixtures"):
        evaluate([_entry(2000, slug="never-recorded")], FIXTURES)


def test_leased_needs_price() -> None:
    with pytest.raises(ValueError, match="lease_price"):
        GoldenEntry(slug="x", address="x", recorded=date(2026, 1, 1), status="leased")


@pytest.mark.parametrize(
    ("current", "baseline", "fails"),
    [
        (
            Metrics(n_leased=10, coverage=0.80, median_width_pct=0.20),
            Metrics(n_leased=10, coverage=0.80, median_width_pct=0.20),
            False,
        ),
        (
            Metrics(n_leased=10, coverage=0.70, median_width_pct=0.20),
            Metrics(n_leased=10, coverage=0.80, median_width_pct=0.20),
            True,
        ),
        (
            Metrics(n_leased=10, coverage=0.80, median_width_pct=0.30),
            Metrics(n_leased=10, coverage=0.80, median_width_pct=0.20),
            True,
        ),
        (
            Metrics(n_leased=10, coverage=0.78, median_width_pct=0.23),
            Metrics(n_leased=10, coverage=0.80, median_width_pct=0.20),
            False,
        ),
        (
            Metrics(n_leased=11, coverage=0.80, median_width_pct=0.20),
            Metrics(n_leased=10, coverage=0.80, median_width_pct=0.20),
            True,
        ),
    ],
)
def test_check_gates_regressions(current: Metrics, baseline: Metrics, fails: bool) -> None:
    report = evaluate([], FIXTURES).model_copy(update=current.model_dump())
    assert bool(check(report, baseline)) is fails


def test_cli_check_and_update_baseline(tmp_path: Path) -> None:
    golden = tmp_path / "golden.toml"
    golden.write_text(
        f'[[entry]]\nslug = "synthetic-gainesville"\naddress = "{ADDRESS}"\n'
        'recorded = 2026-10-20\nstatus = "leased"\nlease_price = 2000\n'
    )
    baseline = tmp_path / "baseline.json"
    args = ["--golden", str(golden), "--fixtures", str(FIXTURES), "--baseline", str(baseline)]

    result = runner.invoke(app, [*args, "--update-baseline"])
    assert result.exit_code == 0, result.output
    assert "Coverage (lease inside range): 100.0%" in result.output

    assert runner.invoke(app, [*args, "--check"]).exit_code == 0

    golden.write_text(golden.read_text().replace("lease_price = 2000", "lease_price = 2600"))
    result = runner.invoke(app, [*args, "--check"])
    assert result.exit_code == 1
    assert "Coverage fell to 0%" in result.output


def test_repo_golden_set_passes_its_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO)
    result = runner.invoke(app, ["--check"])
    assert result.exit_code == 0, result.output
    assert load_golden(REPO / "benchmarks" / "golden.toml")
