"""`calibrate --threshold-kappa` is checked before any row is judged (#342).

It was range-checked only inside `render_report`, after `calibrate(judge, rows)`
had scored every row, and the ValueError escaped at exit 1 -- the code this
command reserves for "kappa below threshold". Measured on main with a counting
backend over `fixtures/calibration.jsonl` (50 rows): nan, inf, 2 and -1.5 each
made 50 judge calls, then raised.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_harness import cli
from eval_harness.calibration import (
    CalibrationResult,
    CalibrationRow,
    render_report,
)
from eval_harness.judge import JudgeScore

REPO = Path(__file__).resolve().parent.parent
CALLS: list[int] = []


class _Counting:
    model = "counting"

    def __init__(self, *_a: object, **_k: object) -> None:
        pass

    def complete(self, system: str, user: str) -> str:
        CALLS.append(1)
        return "SCORE: 0.8\nREASONING: fine"


@pytest.fixture(autouse=True)
def _backend(monkeypatch: pytest.MonkeyPatch) -> None:
    CALLS.clear()
    monkeypatch.setattr(cli, "AnthropicBackend", _Counting)


def _calibrate(tmp_path: Path, kappa: str) -> int:
    return cli.main(
        [
            "calibrate",
            "--calibration",
            str(REPO / "fixtures" / "calibration.jsonl"),
            "--report",
            str(tmp_path / "report.md"),
            f"--threshold-kappa={kappa}",
        ]
    )


@pytest.mark.parametrize("kappa", ["nan", "inf", "-inf", "2", "-1.5", "1.0000001"])
def test_an_invalid_threshold_exits_2_before_any_judge_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kappa: str
) -> None:
    assert _calibrate(tmp_path, kappa) == 2
    assert CALLS == []
    assert not (tmp_path / "report.md").exists()
    err = capsys.readouterr()
    lines = [ln for ln in (err.out + err.err).splitlines() if ln.startswith("::error::")]
    assert len(lines) == 1
    assert "--threshold-kappa" in lines[0]


@pytest.mark.parametrize("kappa", ["-1", "0.6", "1"])
def test_a_valid_threshold_is_judged_as_before(tmp_path: Path, kappa: str) -> None:
    assert _calibrate(tmp_path, kappa) in (0, 1)
    assert len(CALLS) == 50
    assert (tmp_path / "report.md").exists()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 2.0, -1.5, True, "0.6"])
def test_the_report_still_refuses_for_library_callers(bad: object) -> None:
    row = CalibrationRow(
        id="r1", prompt="p", response="a", rubric="rubric text", human_score=1.0, provenance={}
    )
    score = JudgeScore(score=1.0, reasoning="r", raw="SCORE: 1.0\nREASONING: r")
    result = CalibrationResult(
        n=1, cohens_kappa=0.5, pearson_r=0.5, judge_scores=[score], rows=[row]
    )
    with pytest.raises(ValueError, match="threshold_kappa must be"):
        render_report(result, judge_model="m", threshold_kappa=bad)  # type: ignore[arg-type]
    from eval_harness.calibration import checked_threshold_kappa

    with pytest.raises(ValueError, match="threshold_kappa must be"):
        checked_threshold_kappa(bad)
