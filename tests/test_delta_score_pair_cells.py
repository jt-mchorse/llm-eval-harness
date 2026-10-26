"""A delta row's baseline and current cells read as the row's verdict (#350).

#291 widened the Δ cell of both delta tables; the two score cells beside it
stayed at ``.3f``, so 0.5 -> 0.5004 printed ``0.500 | 0.500`` beside
``improved``. The pair now widens, at one shared width, until the difference of
the two rendered decimals is in the same band (flagged / regressed / unchanged
/ improved, D-034) as the true difference.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from eval_harness.comment import _row_to_md
from eval_harness.comparison import render_score_pair
from eval_harness.runner import DeltaReport, RowDelta, render_delta_ascii


def _band(d: Fraction, t: Fraction) -> int:
    return -2 if d < -t else -1 if d < 0 else 0 if d == 0 else 1


def _row(base: float, cur: float, threshold: float) -> RowDelta:
    exact = Fraction(repr(cur)) - Fraction(repr(base))
    t = Fraction(repr(threshold))
    band = _band(exact, t)
    status = {-2: "regressed", -1: "regressed", 0: "unchanged", 1: "improved"}[band]
    return RowDelta("r", base, cur, float(exact), status, band == -2)


def test_the_reported_row_no_longer_prints_two_equal_scores() -> None:
    assert render_score_pair(0.5, 0.5004, 0.1) == ("0.5000", "0.5004")
    assert "| 0.5000 | 0.5004 |" in _row_to_md(_row(0.5, 0.5004, 0.1), 0.1)


@pytest.mark.parametrize(
    ("base", "cur"),
    [(0.8, 0.7), (0.5, 0.25), (0.123, 0.456), (0.9, 0.9), (0.0, 1.0)],
)
def test_scores_of_three_decimals_or_fewer_render_as_before(base: float, cur: float) -> None:
    assert render_score_pair(base, cur, 0.1) == (f"{base:.3f}", f"{cur:.3f}")


_SWEEP = [
    (0.8, 0.8 + d) for d in (-0.10004, -0.1, -0.09996, -0.0004, -0.00004, 0.0, 0.00004, 0.0004)
] + [(0.5, 0.5004), (0.5004, 0.5), (0.6996, 0.6), (0.70004, 0.6)]


@pytest.mark.parametrize(("base", "cur"), _SWEEP)
@pytest.mark.parametrize("threshold", [0.1, 0.05])
def test_the_printed_pair_is_in_the_true_band(base: float, cur: float, threshold: float) -> None:
    b, c = render_score_pair(base, cur, threshold)
    t = Fraction(repr(threshold))
    true = Fraction(repr(cur)) - Fraction(repr(base))
    assert _band(Fraction(c) - Fraction(b), t) == _band(true, t), (b, c)
    assert len(b.split(".")[1]) == len(c.split(".")[1])  # one shared width


@pytest.mark.parametrize(("base", "cur"), _SWEEP)
def test_both_renderers_use_the_pair(base: float, cur: float) -> None:
    b, c = render_score_pair(base, cur, 0.1)
    row = _row(base, cur, 0.1)
    assert f"| {b} | {c} |" in _row_to_md(row, 0.1)
    report = DeltaReport(
        current_run_id="c" * 32,
        baseline_run_id="b" * 32,
        suite="s",
        threshold_drop=0.1,
        rows=(row,),
        # The counts the row gives: the report refuses a summary that
        # contradicts its rows (#435).
        summary={f"n_{row.status}": 1, "n_flagged": int(row.flagged)},
    )
    row_line = next(
        line for line in render_delta_ascii(report).splitlines() if line.startswith(row.status)
    )
    assert f" {b} " in row_line
    assert f" {c} " in row_line
