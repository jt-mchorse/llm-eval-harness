"""Bounded-float validation for `binarize.threshold` and
`render_report.threshold_kappa` in `eval_harness/calibration.py`.

Both were called out as deferred follow-ups in #45's PR body. They share
the bounded-float validator shape used by `compute_drift` in #40:
reject NaN/inf/wrong-type/bool, then enforce the explicit value-domain
range. `binarize.threshold` ranges over `[0, 1]` (matches
`JudgeScore.score`); `render_report.threshold_kappa` ranges over
`[-1, 1]` (matches Cohen's κ).

Silent-failure modes closed:

- `binarize(threshold=NaN)`: every comparison False, all scores
  binarized to 0, `cohens_kappa` returns 0.0 via the degenerate
  `pe == 1.0` branch. Calibration reports κ=0 with no diagnostic.
- `binarize(threshold=2.0)` or `threshold=-1.0`: same silent constant
  rater → silent κ=0.
- `render_report(threshold_kappa=NaN)`: PASS/FAIL comparison False →
  always FAIL. CI gate silently broken.
- `render_report(threshold_kappa=-2)`: gate always passes, silently
  disabled.
"""

from __future__ import annotations

import math

import pytest

from eval_harness.calibration import (
    CalibrationResult,
    binarize,
    render_report,
)

# ======================================================================
# binarize.threshold — bounded float in [0, 1]
# ======================================================================


@pytest.mark.parametrize(
    "bad_threshold",
    [
        math.nan,
        math.inf,
        -math.inf,
        True,  # bool: silently coerced to 1.0 — surprising threshold.
        False,  # bool: silently coerced to 0.0.
        None,
        "0.5",
        [],
        (0.5,),
        {"v": 0.5},
    ],
)
def test_binarize_rejects_non_finite_or_wrong_type_threshold(bad_threshold):
    with pytest.raises(ValueError, match="threshold must be a finite number"):
        binarize(0.5, threshold=bad_threshold)


@pytest.mark.parametrize("bad_threshold", [-0.0001, -1.0, -100, 1.0001, 2.0, 100])
def test_binarize_rejects_out_of_range_threshold(bad_threshold):
    with pytest.raises(ValueError, match=r"threshold must be in \[0, 1\]"):
        binarize(0.5, threshold=bad_threshold)


@pytest.mark.parametrize("good_threshold", [0, 0.0, 0.25, 0.5, 0.75, 1, 1.0])
def test_binarize_accepts_in_range_finite_threshold(good_threshold):
    # No raise; smoke that the function still binarizes correctly.
    assert binarize(1.0, threshold=good_threshold) == 1


def test_binarize_boundary_zero_default_score_behavior():
    # threshold = 0 means everything (including 0) binarizes to 1.
    assert binarize(0.0, threshold=0.0) == 1
    assert binarize(0.5, threshold=0.0) == 1


def test_binarize_boundary_one_default_score_behavior():
    # threshold = 1 means only score == 1 binarizes to 1.
    assert binarize(1.0, threshold=1.0) == 1
    assert binarize(0.99, threshold=1.0) == 0


# ======================================================================
# binarize.score — bounded float in [0, 1] (#77)
# ======================================================================
# #45 guarded `threshold` but not `score`, even though both share
# `JudgeScore.score`'s [0, 1] domain. A NaN score made `score >= threshold`
# False → silent 0; inf / out-of-range → silent constant — either collapses a
# rater and corrupts κ to a silent 0.0, the same failure mode closed for
# `threshold`.


@pytest.mark.parametrize(
    "bad_score",
    [
        math.nan,
        math.inf,
        -math.inf,
        True,  # bool: silently coerced to 1.0.
        False,  # bool: silently coerced to 0.0.
        None,
        "0.5",
        [],
        (0.5,),
        {"v": 0.5},
    ],
)
def test_binarize_rejects_non_finite_or_wrong_type_score(bad_score):
    with pytest.raises(ValueError, match="score must be a finite number"):
        binarize(bad_score, threshold=0.5)


@pytest.mark.parametrize("bad_score", [-0.0001, -1.0, -100, 1.0001, 2.0, 100])
def test_binarize_rejects_out_of_range_score(bad_score):
    with pytest.raises(ValueError, match=r"score must be in \[0, 1\]"):
        binarize(bad_score, threshold=0.5)


@pytest.mark.parametrize("good_score", [0, 0.0, 0.25, 0.5, 0.75, 1, 1.0])
def test_binarize_accepts_in_range_finite_score(good_score):
    # No raise; result is a valid {0, 1} binarization.
    assert binarize(good_score, threshold=0.5) in (0, 1)


# ======================================================================
# render_report.threshold_kappa — bounded float in [-1, 1]
# ======================================================================


def _empty_result() -> CalibrationResult:
    return CalibrationResult(
        n=0,
        cohens_kappa=0.5,
        pearson_r=0.5,
        judge_scores=[],
        rows=[],
    )


@pytest.mark.parametrize(
    "bad_kappa",
    [
        math.nan,
        math.inf,
        -math.inf,
        True,
        False,
        None,
        "0.6",
        [],
    ],
)
def test_render_report_rejects_non_finite_or_wrong_type_threshold_kappa(bad_kappa):
    with pytest.raises(ValueError, match="threshold_kappa must be a finite number"):
        render_report(_empty_result(), judge_model="stub", threshold_kappa=bad_kappa)


@pytest.mark.parametrize(
    "bad_kappa",
    [-1.0001, -2.0, -10, 1.0001, 2.0, 100],
)
def test_render_report_rejects_out_of_range_threshold_kappa(bad_kappa):
    with pytest.raises(ValueError, match=r"threshold_kappa must be in \[-1, 1\]"):
        render_report(_empty_result(), judge_model="stub", threshold_kappa=bad_kappa)


@pytest.mark.parametrize("good_kappa", [-1, -1.0, -0.5, 0, 0.0, 0.6, 1, 1.0])
def test_render_report_accepts_in_range_finite_threshold_kappa(good_kappa):
    md = render_report(_empty_result(), judge_model="stub", threshold_kappa=good_kappa)
    # Smoke: report rendered without ValueError; PASS or FAIL is present.
    assert "PASS" in md or "FAIL" in md
