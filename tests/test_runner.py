"""Tests for the regression runner: scoring, persistence, and per-row diffs."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_harness.judge import Judge
from eval_harness.runner import (
    DatasetEchoSource,
    RunSpec,
    diff_runs,
    render_delta_ascii,
    run_suite,
)
from eval_harness.runs import connect, read_run


class ConstantBackend:
    """Judge backend that always returns a fixed SCORE/REASONING block."""

    def __init__(self, score: float, reasoning: str = "constant") -> None:
        self._block = f"SCORE: {score:.3f}\nREASONING: {reasoning}\n"

    def complete(self, system: str, user: str) -> str:
        return self._block


class PromptMatchBackend:
    """Judge backend that emits a score per prompt-substring match.

    The substring matches against the `user` block (which contains the example
    input + the candidate response), so tests can route by either side.
    """

    def __init__(self, scores: dict[str, float]) -> None:
        self._scores = scores

    def complete(self, system: str, user: str) -> str:
        for needle, score in self._scores.items():
            if needle in user:
                return f"SCORE: {score:.3f}\nREASONING: scored on {needle!r}\n"
        return "SCORE: 0.500\nREASONING: default\n"


def _write_sample_dataset(path: Path) -> None:
    lines = [
        '{"dataset_version":"factuality-v0.1","expected_outputs":[{"kind":"exact","value":"Paris"}],"id":"q1","input":"capital of france","provenance":{"source":"test"}}',
        '{"dataset_version":"factuality-v0.1","expected_outputs":[{"kind":"exact","value":"Tokyo"}],"id":"q2","input":"capital of japan","provenance":{"source":"test"}}',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestRunSuite:
    def test_persists_run_and_returns_aggregate(self, tmp_path: Path) -> None:
        dataset = tmp_path / "ds.jsonl"
        _write_sample_dataset(dataset)
        db = tmp_path / "runs.db"
        judge = Judge(backend=ConstantBackend(score=0.8))
        spec = RunSpec(
            suite="faithfulness",
            dataset_path=dataset,
            judge=judge,
            answer_source=DatasetEchoSource(),
            judge_model="test-model",
        )
        result = run_suite(spec, db_path=db, started_at="2026-05-15T19:00:00Z", run_id="r-fixed")
        assert result.run_id == "r-fixed"
        assert result.n_rows == 2
        assert result.mean_score == pytest.approx(0.8)
        assert {r.example_id for r in result.rows} == {"q1", "q2"}

        # Persistence round-trip.
        with connect(db) as conn:
            stored = read_run(conn, "r-fixed")
        assert stored.mean_score == pytest.approx(0.8)
        assert stored.rows == {"q1": (0.8, "constant"), "q2": (0.8, "constant")}

    def test_empty_dataset_rejected(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        judge = Judge(backend=ConstantBackend(score=1.0))
        spec = RunSpec(
            suite="s",
            dataset_path=empty,
            judge=judge,
            answer_source=DatasetEchoSource(),
        )
        with pytest.raises(ValueError, match="empty"):
            run_suite(spec, db_path=tmp_path / "db.sqlite")


class TestDelta:
    def test_regression_flagged_when_drop_exceeds_threshold(self, tmp_path: Path) -> None:
        dataset = tmp_path / "ds.jsonl"
        _write_sample_dataset(dataset)
        db = tmp_path / "runs.db"
        baseline_judge = Judge(backend=PromptMatchBackend({"france": 0.9, "japan": 0.9}))
        current_judge = Judge(backend=PromptMatchBackend({"france": 0.7, "japan": 0.9}))
        base_spec = RunSpec("s", dataset, baseline_judge, DatasetEchoSource())
        cur_spec = RunSpec("s", dataset, current_judge, DatasetEchoSource())

        baseline_result = run_suite(
            base_spec, db_path=db, started_at="2026-05-15T18:00:00Z", run_id="b1"
        )
        current_result = run_suite(
            cur_spec, db_path=db, started_at="2026-05-15T19:00:00Z", run_id="c1"
        )

        with connect(db) as conn:
            base = read_run(conn, baseline_result.run_id)
            cur = read_run(conn, current_result.run_id)
        report = diff_runs(cur, base, threshold_drop=0.1)
        flagged = {r.example_id: r for r in report.rows if r.flagged}
        assert set(flagged) == {"q1"}
        assert flagged["q1"].delta == pytest.approx(-0.2)
        assert report.summary["n_flagged"] == 1
        assert report.summary["n_regressed"] == 1
        assert report.summary["n_unchanged"] == 1

    def test_new_and_removed_rows_tagged(self, tmp_path: Path) -> None:
        ds_old = tmp_path / "old.jsonl"
        ds_new = tmp_path / "new.jsonl"
        _write_sample_dataset(ds_old)
        # New dataset drops q2, adds q3.
        ds_new.write_text(
            '{"dataset_version":"factuality-v0.1","expected_outputs":[{"kind":"exact","value":"Paris"}],"id":"q1","input":"capital of france","provenance":{"source":"test"}}\n'
            '{"dataset_version":"factuality-v0.1","expected_outputs":[{"kind":"exact","value":"Brasilia"}],"id":"q3","input":"capital of brazil","provenance":{"source":"test"}}\n',
            encoding="utf-8",
        )
        db = tmp_path / "runs.db"
        judge = Judge(backend=ConstantBackend(score=1.0))
        baseline_result = run_suite(
            RunSpec("s", ds_old, judge, DatasetEchoSource()),
            db_path=db,
            started_at="2026-05-15T18:00:00Z",
            run_id="b1",
        )
        current_result = run_suite(
            RunSpec("s", ds_new, judge, DatasetEchoSource()),
            db_path=db,
            started_at="2026-05-15T19:00:00Z",
            run_id="c1",
        )
        with connect(db) as conn:
            report = diff_runs(
                read_run(conn, current_result.run_id), read_run(conn, baseline_result.run_id)
            )
        statuses = {r.example_id: r.status for r in report.rows}
        assert statuses == {"q1": "unchanged", "q2": "removed", "q3": "new"}

    def test_cross_suite_diff_rejected(self, tmp_path: Path) -> None:
        dataset = tmp_path / "ds.jsonl"
        _write_sample_dataset(dataset)
        db = tmp_path / "runs.db"
        judge = Judge(backend=ConstantBackend(score=1.0))
        a = run_suite(
            RunSpec("alpha", dataset, judge, DatasetEchoSource()),
            db_path=db,
            started_at="2026-05-15T18:00:00Z",
            run_id="a",
        )
        b = run_suite(
            RunSpec("beta", dataset, judge, DatasetEchoSource()),
            db_path=db,
            started_at="2026-05-15T19:00:00Z",
            run_id="b",
        )
        with connect(db) as conn, pytest.raises(ValueError, match="across suites"):
            diff_runs(read_run(conn, a.run_id), read_run(conn, b.run_id))


class TestRenderDeltaAscii:
    def test_renders_table_with_flag_and_summary(self, tmp_path: Path) -> None:
        dataset = tmp_path / "ds.jsonl"
        _write_sample_dataset(dataset)
        db = tmp_path / "runs.db"
        baseline_judge = Judge(backend=PromptMatchBackend({"france": 0.9, "japan": 0.9}))
        current_judge = Judge(backend=PromptMatchBackend({"france": 0.5, "japan": 0.95}))
        run_suite(
            RunSpec("s", dataset, baseline_judge, DatasetEchoSource()),
            db_path=db,
            started_at="2026-05-15T18:00:00Z",
            run_id="b1",
        )
        run_suite(
            RunSpec("s", dataset, current_judge, DatasetEchoSource()),
            db_path=db,
            started_at="2026-05-15T19:00:00Z",
            run_id="c1",
        )
        with connect(db) as conn:
            report = diff_runs(read_run(conn, "c1"), read_run(conn, "b1"), threshold_drop=0.1)
        out = render_delta_ascii(report)
        assert "delta c1" in out
        assert "b1" in out
        assert "FLAG" in out
        assert "q1" in out
        assert "q2" in out
        assert "summary:" in out


# ----------------------------------------------------------------------
# threshold_drop validation (#38)
# ----------------------------------------------------------------------
# `_status_for(delta, threshold_drop)` flips the sign: `delta < -threshold_drop`.
# A negative `threshold_drop` silently inverts regression detection (passing
# PRs reported as failing and vice versa). `diff_runs` is the single library
# boundary every CLI surface (`run`, `diff`, `diff-json`) funnels through, so
# the guard lives there.


def _make_two_runs_for_diff(tmp_path: Path) -> tuple:
    """Helper: produce two persisted runs the diff layer can compare."""
    dataset = tmp_path / "ds.jsonl"
    _write_sample_dataset(dataset)
    db = tmp_path / "runs.db"
    baseline_judge = Judge(backend=PromptMatchBackend({"france": 0.9, "japan": 0.9}))
    current_judge = Judge(backend=PromptMatchBackend({"france": 0.7, "japan": 0.9}))
    run_suite(
        RunSpec("s", dataset, baseline_judge, DatasetEchoSource()),
        db_path=db,
        started_at="2026-05-15T18:00:00Z",
        run_id="b1",
    )
    run_suite(
        RunSpec("s", dataset, current_judge, DatasetEchoSource()),
        db_path=db,
        started_at="2026-05-15T19:00:00Z",
        run_id="c1",
    )
    with connect(db) as conn:
        return read_run(conn, "c1"), read_run(conn, "b1")


def test_diff_runs_rejects_negative_threshold_drop(tmp_path: Path) -> None:
    cur, base = _make_two_runs_for_diff(tmp_path)
    # Error message was tightened in #42 from "must be >= 0.0" to "must be
    # a finite number >= 0.0" so the contract covers NaN/+Infinity too.
    with pytest.raises(
        ValueError, match=r"threshold_drop must be a finite number >= 0\.0; got -0\.01"
    ):
        diff_runs(cur, base, threshold_drop=-0.01)


# Issue #42: extend the sign-only threshold_drop check to finiteness. NaN
# slipped past `threshold_drop < 0.0` (NaN comparisons are always false),
# then `delta < -NaN` is also always false → every row silently classified
# as non-flagged → the CI regression gate silently disabled. Same shape in
# sister repo ai-app-integration-tests #24 finiteness sweep.
@pytest.mark.parametrize(
    "bad_value",
    [float("nan"), float("inf"), float("-inf")],
)
def test_diff_runs_rejects_non_finite_threshold_drop(tmp_path: Path, bad_value: float) -> None:
    cur, base = _make_two_runs_for_diff(tmp_path)
    with pytest.raises(ValueError, match=r"threshold_drop must be a finite number >= 0\.0"):
        diff_runs(cur, base, threshold_drop=bad_value)


def test_diff_runs_accepts_zero_threshold_drop(tmp_path: Path) -> None:
    # Boundary case: zero means "flag any drop, no tolerance". Valid setting
    # — pins that the guard is `< 0`, not `<= 0`.
    cur, base = _make_two_runs_for_diff(tmp_path)
    report = diff_runs(cur, base, threshold_drop=0.0)
    # q1 dropped 0.9 → 0.7; with zero tolerance any drop flags.
    flagged_ids = {r.example_id for r in report.rows if r.flagged}
    assert flagged_ids == {"q1"}
    assert report.threshold_drop == 0.0


def test_diff_runs_accepts_positive_threshold_drop(tmp_path: Path) -> None:
    # Regression pin: existing canonical positive value continues to work.
    cur, base = _make_two_runs_for_diff(tmp_path)
    report = diff_runs(cur, base, threshold_drop=0.05)
    assert report.threshold_drop == 0.05
    # 0.2 drop > 0.05 tolerance — q1 still flagged.
    assert any(r.flagged for r in report.rows if r.example_id == "q1")


@pytest.mark.parametrize("bad", [-1e-6, -0.001, -0.5, -1.0])
def test_diff_runs_negative_sweep_all_raise(tmp_path: Path, bad: float) -> None:
    cur, base = _make_two_runs_for_diff(tmp_path)
    # Message tightened in #42 to "must be a finite number >= 0.0".
    with pytest.raises(ValueError, match=r"threshold_drop must be a finite number >= 0\.0"):
        diff_runs(cur, base, threshold_drop=bad)
