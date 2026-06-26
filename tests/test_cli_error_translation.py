"""Lock tests for #104: the read-side CLI subcommands (`list` / `diff` /
`diff-json` / `comment`) translate data-layer exceptions into a clean
`::error::` line on stderr + exit 2, instead of letting them escape as a raw
traceback.

Before the fix each of these inputs raised an uncaught
`ValueError` / `KeyError` / `FileNotFoundError` out of `cli.main`, breaking the
CLI's `0 = clean / 1 = findings|regression / 2 = I/O or usage error` exit
contract (the contract `validate` and `run` already honor). The
success-path guards at the bottom pin the unchanged exit-0 / exit-1 behavior so
the error translation can't silently swallow a real diff result.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness import runs
from eval_harness.cli import main


def _seed_one_run(db: Path, *, run_id: str, suite: str = "s") -> None:
    with runs.connect(db) as conn:
        runs.init_db_on(conn)
        runs.write_run(
            conn,
            run_id=run_id,
            started_at="2026-01-01T00:00:00Z",
            suite=suite,
            dataset_version="v0.1",
            judge_model="fake",
            judge_kappa=0.8,
            mean_score=0.9,
            n_rows=1,
            git_sha=None,
            rows=[("ex1", 0.9, "ok")],
        )


def _run_result_json(path: Path, *, run_id: str, score: float = 0.9) -> None:
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "started_at": "2026-01-01T00:00:00Z",
                "suite": "s",
                "mean_score": score,
                "n_rows": 1,
                "rows": [{"example_id": "ex1", "score": score, "reasoning": "ok"}],
            }
        ),
        encoding="utf-8",
    )


# --- error translation: every read-side path → ::error:: + exit 2 -----------


@pytest.mark.parametrize("limit", ["0", "-3"])
def test_list_bad_limit_exits_two(tmp_path: Path, capsys, limit: str) -> None:
    db = tmp_path / "r.db"
    with runs.connect(db) as conn:
        runs.init_db_on(conn)
    rc = main(["list", "--db", str(db), "--limit", limit])
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


def test_diff_unknown_run_exits_two(tmp_path: Path, capsys) -> None:
    db = tmp_path / "r.db"
    _seed_one_run(db, run_id="real")
    rc = main(["diff", "--db", str(db), "--current", "nope", "--baseline", "real"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "nope" in err


def test_diff_json_missing_file_exits_two(tmp_path: Path, capsys) -> None:
    rc = main(
        ["diff-json", "--current", str(tmp_path / "a.json"), "--baseline", str(tmp_path / "b.json")]
    )
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


def test_diff_json_corrupt_payload_exits_two(tmp_path: Path, capsys) -> None:
    # A non-finite row score is rejected by load_run_result_from_json (ValueError);
    # it must surface as a clean exit 2, not a traceback. `json.loads` parses the
    # bare `NaN` token natively, so this is a reachable on-disk corruption.
    cur = tmp_path / "cur.json"
    cur.write_text(
        '{"run_id":"c","started_at":"t","suite":"s","mean_score":0.9,'
        '"rows":[{"example_id":"ex1","score":NaN,"reasoning":"x"}]}',
        encoding="utf-8",
    )
    base = tmp_path / "base.json"
    _run_result_json(base, run_id="b")
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


def test_diff_json_invalid_json_exits_two(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    base = tmp_path / "base.json"
    _run_result_json(base, run_id="b")
    rc = main(["diff-json", "--current", str(bad), "--baseline", str(base)])
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


def test_comment_missing_file_exits_two(tmp_path: Path, capsys) -> None:
    rc = main(
        [
            "comment",
            "--repo",
            "o/n",
            "--pr",
            "1",
            "--delta-json",
            str(tmp_path / "d.json"),
            "--dry-run",
        ]
    )
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


# --- success-path regression guards: exit 0/1 unchanged ---------------------


def test_diff_json_success_path_unchanged(tmp_path: Path, capsys) -> None:
    # Two identical runs → no regression → exit 0 (the error translation must not
    # swallow a legitimate diff result).
    cur = tmp_path / "cur.json"
    base = tmp_path / "base.json"
    _run_result_json(cur, run_id="c", score=0.9)
    _run_result_json(base, run_id="b", score=0.9)
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 0
    assert "::error::" not in capsys.readouterr().err


def test_diff_json_regression_still_exits_one(tmp_path: Path, capsys) -> None:
    # A real regression (score drops past the default 0.1 threshold) must still
    # exit 1 — the flagged-row exit code is not collapsed into the error path.
    cur = tmp_path / "cur.json"
    base = tmp_path / "base.json"
    _run_result_json(cur, run_id="c", score=0.2)
    _run_result_json(base, run_id="b", score=0.9)
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 1
