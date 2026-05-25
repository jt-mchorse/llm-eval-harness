"""Tests for the SQLite persistence layer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from eval_harness.runs import (
    StoredRun,
    connect,
    init_db,
    latest_run_id_for_suite,
    read_run,
    write_run,
)


def _seed_run(conn: sqlite3.Connection, *, run_id: str, suite: str, started_at: str, rows) -> None:
    write_run(
        conn,
        run_id=run_id,
        started_at=started_at,
        suite=suite,
        dataset_version="v0.1",
        judge_model="claude-haiku-test",
        judge_kappa=0.82,
        mean_score=sum(r[1] for r in rows) / len(rows),
        n_rows=len(rows),
        git_sha=None,
        rows=rows,
    )


class TestInitDB:
    def test_idempotent_init(self, tmp_path: Path) -> None:
        db = tmp_path / "runs.db"
        init_db(db)
        init_db(db)  # second call must not raise
        with connect(db) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            }
        assert {"runs", "rows"}.issubset(tables)

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c" / "runs.db"
        init_db(nested)
        assert nested.exists()

    def test_foreign_keys_enabled(self, tmp_path: Path) -> None:
        db = tmp_path / "runs.db"
        init_db(db)
        with connect(db) as conn:
            (val,) = conn.execute("PRAGMA foreign_keys;").fetchone()
        assert val == 1


class TestWriteAndRead:
    def test_round_trip_one_run(self, tmp_path: Path) -> None:
        db = tmp_path / "runs.db"
        init_db(db)
        with connect(db) as conn:
            _seed_run(
                conn,
                run_id="r1",
                suite="faithfulness",
                started_at="2026-05-15T19:00:00Z",
                rows=[("ex1", 0.9, "ok"), ("ex2", 0.4, "bad")],
            )
            stored = read_run(conn, "r1")
        assert isinstance(stored, StoredRun)
        assert stored.run_id == "r1"
        assert stored.suite == "faithfulness"
        assert stored.mean_score == pytest.approx(0.65)
        assert stored.rows == {"ex1": (0.9, "ok"), "ex2": (0.4, "bad")}

    def test_duplicate_run_id_rejected(self, tmp_path: Path) -> None:
        db = tmp_path / "runs.db"
        init_db(db)
        with connect(db) as conn:
            _seed_run(
                conn,
                run_id="r1",
                suite="s",
                started_at="2026-05-15T19:00:00Z",
                rows=[("ex", 1.0, "ok")],
            )
            with pytest.raises(ValueError, match="failed to persist"):
                _seed_run(
                    conn,
                    run_id="r1",
                    suite="s",
                    started_at="2026-05-15T19:00:00Z",
                    rows=[("ex", 0.0, "no")],
                )

    def test_unknown_run_raises_keyerror(self, tmp_path: Path) -> None:
        db = tmp_path / "runs.db"
        init_db(db)
        with connect(db) as conn, pytest.raises(KeyError):
            read_run(conn, "nope")


class TestLatestForSuite:
    def test_picks_most_recent_started_at(self, tmp_path: Path) -> None:
        db = tmp_path / "runs.db"
        init_db(db)
        with connect(db) as conn:
            _seed_run(
                conn,
                run_id="early",
                suite="s",
                started_at="2026-05-15T09:00:00Z",
                rows=[("ex", 1.0, "ok")],
            )
            _seed_run(
                conn,
                run_id="late",
                suite="s",
                started_at="2026-05-15T19:00:00Z",
                rows=[("ex", 0.5, "meh")],
            )
            _seed_run(
                conn,
                run_id="other_suite",
                suite="t",
                started_at="2026-05-15T23:00:00Z",
                rows=[("ex", 0.1, "no")],
            )
            assert latest_run_id_for_suite(conn, "s") == "late"
            assert latest_run_id_for_suite(conn, "t") == "other_suite"

    def test_no_runs_returns_none(self, tmp_path: Path) -> None:
        db = tmp_path / "runs.db"
        init_db(db)
        with connect(db) as conn:
            assert latest_run_id_for_suite(conn, "anything") is None


# Issue #42: list_runs limit validation extended from sign-only `<= 0`
# to integer + positive. Pre-#42 NaN passed (NaN <= 0 is false) and
# propagated into SQLite's LIMIT bind as a cryptic InterfaceError; 0.5
# silently truncated to 0 in SQLite's integer coercion → no rows.
class TestListRunsLimitValidation:
    def _seeded(self, tmp_path: Path):
        from eval_harness.runs import list_runs

        db = tmp_path / "runs.db"
        init_db(db)
        return list_runs, db

    @pytest.mark.parametrize(
        "bad_value",
        [0, -1, 0.5, 1.5, float("nan"), float("inf"), float("-inf"), "10", True, False],
    )
    def test_rejects_non_positive_or_non_int_limit(self, tmp_path: Path, bad_value) -> None:
        list_runs, db = self._seeded(tmp_path)
        with (
            connect(db) as conn,
            pytest.raises(ValueError, match=r"limit must be a positive integer"),
        ):
            list_runs(conn, limit=bad_value)  # type: ignore[arg-type]

    def test_accepts_positive_integer_limit(self, tmp_path: Path) -> None:
        list_runs, db = self._seeded(tmp_path)
        with connect(db) as conn:
            _seed_run(
                conn,
                run_id="r1",
                suite="s",
                started_at="2026-05-15T19:00:00Z",
                rows=[("ex", 0.5, "meh")],
            )
            assert len(list_runs(conn, limit=1)) == 1
