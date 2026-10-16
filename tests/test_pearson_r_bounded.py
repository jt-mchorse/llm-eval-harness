"""`pearson_r` stays in [-1, 1], so exact agreement calibrates cleanly (#384).

The float quotient `num / den` can land a few ULP outside the range: a judge
that agrees EXACTLY with the human scores [0.1, 0.5, 0.3, 0.25] gave
`1.0000000000000002`, `render_report`'s range check (#204) refused it, and
`eval-harness calibrate` exited 1 with a traceback and no report -- for the
best possible calibration, after every judge call was paid for.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.calibration import pearson_r
from eval_harness.cli import main

# Found by a seeded search: the unclamped quotient overshoots on each.
OVER = [
    [0.1, 0.5, 0.3, 0.25],
    [0.08, 0.79, 0.71, 0.32, 0.17, 0.1, 0.63, 0.52],
    [0.14, 0.43, 0.02, 0.35, 0.32, 0.07, 0.58, 0.23],
    [0.7, 0.74, 0.19, 0.63],
    [0.74, 0.2, 0.7, 0.66],
]
UNDER = [[0.56, 0.21, 0.23], [0.32, 0.59, 0.38], [0.22, 0.0, 0.63, 0.99]]


def _unclamped(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den


def test_the_fixture_really_overshoots() -> None:
    # Anti-vacuity: without these the arms below check nothing.
    assert all(_unclamped(xs, xs) > 1.0 for xs in OVER)
    assert all(_unclamped(xs, [1 - x for x in xs]) < -1.0 for xs in UNDER)


@pytest.mark.parametrize("xs", OVER, ids=lambda xs: f"n{len(xs)}-{xs[0]}")
def test_exact_agreement_is_exactly_one(xs: list[float]) -> None:
    assert pearson_r(xs, xs) == 1.0


@pytest.mark.parametrize("xs", UNDER, ids=lambda xs: f"n{len(xs)}-{xs[0]}")
def test_exact_anti_agreement_is_exactly_minus_one(xs: list[float]) -> None:
    assert pearson_r(xs, [1 - x for x in xs]) == -1.0


def test_ordinary_values_and_the_zero_variance_case_are_unchanged() -> None:
    xs, ys = [0.1, 0.4, 0.35, 0.8], [0.2, 0.3, 0.5, 0.9]
    assert pearson_r(xs, ys) == _unclamped(xs, ys)
    assert pearson_r([0.5, 0.5, 0.5], [0.1, 0.2, 0.3]) == 0.0


class _EchoBackend:
    """Returns the score written into each response (`S=<score>`)."""

    model = "echo"

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def complete(self, system: str, user: str) -> str:
        match = re.search(r"S=([0-9.]+)", user)
        assert match is not None
        return f"SCORE: {match.group(1)}\nREASONING: matches the human label\n"


def test_the_cli_calibrates_an_exactly_agreeing_judge_at_exit_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cal = tmp_path / "cal.jsonl"
    cal.write_text(
        "".join(
            json.dumps(
                {
                    "id": f"r{i}",
                    "prompt": f"P{i}",
                    "response": f"S={s}",
                    "rubric": "r",
                    "human_score": s,
                    "provenance": {},
                }
            )
            + "\n"
            for i, s in enumerate(OVER[0])
        ),
        encoding="utf-8",
    )
    report = tmp_path / "out" / "report.md"
    with patch("eval_harness.cli.AnthropicBackend", _EchoBackend):
        rc = main(["calibrate", "--calibration", str(cal), "--report", str(report)])
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    text = report.read_text(encoding="utf-8")
    assert "**PASS**" in text
    assert "1.000" in text
