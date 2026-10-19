"""`list --limit` past SQLite's int64 is a usage error on both paths (#392).

`check_limit` only required a positive int, so `--limit 9223372036854775808`
reached the `LIMIT ?` bind and raised `OverflowError` -- a traceback at exit 1
when a database existed, while the missing-database answer exited 0. #325 says
the `--limit` answer must not depend on whether the database exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_harness import runs
from eval_harness.cli import main

INT64_MAX = 9223372036854775807


def _argv(db: Path, limit: int, as_json: bool) -> list[str]:
    argv = ["list", "--db", str(db), "--limit", str(limit)]
    if as_json:
        argv.append("--json")
    return argv


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
@pytest.mark.parametrize("has_db", [True, False], ids=["db", "no-db"])
@pytest.mark.parametrize("limit", [INT64_MAX + 1, 10**30], ids=["int64+1", "1e30"])
def test_limit_past_int64_exits_two(
    limit: int, has_db: bool, as_json: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "runs.db"
    if has_db:
        runs.init_db(str(db))
    rc = main(_argv(db, limit, as_json))
    captured = capsys.readouterr()
    assert rc == 2
    assert f"::error::limit must be at most {INT64_MAX}, got {limit}" in captured.err
    assert captured.out == ""
    assert db.exists() is has_db


@pytest.mark.parametrize("has_db", [True, False], ids=["db", "no-db"])
def test_limit_at_int64_max_still_lists(
    has_db: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Control: the largest bindable limit is accepted on both paths."""
    db = tmp_path / "runs.db"
    if has_db:
        runs.init_db(str(db))
    rc = main(_argv(db, INT64_MAX, as_json=True))
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "[]\n"


def test_list_runs_refuses_limit_past_int64() -> None:
    conn = runs.connect(":memory:")
    runs.init_db_on(conn)
    with pytest.raises(ValueError, match="limit must be at most"):
        runs.list_runs(conn, limit=INT64_MAX + 1)
    assert runs.list_runs(conn, limit=INT64_MAX) == []
