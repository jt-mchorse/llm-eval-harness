"""Two renderings are distinct as numbers, not as strings (#388).

`render_comparison` stopped widening once the two strings differed. `-0.000`
and `0.000` differ as strings and both read back as zero, so measured on main,
`calibrate --threshold-kappa 0` with κ = -0.00048 (confusion matrix 5/1/56/11)
annotated the PR check with

    ::error::Cohen's κ -0.000 < threshold 0.000; ...

which is false as written, while the report from the same run said `-0.0005`.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import main
from eval_harness.comparison import render_comparison


@pytest.mark.parametrize(
    ("value", "other"),
    [
        (-0.00048, 0.0),
        (-0.0005, 0.0),
        (0.00048, -0.0),
        (-1e-9, 0.0),
        (-0.0004, 0.0004),
    ],
)
def test_the_renderings_read_back_in_the_values_order(value: float, other: float) -> None:
    a, b = render_comparison(value, other)
    assert float(a) != float(b)
    assert (float(a) < float(b)) == (value < other)


def test_equal_and_ordinary_pairs_are_unchanged() -> None:
    assert render_comparison(0.6, 0.6) == ("0.600", "0.600")
    assert render_comparison(0.5996, 0.6) == ("0.5996", "0.6000")
    assert render_comparison(0.25, 0.75) == ("0.250", "0.750")


class _Stub:
    model = "stub-judge"

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def complete(self, system: str, user: str) -> str:
        return f"SCORE: {user.split('JUDGE=')[1].split()[0]}\nREASONING: stub\n"


def test_the_calibrate_annotation_at_threshold_zero_is_true_as_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # (human, judge) cells a=5 (1,1), b=1 (1,0), c=56 (0,1), d=11 (0,0): κ ≈ -0.00048.
    cells = [(1.0, 1.0)] * 5 + [(1.0, 0.0)] + [(0.0, 1.0)] * 56 + [(0.0, 0.0)] * 11
    cal = tmp_path / "cal.jsonl"
    cal.write_text(
        "".join(
            json.dumps(
                {
                    "id": f"r{i:03d}",
                    "prompt": f"q{i} JUDGE={j}",
                    "response": "a",
                    "rubric": "faithful?",
                    "human_score": h,
                    "provenance": {"src": "t"},
                }
            )
            + "\n"
            for i, (h, j) in enumerate(cells)
        ),
        encoding="utf-8",
    )
    with patch("eval_harness.cli.AnthropicBackend", _Stub):
        rc = main(
            [
                "calibrate",
                "--calibration",
                str(cal),
                "--report",
                str(tmp_path / "report.md"),
                "--threshold-kappa",
                "0",
            ]
        )
    err = capsys.readouterr().err
    assert rc == 1
    line = next(ln for ln in err.splitlines() if ln.startswith("::error::Cohen's κ "))
    kappa, threshold = line.removeprefix("::error::Cohen's κ ").split(";")[0].split(" < threshold ")
    assert float(kappa) < float(threshold), line
