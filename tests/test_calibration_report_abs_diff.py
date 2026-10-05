"""The calibration report's abs_diff is the difference of the scores printed beside it (#293).

`render_report` printed `abs(human - judge):.2f` from the unrounded scores
beside two columns each rounded to `.2f`. With a judge answering 0.625 /
0.375 over the committed calibration set, 6 of 50 rows did not subtract on
main (eaba81f), e.g. `0.95 | 0.62 | 0.32`.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from eval_harness import Judge, calibrate, load_calibration
from eval_harness.calibration import render_report

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "calibration.jsonl"


class _ThreeDecimalBackend:
    def __init__(self) -> None:
        self.n = 0

    def complete(self, system: str, user: str) -> str:
        self.n += 1
        return f"SCORE: {0.625 if self.n % 2 else 0.375}\nREASONING: stub\n"


def test_every_row_subtracts() -> None:
    result = calibrate(Judge(backend=_ThreeDecimalBackend()), load_calibration(_FIXTURE))
    md = render_report(result, judge_model="stub")
    rows = []
    for line in md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0].startswith("`"):
            rows.append(cells)
    assert len(rows) == 50
    for row_id, human, judged, diff, _ in rows:
        assert Fraction(diff) == abs(Fraction(human) - Fraction(judged)), row_id
