"""eval.yml's diff steps tolerate exit 1 (flagged) and fail on 2 (bad input) (#310).

Both `diff-json` steps ended in `|| echo "...regression flagged — continuing"`,
which swallows every non-zero exit. `diff-json` exits 1 when a row is flagged
and 2 on bad input, so a missing or unreadable fixture continued to the comment
step against a `/tmp/delta.json` that was never written. These arms run each
step's real `run:` script under `bash -e`, as Actions does, with a PATH stub
standing in for `eval-harness` that exits with a chosen code.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "eval.yml"


def _diff_steps() -> list[dict]:
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["eval-comment"]["steps"]
    found = [s for s in steps if "run" in s and "diff-json" in s["run"]]
    assert len(found) == 2, "expected the json and the markdown diff steps"
    return found


def _run(step: dict, rc: int, tmp_path: Path) -> int:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "eval-harness"
    stub.write_text(f"#!/bin/sh\nexit {rc}\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    script = tmp_path / "step.sh"
    script.write_text(step["run"], encoding="utf-8")
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(["bash", "-e", str(script)], env=env, timeout=30).returncode


@pytest.mark.parametrize("which", [0, 1], ids=["json", "markdown"])
@pytest.mark.parametrize(
    ("rc", "expected"), [(0, 0), (1, 0), (2, 2)], ids=["clean", "flagged", "bad-input"]
)
def test_each_diff_step_passes_0_and_1_and_fails_on_2(
    which: int, rc: int, expected: int, tmp_path: Path
) -> None:
    assert _run(_diff_steps()[which], rc, tmp_path) == expected
