"""Cohen's κ is exact on round values, so a judge at the gate passes it (#283).

`cohens_kappa` built κ from float `sum/n` marginals, and a κ that is exactly a
round number landed a few ULP below it: the 18-row table below is exactly 3/5
and computed `0.5999999999999996`, so `calibrate`'s report said FAIL against the
documented `>= 0.6` gate and the CLI exited non-zero. At n=50 (the shipped
calibration-set size) exact 2/5 rendered `0.400 | fair`, the wrong rung.
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.calibration import (
    CalibrationRow,
    _interpret_kappa,
    calibrate,
    cohens_kappa,
    render_report,
)
from eval_harness.cli import main
from eval_harness.judge import Judge

RUBRIC = "Score faithfulness."


def _table(
    both_pass: int, human_only: int, judge_only: int, both_fail: int
) -> tuple[list[int], list[int]]:
    human = [1] * both_pass + [1] * human_only + [0] * judge_only + [0] * both_fail
    judge = [1] * both_pass + [0] * human_only + [1] * judge_only + [0] * both_fail
    return human, judge


def _exact(human: list[int], judge: list[int]) -> Fraction | None:
    n = len(human)
    po = Fraction(sum(h == j for h, j in zip(human, judge, strict=True)), n)
    a, b = Fraction(sum(human), n), Fraction(sum(judge), n)
    pe = a * b + (1 - a) * (1 - b)
    return None if pe == 1 else (po - pe) / (1 - pe)


def test_the_issues_table_is_exactly_three_fifths() -> None:
    human, judge = _table(2, 1, 1, 14)
    assert _exact(human, judge) == Fraction(3, 5)
    assert cohens_kappa(human, judge) == 0.6


def test_every_small_table_matches_the_exact_value() -> None:
    # Every 2x2 table up to n=30: the float result is the exact κ, rounded once.
    checked = 0
    for n in range(1, 31):
        for tp in range(n + 1):
            for fn in range(n + 1 - tp):
                for fp in range(n + 1 - tp - fn):
                    human, judge = _table(tp, fn, fp, n - tp - fn - fp)
                    exact = _exact(human, judge)
                    expected = 0.0 if exact is None else float(exact)
                    assert cohens_kappa(human, judge) == expected, (tp, fn, fp, n)
                    checked += 1
    assert checked > 40_000


def test_an_exact_two_fifths_at_n50_is_labelled_moderate() -> None:
    human, judge = _table(10, 0, 15, 25)
    assert _exact(human, judge) == Fraction(2, 5)
    assert _interpret_kappa(cohens_kappa(human, judge)) == _interpret_kappa(0.4)


class _ScriptedBackend:
    """Returns the score encoded at the end of each response (`... #1` / `... #0`)."""

    model = "scripted"

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def complete(self, system: str, user: str) -> str:
        return f"SCORE: {user.strip()[-1]}.0\nREASONING: scripted\n"


def _rows(tmp_path: Path) -> tuple[list[CalibrationRow], Path]:
    human, judge = _table(2, 1, 1, 14)
    rows = [
        CalibrationRow(
            id=f"r{i}",
            prompt="p",
            response=f"answer {i} #{j}",
            rubric=RUBRIC,
            human_score=float(h),
            provenance={},
        )
        for i, (h, j) in enumerate(zip(human, judge, strict=True))
    ]
    path = tmp_path / "cal.jsonl"
    path.write_text(
        "".join(
            json.dumps(
                {
                    "id": r.id,
                    "prompt": r.prompt,
                    "response": r.response,
                    "rubric": r.rubric,
                    "human_score": r.human_score,
                    "provenance": {},
                }
            )
            + "\n"
            for r in rows
        ),
        encoding="utf-8",
    )
    return rows, path


def test_the_report_gate_passes_a_judge_at_exactly_the_threshold(tmp_path: Path) -> None:
    rows, _ = _rows(tmp_path)
    result = calibrate(Judge(backend=_ScriptedBackend()), rows)
    report = render_report(result, judge_model="scripted", threshold_kappa=0.6)
    assert result.cohens_kappa == 0.6
    assert "**PASS**" in report
    assert "**FAIL**" not in report


def test_the_cli_exits_0_for_a_judge_at_exactly_the_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, path = _rows(tmp_path)
    with patch("eval_harness.cli.AnthropicBackend", _ScriptedBackend):
        rc = main(["calibrate", "--calibration", str(path), "--report", str(tmp_path / "r.md")])
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "::error::" not in out.out + out.err
