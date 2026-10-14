"""The committed demo runs record the mean of their own rows (#357).

`fixtures/demo_current.json` recorded `"mean_score": 0.79` over rows that
average 0.77. `.github/workflows/eval.yml` diffs the two demo fixtures on
every PR, so every sticky comment headlined `mean Δ **-0.050**` above a
table whose rows work out to -0.070.

The reader does not catch this, and that is deliberate: #336 made a recorded
`mean_score` that the rows don't reproduce authoritative (locked in
`tests/test_delta_summary_mean.py`). So the invariant `run_suite` writes,
`mean = sum(scores) / len(scores)`, is pinned here on the files themselves.
Equality is on D-034 decimals because the float mean of 0.97, 0.90, 0.55,
0.78 and 0.65 is `0.7700000000000001`, and the fixture is meant to say 0.77.
"""

from __future__ import annotations

import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUN_FIXTURES = sorted((ROOT / "fixtures").glob("*.json"))


def _dec(x: float) -> Fraction:
    return Fraction(repr(x))


def _row_mean(payload: dict) -> Fraction:
    scores = [_dec(r["score"]) for r in payload["rows"]]
    return sum(scores, Fraction(0)) / len(scores)


def test_the_population_is_the_two_demo_runs() -> None:
    # A new committed run fixture joins the parametrization below by glob; this
    # pins that the glob still finds the two the eval workflow reads.
    assert {p.name for p in RUN_FIXTURES} >= {"demo_baseline.json", "demo_current.json"}


@pytest.mark.parametrize("path", RUN_FIXTURES, ids=lambda p: p.name)
def test_recorded_mean_is_the_mean_of_the_rows(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert _dec(payload["mean_score"]) == _row_mean(payload), (
        f"{path.name} records mean_score {payload['mean_score']} but its rows "
        f"average {float(_row_mean(payload))}"
    )


@pytest.mark.parametrize("fmt", ["json", "ascii", "markdown"])
def test_the_demo_diff_headlines_the_row_derived_mean_delta(fmt: str) -> None:
    baseline = json.loads((ROOT / "fixtures/demo_baseline.json").read_text(encoding="utf-8"))
    current = json.loads((ROOT / "fixtures/demo_current.json").read_text(encoding="utf-8"))
    expected = float(_row_mean(current) - _row_mean(baseline))
    assert expected == -0.07
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "diff-json",
            "--current",
            str(ROOT / "fixtures/demo_current.json"),
            "--baseline",
            str(ROOT / "fixtures/demo_baseline.json"),
            "--format",
            fmt,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stderr  # qa_history_01 is the flagged row
    if fmt == "json":
        assert json.loads(proc.stdout)["summary"]["mean_delta"] == expected
    elif fmt == "ascii":
        assert "summary: mean Δ=-0.070 " in proc.stdout
    else:
        assert "mean Δ **-0.070**" in proc.stdout
