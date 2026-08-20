"""Run selection is a pure function of the stored data, not of write order (#206).

`eval_harness/runs.py` sorted all four of its queries on `started_at` alone.
`utc_now_iso()` has one-second resolution, so ties are not a corner case — they
are what consecutive runs normally produce (measured: one distinct timestamp
across 2000 back-to-back calls, and six consecutive real ``run_suite()`` calls
all landing on a single second). Among tied rows SQLite's order is
implementation-defined and tracked insertion order.

Every test here permutes the *insertion order* of runs that share a timestamp
and asserts the observable is invariant. The assertions are anchored to the
measured pre-fix values recorded in #206 — the chosen `run_id`, the `list_runs`
membership, the `mean_delta`, the flagged-row set — rather than to an exception
type, because the pre-fix behaviour raised nothing at all. It returned a
confident, wrong answer.
"""

from __future__ import annotations

import itertools
import sqlite3
from pathlib import Path

import pytest

from eval_harness.runner import diff_runs, load_baseline
from eval_harness.runs import init_db_on, latest_run_id_for_suite, list_runs, read_run, write_run

TIED = "2026-08-20T07:30:00Z"
LATER = "2026-08-20T07:30:05Z"


def _seed(db_path: Path, runs: list[tuple[str, str, float]]) -> sqlite3.Connection:
    """Write `runs` in the given order. Returns an open connection."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    init_db_on(conn)
    for run_id, started_at, mean in runs:
        write_run(
            conn,
            run_id=run_id,
            started_at=started_at,
            suite="faithfulness",
            dataset_version="v1",
            judge_model="claude",
            judge_kappa=0.81,
            mean_score=mean,
            n_rows=2,
            git_sha=None,
            rows=[("ex1", mean, "why"), ("ex2", mean, "why")],
        )
    return conn


# Three runs, all sharing one `started_at`. Distinct ids so the choice is visible.
THREE_TIED: list[tuple[str, str, float]] = [
    ("aaa", TIED, 0.10),
    ("bbb", TIED, 0.50),
    ("ccc", TIED, 0.90),
]

PERMUTATIONS = list(itertools.permutations(THREE_TIED))


class TestLatestRunIdIsOrderIndependent:
    """Pre-fix this returned 'aaa', 'bbb' or 'ccc' depending on write order."""

    def test_same_id_under_every_insertion_order(self, tmp_path: Path) -> None:
        chosen = set()
        for i, perm in enumerate(PERMUTATIONS):
            conn = _seed(tmp_path / f"p{i}.db", list(perm))
            try:
                chosen.add(latest_run_id_for_suite(conn, "faithfulness"))
            finally:
                conn.close()
        assert len(chosen) == 1, (
            f"latest_run_id_for_suite returned {sorted(chosen)} across the six "
            "insertion orders of three runs sharing one timestamp. Pre-fix this "
            "was ['aaa', 'bbb', 'ccc'] — all three."
        )

    def test_tiebreak_is_descending_run_id(self, tmp_path: Path) -> None:
        # Pins the direction, so a future edit that flips it is a deliberate act
        # rather than an accident. `started_at DESC` orders the primary key
        # descending; the secondary key follows it for the least surprise.
        conn = _seed(tmp_path / "dir.db", list(THREE_TIED))
        try:
            assert latest_run_id_for_suite(conn, "faithfulness") == "ccc"
        finally:
            conn.close()

    def test_exclude_run_id_still_excludes(self, tmp_path: Path) -> None:
        # The other half of the collision, which `exclude_run_id` always covered.
        # It must keep working now that the tiebreak would otherwise pick it.
        conn = _seed(tmp_path / "excl.db", list(THREE_TIED))
        try:
            assert latest_run_id_for_suite(conn, "faithfulness", exclude_run_id="ccc") == "bbb"
        finally:
            conn.close()

    def test_strictly_later_run_still_wins_over_a_tied_pair(self, tmp_path: Path) -> None:
        # The tiebreak must not outrank `started_at`. "zzz" sorts after "aaa"
        # on the secondary key but is chronologically older, so the LATER run
        # must win on the primary key regardless.
        conn = _seed(
            tmp_path / "primary.db",
            [("zzz", TIED, 0.10), ("aaa", LATER, 0.90)],
        )
        try:
            assert latest_run_id_for_suite(conn, "faithfulness") == "aaa"
        finally:
            conn.close()


class TestListRunsIsOrderIndependent:
    """Pre-fix `--limit` changed which runs appeared, not just their order."""

    def test_same_order_under_every_insertion_order(self, tmp_path: Path) -> None:
        orders = set()
        for i, perm in enumerate(PERMUTATIONS):
            conn = _seed(tmp_path / f"o{i}.db", list(perm))
            try:
                orders.add(tuple(r.run_id for r in list_runs(conn, limit=10)))
            finally:
                conn.close()
        assert len(orders) == 1, (
            f"list_runs produced {len(orders)} distinct orders across six insertion "
            "orders. Pre-fix it produced all six."
        )

    def test_membership_at_the_limit_boundary_is_stable(self, tmp_path: Path) -> None:
        """The sharp half: a run was silently dropped from the operator's history.

        Pre-fix, `limit=2` over three tied runs returned three different SETS —
        {aaa,bbb}, {aaa,ccc}, {bbb,ccc} — so which run vanished depended on
        write order. Reordering output is cosmetic; dropping a row is not.
        """
        sets = set()
        for i, perm in enumerate(PERMUTATIONS):
            conn = _seed(tmp_path / f"m{i}.db", list(perm))
            try:
                sets.add(tuple(sorted(r.run_id for r in list_runs(conn, limit=2))))
            finally:
                conn.close()
        assert sets == {("bbb", "ccc")}, (
            f"list_runs(limit=2) returned {sorted(sets)} across the six insertion "
            "orders. Pre-fix: [('aaa','bbb'), ('aaa','ccc'), ('bbb','ccc')]."
        )

    def test_suite_filtered_branch_is_also_stable(self, tmp_path: Path) -> None:
        # `list_runs` builds two different queries. Both carry the tiebreak;
        # the un-filtered branch is covered above, this is the `WHERE suite`
        # branch — the same operand-enumeration point that motivated #204.
        sets = set()
        for i, perm in enumerate(PERMUTATIONS):
            conn = _seed(tmp_path / f"s{i}.db", list(perm))
            try:
                sets.add(tuple(r.run_id for r in list_runs(conn, limit=2, suite="faithfulness")))
            finally:
                conn.close()
        assert sets == {("ccc", "bbb")}


class TestDiffVerdictIsOrderIndependent:
    """The operator-visible consequence: a pass or a regression, same three runs."""

    @staticmethod
    def _report(db_path: Path, prior_order: list[tuple[str, str, float]]):
        conn = _seed(db_path, [*prior_order, ("run_curr", LATER, 0.60)])
        try:
            baseline = load_baseline(conn, "faithfulness", None, exclude_run_id="run_curr")
            assert baseline is not None
            current = read_run(conn, "run_curr")
            return baseline.run_id, diff_runs(current, baseline, threshold_drop=0.10)
        finally:
            conn.close()

    def test_same_baseline_and_same_verdict_either_way(self, tmp_path: Path) -> None:
        good = ("run_good", TIED, 0.90)
        bad = ("run_bad_", TIED, 0.30)

        id_a, report_a = self._report(tmp_path / "a.db", [good, bad])
        id_b, report_b = self._report(tmp_path / "b.db", [bad, good])

        assert id_a == id_b, (
            f"baseline was {id_a} when the good run was written first and {id_b} "
            "when the bad one was. Pre-fix: run_bad_ / run_good."
        )

        flagged_a = sorted(r.example_id for r in report_a.rows if r.flagged)
        flagged_b = sorted(r.example_id for r in report_b.rows if r.flagged)
        assert flagged_a == flagged_b, (
            f"flagged rows were {flagged_a} vs {flagged_b}. Pre-fix: [] vs "
            "['ex1', 'ex2'] — a clean pass or a regression on every row."
        )

        delta_a = report_a.summary.get("mean_delta")
        delta_b = report_b.summary.get("mean_delta")
        assert delta_a == pytest.approx(delta_b), (
            f"mean_delta was {delta_a} vs {delta_b}. Pre-fix: +0.30 vs -0.30."
        )

    def test_the_surviving_baseline_is_the_higher_run_id(self, tmp_path: Path) -> None:
        # Anchors the concrete numbers so a future change to the tiebreak
        # direction shows up as a value change, not just a stability change.
        # 'run_good' > 'run_bad_' as strings, so it wins the DESC tiebreak.
        baseline_id, report = self._report(
            tmp_path / "c.db", [("run_bad_", TIED, 0.30), ("run_good", TIED, 0.90)]
        )
        assert baseline_id == "run_good"
        assert report.summary.get("mean_delta") == pytest.approx(-0.30)
        assert sorted(r.example_id for r in report.rows if r.flagged) == ["ex1", "ex2"]


def test_untied_runs_are_unaffected(tmp_path: Path) -> None:
    """The tiebreak only ever fires on equal `started_at`.

    Guards against a fix that accidentally sorts by `run_id` first. Written so
    the chronologically-latest run has the lexicographically-smallest id: if
    `run_id` outranked `started_at`, this would return "aaa".
    """
    conn = _seed(
        tmp_path / "untied.db",
        [("zzz", "2026-08-20T07:30:00Z", 0.1), ("aaa", "2026-08-20T07:30:09Z", 0.9)],
    )
    try:
        assert latest_run_id_for_suite(conn, "faithfulness") == "aaa"
        assert [r.run_id for r in list_runs(conn, limit=10)] == ["aaa", "zzz"]
    finally:
        conn.close()
