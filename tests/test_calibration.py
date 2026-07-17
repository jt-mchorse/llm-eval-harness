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
    CalibrationRow,
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


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_pearson_rejects_non_finite_in_xs(bad):
    # A non-finite element silently produced a NaN result that
    # _interpret_pearson then rendered as "very strong" (#102). Fail loud,
    # the same contract as binarize (#45).
    with pytest.raises(ValueError, match="xs\\[1\\] must be finite"):
        pearson_r([0.1, bad, 0.3], [0.2, 0.3, 0.4])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_pearson_rejects_non_finite_in_ys(bad):
    with pytest.raises(ValueError, match="ys\\[2\\] must be finite"):
        pearson_r([0.1, 0.2, 0.3], [0.2, 0.3, bad])


def test_pearson_rejects_non_numeric_element():
    with pytest.raises(ValueError, match="xs\\[0\\] must be a number"):
        pearson_r(["x", 0.2, 0.3], [0.1, 0.2, 0.3])  # type: ignore[list-item]


def test_pearson_rejects_bool_element():
    # bool is an int subclass; the module rejects it in score contexts.
    with pytest.raises(ValueError, match="ys\\[0\\] must be a number"):
        pearson_r([0.1, 0.2, 0.3], [True, 0.2, 0.3])  # type: ignore[list-item]


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


@pytest.mark.parametrize("bad_rubric", ["", "   ", "\t\n"])
def test_load_rejects_empty_rubric(tmp_path, bad_rubric):
    # #75: rubric is the judge instruction — an empty/whitespace one is malformed
    # and must fail loud, not silently fall back to the default rubric (which the
    # old `row.rubric or FAITHFULNESS_RUBRIC` in calibrate() did).
    p = tmp_path / "bad.jsonl"
    obj = {
        "id": "a",
        "prompt": "p",
        "response": "r",
        "rubric": bad_rubric,
        "human_score": 1.0,
        "provenance": {},
    }
    p.write_text(json.dumps(obj) + "\n", encoding="utf-8")
    with pytest.raises(CalibrationLoadError, match="rubric must be a non-empty string"):
        load_calibration(p)


def test_calibrate_passes_row_rubric_verbatim_to_judge():
    # #75: calibrate() must judge each row against its own rubric, not silently
    # swap in the default. A recording judge captures the rubric it receives.
    from eval_harness.judge import JudgeScore

    class RecordingJudge:
        def __init__(self) -> None:
            self.rubrics: list[str] = []

        def score(self, prompt: str, response: str, *, rubric: str) -> JudgeScore:
            self.rubrics.append(rubric)
            return JudgeScore(score=0.5, reasoning="stub", raw="SCORE: 0.5")

    rows = [
        CalibrationRow(
            id="r1",
            prompt="p1",
            response="resp1",
            rubric="Rate strictly on citation accuracy.",
            human_score=0.5,
            provenance={},
        ),
        CalibrationRow(
            id="r2",
            prompt="p2",
            response="resp2",
            rubric="Rate on completeness only.",
            human_score=0.5,
            provenance={},
        ),
    ]
    judge = RecordingJudge()
    calibrate(judge, rows)
    assert judge.rubrics == [
        "Rate strictly on citation accuracy.",
        "Rate on completeness only.",
    ]


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


def test_render_report_neutralizes_backtick_in_judge_model_so_span_stays_single():
    # #182: the `` - judge model: `{judge_model}` `` list item is a non-table code
    # span (#180 fixed only the table cells). judge_model derives from `--model`,
    # so a backtick in it closes the span early. The list-item line must carry
    # exactly the two backticks of its own span.
    rows = load_calibration(REPO_ROOT / "fixtures" / "calibration.jsonl")[:10]
    backend = EchoBackend({r.response: r.human_score for r in rows})
    judge = Judge(backend=backend)
    result = calibrate(judge, rows)
    md = render_report(result, judge_model="claude`rm -rf`x", threshold_kappa=0.6)
    line = next(ln for ln in md.splitlines() if ln.startswith("- judge model:"))
    assert line.count("`") == 2, line
    assert "rm -rf" in line


def test_render_report_escapes_pipe_in_id_and_reasoning_so_columns_dont_break():
    # #134 (sibling to comment.py #130): `row.id` and the free-form
    # `js.reasoning` land in a GFM per-row table cell. Backticks do NOT protect
    # a literal `|` — GFM splits table cells on unescaped pipes before it parses
    # inline-code spans, so a piped id or reasoning injects an extra column and
    # corrupts the whole table. The fix escapes `|` -> `\|`; the invariant is
    # that the data row's unescaped-pipe count equals the header row's. Fails
    # pre-fix (the piped row carried 8 unescaped pipes vs the header's 6).
    import re

    from eval_harness.calibration import CalibrationResult
    from eval_harness.judge import JudgeScore

    rows = [
        CalibrationRow(
            id="lang=py|framework=x",
            prompt="p",
            response="r",
            rubric="score it",
            human_score=0.8,
            provenance={},
        )
    ]
    judge_scores = [JudgeScore(score=0.7, reasoning="faithful | grounded in prompt", raw="raw")]
    result = CalibrationResult(
        n=1, cohens_kappa=1.0, pearson_r=1.0, judge_scores=judge_scores, rows=rows
    )
    md = render_report(result, judge_model="stub", threshold_kappa=0.6)

    lines = md.splitlines()
    header_line = next(line for line in lines if line.startswith("| id "))
    row_line = next(line for line in lines if "lang=py" in line)

    def unescaped_pipes(s: str) -> int:
        # A `\|` renders as a literal pipe and does NOT split the cell; only a
        # bare, unescaped `|` is a column delimiter.
        return len(re.findall(r"(?<!\\)\|", s))

    assert unescaped_pipes(row_line) == unescaped_pipes(header_line)
    # The literal pipes are preserved (escaped), not dropped.
    assert "lang=py\\|framework=x" in row_line
    assert "faithful \\| grounded in prompt" in row_line


def test_render_report_neutralizes_newline_in_id_so_the_row_stays_one_line():
    # #142 (companion to #134): a literal newline in `row.id` is a GFM *row*
    # delimiter — it splits the per-row cell across two physical lines and
    # corrupts the table exactly as an unescaped pipe corrupts columns.
    # `load_calibration` only requires `id` be a non-empty string, so a newline
    # is reachable. The piped-and-newlined data row must stay a single physical
    # line with the same structural-pipe count as the header. Fails pre-fix
    # (the row split into two lines).
    import re

    from eval_harness.calibration import CalibrationResult
    from eval_harness.judge import JudgeScore

    rows = [
        CalibrationRow(
            id="row\n| INJ",
            prompt="p",
            response="r",
            rubric="score it",
            human_score=0.5,
            provenance={},
        )
    ]
    judge_scores = [JudgeScore(score=0.5, reasoning="fine", raw="raw")]
    result = CalibrationResult(
        n=1, cohens_kappa=1.0, pearson_r=1.0, judge_scores=judge_scores, rows=rows
    )
    md = render_report(result, judge_model="stub", threshold_kappa=0.6)

    lines = md.splitlines()
    header_line = next(line for line in lines if line.startswith("| id "))
    inj_lines = [line for line in lines if "INJ" in line]

    def unescaped_pipes(s: str) -> int:
        return len(re.findall(r"(?<!\\)\|", s))

    assert len(inj_lines) == 1, lines
    assert unescaped_pipes(inj_lines[0]) == unescaped_pipes(header_line)
    # The literal pipe is preserved as an escape, not dropped.
    assert "\\| INJ" in inj_lines[0]


def test_render_report_neutralizes_backtick_in_id_so_the_code_span_stays_single():
    # #180 (sibling to comment.py #180 and chunking#135): `row.id` is WRAPPED in
    # an inline-code span (`` `{id}` ``). A backtick in the id closes that span
    # early — `` `a`b`c` `` tokenizes as two code spans with `b` leaking out as
    # prose. `load_calibration` only requires `id` be a non-empty string, so a
    # backtick is reachable. The id cell must carry exactly its own two backticks.
    from eval_harness.calibration import CalibrationResult
    from eval_harness.judge import JudgeScore

    rows = [
        CalibrationRow(
            id="suite/case`rm -rf`x",
            prompt="p",
            response="r",
            rubric="score it",
            human_score=0.5,
            provenance={},
        )
    ]
    judge_scores = [JudgeScore(score=0.5, reasoning="fine", raw="raw")]
    result = CalibrationResult(
        n=1, cohens_kappa=1.0, pearson_r=1.0, judge_scores=judge_scores, rows=rows
    )
    md = render_report(result, judge_model="stub", threshold_kappa=0.6)

    row_line = next(line for line in md.splitlines() if "rm -rf" in line)
    id_cell = row_line.split("|")[1]
    assert id_cell.count("`") == 2, row_line
    assert "rm -rf" in id_cell
