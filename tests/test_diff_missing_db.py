"""`diff` on a `--db` that does not exist creates nothing (#323).

`diff` only reads the run history, but it opened the path with `connect`
(which `mkdir -p`s the parent) and `init_db_on` (which writes the schema)
before looking the runs up. A typo'd `--db` therefore left a fresh empty
database, and any missing directories, on disk, and then reported
"no run with id". `list` already answers a missing path without creating it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_harness import runs
from eval_harness.cli import main


@pytest.mark.parametrize("fmt", ["ascii", "json", "markdown"])
def test_diff_on_a_missing_db_creates_nothing(
    fmt: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parent = tmp_path / "typo"
    db = parent / "runs.db"
    rc = main(["diff", "--db", str(db), "--current", "a", "--baseline", "b", "--format", fmt])
    err = capsys.readouterr().err
    assert rc == 2
    assert f"::error::cannot use --db {db}: no database at that path" in err
    assert not db.exists()
    assert not parent.exists()


def test_diff_on_a_missing_db_in_an_existing_dir_creates_no_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "runs.db"
    rc = main(["diff", "--db", str(db), "--current", "a", "--baseline", "b"])
    assert rc == 2
    assert "no database at that path" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_diff_on_an_existing_db_still_reports_the_unknown_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Control: an existing database still reaches the run lookup."""
    db = tmp_path / "runs.db"
    with runs.connect(db) as conn:
        runs.init_db_on(conn)
    rc = main(["diff", "--db", str(db), "--current", "a", "--baseline", "b"])
    assert rc == 2
    assert "::error::no run with id 'a'" in capsys.readouterr().err
