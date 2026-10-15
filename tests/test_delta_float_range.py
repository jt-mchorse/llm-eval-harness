"""A difference with no float value is bad input at exit 2, not an OverflowError (#368).

D-034 (#289) and #336 compute each row delta and the summary `mean_delta`
exactly and publish `float()` of the result. Past the double range there is no
float to publish, and `float(Fraction)` raised `OverflowError`. Measured on main
with two run files `load_run_result_from_json` accepts (every value finite)::

    current score 1e308, baseline -1e308 -> runner.py:952 OverflowError, exit 1
    current mean 1e308,  baseline -1e308 -> runner.py:972 OverflowError, exit 1

Exit 1 is what `diff-json` uses for "a row regressed". Before #289 the float
subtraction gave `inf`, the delta record refused it, and the exit was 2.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval_harness.runner import diff_runs
from eval_harness.runs import StoredRun


def _run(run_id: str, score: float, mean: float) -> StoredRun:
    return StoredRun(
        run_id=run_id,
        started_at="2026-01-01T00:00:00Z",
        suite="s",
        dataset_version="v",
        judge_model=None,
        judge_kappa=None,
        mean_score=mean,
        n_rows=1,
        git_sha=None,
        rows={"a": (score, "r")},
    )


def _payload(run: StoredRun) -> dict:
    return {
        "run_id": run.run_id,
        "started_at": run.started_at,
        "suite": run.suite,
        "dataset_version": run.dataset_version,
        "judge_model": None,
        "judge_kappa": None,
        "mean_score": run.mean_score,
        "n_rows": run.n_rows,
        "git_sha": None,
        "rows": [{"example_id": k, "score": v[0], "reasoning": v[1]} for k, v in run.rows.items()],
    }


# (current, baseline, the phrase the error must name). The row case keeps the
# means consistent with the rows; the mean case keeps the rows ordinary, so
# `_decimal_mean` falls back to the recorded means and only the summary overflows.
CASES = {
    "row_delta": (_run("c", 1e308, 1e308), _run("b", -1e308, -1e308), "example_id 'a'"),
    "mean_delta": (_run("c", 0.5, 1e308), _run("b", 0.5, -1e308), "mean_delta"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_diff_runs_refuses_a_difference_past_the_float_range(case: str) -> None:
    current, baseline, named = CASES[case]
    with pytest.raises(ValueError, match="outside the float range") as info:
        diff_runs(current, baseline)
    assert named in str(info.value)


@pytest.mark.parametrize("case", sorted(CASES))
def test_diff_json_exits_2_without_a_traceback(case: str, tmp_path: Path) -> None:
    current, baseline, named = CASES[case]
    cur = tmp_path / "current.json"
    base = tmp_path / "baseline.json"
    cur.write_text(json.dumps(_payload(current)), encoding="utf-8")
    base.write_text(json.dumps(_payload(baseline)), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "eval_harness.cli", "diff-json"]
        + ["--current", str(cur), "--baseline", str(base)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, proc.stderr
    assert "Traceback" not in proc.stderr
    assert "::error::" in proc.stderr
    assert named in proc.stderr


def test_a_difference_at_the_edge_of_the_range_still_publishes() -> None:
    # The nearest float exists, so this is a value to publish, not an error:
    # the guard is on the overflow, not on large scores.
    edge = 1.7976931348623157e308
    report = diff_runs(_run("c", edge, edge), _run("b", 0.0, 0.0))
    assert report.rows[0].delta == edge
    assert report.summary["mean_delta"] == edge
    assert report.rows[0].status == "improved"
