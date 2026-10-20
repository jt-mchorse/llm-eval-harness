"""A judge score of negative zero is zero, with no sign (#404).

Measured on `main` (fea91e5): a judge answering `SCORE: -0` was stored as
`-0.0`, because `clamp_judge_score` only clamped `x < 0.0`. The `--out` JSON
kept the sign and SQLite `REAL` dropped it, so for the same two runs

    diff       | unchanged | `q2` | 0.000 | 0.000 | +0.000 |  |
    diff-json  | unchanged | `q2` | -0.000 | 0.000 | +0.000 |  |

and `calibrate`'s per-row table printed `-0.00` for the judge column.
`test_judge.py::test_parse_negative_zero_is_zero` asserts `== 0.0`, which
`-0.0` satisfies, so the sign is checked with `math.copysign` here.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import main
from eval_harness.judge import JudgeScore, clamp_judge_score, parse_judge_output


def _positive(x: float) -> bool:
    return math.copysign(1.0, x) == 1.0


@pytest.mark.parametrize("text", ["-0", "-0.0", "-0.00", "-.0"])
def test_a_parsed_negative_zero_has_no_sign(text: str) -> None:
    score = parse_judge_output(f"SCORE: {text}\nREASONING: zero").score
    assert score == 0.0
    assert _positive(score)


@pytest.mark.parametrize("value", [-0.0, -0.1, -1e-300])
def test_clamp_returns_positive_zero_at_or_below_zero(value: float) -> None:
    assert _positive(clamp_judge_score(value))


def test_a_judge_score_built_directly_with_negative_zero_has_no_sign() -> None:
    # A BYO `Judge` builds `JudgeScore` itself and never calls the clamp.
    assert _positive(JudgeScore(score=-0.0, reasoning="r", raw="").score)


@pytest.mark.parametrize("value", [0.0, 0.25, 1.0])
def test_in_range_scores_are_unchanged(value: float) -> None:
    # Control: only the sign of zero moves.
    assert clamp_judge_score(value) == value
    assert _positive(clamp_judge_score(value))
    assert JudgeScore(score=value, reasoning="r", raw="").score == value


def _stub(scores: Iterator[str]) -> type:
    class _Judge:
        def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
            self.model = model or "fake-judge"

        def complete(self, system: str, user: str) -> str:
            return f"SCORE: {next(scores)}\nREASONING: stub\n"

    return _Judge


def _run(tmp_path: Path, name: str, db: Path, dataset: Path, scores: list[str]) -> str:
    out = tmp_path / f"{name}.json"
    argv = ["run", "--suite", "s", "--dataset", str(dataset), "--db", str(db), "--out", str(out)]
    with patch("eval_harness.cli.AnthropicBackend", _stub(iter(scores))):
        assert main(argv) in (0, 1)
    return str(out)


@pytest.mark.parametrize("fmt", ["markdown", "ascii", "json"])
def test_diff_and_diff_json_render_a_negative_zero_judge_score_alike(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fmt: str
) -> None:
    dataset = tmp_path / "d.jsonl"
    dataset.write_text(
        "".join(
            json.dumps(
                {
                    "id": i,
                    "input": f"question {i}?",
                    "expected_outputs": [{"kind": "exact", "value": "a"}],
                    "provenance": {"source": "t"},
                    "dataset_version": "v1",
                }
            )
            + "\n"
            for i in ("q1", "q2")
        ),
        encoding="utf-8",
    )
    db = tmp_path / "runs.db"
    base_out = _run(tmp_path, "base", db, dataset, ["0.5", "-0"])
    cur_out = _run(tmp_path, "cur", db, dataset, ["0.5", "0"])
    capsys.readouterr()
    base_id = json.loads(Path(base_out).read_text())["run_id"]
    cur_id = json.loads(Path(cur_out).read_text())["run_id"]

    main(["diff", "--db", str(db), "--current", cur_id, "--baseline", base_id, "--format", fmt])
    from_db = capsys.readouterr().out
    main(["diff-json", "--current", cur_out, "--baseline", base_out, "--format", fmt])
    from_json = capsys.readouterr().out
    # `diff --format ascii` ends with one more newline than `diff-json`; that
    # is the commands' own framing, not the scores.
    assert from_db.rstrip("\n") == from_json.rstrip("\n")
    assert "-0.0" not in from_json


def test_the_calibrate_row_table_prints_no_negative_zero(tmp_path: Path) -> None:
    class _Stub:
        model = "stub-judge"

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def complete(self, system: str, user: str) -> str:
            return f"SCORE: {user.split('JUDGE=')[1].split()[0]}\nREASONING: stub\n"

    cells = [(1.0, "1"), (1.0, "0.9"), (0.0, "-0"), (0.0, "0.1")]
    cal = tmp_path / "cal.jsonl"
    cal.write_text(
        "".join(
            json.dumps(
                {
                    "id": f"r{i:03d}",
                    "prompt": f"q{i} JUDGE={j}",
                    "response": "a",
                    "rubric": "faithful?",
                    "human_score": h,
                    "provenance": {"src": "t"},
                }
            )
            + "\n"
            for i, (h, j) in enumerate(cells)
        ),
        encoding="utf-8",
    )
    report = tmp_path / "report.md"
    with patch("eval_harness.cli.AnthropicBackend", _Stub):
        main(["calibrate", "--calibration", str(cal), "--report", str(report)])
    text = report.read_text(encoding="utf-8")
    assert "| `r002` |" in text
    assert "-0.0" not in text
