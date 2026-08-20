"""`cohens_kappa` enforces the binary scale its docstring names (#204).

The defect was an *asymmetry*, not a lone missing check: `eval_harness`
exports three calibration metric entry points — `binarize`, `pearson_r`,
`cohens_kappa` — and two of the three validated their inputs. `cohens_kappa`
validated only length and emptiness and never looked at an element, while
`_require_finite_numbers` sits one definition below it in the same file doing
exactly that job for `pearson_r`.

Every assertion here is anchored to a value measured on `main` @ cf6cfe6, not
to an exception type, so widening a guard later cannot make these pass
vacuously:

    cohens_kappa([nan, 1, 0], [0, 1, 0])   -> nan
    _interpret_kappa(nan)                  -> 'almost perfect'
    cohens_kappa([inf, 1, 0], [0, 1, 0])   -> nan
    cohens_kappa([3, 3, 0], [1, 0, 1])     -> -9007199254740991.0
    cohens_kappa([True, False], [1, 0])    -> 1.0   (pearson_r raises)
    cohens_kappa(['1', '0'], [1, 0])       -> TypeError (NOT a ValueError)

The last row matters beyond tidiness: `cli` translates `ValueError` into its
documented exit code, so a `TypeError` from inside `sum()` escaped as a raw
traceback — the same contract hole `runner._require_int` documents for
`OverflowError`.
"""

from __future__ import annotations

import math

import pytest

from eval_harness.calibration import (
    CalibrationResult,
    CalibrationRow,
    _interpret_kappa,
    cohens_kappa,
    pearson_r,
    render_report,
)
from eval_harness.judge import JudgeScore

NAN = float("nan")
INF = float("inf")


def _result(kappa: float, r: float = 0.9) -> CalibrationResult:
    """A one-row `CalibrationResult` carrying an arbitrary κ / r.

    Constructed directly rather than via `calibrate` on purpose: `calibrate`
    feeds `cohens_kappa` guarded `binarize` output, so the *only* way a
    corrupt κ reaches `render_report` is a caller building the public
    dataclass — which is exactly the reachable path, since
    `CalibrationResult` and `render_report` are both in `eval_harness.__all__`.
    """
    rows = [
        CalibrationRow(
            id="r1",
            prompt="p",
            response="a",
            rubric="rubric text",
            human_score=1.0,
            provenance={},
        )
    ]
    scores = [
        JudgeScore(score=1.0, reasoning="looks right", raw="SCORE: 1.0\nREASONING: looks right")
    ]
    return CalibrationResult(n=1, cohens_kappa=kappa, pearson_r=r, judge_scores=scores, rows=rows)


# ----------------------------------------------------------------------
# The corruption this guard exists to stop, stated as the value it produced
# ----------------------------------------------------------------------


def test_interpret_kappa_labels_a_nan_almost_perfect() -> None:
    # This is the *reason* the guard belongs on the producer rather than on
    # the renderer alone. `_interpret_kappa` is a ladder of `<` comparisons,
    # and every comparison against NaN is False, so NaN falls through to the
    # final `return "almost perfect"`. The ladder is not wrong; it is simply
    # not a place where a NaN can be caught.
    assert _interpret_kappa(NAN) == "almost perfect"
    # Contrast: a legitimately terrible κ is labelled as such.
    assert _interpret_kappa(-0.4) == "worse than chance"


@pytest.mark.parametrize("bad", [NAN, INF, -INF])
def test_non_finite_rating_no_longer_yields_a_nan_kappa(bad: float) -> None:
    # Pre-fix all three returned `nan`, which the line above renders as
    # "almost perfect" in `docs/calibration_report.md` — the file D-005 gates
    # CI on. `pearson_r` has rejected the same element since #102.
    with pytest.raises(ValueError, match=r"rater_a\[0\] must be finite"):
        cohens_kappa([bad, 1, 0], [0, 1, 0])
    # Both lists are checked, not just the first.
    with pytest.raises(ValueError, match=r"rater_b\[2\] must be finite"):
        cohens_kappa([0, 1, 0], [0, 1, bad])


def test_the_measured_extreme_out_of_range_kappa_is_rejected() -> None:
    # Brute-forcing the element domain {-1,0,1,2,3} at n=2 and n=3 finds 8088
    # input pairs whose κ is NaN or outside [-1, 1]. This is the extreme one.
    # κ is *defined* on [-1, 1]; -9.0e15 is not a bad correlation, it is the
    # marginal-proportion formula being evaluated on things that aren't
    # proportions.
    with pytest.raises(ValueError, match=r"rater_a\[0\] must be 0 or 1"):
        cohens_kappa([3, 3, 0], [1, 0, 1])


@pytest.mark.parametrize(
    ("rater_a", "rater_b", "offender"),
    [
        ([0, 2, 0, 2], [0, 1, 0, 1], r"rater_a\[1\]"),  # returned 0.0 — a plausible κ
        ([0, -1, 0, -1], [0, 1, 0, 1], r"rater_a\[1\]"),  # returned 0.0
        ([10, 0, 10, 0], [1, 0, 1, 0], r"rater_a\[0\]"),  # returned 0.0
        ([0.5, 0.5], [0, 1], r"rater_a\[0\]"),  # returned -1.0 — looks like real disagreement
        ([0, 1], [0, 7], r"rater_b\[1\]"),
    ],
)
def test_non_binary_ratings_are_rejected_instead_of_scored(
    rater_a: list, rater_b: list, offender: str
) -> None:
    # The worst of these is not the -9e15 above but this set: every one
    # returned a number that sits comfortably inside κ's real range and reads
    # as an ordinary calibration result. There is nothing downstream that
    # could notice.
    with pytest.raises(ValueError, match=offender + " must be 0 or 1"):
        cohens_kappa(rater_a, rater_b)


def test_a_string_element_raises_ValueError_not_TypeError() -> None:
    # Pre-fix: TypeError from inside `sum()`, which is not a ValueError, so it
    # walked past `cli`'s `except ValueError` translation and surfaced as a raw
    # traceback rather than the documented exit code.
    with pytest.raises(ValueError, match=r"rater_a\[0\] must be a number"):
        cohens_kappa(["1", "0"], [1, 0])
    with pytest.raises(ValueError, match=r"rater_b\[0\] must be a number"):
        cohens_kappa([1, 0], [None, 0])


# ----------------------------------------------------------------------
# The asymmetry itself — the actual defect. Pin it so it cannot come back.
# ----------------------------------------------------------------------


@pytest.mark.parametrize("bad", [NAN, INF, "1", None, True])
def test_the_two_sibling_metrics_now_agree_on_the_same_bad_element(bad: object) -> None:
    # `calibrate` feeds `pearson_r` the continuous scores and `cohens_kappa`
    # the binarized ones, from the same rows. Before #204 the two disagreed
    # about every one of these values: `pearson_r` raised ValueError for all
    # five while `cohens_kappa` returned nan, nan, TypeError, TypeError and
    # 1.0 respectively.
    with pytest.raises(ValueError, match=r"xs\[0\] must be"):
        pearson_r([bad, 1.0, 0.0], [0.0, 1.0, 0.0])  # type: ignore[list-item]
    with pytest.raises(ValueError, match=r"rater_a\[0\] must be"):
        cohens_kappa([bad, 1, 0], [0, 1, 0])  # type: ignore[list-item]


def test_bool_is_rejected_even_though_it_returned_the_right_answer() -> None:
    # Called out explicitly because this is the one case where the guard
    # NARROWS working behaviour: `cohens_kappa([True, False], [1, 0])`
    # returned a correct 1.0. It is rejected so the module holds one opinion
    # about `True` instead of three — `binarize` (#45) and
    # `_require_finite_numbers` (#102) already reject it, and all three are
    # fed from the same place by `calibrate`.
    with pytest.raises(ValueError, match=r"rater_a\[0\] must be an int 0 or 1, not a bool"):
        cohens_kappa([True, False], [1, 0])
    # The message names the fix rather than just the rule.
    with pytest.raises(ValueError, match=r"pass 1 instead"):
        cohens_kappa([True, False], [1, 0])


# ----------------------------------------------------------------------
# Everything the guard must NOT change
# ----------------------------------------------------------------------


def test_valid_binary_input_is_untouched() -> None:
    assert cohens_kappa([1, 1, 0, 0, 1], [1, 1, 0, 0, 1]) == pytest.approx(1.0)
    assert cohens_kappa([1, 0, 1, 0], [0, 1, 0, 1]) == pytest.approx(-1.0)
    assert cohens_kappa([1, 1, 1, 1], [1, 1, 1, 1]) == 0.0


def test_integral_floats_are_accepted_because_a_json_round_trip_produces_them() -> None:
    # `1.0` is what a JSON round-trip of an int looks like, and it is
    # unambiguously in the binary domain. Same posture as `runner._require_int`,
    # which accepts an integral float and rejects a fractional one.
    assert cohens_kappa([1.0, 0.0, 1.0, 0.0], [1, 0, 1, 0]) == pytest.approx(1.0)


def test_length_and_empty_guards_still_fire_first() -> None:
    # Ordering matters: a caller with mismatched lengths AND a bad element
    # should hear about the length, which is the more likely mistake. The new
    # guard sits after both, mirroring `pearson_r`.
    with pytest.raises(ValueError, match="same length"):
        cohens_kappa([NAN, 0], [1])
    with pytest.raises(ValueError, match="empty"):
        cohens_kappa([], [])


# ----------------------------------------------------------------------
# render_report: the OTHER operand of the gate comparison
# ----------------------------------------------------------------------


def test_render_report_rejects_a_nan_kappa_it_would_have_labelled_almost_perfect() -> None:
    # Measured pre-fix, verbatim from the rendered markdown:
    #
    #   | Cohen's κ (binarized at 0.5) | nan | almost perfect |
    #
    # with `- result: **FAIL**` above it, because `nan >= 0.6` is False. A
    # report that says FAIL and "almost perfect" in the same table is worse
    # than one that doesn't render.
    with pytest.raises(ValueError, match=r"result\.cohens_kappa must be finite"):
        render_report(_result(NAN), judge_model="claude-haiku-4-5")


@pytest.mark.parametrize("bad", [INF, -INF, 1.5, -9007199254740991.0])
def test_render_report_rejects_an_out_of_range_kappa(bad: float) -> None:
    # `render_report` already guarded `threshold_kappa` with this exact
    # reasoning ("finite values outside that range cannot ever match ... so
    # the gate is silently broken"). It was applied to one operand of
    # `result.cohens_kappa >= threshold_kappa` and not the other.
    with pytest.raises(ValueError, match=r"result\.cohens_kappa must be"):
        render_report(_result(bad), judge_model="claude-haiku-4-5")


def test_render_report_rejects_an_out_of_range_pearson_r() -> None:
    # r shares κ's [-1, 1] range and feeds `_interpret_pearson`, whose ladder
    # has the identical NaN fall-through — `abs(nan) < 0.1` is False all the
    # way down to "very strong".
    with pytest.raises(ValueError, match=r"result\.pearson_r must be finite"):
        render_report(_result(0.5, r=NAN), judge_model="claude-haiku-4-5")
    with pytest.raises(ValueError, match=r"result\.pearson_r must be in \[-1, 1\]"):
        render_report(_result(0.5, r=2.0), judge_model="claude-haiku-4-5")


def test_render_report_still_renders_every_legitimate_kappa() -> None:
    # The boundaries are inclusive, and the PASS/FAIL gate is unchanged.
    for kappa, expected in ((-1.0, "FAIL"), (0.6, "PASS"), (1.0, "PASS"), (0.59, "FAIL")):
        out = render_report(_result(kappa), judge_model="claude-haiku-4-5", threshold_kappa=0.6)
        assert f"- result: **{expected}**" in out
        assert math.isfinite(kappa)
