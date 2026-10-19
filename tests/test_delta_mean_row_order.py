"""Equal means publish 0 whatever order the rows load in and whichever interpreter
summed them (#386).

#336 trusts a run's rows when `sum(scores) / n` reproduces its `mean_score`.
Float `sum` is not one function across the supported versions: 3.11's is a plain
left fold, so its result depends on order, and 3.12+ compensate. `read_run` read
rows with no ORDER BY and SQLite returned them by example_id (q1, q10, q2), so
measured on 3.11.14 with ids q1/q2/q10, baseline 0.3/0.9/0.2 and current
0.5/0.1/0.8 (both exactly 7/15):

    eval-harness diff --db ...   summary: mean Δ=-0.0000000000000001
    diff-json on the same runs   mean Δ=+0.000

and the same DB read on 3.14 printed the same wrong value.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from eval_harness import Judge
from eval_harness.cli import main
from eval_harness.runner import DatasetEchoSource, RunSpec, diff_runs, run_suite
from eval_harness.runs import StoredRun, connect, read_run

IDS = ["q1", "q2", "q10"]  # scoring order; example_id order is q1, q10, q2
BASELINE = [0.3, 0.9, 0.2]
CURRENT = [0.5, 0.1, 0.8]  # its left fold and its compensated sum round apart


class _EchoBackend:
    def complete(self, system: str, user: str) -> str:
        match = re.search(r"S=([0-9.]+)", user)
        assert match is not None
        return f"SCORE: {match.group(1)}\nREASONING: fixed\n"


def _dataset(path: Path, scores: list[float]) -> Path:
    path.write_text(
        "".join(
            json.dumps(
                {
                    "dataset_version": "v1",
                    "expected_outputs": [{"kind": "exact", "value": f"S={s}"}],
                    "id": i,
                    "input": f"x{i}",
                    "provenance": {"source": "x"},
                }
            )
            + "\n"
            for i, s in zip(IDS, scores, strict=True)
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "h.db"
    for run_id, scores in (("base", BASELINE), ("cur", CURRENT)):
        run_suite(
            RunSpec(
                suite="s",
                dataset_path=str(_dataset(tmp_path / f"{run_id}.jsonl", scores)),
                judge=Judge(backend=_EchoBackend()),
                answer_source=DatasetEchoSource(),
            ),
            db_path=db_path,
            run_id=run_id,
        )
    return db_path


def _left_fold_mean(scores: list[float]) -> float:
    total = 0.0
    for s in scores:
        total += s
    return total / len(scores)


def test_the_fixture_needs_the_order_and_the_interpreter() -> None:
    # Anti-vacuity: the current run's left fold (3.11's `sum`) and its
    # compensated sum round apart, and example_id order is not scoring order.
    assert _left_fold_mean(CURRENT) != _left_fold_mean([CURRENT[0], CURRENT[2], CURRENT[1]])
    assert sorted(IDS) != IDS


def test_read_run_returns_rows_in_scoring_order(db: Path) -> None:
    with connect(db) as conn:
        assert list(read_run(conn, "cur").rows) == IDS


@pytest.mark.parametrize("fmt", ["ascii", "markdown", "json"])
def test_diff_publishes_zero_for_equal_means(
    db: Path, fmt: str, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["diff", "--db", str(db), "--current", "cur", "--baseline", "base", "--format", fmt])
    out = capsys.readouterr().out
    if fmt == "json":
        assert json.loads(out)["summary"]["mean_delta"] == 0
    elif fmt == "ascii":
        assert "mean Δ=+0.000" in out
    else:
        assert "mean Δ **+0.000**" in out


def _stored(run_id: str, scores: list[float], mean: float) -> StoredRun:
    return StoredRun(
        run_id=run_id,
        started_at="2026-01-01T00:00:00Z",
        suite="s",
        dataset_version="v",
        judge_model=None,
        judge_kappa=None,
        mean_score=mean,
        n_rows=len(scores),
        git_sha=None,
        rows={i: (s, "r") for i, s in zip(IDS, scores, strict=True)},
    )


def test_a_mean_recorded_by_3_11_reads_as_its_rows_on_any_interpreter() -> None:
    # A baseline written on 3.11 stores the left fold. Read on 3.12+, `sum()`
    # compensates and does not reproduce it, which used to fall back to the
    # float field and publish -6.7e-17 against an equal mean.
    cur = _stored("cur", CURRENT, _left_fold_mean(CURRENT))
    base = _stored("base", BASELINE, _left_fold_mean(BASELINE))
    assert diff_runs(cur, base).summary["mean_delta"] == 0


def test_a_mean_the_rows_do_not_reproduce_is_still_taken_as_recorded() -> None:
    # #336's other branch, unchanged: a hand-edited field wins.
    cur = _stored("cur", CURRENT, 0.75)
    base = _stored("base", BASELINE, _left_fold_mean(BASELINE))
    assert diff_runs(cur, base).summary["mean_delta"] == pytest.approx(0.75 - 7 / 15)
