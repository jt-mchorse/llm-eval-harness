"""A delta record's `mean_delta` must be one `diff_runs` could publish (#449).

#435 refused a summary whose counts disagree with its rows and left the mean
unchecked, on the premise that "a mean cannot be checked against the rows".
The record carries both runs' `mean_score_*` and every score, which is all
`diff_runs` computes `mean_delta` from. A hand-edited `mean_delta` of `+0.5`,
over means of 0.77 and 0.84, was posted as the PR comment's headline at exit 0.
"""

from __future__ import annotations

import json
import math
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from eval_harness.runner import DeltaReport, diff_runs
from eval_harness.runs import StoredRun

ROOT = Path(__file__).resolve().parent.parent


def _run(run_id: str, rows: dict[str, float], mean: float | None = None) -> StoredRun:
    return StoredRun(
        run_id=run_id,
        started_at="2026-01-01T00:00:00Z",
        suite="s",
        dataset_version="v",
        judge_model=None,
        judge_kappa=None,
        mean_score=sum(rows.values()) / len(rows) if mean is None else mean,
        n_rows=len(rows),
        git_sha=None,
        rows={k: (v, "r") for k, v in rows.items()},
    )


def _demo_payload(tmp_path: Path) -> dict[str, Any]:
    out = tmp_path / "d.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "diff-json",
            "--current",
            str(ROOT / "fixtures" / "demo_current.json"),
            "--baseline",
            str(ROOT / "fixtures" / "demo_baseline.json"),
            "--format",
            "json",
            "--out",
            str(out),
        ],
        capture_output=True,
        cwd=ROOT,
    )  # fmt: skip  -- exit 1 means "a row regressed", which the demo pair has
    return json.loads(out.read_text())


def test_the_issue_repro_is_refused_by_the_comment_cli(tmp_path: Path) -> None:
    payload = _demo_payload(tmp_path)
    assert payload["summary"]["mean_delta"] == pytest.approx(-0.07)
    payload["summary"]["mean_delta"] = 0.5
    edited = tmp_path / "d2.json"
    edited.write_text(json.dumps(payload))
    r = subprocess.run(
        [sys.executable, "-m", "eval_harness.cli", "comment", "--repo", "a/b", "--pr", "1",
         "--delta-json", str(edited), "--dry-run"],
        capture_output=True, text=True, cwd=ROOT,
    )  # fmt: skip
    assert r.returncode == 2, r.stdout + r.stderr
    assert "mean_delta" in r.stdout + r.stderr
    assert "+0.500" not in r.stdout


@pytest.mark.parametrize("bad", [0.5, -0.0700001, 0.07, 0.0, -0.84])
def test_a_contradicting_mean_delta_is_refused_on_both_paths(tmp_path: Path, bad: float) -> None:
    payload = _demo_payload(tmp_path)
    payload["summary"]["mean_delta"] = bad
    with pytest.raises(ValueError, match="'mean_delta' is"):
        DeltaReport.from_json(payload)
    good = DeltaReport.from_json(_demo_payload(tmp_path))
    with pytest.raises(ValueError, match="'mean_delta' is"):
        DeltaReport(
            current_run_id=good.current_run_id,
            baseline_run_id=good.baseline_run_id,
            suite=good.suite,
            threshold_drop=good.threshold_drop,
            rows=good.rows,
            summary={**good.summary, "mean_delta": bad},
        )


@pytest.mark.parametrize("missing", ["null", "absent"])
def test_an_absent_or_null_mean_delta_still_reads(tmp_path: Path, missing: str) -> None:
    payload = _demo_payload(tmp_path)
    if missing == "null":
        payload["summary"]["mean_delta"] = None
    else:
        del payload["summary"]["mean_delta"]
    assert DeltaReport.from_json(payload).summary.get("mean_delta") is None


def _left_fold_mean(scores: list[float]) -> float:
    total = 0.0
    for s in scores:
        total += s
    return total / len(scores)


def _recorded_mean(rows: dict[str, float], how: str) -> float:
    scores = list(rows.values())
    if how == "left_fold":
        return _left_fold_mean(scores)
    if how == "fsum":
        return math.fsum(scores) / len(scores)
    return sum(scores) / len(scores)


@pytest.mark.parametrize("seed", range(200))
def test_every_diff_runs_record_reads_back(seed: int) -> None:
    """No false refusal: any record `diff_runs` writes is accepted by its reader.

    The runs' `mean_score` is recorded three ways, as the supported interpreters
    can record it: `sum / n`, a 3.11 left fold in *scoring* order (the record's
    rows are sorted by id, so they need not reproduce it), and `fsum / n`.
    """
    rng = random.Random(seed)
    grid = [round(rng.random(), rng.choice([1, 2, 3, 7, 17])) for _ in range(40)]
    ids = [f"e{i:02d}" for i in range(rng.randint(1, 12))]
    cur_ids = [i for i in ids if rng.random() < 0.85] or ids[:1]
    base_ids = [i for i in ids if rng.random() < 0.85] or ids[-1:]
    # Rows in scoring order, as `read_run` returns them; the record sorts by id.
    rng.shuffle(cur_ids)
    rng.shuffle(base_ids)
    cur = {i: rng.choice(grid) for i in cur_ids}
    base = {i: rng.choice(grid) for i in base_ids}
    for how in ("sum", "left_fold", "fsum"):
        current = _run("c", cur, _recorded_mean(cur, how))
        report = diff_runs(current, _run("b", base, _recorded_mean(base, how)))
        assert DeltaReport.from_json(json.loads(json.dumps(report.to_json()))) == report


def test_a_left_fold_mean_recorded_in_scoring_order_reads_back() -> None:
    """Why the check accepts any pairing instead of re-making `_decimal_mean`'s pick.

    `diff_runs` sees these rows in scoring order, where 3.11's left fold
    reproduces `mean_score`, so it uses the exact row mean. The record's rows
    are sorted by id, where no float mean reproduces it. Re-deciding the pick
    from the record took `_decimal(mean_score)` instead and refused this
    genuine record: measured, 2688 of 20,000 random such records.
    """
    cur = {"e6": 0.5, "e5": 0.957, "e0": 0.412, "e1": 0.611, "e3": 0.92, "e4": 1.0, "e2": 0.0}
    base = {"e0": 0.8, "e1": 0.6, "e2": 0.4, "e3": 0.5, "e4": 0.8, "e5": 0.2, "e6": 0.3}
    mean = _left_fold_mean(list(cur.values()))
    assert mean == 0.6285714285714284
    report = diff_runs(_run("c", cur, mean), _run("b", base))
    assert DeltaReport.from_json(report.to_json()) == report


@pytest.mark.parametrize(
    ("cur", "base"),
    [
        # One-sided suites: an all-new and an all-removed record.
        ({"a": 0.5, "b": 0.75}, {"z": 0.25}),
        ({"a": 0.2, "b": 0.1}, {"a": 0.3, "b": 0.0}),  # #336's -2.8e-17 pair
    ],
)
def test_records_from_hand_built_runs_read_back(cur: dict, base: dict) -> None:
    report = diff_runs(_run("c", cur), _run("b", base))
    assert DeltaReport.from_json(report.to_json()) == report


def test_a_record_written_before_336_still_reads() -> None:
    """Pre-#336 `diff_runs` published the float difference of the two means."""
    report = diff_runs(_run("c", {"a": 0.2, "b": 0.1}), _run("b", {"a": 0.3, "b": 0.0}))
    payload = report.to_json()
    legacy = payload["summary"]["mean_score_current"] - payload["summary"]["mean_score_baseline"]
    assert legacy != 0.0  # 2.8e-17: the value #336 stopped publishing
    payload["summary"]["mean_delta"] = legacy
    assert DeltaReport.from_json(payload).summary["mean_delta"] == legacy


def test_a_record_with_no_means_is_checked_against_its_rows() -> None:
    report = diff_runs(_run("c", {"a": 0.5}), _run("b", {"a": 0.75}))
    payload = report.to_json()
    for key in ("mean_score_current", "mean_score_baseline"):
        del payload["summary"][key]
    assert DeltaReport.from_json(payload).summary["mean_delta"] == -0.25
    payload["summary"]["mean_delta"] = 0.25
    with pytest.raises(ValueError, match="'mean_delta' is 0.25 but"):
        DeltaReport.from_json(payload)
