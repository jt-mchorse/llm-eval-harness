"""Smoke test for `scripts/capture_demo.sh` (issue #20).

The capture script is the deterministic driver for the 60-second README demo.
JT records the GIF/video while it runs; CI runs it with `CAPTURE_PACE_SECONDS=0`
to make sure the demo can't bitrot the same way `tests/test_examples_smoke.py`
protects the per-surface example scripts.

Contract this test pins:

1. The script exits 0 on a fresh clone with no API key.
2. Each of the three surfaces actually runs (their distinctive output lines appear).
3. The sticky-comment marker is present in BOTH the push-1 and push-2 renderings
   — that is the entire point of D-009 (marker-based identity), and the
   capture's job is to make it visible to the viewer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "capture_demo.sh"


@pytest.fixture(scope="module")
def capture_output() -> str:
    """Run the capture script once and reuse its stdout across assertions.

    `CAPTURE_PACE_SECONDS=0` removes the recording pauses; `CAPTURE_OPEN_HTML`
    is left unset so no browser is launched in CI.
    """
    if not SCRIPT.exists():
        pytest.fail(f"missing {SCRIPT}")
    if shutil.which("bash") is None:
        pytest.skip("bash not available")

    env = dict(os.environ)
    env["CAPTURE_PACE_SECONDS"] = "0"
    env.pop("CAPTURE_OPEN_HTML", None)
    # Ensure `eval-harness` (and the editable `eval_harness` package) resolve
    # via the same interpreter pytest is using — capture_demo.sh shells out to
    # `eval-harness` and `python`, so put the active venv's bin first on PATH.
    venv_bin = Path(sys.executable).parent
    env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"capture_demo.sh exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    return result.stdout


def test_surface_1_regression_run_and_diff(capture_output: str) -> None:
    assert "1/3 · regression runner" in capture_output
    assert "baseline run_id=" in capture_output
    assert "current  run_id=" in capture_output
    assert "FLAG" in capture_output, "expected the regressed row flagged on push #1"
    assert "qa_003" in capture_output, "regression_run_and_diff.py regresses qa_003"


def test_surface_2_drift_report(capture_output: str) -> None:
    assert "2/3 · three-axis drift report" in capture_output
    for axis in ("length axis", "embedding axis", "judge axis"):
        assert axis in capture_output, f"missing {axis!r} in capture output"
    assert "HTML report written to:" in capture_output


def test_surface_3_sticky_comment_marker_is_stable_across_pushes(
    capture_output: str,
) -> None:
    """D-009: marker-based identity. The same marker line appears on every push;
    the action edits the prior comment in place instead of stacking duplicates."""
    assert "3/3 · PR sticky-comment flow" in capture_output
    assert "push #1" in capture_output
    assert "push #2" in capture_output
    marker = "<!-- eval-harness:sticky-comment -->"
    assert capture_output.count(marker) >= 2, (
        f"expected the {marker!r} marker in both push #1 and push #2 renderings; "
        f"found {capture_output.count(marker)}"
    )
    # The push-2 synth flips the headline status away from `[X]` (flagged)
    # since the worst row's bump clears the threshold-drop flag.
    assert "[X] mean" in capture_output, "push #1 should be a flagged headline"


def test_capture_demo_script_exists_and_is_executable() -> None:
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} should be executable"
