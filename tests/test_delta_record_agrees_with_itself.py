"""A delta record agrees with itself: summary with rows, rows with their scores (#435).

`DeltaReport.from_json` replaced a missing `summary` with `{}` and never checked
it against `rows`, and both renderers take the headline counts and the
`[X]/[!]/[+]/[=]` verdict from `summary` alone. Measured on 7de275b: the demo
`diff-json` output with its summary deleted posted

    [=] mean Δ **+0.000** · flagged **0** · regressed 0 · improved 0 · ...
    | regressed | `qa_history_01` | 0.800 | 0.550 | -0.250 | :warning: |

at exit 0. The reader also took rows `diff_runs` cannot produce: `status:
"unchanged"` beside `delta: +0.4, flagged: true`, and a repeated `example_id`.

Refused now (#266/D-033's precedent), through one definition: `_row_verdict` is
what `diff_runs` builds each row from and what `_check_delta_rows` compares a
row to, and `_check_delta_summary_counts` reads each count the way the
renderers read it. A mean Δ cannot be derived from the rows, so a missing one
renders as a dash instead of `+0.000`.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from eval_harness.cli import main
from eval_harness.comment import render_delta_markdown
from eval_harness.runner import DeltaReport, RowDelta, diff_runs, render_delta_ascii
from eval_harness.runs import StoredRun

_ROOT = Path(__file__).resolve().parent.parent
_RUNNER = _ROOT / "eval_harness" / "runner.py"
_DEMO_CURRENT = _ROOT / "fixtures" / "demo_current.json"
_DEMO_BASELINE = _ROOT / "fixtures" / "demo_baseline.json"


def _demo_delta(tmp_path: Path) -> dict[str, Any]:
    """The real `diff-json` output over the committed demo fixtures."""
    out = tmp_path / "delta.json"
    rc = main(
        [
            "diff-json",
            "--current",
            str(_DEMO_CURRENT),
            "--baseline",
            str(_DEMO_BASELINE),
            "--format",
            "json",
            "--out",
            str(out),
        ]
    )
    assert rc == 1  # the demo flags qa_history_01
    payload: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    return payload


def _comment(tmp_path: Path, payload: dict[str, Any]) -> tuple[int, str, str]:
    delta = tmp_path / "edited.json"
    delta.write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "comment",
            "--repo",
            "o/r",
            "--pr",
            "1",
            "--delta-json",
            str(delta),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ----------------------------------------------------------------------
# The issue's reproduction, end to end
# ----------------------------------------------------------------------


def test_the_real_diff_json_output_still_round_trips(tmp_path: Path) -> None:
    payload = _demo_delta(tmp_path)
    assert DeltaReport.from_json(payload).to_json() == payload
    rc, out, err = _comment(tmp_path, payload)
    assert rc == 0, err
    assert "[X] mean Δ **-0.070** · flagged **1** · regressed 2" in out


def test_a_delta_json_without_its_summary_is_refused_at_exit_2(tmp_path: Path) -> None:
    payload = _demo_delta(tmp_path)
    del payload["summary"]
    rc, out, err = _comment(tmp_path, payload)
    assert rc == 2
    assert "Traceback" not in err
    assert "n_flagged" in err
    assert "rows give 1" in err
    assert "flagged **0**" not in out


_COUNTS = ["n_flagged", "n_regressed", "n_improved", "n_unchanged", "n_new", "n_removed"]


@pytest.mark.parametrize("key", _COUNTS)
@pytest.mark.parametrize("edit", ["deleted", "null", "off_by_one"])
def test_each_count_that_disagrees_with_the_rows_is_refused(
    tmp_path: Path, key: str, edit: str
) -> None:
    payload = _demo_delta(tmp_path)
    true_count = payload["summary"][key]
    assert true_count > 0  # every count is non-zero in the demo, so each arm can fire
    if edit == "deleted":
        del payload["summary"][key]
    elif edit == "null":
        payload["summary"][key] = None
    else:
        payload["summary"][key] = true_count + 1
    with pytest.raises(ValueError, match=f"'{key}' is .* but the rows give {true_count}"):
        DeltaReport.from_json(payload)


def test_a_missing_count_beside_rows_that_give_zero_still_reads(tmp_path: Path) -> None:
    # Control: missing means 0 to the renderers, so it is refused only when the
    # rows say otherwise. Older and partial payloads keep reading.
    report = DeltaReport.from_json({"rows": [], "summary": {}})
    assert report.summary == {}
    payload = _demo_delta(tmp_path)
    payload["rows"] = [r for r in payload["rows"] if r["status"] == "unchanged"]
    payload["summary"] = {"n_unchanged": 1}
    assert DeltaReport.from_json(payload).summary == {"n_unchanged": 1}


# ----------------------------------------------------------------------
# Rows `diff_runs` cannot produce
# ----------------------------------------------------------------------


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "example_id": "a",
        "baseline_score": 0.9,
        "current_score": 0.5,
        "delta": -0.4,
        "status": "regressed",
        "flagged": True,
    }
    row.update(over)
    return row


def _summary_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"n_flagged": sum(1 for r in rows if r.get("flagged"))}
    for r in rows:
        summary[f"n_{r['status']}"] = summary.get(f"n_{r['status']}", 0) + 1
    return summary


# (id, the row(s), a substring of the refusal). Each summary agrees with its
# rows, so the row rule is the only one that can fire.
_BAD_ROWS: list[tuple[str, list[dict[str, Any]], str]] = [
    (
        "issue_unchanged_beside_a_flagged_rise",
        [_row(baseline_score=0.5, current_score=0.5, delta=0.4, status="unchanged")],
        "give delta=0.0, status='unchanged', flagged=False",
    ),
    (
        "flag_on_a_drop_inside_the_threshold",
        [_row(current_score=0.85, delta=-0.05)],
        "status='regressed', flagged=False",
    ),
    (
        "flag_missing_on_a_drop_past_the_threshold",
        [_row(flagged=False)],
        "status='regressed', flagged=True",
    ),
    (
        "the_d034_exact_threshold_drop_flagged",
        [_row(baseline_score=0.8, current_score=0.7, delta=-0.1)],
        "give delta=-0.1, status='regressed', flagged=False",
    ),
    (
        "improved_status_on_a_drop",
        [_row(current_score=0.85, delta=-0.05, status="improved", flagged=False)],
        "status='regressed'",
    ),
    (
        "delta_that_is_not_the_scores_difference",
        [_row(delta=-0.3)],
        "give delta=-0.4",
    ),
    (
        "new_row_with_a_baseline_score",
        [_row(current_score=0.5, delta=None, status="new", flagged=False)],
        "status='regressed'",
    ),
    (
        "new_row_without_a_current_score",
        [_row(current_score=None, delta=None, status="new", flagged=False)],
        "status='removed'",
    ),
    (
        "removed_row_with_a_current_score",
        [_row(baseline_score=None, delta=None, status="removed", flagged=False)],
        "status='new'",
    ),
    (
        "row_with_neither_score",
        [_row(baseline_score=None, current_score=None, delta=None, status="new", flagged=False)],
        "neither a baseline_score nor a current_score",
    ),
    (
        "duplicate_example_id",
        [_row(), _row()],
        "duplicate example_id 'a'",
    ),
]


@pytest.mark.parametrize(
    ("rows", "needle"), [c[1:] for c in _BAD_ROWS], ids=[c[0] for c in _BAD_ROWS]
)
def test_a_row_diff_runs_cannot_produce_is_refused_on_both_paths(
    rows: list[dict[str, Any]], needle: str
) -> None:
    payload = {"threshold_drop": 0.1, "rows": rows, "summary": _summary_for(rows)}
    with pytest.raises(ValueError, match=re.escape(needle)) as read:
        DeltaReport.from_json(payload)
    with pytest.raises(ValueError, match=re.escape(needle)) as built:
        DeltaReport(
            current_run_id="current",
            baseline_run_id="baseline",
            suite="(unknown)",
            threshold_drop=0.1,
            rows=tuple(RowDelta(**r) for r in rows),
            summary=_summary_for(rows),
        )
    # One definition: the same words on both paths.
    assert str(read.value) == str(built.value)


@pytest.mark.parametrize(("rows", "needle"), [c[1:] for c in _BAD_ROWS[:1]], ids=["issue_row"])
def test_the_comment_cli_refuses_it_at_exit_2(
    tmp_path: Path, rows: list[dict[str, Any]], needle: str
) -> None:
    payload = {"threshold_drop": 0.1, "rows": rows, "summary": _summary_for(rows)}
    rc, out, err = _comment(tmp_path, payload)
    assert rc == 2
    assert needle in err
    assert "Traceback" not in err
    assert out == ""


def test_a_hand_built_report_with_the_default_summary_and_a_flagged_row_is_refused() -> None:
    # The issue's in-code shape: rendered `regressed=0 (flagged=0)` above a FLAG row.
    with pytest.raises(ValueError, match="'n_flagged' is None but the rows give 1"):
        DeltaReport("c", "b", "s", 0.1, (RowDelta("a", 0.9, 0.5, -0.4, "regressed", True),))


# ----------------------------------------------------------------------
# One definition: diff_runs builds rows the check accepts, at every threshold
# ----------------------------------------------------------------------


def _run(run_id: str, scores: dict[str, float]) -> StoredRun:
    return StoredRun(
        run_id=run_id,
        started_at="2026-01-01T00:00:00Z",
        suite="s",
        dataset_version="v1",
        judge_model=None,
        judge_kappa=None,
        mean_score=sum(scores.values()) / len(scores),
        n_rows=len(scores),
        git_sha=None,
        rows={k: (v, "r") for k, v in scores.items()},
    )


@pytest.mark.parametrize("threshold", [0.0, 0.0125, 0.05, 0.1, 0.30000000000000004, 1.0])
def test_every_report_diff_runs_builds_reads_back(threshold: float) -> None:
    # The ten one-decimal drops of #289 plus a rise, an unchanged, a new and a
    # removed id: diff_runs constructs a DeltaReport, so a disagreement between
    # its rows and the check would raise here, and the JSON must read back equal.
    base = {f"d{i}": (i + 1) / 10 for i in range(10)} | {"up": 0.2, "same": 0.5, "gone": 0.4}
    cur = {f"d{i}": i / 10 for i in range(10)} | {"up": 0.9, "same": 0.5, "fresh": 0.3}
    report = diff_runs(_run("cur", cur), _run("base", base), threshold_drop=threshold)
    assert {r.status for r in report.rows} == {
        "regressed",
        "improved",
        "unchanged",
        "new",
        "removed",
    }
    again = DeltaReport.from_json(json.loads(json.dumps(report.to_json())))
    assert again == report


def _calls(fn_name: str) -> set[str]:
    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    return {
        n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def test_diff_runs_and_the_row_check_share_one_verdict() -> None:
    assert "_row_verdict" in _calls("diff_runs")
    assert "_row_verdict" in _calls("_check_delta_rows")
    # And diff_runs no longer decides a row on its own.
    assert "_status_for" not in _calls("diff_runs")


# ----------------------------------------------------------------------
# A mean Δ the record does not carry renders as a dash, never +0.000
# ----------------------------------------------------------------------


@pytest.mark.parametrize("mean", ["missing", None])
def test_an_unknown_mean_delta_is_a_dash_in_both_renderers(tmp_path: Path, mean: Any) -> None:
    payload = _demo_delta(tmp_path)
    if mean == "missing":
        del payload["summary"]["mean_delta"]
    else:
        payload["summary"]["mean_delta"] = mean
    report = DeltaReport.from_json(payload)
    md = render_delta_markdown(report)
    assert "[X] mean Δ **—** · flagged **1**" in md
    ascii_summary = render_delta_ascii(report).splitlines()[-1]
    assert ascii_summary.startswith("summary: mean Δ=-  regressed=2 (flagged=1)")


def test_a_present_mean_delta_still_renders_its_value(tmp_path: Path) -> None:
    # Control: a real 0.0 is a value, not a missing one.
    payload = _demo_delta(tmp_path)
    payload["summary"]["mean_delta"] = 0.0
    report = DeltaReport.from_json(payload)
    assert "mean Δ **+0.000**" in render_delta_markdown(report)
    assert "summary: mean Δ=+0.000  " in render_delta_ascii(report)
