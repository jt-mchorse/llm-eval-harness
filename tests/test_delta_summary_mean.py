"""The summary mean Δ is the decimal difference, rendered on the right side of 0 (#336).

`diff_runs` published `mean_delta` as `current.mean_score - baseline.mean_score`,
two float means, and both renderers printed it at `+.3f`. Measured on main::

    baseline rows [0.2, 0.1] -> mean_score 0.15000000000000002
    current  rows [0.3, 0.0] -> mean_score 0.15

    --format json      "mean_delta": -2.7755575615628914e-17
    --format ascii     summary: mean Δ=-0.000  regressed=1 ...
    --format markdown  [!] mean Δ **-0.000** · flagged **0** ...

The rows beside it already used D-034's decimals (#289) and #291's
classified rendering; the summary line used neither.
"""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from eval_harness.comment import render_delta_markdown
from eval_harness.runner import DeltaReport, RowScore, RunResult, diff_runs, render_delta_ascii
from eval_harness.runs import StoredRun


def _run(run_id: str, scores: list[float], mean: float | None = None) -> StoredRun:
    return StoredRun(
        run_id=run_id,
        started_at="2026-01-01T00:00:00Z",
        suite="s",
        dataset_version="v",
        judge_model=None,
        judge_kappa=None,
        mean_score=sum(scores) / len(scores) if mean is None else mean,
        n_rows=len(scores),
        git_sha=None,
        rows={f"e{i}": (s, "r") for i, s in enumerate(scores)},
    )


def _ascii_mean(report: DeltaReport) -> str:
    line = next(ln for ln in render_delta_ascii(report).splitlines() if ln.startswith("summary:"))
    return line.split("mean Δ=")[1].split()[0]


def _markdown_mean(report: DeltaReport) -> str:
    return render_delta_markdown(report).split("mean Δ **")[1].split("**")[0]


def _equal_mean_pairs() -> list[tuple[list[float], list[float]]]:
    # Every pair of two-row runs on the one-decimal grid whose decimal means are
    # equal and whose float means are not: 22 of them, each of which main
    # published as a nonzero mean_delta.
    grid = [round(i * 0.1, 1) for i in range(11)]
    two = list(itertools.combinations_with_replacement(grid, 2))
    return [
        (list(a), list(b))
        for a, b in itertools.product(two, two)
        if a < b and sum(map(_dec, a)) == sum(map(_dec, b)) and sum(a) / 2 != sum(b) / 2
    ]


def _dec(x: float) -> Fraction:
    return Fraction(repr(x))


EQUAL_MEAN_PAIRS = _equal_mean_pairs()


def test_the_grid_has_the_cases_main_got_wrong() -> None:
    assert len(EQUAL_MEAN_PAIRS) == 22


@pytest.mark.parametrize(
    ("baseline", "current"),
    [*EQUAL_MEAN_PAIRS, ([0.1, 0.1, 0.1], [0.0, 0.0, 0.3])],
)
def test_equal_decimal_means_publish_zero(baseline: list[float], current: list[float]) -> None:
    b, c = _run("base0000", baseline), _run("curr0000", current)
    assert b.mean_score != c.mean_score  # the float means do differ
    for report in (diff_runs(c, b), diff_runs(b, c)):
        assert report.summary["mean_delta"] == 0.0
        assert _ascii_mean(report) == "+0.000"
        assert _markdown_mean(report) == "+0.000"


def test_a_real_move_keeps_its_value_and_sign() -> None:
    report = diff_runs(_run("c", [0.7, 0.8]), _run("b", [0.8, 0.8]))
    assert report.summary["mean_delta"] == -0.05
    assert _ascii_mean(report) == "-0.050"
    assert _markdown_mean(report) == "-0.050"


def test_a_tiny_move_widens_instead_of_reading_as_no_change() -> None:
    # 0.5 -> 0.5002 over two rows: a +0.0001 mean move, below `.3f`.
    report = diff_runs(_run("c", [0.5, 0.5002]), _run("b", [0.5, 0.5]))
    assert report.summary["mean_delta"] == pytest.approx(0.0001)
    assert _ascii_mean(report) == "+0.0001"
    assert _markdown_mean(report) == "+0.0001"
    down = diff_runs(_run("b", [0.5, 0.5]), _run("c", [0.5, 0.5002]))
    assert _ascii_mean(down) == "-0.0001"


def test_a_mean_the_rows_do_not_reproduce_is_taken_as_recorded() -> None:
    # A hand-built or hand-edited run whose mean_score is not its rows' mean:
    # the field is what the run says, read as its own decimal.
    report = diff_runs(_run("c", [0.3, 0.0], mean=0.4), _run("b", [0.2, 0.1], mean=0.1))
    assert report.summary["mean_delta"] == pytest.approx(0.3)
    assert _ascii_mean(report) == "+0.300"


def test_the_cli_publishes_zero_in_every_format(tmp_path: Path) -> None:
    def write(name: str, scores: list[float]) -> Path:
        rows = tuple(
            RowScore(example_id=f"e{i}", score=s, reasoning="r") for i, s in enumerate(scores)
        )
        run = RunResult(
            run_id=name,
            started_at="2026-10-09T00:00:00Z",
            suite="s",
            dataset_version="v1",
            judge_model="m",
            judge_kappa=None,
            mean_score=sum(scores) / len(scores),
            n_rows=len(scores),
            git_sha=None,
            rows=rows,
        )
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(run.to_json()))
        return path

    base, cur = write("base", [0.2, 0.1]), write("cur", [0.3, 0.0])
    out = {}
    for fmt in ("json", "ascii", "markdown"):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval_harness.cli",
                "diff-json",
                "--current",
                str(cur),
                "--baseline",
                str(base),
                "--format",
                fmt,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        out[fmt] = proc.stdout
    assert json.loads(out["json"])["summary"]["mean_delta"] == 0.0
    assert "mean Δ=+0.000" in out["ascii"]
    assert "mean Δ **+0.000**" in out["markdown"]
    # Read back from the published JSON, the renderers say the same.
    report = DeltaReport.from_json(json.loads(out["json"]))
    assert _ascii_mean(report) == _markdown_mean(report) == "+0.000"
