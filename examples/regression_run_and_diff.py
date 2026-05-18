"""Two regression runs against a deterministic backend, then a diff.

Demonstrates the runner / SQLite history / diff loop end-to-end with stub
backends. The first run becomes the baseline; the second run uses a slightly
worse backend that regresses a single row; `diff_runs` produces a structured
delta and `render_delta_ascii` prints the markdown-friendly table.

Hermetic — no API key, no live network. The SQLite history lives in a
`tempfile.TemporaryDirectory` so re-running the example doesn't pollute
`~/.eval-harness/runs.db`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from eval_harness import (
    Judge,
    RunSpec,
    diff_runs,
    render_delta_ascii,
    run_suite,
)
from eval_harness.runner import DatasetEchoSource
from eval_harness.runs import connect, read_run

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET = REPO_ROOT / "fixtures" / "sample_factuality_v1.jsonl"


class ConstantBackend:
    """Always returns the same SCORE — useful for pinning a baseline."""

    def __init__(self, score: float) -> None:
        self._block = f"SCORE: {score:.3f}\nREASONING: constant baseline\n"

    def complete(self, system: str, user: str) -> str:
        return self._block


class RegressOnPromptBackend:
    """Returns `regressed_score` whenever the prompt contains `needle`, else `base_score`.

    Lets the example simulate a localized regression — the kind of one-row
    drop the runner's `--threshold-drop` flag is designed to catch.
    """

    def __init__(self, *, base_score: float, regressed_score: float, needle: str) -> None:
        self._base = f"SCORE: {base_score:.3f}\nREASONING: base\n"
        self._regressed = f"SCORE: {regressed_score:.3f}\nREASONING: regressed on {needle!r}\n"
        self._needle = needle

    def complete(self, system: str, user: str) -> str:
        return self._regressed if self._needle in user else self._base


def main() -> int:
    """Two runs against the same dataset, then diff. Exit 0 on success."""
    with tempfile.TemporaryDirectory(prefix="eval-harness-example-") as tmp:
        db_path = Path(tmp) / "runs.db"

        baseline_spec = RunSpec(
            suite="examples-factuality",
            dataset_path=DATASET,
            judge=Judge(backend=ConstantBackend(score=0.90)),
            answer_source=DatasetEchoSource(),
        )
        current_spec = RunSpec(
            suite="examples-factuality",
            dataset_path=DATASET,
            judge=Judge(
                backend=RegressOnPromptBackend(
                    base_score=0.90,
                    regressed_score=0.20,  # well past the default threshold_drop=0.1
                    needle="Berlin Wall",
                )
            ),
            answer_source=DatasetEchoSource(),
        )

        baseline = run_suite(baseline_spec, db_path=db_path)
        current = run_suite(current_spec, db_path=db_path)

        print(
            f"[example] baseline run_id={baseline.run_id[:8]} "
            f"mean={baseline.mean_score:.3f} n={baseline.n_rows}"
        )
        print(
            f"[example] current  run_id={current.run_id[:8]} "
            f"mean={current.mean_score:.3f} n={current.n_rows}"
        )

        with connect(db_path) as conn:
            baseline_stored = read_run(conn, baseline.run_id)
            current_stored = read_run(conn, current.run_id)
        assert baseline_stored is not None
        assert current_stored is not None

        report = diff_runs(current_stored, baseline_stored)
        print()
        print(render_delta_ascii(report))
        print(f"[example] regressed example_ids: {report.regressed_ids}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
