"""A calibration `human_score` that is an int too large for a double is a finding (#359).

#318 turned `float()` of a huge JSON integer into a `ValueError` at the six
`runner.py` sites. `calibration._row_from_dict`, the choke point both
`load_calibration` and `validate_calibration` share, kept a bare
`float(score)`. Measured on `main` (c46b3fb): a row whose `human_score` is a
401-digit integer literal made `validate --calibration` and `calibrate` print
an `OverflowError: int too large to convert to float` traceback at exit 1 --
"findings" for one and "kappa below threshold" for the other -- while the same
row with `1e400` gets a clean `score_range` finding.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval_harness import cli
from eval_harness.calibration import CalibrationLoadError, load_calibration, validate_calibration

HUGE = "9" * 401


def _row(row_id: str, score: str) -> str:
    base = {
        "id": row_id,
        "prompt": "p",
        "response": "r",
        "rubric": "x",
        "human_score": "__SCORE__",
        "provenance": {},
    }
    return json.dumps(base).replace('"__SCORE__"', score)


def _write(tmp_path: Path, *lines: str) -> Path:
    p = tmp_path / "cal.jsonl"
    p.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return p


def test_load_calibration_refuses_it_as_score_range(tmp_path: Path) -> None:
    p = _write(tmp_path, _row("a", HUGE))
    assert HUGE in p.read_text()
    with pytest.raises(CalibrationLoadError, match="too large to be a finite number") as exc:
        load_calibration(p)
    assert exc.value.code == "score_range"


def test_validate_collects_it_beside_the_other_rows(tmp_path: Path) -> None:
    # Collecting mode: the huge row is one finding and the walk continues, so
    # the `2.0` row after it is still reported.
    p = _write(tmp_path, _row("a", "0.5"), _row("b", HUGE), _row("c", "2.0"))
    report = validate_calibration(p)
    assert [(f.line_no, f.code) for f in report.findings] == [
        (2, "score_range"),
        (3, "score_range"),
    ]
    assert (report.n_rows, report.n_valid) == (3, 1)


def test_validate_cli_reports_it_without_a_traceback(tmp_path: Path) -> None:
    p = _write(tmp_path, _row("a", HUGE))
    proc = subprocess.run(
        [sys.executable, "-m", "eval_harness.cli", "validate", "--calibration", str(p)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "line 1 [score_range]: human_score must be in [0, 1]" in proc.stdout + proc.stderr


def test_calibrate_cli_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # The file is loaded before the judge backend is built, so this is hermetic.
    p = _write(tmp_path, _row("a", HUGE))
    rc = cli.main(["calibrate", "--calibration", str(p), "--report", str(tmp_path / "r.md")])
    assert rc == 2
    assert "too large to be a finite number" in capsys.readouterr().err
    assert not (tmp_path / "r.md").exists()
