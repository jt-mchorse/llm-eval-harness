"""A bad `--db` is the CLI's exit-2 line, and `run` finds out before it pays (#275).

The `--db` path was the one operator input of `run`, `diff` and `list` with no
exit-2 guard. Measured on `23ec9ab`:

    list --db junk.db                -> exit 1  sqlite3.DatabaseError: file is not a database
    list --db dirdb                  -> exit 1  sqlite3.OperationalError: unable to open database file
    diff --db afile/x.db ...         -> exit 1  FileExistsError (connect's mkdir)
    run  --db junk.db  (10 rows)     -> exit 1  after 10 judge calls, result never printed

Exit 1 on these subcommands means "a row regressed".
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import main
from eval_harness.judge import Judge
from eval_harness.runner import DatasetEchoSource, RunSpec, run_suite

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATASET = ROOT / "fixtures" / "sample_factuality_v1.jsonl"


class _CountingBackend:
    calls = 0

    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake"
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        type(self).calls += 1
        return "SCORE: 1.0\nREASONING: ok\n"


def _bad_db(kind: str, tmp_path: Path) -> Path:
    if kind == "not-a-database":
        p = tmp_path / "junk.db"
        p.write_text("not a db", encoding="utf-8")
        return p
    if kind == "a-directory":
        p = tmp_path / "dirdb"
        p.mkdir()
        return p
    # A parent that is a regular file: connect()'s mkdir raises FileExistsError.
    parent = tmp_path / "afile"
    parent.write_text("", encoding="utf-8")
    return parent / "x.db"


KINDS = ["not-a-database", "a-directory", "parent-is-a-file"]


@pytest.mark.parametrize("kind", KINDS)
def test_run_refuses_a_bad_db_before_any_judge_call(
    kind: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _bad_db(kind, tmp_path)
    _CountingBackend.calls = 0
    out = tmp_path / "result.json"
    with patch("eval_harness.cli.AnthropicBackend", _CountingBackend):
        rc = main(
            [
                "run",
                "--suite",
                "s",
                "--dataset",
                str(SAMPLE_DATASET),
                "--db",
                str(db),
                "--no-diff",
                "--out",
                str(out),
            ]
        )
    err = capsys.readouterr().err
    assert rc == 2
    assert f"::error::cannot use --db {db}" in err
    assert "Traceback" not in err
    assert _CountingBackend.calls == 0
    assert not out.exists()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("subcommand", ["diff", "list"])
def test_read_side_subcommands_exit_two_on_a_bad_db(
    kind: str, subcommand: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _bad_db(kind, tmp_path)
    argv = ["list", "--db", str(db)]
    if subcommand == "diff":
        argv = ["diff", "--db", str(db), "--current", "a", "--baseline", "b"]
    rc = main(argv)
    captured = capsys.readouterr()
    if subcommand == "list" and kind == "parent-is-a-file":
        # `list` answers a path that does not exist with "no runs" on purpose
        # (it never creates a database); a parent that is a file is such a path.
        assert rc == 0
        assert "no database at" in captured.out
        return
    assert rc == 2
    assert f"::error::cannot use --db {db}" in captured.err


def test_run_suite_checks_the_database_before_scoring(tmp_path: Path) -> None:
    """The library seam too: a caller of `run_suite` paid per row as well."""
    _CountingBackend.calls = 0
    spec = RunSpec(
        suite="s",
        dataset_path=SAMPLE_DATASET,
        judge=Judge(backend=_CountingBackend()),
        answer_source=DatasetEchoSource(),
    )
    import sqlite3

    with pytest.raises(sqlite3.DatabaseError):
        run_suite(spec, db_path=_bad_db("not-a-database", tmp_path))
    assert _CountingBackend.calls == 0


def test_a_good_db_still_runs_and_writes(tmp_path: Path) -> None:
    """Control: the preflight creates the schema and the run proceeds."""
    _CountingBackend.calls = 0
    db = tmp_path / "nested" / "runs.db"
    with patch("eval_harness.cli.AnthropicBackend", _CountingBackend):
        rc = main(
            ["run", "--suite", "s", "--dataset", str(SAMPLE_DATASET), "--db", str(db), "--no-diff"]
        )
    assert rc == 0
    assert _CountingBackend.calls > 0
    assert main(["list", "--db", str(db)]) == 0
