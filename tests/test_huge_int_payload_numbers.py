"""A payload number that is an int too large for a double is bad input (exit 2) (#318).

`float(10**400)` raises OverflowError, which no reader catch block translated.
Measured on `main` (a hunt agent, re-run here): a RunResult JSON whose `score`
is a 401-digit integer literal made `eval-harness diff-json` print a raw
`OverflowError: int too large to convert to float` traceback and exit 1 -- the
code that means "a row was flagged as a regression" -- while the same file with
`1e400` gave the clean `non-finite score` error at exit 2.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval_harness.runner import DeltaReport, load_run_result_from_json

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HUGE = "9" * 401


def _with_huge(payload: dict, path: list[str | int]) -> dict:
    text = json.dumps(payload)
    obj = json.loads(text)
    target = obj
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = "__HUGE__"
    return json.loads(json.dumps(obj).replace('"__HUGE__"', HUGE))


@pytest.mark.parametrize(
    "path", [["rows", 0, "score"], ["mean_score"]], ids=["row score", "mean_score"]
)
def test_a_run_result_refuses_it_as_a_value_error(path: list, tmp_path: Path) -> None:
    payload = _with_huge(json.loads((FIXTURES / "demo_current.json").read_text()), path)
    p = tmp_path / "run.json"
    p.write_text(json.dumps(payload))
    assert HUGE in p.read_text()
    with pytest.raises(ValueError, match="too large to be a finite number"):
        load_run_result_from_json(p)


def test_diff_json_exits_2_not_1(tmp_path: Path) -> None:
    cur = json.loads((FIXTURES / "demo_current.json").read_text())
    (tmp_path / "cur.json").write_text(json.dumps(_with_huge(cur, ["rows", 0, "score"])))
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "diff-json",
            "--current",
            str(tmp_path / "cur.json"),
            "--baseline",
            str(FIXTURES / "demo_baseline.json"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 2, proc.stderr
    assert "Traceback" not in proc.stderr
    assert "too large to be a finite number" in proc.stderr


def test_a_delta_report_refuses_a_huge_threshold_drop(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "diff-json",
            "--current",
            str(FIXTURES / "demo_current.json"),
            "--baseline",
            str(FIXTURES / "demo_baseline.json"),
            "--format",
            "json",
            "--out",
            str(tmp_path / "d.json"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    delta = json.loads((tmp_path / "d.json").read_text())
    with pytest.raises(ValueError, match="too large to be a finite number"):
        DeltaReport.from_json(_with_huge(delta, ["threshold_drop"]))
    assert proc.returncode in (0, 1)


def test_an_ordinary_score_still_loads() -> None:  # control
    assert load_run_result_from_json(FIXTURES / "demo_current.json").rows
