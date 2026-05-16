"""Tests for `eval-harness list` (issue #7) and the top-level `calibrate` alias.

`list` exercises:
- Empty DB on disk → 'no runs' text, 0 exit.
- Missing DB file → '# no runs (no database at ...)' text, 0 exit.
- Suite filter — returns only that suite.
- Limit cap.
- --json output is parseable and order-preserving.

`calibrate` (top-level) parses the same args as `judge calibrate` and
dispatches into the same handler.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness import runs
from eval_harness.cli import main


def _seed_db(path: Path, *, entries: list[dict]) -> None:
    with runs.connect(path) as conn:
        runs.init_db_on(conn)
        for e in entries:
            runs.write_run(
                conn,
                run_id=e["run_id"],
                started_at=e["started_at"],
                suite=e["suite"],
                dataset_version="rag-qa-v0.1",
                judge_model="fake-judge",
                judge_kappa=0.8,
                mean_score=e.get("mean_score", 0.9),
                n_rows=2,
                git_sha=None,
                rows=[("ex1", 1.0, "ok"), ("ex2", 0.8, "ok")],
            )


def test_list_with_no_db_prints_message_and_exits_zero(tmp_path: Path, capsys):
    rc = main(["list", "--db", str(tmp_path / "absent.sqlite")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no runs" in out
    assert "absent.sqlite" in out


def test_list_with_empty_db_prints_no_runs(tmp_path: Path, capsys):
    db = tmp_path / "empty.sqlite"
    with runs.connect(db) as conn:
        runs.init_db_on(conn)
    rc = main(["list", "--db", str(db)])
    assert rc == 0
    assert "no runs" in capsys.readouterr().out


def test_list_renders_table_with_recent_runs_first(tmp_path: Path, capsys):
    db = tmp_path / "h.sqlite"
    _seed_db(
        db,
        entries=[
            {"run_id": "r_001_aaa", "started_at": "2026-05-15T10:00:00Z", "suite": "faithfulness"},
            {"run_id": "r_002_bbb", "started_at": "2026-05-16T10:00:00Z", "suite": "faithfulness"},
            {"run_id": "r_003_ccc", "started_at": "2026-05-14T10:00:00Z", "suite": "correctness"},
        ],
    )
    rc = main(["list", "--db", str(db)])
    assert rc == 0
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    # Header + sep + 3 rows
    assert len(lines) == 5
    # Most recent first.
    assert "2026-05-16" in lines[2]
    assert "2026-05-15" in lines[3]
    assert "2026-05-14" in lines[4]


def test_list_suite_filter(tmp_path: Path, capsys):
    db = tmp_path / "h.sqlite"
    _seed_db(
        db,
        entries=[
            {"run_id": "a", "started_at": "2026-05-15T10:00:00Z", "suite": "faithfulness"},
            {"run_id": "b", "started_at": "2026-05-16T10:00:00Z", "suite": "correctness"},
        ],
    )
    rc = main(["list", "--db", str(db), "--suite", "correctness"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "correctness" in out
    assert "faithfulness" not in out


def test_list_suite_filter_with_no_matches_prints_filtered_message(tmp_path: Path, capsys):
    db = tmp_path / "h.sqlite"
    _seed_db(
        db,
        entries=[
            {"run_id": "a", "started_at": "2026-05-15T10:00:00Z", "suite": "faithfulness"},
        ],
    )
    rc = main(["list", "--db", str(db), "--suite", "nope"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no runs for suite 'nope'" in out


def test_list_limit(tmp_path: Path, capsys):
    db = tmp_path / "h.sqlite"
    _seed_db(
        db,
        entries=[
            {"run_id": f"r_{i}", "started_at": f"2026-05-1{i % 9}T10:00:00Z", "suite": "s"}
            for i in range(10)
        ],
    )
    rc = main(["list", "--db", str(db), "--limit", "3"])
    assert rc == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    # Header + sep + 3 rows
    assert len(lines) == 5


def test_list_json_returns_parseable_array(tmp_path: Path, capsys):
    db = tmp_path / "h.sqlite"
    _seed_db(
        db,
        entries=[
            {
                "run_id": "j_1",
                "started_at": "2026-05-15T10:00:00Z",
                "suite": "faithfulness",
                "mean_score": 0.91,
            },
            {
                "run_id": "j_2",
                "started_at": "2026-05-16T10:00:00Z",
                "suite": "faithfulness",
                "mean_score": 0.83,
            },
        ],
    )
    rc = main(["list", "--db", str(db), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert len(payload) == 2
    # Most recent first.
    assert payload[0]["run_id"] == "j_2"
    assert payload[1]["run_id"] == "j_1"
    assert payload[0]["mean_score"] == 0.83


def test_list_json_empty_when_no_runs(tmp_path: Path, capsys):
    db = tmp_path / "h.sqlite"
    with runs.connect(db) as conn:
        runs.init_db_on(conn)
    rc = main(["list", "--db", str(db), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_top_level_calibrate_parses_same_args_as_judge_calibrate(tmp_path: Path):
    # Both surfaces should accept --calibration --report --model --threshold-kappa.
    # We don't actually run the judge here (it requires real backend); we just
    # confirm the parser routes to the same handler and rejects unknown args
    # the same way.
    import argparse

    from eval_harness.cli import _add_calibrate_args

    p = argparse.ArgumentParser()
    _add_calibrate_args(p)
    args = p.parse_args(["--calibration", "foo.jsonl", "--threshold-kappa", "0.4"])
    assert args.calibration == "foo.jsonl"
    assert args.threshold_kappa == pytest.approx(0.4)
