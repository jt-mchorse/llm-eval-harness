"""`run` rejects a bad --threshold-drop or --baseline before it scores or saves (#301).

Both were checked only inside the post-run diff, after every row was scored
and the run saved. The command exited 2, but the saved run became the suite's
latest -- the next run's default baseline. Measured with stub judges: a 0.9
baseline, then a 0.2 run with a typo'd ``--threshold-drop -0.1`` (exit 2, 10
judge calls, saved), then the same 0.2 run with the typo fixed: it diffed
against the rejected run and passed the gate at exit 0.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import main

ROOT = Path(__file__).resolve().parent.parent
DATASET = "fixtures/sample_factuality_v1.jsonl"


class _Counting:
    """A judge backend scoring every row at `score`, counting its calls."""

    calls = 0
    score = 0.9

    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake-judge"

    def complete(self, system: str, user: str) -> str:
        type(self).calls += 1
        return f"SCORE: {type(self).score}\nREASONING: stub\n"


@pytest.fixture(autouse=True)
def _at_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    _Counting.calls = 0
    _Counting.score = 0.9


def _run(db: Path, *extra: str, score: float = 0.9) -> int:
    _Counting.score = score
    with patch("eval_harness.cli.AnthropicBackend", _Counting):
        return main(["run", "--suite", "s", "--dataset", DATASET, "--db", str(db), *extra])


def _saved_runs(db: Path) -> int:
    if not db.exists():
        return 0
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT count(*) FROM runs").fetchone()[0]


@pytest.mark.parametrize("value", ["-0.1", "nan", "inf"])
@pytest.mark.parametrize("first_run", [True, False], ids=["first-run", "with-baseline"])
@pytest.mark.parametrize("no_diff", [False, True], ids=["diff", "no-diff"])
def test_a_bad_threshold_costs_nothing_and_saves_nothing(
    tmp_path: Path, capsys, value: str, first_run: bool, no_diff: bool
) -> None:
    db = tmp_path / "runs.db"
    if not first_run:
        assert _run(db) == 0
    calls, runs = _Counting.calls, _saved_runs(db)
    extra = ["--threshold-drop", value, *(["--no-diff"] if no_diff else [])]
    assert _run(db, *extra, score=0.2) == 2
    assert "threshold_drop must be a finite number" in capsys.readouterr().err
    assert _Counting.calls == calls, "the judge was paid for a run that was going to be rejected"
    assert _saved_runs(db) == runs, "a rejected run was saved and would become the next baseline"


def test_an_unknown_baseline_costs_nothing_and_saves_nothing(tmp_path: Path, capsys) -> None:
    db = tmp_path / "runs.db"
    assert _run(db) == 0
    calls = _Counting.calls
    assert _run(db, "--baseline", "no-such-run", score=0.2) == 2
    assert "no-such-run" in capsys.readouterr().err
    assert _Counting.calls == calls
    assert _saved_runs(db) == 1


def test_the_gate_still_fails_after_a_rejected_typo(tmp_path: Path) -> None:
    # The measured sequence, end to end: the regression must not be laundered.
    db = tmp_path / "runs.db"
    assert _run(db, score=0.9) == 0
    assert _run(db, "--threshold-drop", "-0.1", score=0.2) == 2
    assert _run(db, "--threshold-drop", "0.1", score=0.2) == 1
