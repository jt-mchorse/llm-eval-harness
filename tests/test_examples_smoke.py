"""Smoke tests for `examples/`.

Imports each example module and runs its `main()` (or, for the pytest example,
verifies it can be discovered and parametrized). The point isn't to test
the eval-harness API a second time — the rest of `tests/` covers that — it's
to make sure the example files don't bitrot when the public API changes.

The runtime contract is small: every example must expose a `main() -> int`
callable, must run end-to-end without an API key, and must exit 0 on success.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _run_example_main(module_path: str) -> tuple[int, str]:
    """Import the module fresh, call `main()`, capture stdout. Returns (rc, stdout)."""
    import importlib

    # Force a fresh import so we don't accidentally short-circuit module-level work.
    if module_path in sys.modules:
        del sys.modules[module_path]
    mod = importlib.import_module(module_path)
    assert hasattr(mod, "main"), f"{module_path} must expose a `main()` callable"

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main()
    return rc, buf.getvalue()


def test_judge_calibration_stub_runs_and_prints_metrics() -> None:
    rc, out = _run_example_main("examples.judge_calibration_stub")
    assert rc == 0, f"example exited {rc}; stdout:\n{out}"
    assert "Cohen" in out, f"expected Cohen's κ in stdout; got:\n{out}"
    assert "Pearson" in out, f"expected Pearson r in stdout; got:\n{out}"
    assert "50 rows" in out, f"expected calibration row count in stdout; got:\n{out}"


def test_regression_run_and_diff_runs_and_flags_regression() -> None:
    rc, out = _run_example_main("examples.regression_run_and_diff")
    assert rc == 0, f"example exited {rc}; stdout:\n{out}"
    assert "baseline run_id=" in out
    assert "current  run_id=" in out
    # The example regresses qa_003 (Berlin Wall) by 0.7, well past the 0.1 threshold.
    assert "FLAG" in out, "expected at least one row flagged; got:\n" + out
    assert re.search(r"regressed example_ids: \[.*qa_003.*\]", out), (
        "expected qa_003 in the regressed_ids list; got:\n" + out
    )


def test_drift_report_runs_and_writes_html_file() -> None:
    rc, out = _run_example_main("examples.drift_report")
    assert rc == 0, f"example exited {rc}; stdout:\n{out}"
    for axis in ("length axis", "embedding axis", "judge axis"):
        assert axis in out, f"expected {axis!r} in stdout; got:\n{out}"
    match = re.search(r"HTML report written to: (.+\.html)", out)
    assert match, "expected an HTML report path in stdout; got:\n" + out
    html_path = Path(match.group(1).strip())
    assert html_path.exists(), f"expected {html_path} to exist on disk"
    content = html_path.read_text()
    assert "<svg" in content, (
        "expected inline SVG in HTML report; got first 200 chars:\n" + content[:200]
    )
    assert "</html>" in content, (
        "expected closing </html> tag in HTML report; got first 200 chars:\n" + content[:200]
    )


def test_pytest_eval_example_collects_and_passes() -> None:
    """The pytest example uses the harness's plugin — invoke pytest as a subprocess.

    Calling `main()` would re-invoke pytest from inside pytest (which works but
    is noisy); shelling out keeps the suites cleanly isolated. The example's
    `main()` does the same subprocess hop, so this also exercises that path
    indirectly.
    """
    example = EXAMPLES_DIR / "pytest_eval.py"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "--no-header", str(example)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"pytest example exited {result.returncode}; stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "passed" in result.stdout
    # 10 rows in fixtures/sample_factuality_v1.jsonl → 10 parametrized items.
    assert re.search(r"10 passed", result.stdout), (
        "expected 10 parametrized items to pass; got:\n" + result.stdout
    )


@pytest.mark.parametrize(
    "example_name",
    [
        "judge_calibration_stub",
        "regression_run_and_diff",
        "drift_report",
        "pytest_eval",
    ],
)
def test_example_file_exposes_main(example_name: str) -> None:
    """Every example file ships a `main()` so the smoke contract is uniform."""
    example_path = EXAMPLES_DIR / f"{example_name}.py"
    assert example_path.exists(), f"missing example: {example_path}"
    source = example_path.read_text()
    assert "def main(" in source, f"{example_name}.py must define `main(...)`"
    assert "__name__" in source, (
        f"{example_name}.py must reference __name__ for an `if __name__ == '__main__'` guard"
    )
    assert "__main__" in source, (
        f"{example_name}.py must reference __main__ for an `if __name__ == '__main__'` guard"
    )
