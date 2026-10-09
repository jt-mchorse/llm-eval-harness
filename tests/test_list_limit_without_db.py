"""`list --limit` is validated whether or not the database exists (#325).

`_run_list` answers a missing `--db` with "no runs" before it calls
`list_runs`, which was the only place the limit was checked. So `--limit 0`
exited 0 with an empty listing on a fresh machine and exited 2 once a database
existed. The existing lock (`test_list_bad_limit_exits_two`) only covers a
database that already exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_harness import runs
from eval_harness.cli import main


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
@pytest.mark.parametrize("limit", ["0", "-3"])
def test_bad_limit_exits_two_without_a_database(
    limit: str, as_json: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "missing.db"
    argv = ["list", "--db", str(db), "--limit", limit]
    if as_json:
        argv.append("--json")
    rc = main(argv)
    captured = capsys.readouterr()
    assert rc == 2
    assert f"::error::limit must be a positive integer, got {int(limit)}" in captured.err
    assert captured.out == ""
    assert not db.exists()


def test_bad_limit_with_out_writes_nothing_without_a_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "list.txt"
    rc = main(["list", "--db", str(tmp_path / "missing.db"), "--limit", "0", "--out", str(out)])
    assert rc == 2
    assert not out.exists()


def test_valid_limit_without_a_database_still_lists_no_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Control: the missing-database answer itself is unchanged."""
    db = tmp_path / "missing.db"
    rc = main(["list", "--db", str(db), "--limit", "1"])
    assert rc == 0
    assert "no database at" in capsys.readouterr().out
    assert not db.exists()


@pytest.mark.parametrize("bad", [0, -1, True, 1.0, float("nan"), "3"])
def test_check_limit_is_the_list_runs_rule(bad: object) -> None:
    with pytest.raises(ValueError, match="limit must be a positive integer"):
        runs.check_limit(bad)
    conn = runs.connect(":memory:")
    runs.init_db_on(conn)
    with pytest.raises(ValueError, match="limit must be a positive integer"):
        runs.list_runs(conn, limit=bad)  # type: ignore[arg-type]
