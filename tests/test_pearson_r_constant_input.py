"""`pearson_r` of a constant input is exactly 0.0, as documented (#420).

The zero-variance guard tested the float `den`. A constant judge whose score is
not exactly representable -- `[0.05] * 3` -- has a float mean an ULP away from
0.05, so `var_x` was a tiny non-zero number, the guard missed it, and r came
out as float noise (`-3.925231146709437e-16`) that `render_report` and the CLI
summary printed as `-0.000`. The guard now reads the input's shape.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.calibration import CalibrationRow, calibrate, pearson_r, render_report
from eval_harness.cli import main
from eval_harness.judge import Judge

AWKWARD = [0.05, 0.1, 0.7, 1 / 3]
LENGTHS = range(2, 13)
ISSUE_HUMAN = [0.5, 0.9, 0.9]


def _other(n: int) -> list[float]:
    # A non-constant partner; the issue's three human scores, then a ramp.
    return (ISSUE_HUMAN + [i / 7 for i in range(n)])[:n]


def _float_path(xs: list[float], ys: list[float]) -> float:
    """The pre-#420 arithmetic, guard on `den` only."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return 0.0 if den == 0 else num / den


CASES = [(c, n) for c in AWKWARD for n in LENGTHS]


def test_the_float_path_is_noisy_for_some_constant_sets_on_this_interpreter() -> None:
    # Anti-vacuity: the arms below cover sets where the old guard really missed.
    # Which ones miss depends on how `sum` rounds (3.11 vs 3.12+), so count them.
    noisy = [(c, n) for c, n in CASES if _float_path([c] * n, _other(n)) != 0.0]
    assert len(noisy) >= 3, noisy


def test_the_issue_measurement_is_exactly_zero() -> None:
    assert pearson_r([0.05] * 3, ISSUE_HUMAN) == 0.0
    assert pearson_r(ISSUE_HUMAN, [0.05] * 3) == 0.0


@pytest.mark.parametrize("side", ["xs", "ys"])
def test_a_constant_input_at_an_awkward_value_is_exactly_zero(side: str) -> None:
    bad = []
    for c, n in CASES:
        const, other = [c] * n, _other(n)
        r = pearson_r(const, other) if side == "xs" else pearson_r(other, const)
        if r != 0.0 or math.copysign(1.0, r) < 0:
            bad.append((c, n, r))
    assert bad == []


def test_the_report_and_the_cli_line_print_zero_not_minus_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [
        CalibrationRow(
            id=f"r{i}", prompt=f"P{i}", response=f"R{i}", rubric="r", human_score=h, provenance={}
        )
        for i, h in enumerate(ISSUE_HUMAN)
    ]

    class _Constant:
        model = "constant"

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def complete(self, system: str, user: str) -> str:
            return "SCORE: 0.05\nREASONING: stub"

    result = calibrate(Judge(backend=_Constant()), rows)
    assert result.pearson_r == 0.0
    md = render_report(result, judge_model="stub")
    line = next(ln for ln in md.splitlines() if ln.startswith("| Pearson r"))
    assert "-0.000" not in line, line
    assert "| 0.000 |" in line, line

    cal = tmp_path / "cal.jsonl"
    cal.write_text(
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
    with patch("eval_harness.cli.AnthropicBackend", _Constant):
        main(["calibrate", "--calibration", str(cal), "--report", str(tmp_path / "r.md")])
    out = capsys.readouterr().out
    assert "pearson_r=0.000" in out, out
    assert "pearson_r=-0.000" not in out, out


def test_control_a_real_correlation_is_unchanged() -> None:
    # Green before and after: non-constant input still takes the float path.
    xs, ys = [0.1, 0.4, 0.35, 0.8], [0.2, 0.3, 0.5, 0.9]
    assert pearson_r(xs, ys) == _float_path(xs, ys)
    # Two equal values plus one different is NOT constant.
    assert pearson_r([0.05, 0.05, 0.1], ISSUE_HUMAN) == _float_path([0.05, 0.05, 0.1], ISSUE_HUMAN)
    assert pearson_r([0.05, 0.05, 0.1], ISSUE_HUMAN) != 0.0


def test_control_an_exactly_representable_constant_was_already_zero() -> None:
    assert pearson_r([0.5, 0.5, 0.5], [0.1, 0.2, 0.3]) == 0.0
    assert pearson_r([1.0] * 4, [0.0, 0.25, 0.5, 1.0]) == 0.0
