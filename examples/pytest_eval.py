"""`@pytest.mark.eval` example with stub backends, runnable as a pytest module.

Demonstrates how a downstream repo wires evals into its existing pytest suite.
The marker takes a dataset path + an `answer_source` + a `judge_backend`; the
plugin parametrizes the test once per row in the dataset and asserts
`score >= threshold` automatically.

Run this file with pytest::

    pytest examples/pytest_eval.py -v

In production, swap the stub backends for `AnthropicBackend()` (judge) and a
real `AnswerSource` that calls your model under test.

This module also exposes a `main()` so the smoke test in
`tests/test_examples_smoke.py` can run it programmatically without invoking
pytest a second time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_harness.dataset import Example
from eval_harness.runner import DatasetEchoSource

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET = REPO_ROOT / "fixtures" / "sample_factuality_v1.jsonl"


class StubJudgeBackend:
    """Judge backend that always returns a fixed SCORE/REASONING block.

    A real downstream-repo wiring swaps this for `AnthropicBackend()` (which
    needs the `judge` extra and an `ANTHROPIC_API_KEY`). The plugin contract
    is the same either way.
    """

    def __init__(self, score: float = 0.9) -> None:
        self._block = f"SCORE: {score:.2f}\nREASONING: stub judge for the example\n"

    def complete(self, system: str, user: str) -> str:
        return self._block


@pytest.mark.eval(
    suite="examples-faithfulness",
    dataset=str(DATASET),
    answer_source=DatasetEchoSource(),  # echo the expected output; full faithful score
    judge_backend=StubJudgeBackend(score=0.9),
    threshold=0.6,
)
def test_faithfulness_eval(eval_row: Example, judge_score) -> None:
    """Body is optional — the plugin asserts `score >= threshold` automatically.

    Reference `eval_row` (the dataset `Example`) and `judge_score` (a
    `JudgeScore` dataclass) if you want row-level invariants beyond the
    threshold. Here we just sanity-check the response shape so the example
    demonstrates the fixture surface.
    """
    assert eval_row.id, "every row has a non-empty id"
    assert 0.0 <= judge_score.score <= 1.0


def main() -> int:
    """Programmatic entry for the smoke test.

    Importing this module doesn't run the test — pytest collection does.
    The smoke test calls `main()` to invoke pytest on this file as a
    subprocess; that flow is what `tests/test_examples_smoke.py` exercises.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "--no-header", str(Path(__file__))],
        check=False,
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
