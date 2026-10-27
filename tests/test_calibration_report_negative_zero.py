"""A κ or r of negative zero is published as zero, with no sign (#445).

#416 normalised `-0.0` for the report's threshold line. The κ and r cells in
the table below it have the same shape and were not listed. Measured on `main`
(fcc9bb3)::

    render_report(CalibrationResult(n=0, cohens_kappa=-0.0, pearson_r=-0.0,
                                    judge_scores=[], rows=[]), judge_model="m")
    | Cohen's κ (binarized at 0.5) | -0.000 | slight |
    | Pearson r (continuous)       | -0.000 | negligible |

Since #441 a result with rows must state the κ and r its rows give, so only an
empty, hand-built result reaches this; the last two tests check that
`cohens_kappa` and `pearson_r` never return `-0.0` themselves.
"""

from __future__ import annotations

import itertools
import math

import pytest

from eval_harness.calibration import (
    CalibrationResult,
    cohens_kappa,
    pearson_r,
    render_report,
)


def _report(kappa: float, r: float, threshold_kappa: float = 0.6) -> str:
    result = CalibrationResult(n=0, cohens_kappa=kappa, pearson_r=r, judge_scores=[], rows=[])
    return render_report(result, judge_model="m", threshold_kappa=threshold_kappa)


def _cell(report: str, metric: str) -> tuple[str, str]:
    for line in report.splitlines():
        if line.startswith(f"| {metric}"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            return cells[1], cells[2]
    raise AssertionError(f"no {metric} row in:\n{report}")


def test_issue_repro_both_cells() -> None:
    report = _report(-0.0, -0.0)
    assert _cell(report, "Cohen's κ") == ("0.000", "slight")
    assert _cell(report, "Pearson r") == ("0.000", "negligible")
    assert "-0.000" not in report


@pytest.mark.parametrize(
    ("kappa", "r"),
    [(-0.0, -0.0), (-0.0, 0.0), (0.0, -0.0)],
    ids=["both", "kappa", "r"],
)
@pytest.mark.parametrize("threshold_kappa", [0.6, 0.0, -0.0, -0.5])
def test_negative_zero_report_is_the_zero_report(kappa, r, threshold_kappa) -> None:
    """The whole report, byte for byte, is the report of an unsigned zero."""
    assert _report(kappa, r, threshold_kappa) == _report(0.0, 0.0, threshold_kappa)


def test_at_threshold_zero_the_pass_reads_zero_against_zero() -> None:
    report = _report(-0.0, 0.0, threshold_kappa=0.0)
    assert "- threshold for κ: 0.000" in report
    assert "- result: **PASS**" in report
    assert _cell(report, "Cohen's κ")[0] == "0.000"


# Controls: only a zero loses its sign. A real negative value keeps it.


def test_small_negative_kappa_keeps_its_sign_and_label() -> None:
    value, label = _cell(_report(-0.0001, 0.0), "Cohen's κ")
    assert value.startswith("-")
    assert label == "worse than chance"


def test_small_negative_r_keeps_its_sign() -> None:
    value, label = _cell(_report(0.0, -0.0001), "Pearson r")
    assert value == "-0.000"
    assert label == "negligible"


def test_pearson_r_never_returns_negative_zero() -> None:
    grid = [0.0, 0.25, 0.5, 0.75, 1.0]
    seen_zero = 0
    for xs in itertools.product(grid, repeat=3):
        for ys in itertools.product(grid, repeat=3):
            r = pearson_r(list(xs), list(ys))
            if r == 0:
                seen_zero += 1
                assert math.copysign(1.0, r) == 1.0, (xs, ys)
    assert seen_zero > 0


def test_cohens_kappa_never_returns_negative_zero() -> None:
    seen_zero = 0
    for a in itertools.product([0, 1], repeat=4):
        for b in itertools.product([0, 1], repeat=4):
            k = cohens_kappa(list(a), list(b))
            if k == 0:
                seen_zero += 1
                assert math.copysign(1.0, k) == 1.0, (a, b)
    assert seen_zero > 0
