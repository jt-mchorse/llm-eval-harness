"""The calibration report's per-row scores binarize as κ binarized them (#361).

κ is Cohen's κ on `binarize(score)` (`>= 0.5`), and the report says so, but the
per-row `human` / `judge` cells were a fixed `.2f`: a score in `[0.495, 0.5)`
printed `0.50`. With a judge answering 0.497 where the human said 0.5-0.7, main
(c46b3fb) published a FAIL at κ 0.546 above rows reading `0.50 | 0.50 | 0.00`,
and the printed table re-binarizes to κ 0.798.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from eval_harness import Judge, calibrate, load_calibration
from eval_harness.calibration import (
    CalibrationResult,
    _render_score_pair,
    binarize,
    cohens_kappa,
    render_report,
)

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "calibration.jsonl"


class _JustBelowCutoffBackend:
    """Echo the human score, except answer 0.497 where the human said [0.5, 0.8)."""

    def __init__(self, humans: dict[str, float]) -> None:
        self.humans = humans

    def complete(self, system: str, user: str) -> str:
        prompt = next(c for c in user.split("\n\n") if c.startswith("PROMPT:"))[7:].strip()
        human = self.humans[prompt]
        score = 0.497 if 0.5 <= human < 0.8 else human
        return f"SCORE: {score}\nREASONING: stub\n"


def _result() -> CalibrationResult:
    rows = load_calibration(_FIXTURE)
    backend = _JustBelowCutoffBackend({r.prompt: r.human_score for r in rows})
    return calibrate(Judge(backend=backend), rows)


def _table(md: str) -> list[list[str]]:
    rows = []
    for line in md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0].startswith("`"):
            rows.append(cells)
    return rows


def test_the_printed_table_rebinarizes_to_the_reported_kappa() -> None:
    result = _result()
    rows = _table(render_report(result, judge_model="stub"))
    assert len(rows) == 50
    human = [binarize(float(r[1])) for r in rows]
    judged = [binarize(float(r[2])) for r in rows]
    assert cohens_kappa(human, judged) == result.cohens_kappa


def test_the_reported_row_prints_the_judge_below_the_cutoff() -> None:
    rows = {r[0]: r for r in _table(render_report(_result(), judge_model="stub"))}
    assert rows["`part_005`"][1:4] == ["0.700", "0.497", "0.203"]


def test_every_row_still_subtracts() -> None:
    # #293's invariant, over the widened rows.
    for row_id, human, judged, diff, _ in _table(render_report(_result(), judge_model="stub")):
        assert Fraction(diff) == abs(Fraction(human) - Fraction(judged)), row_id


@pytest.mark.parametrize(
    ("human", "judged", "expected"),
    [
        (0.625, 0.375, ("0.62", "0.38")),  # two decimals are enough: unchanged
        (0.5, 0.503, ("0.50", "0.50")),  # same class at two places: not widened
        (0.495, 0.0, ("0.49", "0.00")),  # 0.495 is a double just below and rounds down
        (0.497, 0.7, ("0.497", "0.700")),
        (0.7, 0.4999, ("0.7000", "0.4999")),
        (
            0.5,
            0.49999999999999994,
            ("0.5000000000000000", "0.4999999999999999"),
        ),  # last double below
    ],
)
def test_the_pair_widens_only_as_far_as_the_class_needs(
    human: float, judged: float, expected: tuple[str, str]
) -> None:
    rendered_human, rendered_judged, width = _render_score_pair(human, judged)
    assert (rendered_human, rendered_judged) == expected
    assert len(rendered_human.split(".")[1]) == len(rendered_judged.split(".")[1]) == width


def test_every_score_on_a_fine_grid_prints_in_its_own_class() -> None:
    for i in range(100_001):
        score = i / 100_000
        rendered, _, _ = _render_score_pair(score, 1.0)
        assert binarize(float(rendered)) == binarize(score), (score, rendered)
