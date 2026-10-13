"""A ``threshold_drop`` above 1 is refused: it can never flag a row (#363).

Scores are in ``[0, 1]``, so a row's delta is in ``[-1, 1]`` and the gate
``delta < -threshold_drop`` cannot hold past 1. ``_checked_threshold_drop``
refused ``inf`` because it "flags nothing" and accepted ``5``, which flags
nothing too. On main (c46b3fb), ``diff-json --threshold-drop 5`` over a run
whose every row collapsed to 0 printed ``flagged=0`` and exited 0, where
``--threshold-drop 0.1`` exited 1.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import main
from eval_harness.runner import DeltaReport, diff_runs
from eval_harness.runs import StoredRun

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "fixtures" / "demo_baseline.json"

_TOO_LARGE = [1.0000000000000002, 1.5, 5.0, 10.0, 100.0]


def _collapsed(tmp_path: Path) -> Path:
    run = json.loads(BASELINE.read_text(encoding="utf-8"))
    run["run_id"] = "collapsed-" + run["run_id"]
    run["rows"] = [dict(r, score=0.0) for r in run["rows"]]
    run["mean_score"] = 0.0
    path = tmp_path / "collapsed.json"
    path.write_text(json.dumps(run), encoding="utf-8")
    return path


def _stored(run_id: str, score: float) -> StoredRun:
    return StoredRun(
        run_id=run_id,
        started_at="2026-10-13T00:00:00Z",
        suite="s",
        dataset_version="v",
        judge_model=None,
        judge_kappa=None,
        mean_score=score,
        n_rows=1,
        git_sha=None,
        rows={"e1": (score, "r")},
    )


@pytest.mark.parametrize("value", _TOO_LARGE)
def test_diff_runs_refuses_a_threshold_that_cannot_flag(value: float) -> None:
    with pytest.raises(ValueError, match=r"threshold_drop must be in \[0\.0, 1\.0\]"):
        diff_runs(_stored("cur", 0.0), _stored("base", 1.0), threshold_drop=value)


@pytest.mark.parametrize("value", _TOO_LARGE)
def test_the_delta_reader_refuses_it_too(value: float) -> None:
    with pytest.raises(ValueError, match=r"threshold_drop must be in \[0\.0, 1\.0\]"):
        DeltaReport.from_json({"threshold_drop": value, "rows": []})


def test_diff_json_exits_2_instead_of_passing_a_collapsed_run(tmp_path: Path, capsys) -> None:
    current = _collapsed(tmp_path)
    argv = ["diff-json", "--current", str(current), "--baseline", str(BASELINE)]
    assert main([*argv, "--threshold-drop", "0.1"]) == 1
    capsys.readouterr()
    assert main([*argv, "--threshold-drop", "5"]) == 2
    assert "threshold_drop must be in [0.0, 1.0]" in capsys.readouterr().err


def test_run_refuses_it_before_judging(tmp_path: Path, capsys, monkeypatch) -> None:
    calls = []

    class _Judge:
        def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
            self.model = model or "fake-judge"

        def complete(self, system: str, user: str) -> str:
            calls.append(user)
            return "SCORE: 0.2\nREASONING: stub\n"

    monkeypatch.chdir(ROOT)
    db = tmp_path / "runs.db"
    argv = ["run", "--suite", "s", "--dataset", "fixtures/sample_factuality_v1.jsonl"]
    with patch("eval_harness.cli.AnthropicBackend", _Judge):
        assert main([*argv, "--db", str(db), "--threshold-drop", "5"]) == 2
    assert "threshold_drop must be in [0.0, 1.0]" in capsys.readouterr().err
    assert calls == []


@pytest.mark.parametrize("value", [0.0, 0.1, 0.999, 1.0])
def test_the_domain_itself_is_still_accepted(value: float) -> None:
    report = diff_runs(_stored("cur", 0.0), _stored("base", 1.0), threshold_drop=value)
    assert report.threshold_drop == value
    assert DeltaReport.from_json({"threshold_drop": value, "rows": []}).threshold_drop == value
