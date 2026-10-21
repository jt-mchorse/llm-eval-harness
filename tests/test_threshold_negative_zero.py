"""A threshold of negative zero is published as zero, with no sign (#416).

#412 normalised `-0.0` at the reader seams and at `threshold_drop`, whose
`< 0.0` check `-0.0` passes. Two more thresholds have the same shape and were
not listed. Measured on `main` (f547a04): `calibrate --threshold-kappa -0` wrote
`- threshold for κ: -0.000` where `--threshold-kappa 0` wrote `0.000`, and
`compute_drift(..., length_threshold=-0.0)` kept `-0.0` on the report and printed
`<td>-0.0000</td>` in the HTML table.

`checked_threshold_kappa` already returned a value, but both of its callers
discarded it, so the fix is the return AND its use. `-0.0 == 0.0`, so the sign
is checked with `math.copysign`.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from eval_harness import cli
from eval_harness.calibration import (
    CalibrationResult,
    CalibrationRow,
    checked_threshold_kappa,
    render_report,
)
from eval_harness.drift import compute_drift, render_html
from eval_harness.judge import JudgeScore

REPO = Path(__file__).resolve().parent.parent


def _positive(x: float) -> bool:
    return math.copysign(1.0, x) == 1.0


def _result(kappa: float) -> CalibrationResult:
    row = CalibrationRow(
        id="r1", prompt="p", response="a", rubric="rubric text", human_score=1.0, provenance={}
    )
    score = JudgeScore(score=1.0, reasoning="r", raw="SCORE: 1.0\nREASONING: r")
    return CalibrationResult(
        n=1, cohens_kappa=kappa, pearson_r=0.5, judge_scores=[score], rows=[row]
    )


def _threshold_line(report: str) -> str:
    (line,) = [ln for ln in report.splitlines() if ln.startswith("- threshold for κ:")]
    return line


# ----------------------------------------------------------------------
# --threshold-kappa
# ----------------------------------------------------------------------


def test_checked_threshold_kappa_returns_negative_zero_unsigned() -> None:
    assert _positive(checked_threshold_kappa(-0.0))


@pytest.mark.parametrize("value", [0.0, 0, 0.6, -0.25, -1.0, 1.0])
def test_checked_threshold_kappa_passes_every_other_value_through(value: float) -> None:
    # Control: only the sign of zero changes.
    out = checked_threshold_kappa(value)
    assert out == value
    assert math.copysign(1.0, out) == math.copysign(1.0, value)


def test_render_report_prints_a_negative_zero_threshold_as_zero() -> None:
    line = _threshold_line(render_report(_result(0.5), judge_model="m", threshold_kappa=-0.0))
    assert line == _threshold_line(
        render_report(_result(0.5), judge_model="m", threshold_kappa=0.0)
    )
    assert "-0" not in line


class _Stub:
    model = "stub"

    def __init__(self, *_a: object, **_k: object) -> None:
        pass

    def complete(self, system: str, user: str) -> str:
        return "SCORE: 0.9\nREASONING: fine"


def _calibrate(tmp_path: Path, kappa: str) -> str:
    report = tmp_path / f"report{kappa}.md"
    rc = cli.main(
        [
            "calibrate",
            "--calibration",
            str(REPO / "fixtures" / "calibration.jsonl"),
            "--report",
            str(report),
            f"--threshold-kappa={kappa}",
        ]
    )
    assert rc in (0, 1)
    return _threshold_line(report.read_text(encoding="utf-8"))


def test_calibrate_cli_report_prints_threshold_kappa_minus_zero_as_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The issue's repro: a backend that always answers 0.9.
    monkeypatch.setattr(cli, "AnthropicBackend", _Stub)
    assert _calibrate(tmp_path, "-0") == _calibrate(tmp_path, "0") == "- threshold for κ: 0.000"


def test_calibrate_cli_error_annotation_prints_threshold_kappa_minus_zero_as_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The `::error::` annotation is the other place the CLI prints the threshold,
    # reached when κ is below it -- here a negative κ below `-0`.
    monkeypatch.setattr(cli, "AnthropicBackend", _Stub)
    monkeypatch.setattr(cli, "calibrate", lambda _judge, _rows: _result(-0.25))
    rc = cli.main(
        [
            "calibrate",
            "--calibration",
            str(REPO / "fixtures" / "calibration.jsonl"),
            "--report",
            str(tmp_path / "report.md"),
            "--threshold-kappa=-0",
        ]
    )
    assert rc == 1
    (line,) = [ln for ln in capsys.readouterr().err.splitlines() if ln.startswith("::error::")]
    assert "threshold -0" not in line
    assert "< threshold 0" in line


# ----------------------------------------------------------------------
# compute_drift thresholds
# ----------------------------------------------------------------------

GOLDEN = ["what is a cat", "who wrote macbeth", "the sky is blue"]
CANDIDATE = ["how to bake bread", "stock prices today"]


def _drift(value: float):
    return compute_drift(
        GOLDEN,
        CANDIDATE,
        judge_score_fn=lambda _s: 0.5,
        length_threshold=value,
        embedding_threshold=value,
        judge_threshold=value,
    )


def test_compute_drift_stores_negative_zero_thresholds_unsigned() -> None:
    report = _drift(-0.0)
    assert report.judge is not None
    for axis in (report.length, report.embedding, report.judge):
        assert _positive(axis.threshold)


def test_drift_html_prints_negative_zero_thresholds_as_zero() -> None:
    html = render_html(_drift(-0.0))
    assert "-0.0000" not in html
    # Control: the same report built from `0.0` renders identically.
    assert html.count("<td>0.0000</td>") == render_html(_drift(0.0)).count("<td>0.0000</td>")
    assert html.count("<td>0.0000</td>") >= 3


@pytest.mark.parametrize("value", [0.0, 0.1, 1.0])
def test_compute_drift_passes_every_other_threshold_through(value: float) -> None:
    report = _drift(value)
    assert report.judge is not None
    for axis in (report.length, report.embedding, report.judge):
        assert axis.threshold == value
        assert _positive(axis.threshold)
