"""A drop of exactly `threshold_drop` passes the gate wherever it happens (#289, D-034).

`diff_runs` subtracted the float scores: `0.7 - 0.8 == -0.10000000000000009`
but `0.6 - 0.7 == -0.09999999999999998`. Of the ten one-decimal drops at the
default threshold of 0.1, two (0.4 -> 0.3 and 0.8 -> 0.7) were flagged and
eight were not, although the README says a row is flagged when it regresses
by *more than* the threshold. `run`'s auto-diff -- the CI gate -- exited 1.
"""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import main
from eval_harness.runner import diff_runs
from eval_harness.runs import StoredRun

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATASET = Path("fixtures/sample_factuality_v1.jsonl")

_ONE_DECIMAL_DROPS = [(b / 10, (b - 1) / 10) for b in range(1, 11)]


def _run(run_id: str, rows: dict[str, float]) -> StoredRun:
    return StoredRun(
        run_id=run_id,
        started_at="2026-01-01T00:00:00Z",
        suite="s",
        dataset_version="v",
        judge_model=None,
        judge_kappa=None,
        mean_score=0.5,
        n_rows=len(rows),
        git_sha=None,
        rows={k: (v, "r") for k, v in rows.items()},
    )


def _diff(pairs: list[tuple[float, float]], threshold_drop: float = 0.1):
    base = _run("base0000", {f"r{i}": b for i, (b, _) in enumerate(pairs)})
    cur = _run("curr0000", {f"r{i}": c for i, (_, c) in enumerate(pairs)})
    return diff_runs(cur, base, threshold_drop=threshold_drop)


def test_every_drop_of_exactly_the_threshold_is_regressed_but_not_flagged() -> None:
    # The float subtraction really does split these, or this test is vacuous.
    assert sorted(c - b < -0.1 for b, c in _ONE_DECIMAL_DROPS) == [False] * 8 + [True] * 2
    report = _diff(_ONE_DECIMAL_DROPS)
    assert [(r.status, r.flagged) for r in report.rows] == [("regressed", False)] * 10
    assert report.summary["n_flagged"] == 0
    # The published delta is the exact difference, so it reads back as the drop.
    assert {r.delta for r in report.rows} == {-0.1}


@pytest.mark.parametrize(
    ("base", "cur", "threshold", "flagged"),
    [
        # One ULP past the threshold is past it: exactness is not a tolerance.
        (math.nextafter(0.8, 1.0), 0.7, 0.1, True),
        (0.8, math.nextafter(0.7, 0.0), 0.1, True),
        (0.8, 0.69, 0.1, True),
        (0.8, 0.71, 0.1, False),
        # Non-default thresholds.
        (0.8, 0.75, 0.05, False),
        (0.35, 0.3, 0.05, False),
        (0.9, 0.6, 0.3, False),
        (0.9, 0.59, 0.3, True),
        # A threshold of zero flags any drop at all, and nothing else.
        (0.3, 0.2, 0.0, True),
        (0.3, 0.3, 0.0, False),
    ],
)
def test_the_flag_is_decided_on_the_decimal_values(
    base: float, cur: float, threshold: float, flagged: bool
) -> None:
    (row,) = _diff([(base, cur)], threshold_drop=threshold).rows
    assert row.flagged is flagged


def test_equal_scores_are_unchanged_and_a_rise_is_improved() -> None:
    report = _diff([(0.3, 0.3), (0.1 + 0.2, 0.4)])
    assert [r.status for r in report.rows] == ["unchanged", "improved"]
    assert report.rows[0].delta == 0.0


class _Judge:
    score = "0.8"

    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake"

    def complete(self, system: str, user: str) -> str:
        return f"SCORE: {self.score}\nREASONING: stub\n"


def _judged_run(db: Path, score: str, *, diff: bool) -> int:
    judge = type("Judge", (_Judge,), {"score": score})
    argv = ["run", "--suite", "smoke", "--dataset", str(SAMPLE_DATASET), "--db", str(db)]
    with patch("eval_harness.cli.AnthropicBackend", judge):
        return main([*argv] if diff else [*argv, "--no-diff"])


@pytest.mark.parametrize(("baseline", "current"), [("0.8", "0.7"), ("0.4", "0.3")])
def test_the_ci_gate_passes_an_exact_threshold_drop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, baseline: str, current: str
) -> None:
    """Through `run`'s auto-diff, the exit code CI reads."""
    monkeypatch.chdir(ROOT)
    db = tmp_path / "runs.db"
    assert _judged_run(db, baseline, diff=False) == 0
    assert _judged_run(db, current, diff=True) == 0


def test_the_ci_gate_still_fails_a_drop_past_the_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    db = tmp_path / "runs.db"
    assert _judged_run(db, "0.8", diff=False) == 0
    assert _judged_run(db, "0.69", diff=True) == 1
