"""A database `run` can read but not write is refused before any judge call (#281).

#276's preflight, `check_db`, opened the database and ran the schema's
`CREATE TABLE IF NOT EXISTS`. On an existing database that writes nothing, so a
read-only one passed. Measured on `main`: `run_suite` over the 10-row sample
paid 10 judge calls and then raised `OperationalError: attempt to write a
readonly database`; `cli run` let it escape as a traceback at exit 1, which on
`run` reads as "a row regressed".
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import main
from eval_harness.judge import Judge
from eval_harness.runner import DatasetEchoSource, RunSpec, run_suite
from eval_harness.runs import check_db, connect, init_db

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATASET = ROOT / "fixtures" / "sample_factuality_v1.jsonl"

pytestmark = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores file permissions, so nothing here is read-only",
)


class _CountingBackend:
    calls = 0

    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake"
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        type(self).calls += 1
        return "SCORE: 1.0\nREASONING: ok\n"


@pytest.fixture(params=["read-only-file", "read-only-directory"])
def readonly_db(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Path]:
    folder = tmp_path / "dbdir"
    folder.mkdir()
    db = folder / "runs.db"
    init_db(db)
    target = db if request.param == "read-only-file" else folder
    target.chmod(0o444 if request.param == "read-only-file" else 0o555)
    try:
        yield db
    finally:
        target.chmod(0o644 if request.param == "read-only-file" else 0o755)


def test_check_db_refuses_a_database_it_cannot_write(readonly_db: Path) -> None:
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        check_db(readonly_db)


def test_run_suite_pays_no_judge_call_on_a_read_only_database(readonly_db: Path) -> None:
    backend = _CountingBackend()
    _CountingBackend.calls = 0
    spec = RunSpec("s", SAMPLE_DATASET, Judge(backend=backend), DatasetEchoSource())
    with pytest.raises(sqlite3.OperationalError):
        run_suite(spec, db_path=readonly_db)
    assert _CountingBackend.calls == 0


def test_cli_run_exits_2_before_any_judge_call(
    readonly_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _CountingBackend.calls = 0
    with patch("eval_harness.cli.AnthropicBackend", _CountingBackend):
        rc = main(
            [
                "run",
                "--suite",
                "s",
                "--dataset",
                str(SAMPLE_DATASET),
                "--db",
                str(readonly_db),
                "--no-diff",
                "--out",
                str(tmp_path / "result.json"),
            ]
        )
    err = capsys.readouterr().err
    assert rc == 2, err
    assert _CountingBackend.calls == 0
    assert "readonly" in err
    assert len([line for line in err.splitlines() if line.strip()]) == 1


def test_a_writable_existing_database_passes_and_keeps_no_trace(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    init_db(db)
    with connect(db) as conn:
        before = conn.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall()
    check_db(db)
    with connect(db) as conn:
        after = conn.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall()
    assert after == before
    assert all("probe" not in name for (name,) in after)


def test_a_fresh_path_is_still_created_with_the_schema(tmp_path: Path) -> None:
    db = tmp_path / "new" / "runs.db"
    check_db(db)
    with connect(db) as conn:
        tables = {n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"runs", "rows"} <= tables
