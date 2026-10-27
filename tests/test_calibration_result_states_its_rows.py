"""`CalibrationResult` states κ and r; the rows it carries must give them (#438).

`__post_init__` checked `n` against the rows (#262) and nothing else, so a
hand-built result rendered a verdict its own table contradicted. Measured on
`main` (ea25ba0), verbatim from `render_report`:

    CalibrationResult(n=4, cohens_kappa=0.95, pearson_r=0.97, ...)
    over human [1, 0, 1, 0] / judge [0, 1, 0, 1]
    - result: **PASS**
    | Cohen's κ (binarized at 0.5) | 0.950 | almost perfect |
    | Pearson r (continuous)       | 0.970 | very strong |

The rows give κ = -1.0 and r = -1.0. `CalibrationResult` and `render_report`
are both public (`eval_harness.__all__`).
"""

from __future__ import annotations

import random

import pytest

from eval_harness.calibration import (
    CalibrationResult,
    CalibrationRow,
    binarize,
    calibrate,
    cohens_kappa,
    pearson_r,
    render_report,
)
from eval_harness.judge import JudgeScore


def _rows(human: list[float]) -> list[CalibrationRow]:
    return [
        CalibrationRow(
            id=f"r{i}", prompt="p", response="a", rubric="rubric", human_score=h, provenance={}
        )
        for i, h in enumerate(human)
    ]


def _scores(judge: list[float]) -> list[JudgeScore]:
    return [JudgeScore(score=j, reasoning="r", raw=f"SCORE: {j}") for j in judge]


def _result(human: list[float], judge: list[float], kappa: float, r: float) -> CalibrationResult:
    return CalibrationResult(
        n=len(human),
        cohens_kappa=kappa,
        pearson_r=r,
        judge_scores=_scores(judge),
        rows=_rows(human),
    )


def _true(human: list[float], judge: list[float]) -> tuple[float, float]:
    """κ and r computed here from the public metric functions, not via the helper under test."""
    return (
        cohens_kappa([binarize(h) for h in human], [binarize(j) for j in judge]),
        pearson_r(human, judge),
    )


HUMAN = [1.0, 0.0, 1.0, 0.0]
JUDGE = [0.0, 1.0, 0.0, 1.0]


def test_the_issue_repro_is_refused_before_it_can_render() -> None:
    assert _true(HUMAN, JUDGE) == (-1.0, -1.0)
    with pytest.raises(ValueError, match=r"cohens_kappa=0\.95 but the 4 rows give -1\.0"):
        _result(HUMAN, JUDGE, kappa=0.95, r=0.97)


def test_a_wrong_r_beside_a_right_kappa_is_refused() -> None:
    # The r check is not riding on the κ check: κ here is exactly right.
    with pytest.raises(ValueError, match=r"pearson_r=0\.97 but the 4 rows give -1\.0"):
        _result(HUMAN, JUDGE, kappa=-1.0, r=0.97)


def test_a_wrong_kappa_beside_a_right_r_is_refused() -> None:
    with pytest.raises(ValueError, match=r"cohens_kappa=0\.95 but the 4 rows give -1\.0"):
        _result(HUMAN, JUDGE, kappa=0.95, r=-1.0)


def test_a_non_finite_kappa_over_rows_is_refused_at_construction() -> None:
    # Before, NaN reached `render_report`'s own guard (#204); a result with rows
    # now cannot carry it at all.
    with pytest.raises(ValueError, match=r"cohens_kappa=nan but the 4 rows give"):
        _result(HUMAN, JUDGE, kappa=float("nan"), r=-1.0)


def test_a_kappa_a_few_ulp_below_what_the_rows_give_is_refused() -> None:
    """Exact, not within a tolerance: this is the value #283 removed from the producer.

    Rows giving exactly κ = 0.6 (the default gate) stated as the float-drift
    value 0.5999999999999996 read FAIL against a judge that met the gate.
    """
    human = [1.0] + [0.0] * 7
    judge = [1.0, 1.0] + [0.0] * 6
    kappa, r = _true(human, judge)
    assert kappa == 0.6  # precondition: the rows really give the gate value
    with pytest.raises(ValueError, match=r"cohens_kappa=0\.5999999999999996"):
        _result(human, judge, kappa=0.5999999999999996, r=r)


@pytest.mark.parametrize(
    ("field", "value"),
    [("cohens_kappa", -0.0), ("pearson_r", -0.0), ("cohens_kappa", False)],
    ids=["kappa-negative-zero", "r-negative-zero", "kappa-bool"],
)
def test_a_value_equal_to_the_rows_but_not_the_same_number_is_refused(
    field: str, value: object
) -> None:
    # One row: both raters are constant, so κ and r are both exactly 0.0. A
    # stated -0.0 compares equal and rendered `-0.000` over that table.
    human, judge = [1.0], [1.0]
    assert _true(human, judge) == (0.0, 0.0)
    kwargs = {"cohens_kappa": 0.0, "pearson_r": 0.0, field: value}
    with pytest.raises(ValueError, match=rf"{field}={value!r} but the 1 rows give 0\.0"):
        CalibrationResult(n=1, judge_scores=_scores(judge), rows=_rows(human), **kwargs)  # type: ignore[arg-type]


def test_a_hand_built_result_stating_what_its_rows_give_still_renders() -> None:
    # Control: the check refuses a contradiction, not a hand-built result.
    kappa, r = _true(HUMAN, JUDGE)
    md = render_report(_result(HUMAN, JUDGE, kappa=kappa, r=r), judge_model="m")
    assert "- result: **FAIL**" in md
    assert "| Cohen's κ (binarized at 0.5) | -1.000 |" in md


def test_an_int_equal_to_what_the_rows_give_is_accepted() -> None:
    # Control: `0` is the number `0.0`, unlike `False`.
    _result([1.0], [1.0], kappa=0, r=0)


def test_an_empty_result_still_carries_any_kappa() -> None:
    # Control, and the scope line: with no rows there is nothing to recompute
    # from, so the renderer's own range checks stay the guard there.
    CalibrationResult(n=0, cohens_kappa=0.95, pearson_r=0.97, judge_scores=[], rows=[])


class _ReplayJudge:
    def __init__(self, scores: list[float]) -> None:
        self._scores = iter(scores)

    def score(self, prompt: str, response: str, *, rubric: str) -> JudgeScore:
        j = next(self._scores)
        return JudgeScore(score=j, reasoning="r", raw=f"SCORE: {j}")


# Grid values that are not exactly representable (0.05, 0.1, 0.3) are in on
# purpose: they are where float means and sums drift, which is where a
# recomputation that differed from the producer's would show.
_GRID = [0.0, 0.05, 0.1, 0.25, 0.3, 0.49, 0.5, 0.51, 0.7, 0.95, 1.0]


@pytest.mark.parametrize("seed", range(40))
def test_calibrate_round_trip_is_never_refused(seed: int) -> None:
    """The one producer's output always passes its own record's check."""
    rng = random.Random(seed)
    for n in (1, 2, 3, 5, 8, 13, 50):
        human = [rng.choice(_GRID) for _ in range(n)]
        if seed % 4 == 0:
            judge = [human[0]] * n  # constant judge: r = 0 by shape (#420)
        elif seed % 4 == 1:
            judge = list(human)  # perfect agreement: r clamped to 1 (#384)
        else:
            judge = [rng.choice(_GRID) for _ in range(n)]
        result = calibrate(_ReplayJudge(judge), _rows(human))
        assert (result.cohens_kappa, result.pearson_r) == _true(human, judge)
