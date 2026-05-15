"""Tests for the calibration module.

Two layers covered hermetically:

1. Math (cohens_kappa, pearson_r). Tested against textbook examples plus
   degenerate cases. No network.
2. Loader (load_calibration). Loads the committed 50-row file + small
   synthetic ones for failure-case coverage.

The end-to-end calibrate() function uses a stub Judge so it runs without an
API key. The CI gate (κ ≥ 0.6) is exercised by render_report's PASS/FAIL string.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness.calibration import (
    CalibrationLoadError,
    binarize,
    calibrate,
    cohens_kappa,
    load_calibration,
    pearson_r,
    render_report,
)
from eval_harness.judge import Judge

REPO_ROOT = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------
# binarize
# ----------------------------------------------------------------------


def test_binarize_threshold_inclusive():
    assert binarize(0.5) == 1
    assert binarize(0.49) == 0
    assert binarize(1.0) == 1
    assert binarize(0.0) == 0


def test_binarize_custom_threshold():
    assert binarize(0.7, threshold=0.8) == 0
    assert binarize(0.8, threshold=0.8) == 1


# ----------------------------------------------------------------------
# cohens_kappa
# ----------------------------------------------------------------------


def test_kappa_perfect_agreement_is_one():
    assert cohens_kappa([1, 1, 0, 0, 1], [1, 1, 0, 0, 1]) == pytest.approx(1.0)


def test_kappa_perfect_disagreement_is_negative():
    # Two raters, both with marginal 50/50, total disagreement: kappa = -1
    assert cohens_kappa([1, 0, 1, 0], [0, 1, 0, 1]) == pytest.approx(-1.0)


def test_kappa_chance_agreement_near_zero():
    # Both raters call 50% positive; agreement matches chance.
    assert abs(cohens_kappa([1, 1, 0, 0], [1, 0, 1, 0])) < 1e-9


def test_kappa_textbook_example():
    # Classical 2x2 contingency: a=20, b=5, c=10, d=15 (n=50)
    # po = (20+15)/50 = 0.7
    # pe = ((25*30) + (25*20)) / 50^2 = (750 + 500)/2500 = 0.5
    # kappa = (0.7 - 0.5) / (1 - 0.5) = 0.4
    rater_a = [1] * 25 + [0] * 25
    rater_b = [1] * 20 + [0] * 5 + [1] * 10 + [0] * 15
    assert cohens_kappa(rater_a, rater_b) == pytest.approx(0.4)


def test_kappa_degenerate_constant_returns_zero():
    # Both raters return all 1s — pe == 1, kappa undefined; convention: 0.0
    assert cohens_kappa([1, 1, 1, 1], [1, 1, 1, 1]) == 0.0


def test_kappa_length_mismatch_raises():
    with pytest.raises(ValueError, match="same length"):
        cohens_kappa([1, 0], [1])


def test_kappa_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        cohens_kappa([], [])


# ----------------------------------------------------------------------
# pearson_r
# ----------------------------------------------------------------------


def test_pearson_perfect_positive():
    assert pearson_r([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0]) == pytest.approx(1.0)


def test_pearson_perfect_negative():
    assert pearson_r([1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]) == pytest.approx(-1.0)


def test_pearson_no_variance_returns_zero():
    assert pearson_r([1.0, 1.0, 1.0], [2.0, 3.0, 4.0]) == 0.0


def test_pearson_textbook_example():
    # x = [1,2,3,4,5], y = [2,4,5,4,5] -> r ≈ 0.7745966692
    r = pearson_r([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 4.0, 5.0, 4.0, 5.0])
    assert r == pytest.approx(0.7745966692, abs=1e-6)


def test_pearson_length_mismatch_raises():
    with pytest.raises(ValueError, match="same length"):
        pearson_r([1.0], [1.0, 2.0])


# ----------------------------------------------------------------------
# load_calibration
# ----------------------------------------------------------------------


def test_load_committed_calibration_set_has_50_rows():
    rows = load_calibration(REPO_ROOT / "fixtures" / "calibration.jsonl")
    assert len(rows) == 50
    # All ids unique (loader enforces; double-check here for visibility).
    assert len({r.id for r in rows}) == 50
    # All human_scores in [0, 1].
    for r in rows:
        assert 0.0 <= r.human_score <= 1.0
    # Provenance is non-empty on every row.
    for r in rows:
        assert isinstance(r.provenance, dict)
        assert r.provenance


def test_load_rejects_blank_line(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text(
        json.dumps(
            {
                "id": "a",
                "prompt": "p",
                "response": "r",
                "rubric": "rub",
                "human_score": 1.0,
                "provenance": {"x": 1},
            }
        )
        + "\n\n",
        encoding="utf-8",
    )
    with pytest.raises(CalibrationLoadError, match="blank line"):
        load_calibration(p)


def test_load_rejects_invalid_json(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(CalibrationLoadError, match="invalid JSON"):
        load_calibration(p)


def test_load_rejects_missing_required_field(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps({"id": "a", "prompt": "p"}) + "\n", encoding="utf-8")
    with pytest.raises(CalibrationLoadError, match="missing required fields"):
        load_calibration(p)


def test_load_rejects_unknown_field(tmp_path):
    p = tmp_path / "bad.jsonl"
    obj = {
        "id": "a",
        "prompt": "p",
        "response": "r",
        "rubric": "rub",
        "human_score": 1.0,
        "provenance": {},
        "extra": "nope",
    }
    p.write_text(json.dumps(obj) + "\n", encoding="utf-8")
    with pytest.raises(CalibrationLoadError, match="unknown top-level field"):
        load_calibration(p)


def test_load_rejects_human_score_out_of_range(tmp_path):
    p = tmp_path / "bad.jsonl"
    obj = {
        "id": "a",
        "prompt": "p",
        "response": "r",
        "rubric": "rub",
        "human_score": 1.5,
        "provenance": {},
    }
    p.write_text(json.dumps(obj) + "\n", encoding="utf-8")
    with pytest.raises(CalibrationLoadError, match=r"\[0, 1\]"):
        load_calibration(p)


def test_load_rejects_duplicate_ids(tmp_path):
    p = tmp_path / "bad.jsonl"
    obj = {
        "id": "a",
        "prompt": "p",
        "response": "r",
        "rubric": "rub",
        "human_score": 1.0,
        "provenance": {},
    }
    p.write_text((json.dumps(obj) + "\n") * 2, encoding="utf-8")
    with pytest.raises(CalibrationLoadError, match="duplicate id"):
        load_calibration(p)


# ----------------------------------------------------------------------
# calibrate() end-to-end with a stub Judge
# ----------------------------------------------------------------------


class EchoBackend:
    """Backend that returns whatever score is encoded in the prompt's response field.

    For tests, we control the judge's output by embedding it in the response.
    """

    def __init__(self, score_for_response: dict[str, float]):
        self.scores = score_for_response

    def complete(self, system: str, user: str) -> str:
        # Pull the response substring out of USER_TEMPLATE shape.
        response_marker = "RESPONSE: "
        idx = user.find(response_marker)
        response = user[idx + len(response_marker) :].strip()
        score = self.scores.get(response, 0.5)
        return f"SCORE: {score}\nREASONING: stub"


def test_calibrate_runs_judge_over_every_row_and_computes_metrics():
    rows = load_calibration(REPO_ROOT / "fixtures" / "calibration.jsonl")
    # Stub backend that returns the exact human score for every response.
    # Judge agrees perfectly with humans → kappa == 1.0, r == 1.0.
    backend = EchoBackend({r.response: r.human_score for r in rows})
    judge = Judge(backend=backend)
    result = calibrate(judge, rows)
    assert result.n == 50
    assert result.cohens_kappa == pytest.approx(1.0)
    assert result.pearson_r == pytest.approx(1.0)


def test_calibrate_against_anti_correlated_judge():
    rows = load_calibration(REPO_ROOT / "fixtures" / "calibration.jsonl")
    # Judge returns the *opposite* of the human score.
    backend = EchoBackend({r.response: 1.0 - r.human_score for r in rows})
    judge = Judge(backend=backend)
    result = calibrate(judge, rows)
    # Kappa should be negative; Pearson r near -1 (continuous flip).
    assert result.cohens_kappa < 0
    assert result.pearson_r < -0.5


def test_render_report_marks_pass_above_threshold():
    rows = load_calibration(REPO_ROOT / "fixtures" / "calibration.jsonl")
    backend = EchoBackend({r.response: r.human_score for r in rows})
    judge = Judge(backend=backend)
    result = calibrate(judge, rows)
    md = render_report(result, judge_model="stub", threshold_kappa=0.6)
    assert "**PASS**" in md
    assert "n=" not in md  # we use markdown bullet, not text dump
    assert "Cohen's κ" in md or "Cohen's" in md
    assert "Pearson r" in md or "Pearson" in md


def test_render_report_marks_fail_below_threshold():
    rows = load_calibration(REPO_ROOT / "fixtures" / "calibration.jsonl")[:10]
    # All-ones backend → kappa == 0 (degenerate) → below 0.6 threshold.
    backend = EchoBackend({r.response: 1.0 for r in rows})
    judge = Judge(backend=backend)
    result = calibrate(judge, rows)
    md = render_report(result, judge_model="stub", threshold_kappa=0.6)
    assert "**FAIL**" in md
