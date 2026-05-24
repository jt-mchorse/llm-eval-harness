"""Smoke test for `scripts/capture_demo.py`.

Same hermetic contract as `tests/test_examples_smoke.py` — runs
end-to-end under stub backends, no API key, no live network. Asserts
the script sequences both example flows, copies the drift HTML to a
stable artifact path, and prints the STAGE 3 cheat-sheet by default
but not under `--skip-sticky-cheatsheet`.

The architecture-doc lock (`tests/test_architecture_doc.py`) explicitly
excludes #20 from the closed-feature-issue coverage check on the
grounds that "capture script shipped in a separate PR and locked by
tests/test_capture_demo_smoke.py" — this file is that lock.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path


def _load_capture_module():
    """Load `scripts/capture_demo.py` as a fresh module.

    `scripts/` isn't a package and is intentionally not on the default
    import path — adding it here keeps the script self-contained while
    still letting the smoke test exercise its `main(argv)` entry point
    directly (faster + clearer failure output than a subprocess shell-out).
    """
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if "capture_demo" in sys.modules:
        del sys.modules["capture_demo"]
    import capture_demo  # noqa: WPS433 — dynamic import is the whole point here.

    return capture_demo


def test_capture_demo_runs_both_flows_and_writes_stable_artifact(tmp_path: Path) -> None:
    capture_demo = _load_capture_module()

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = capture_demo.main(
            [
                "--pause-seconds",
                "0",
                "--no-open",
                "--output-dir",
                str(tmp_path),
                "--skip-sticky-cheatsheet",
            ]
        )
    out = buf.getvalue()

    assert rc == 0, f"capture_demo exited {rc}; stdout:\n{out}"

    # Stage banners present.
    assert "STAGE 1" in out, f"expected STAGE 1 banner; got:\n{out}"
    assert "STAGE 2" in out, f"expected STAGE 2 banner; got:\n{out}"

    # STAGE 1 — markers from examples/regression_run_and_diff.py.
    assert "baseline run_id=" in out
    assert "current  run_id=" in out
    assert "FLAG" in out, f"expected at least one regression flagged; got:\n{out}"

    # STAGE 2 — markers from examples/drift_report.py.
    for axis in ("length axis", "embedding axis", "judge axis"):
        assert axis in out, f"expected {axis!r} in stdout; got:\n{out}"

    # Stable artifact copied + path rewrite worked.
    stable = tmp_path / "drift_report.html"
    assert stable.exists(), f"expected stable artifact at {stable}"
    content = stable.read_text(encoding="utf-8")
    assert "<svg" in content, (
        "expected inline SVG in stable HTML artifact; got first 200 chars:\n" + content[:200]
    )
    assert "</html>" in content, (
        "expected closing </html> tag in stable HTML artifact; got first 200 chars:\n"
        + content[:200]
    )
    assert str(stable) in out, (
        "expected the stable artifact path to appear in stdout (path-rewrite "
        f"should replace the tempfile path); got:\n{out}"
    )


def test_capture_demo_prints_sticky_cheatsheet_by_default(tmp_path: Path) -> None:
    capture_demo = _load_capture_module()

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = capture_demo.main(
            [
                "--pause-seconds",
                "0",
                "--no-open",
                "--output-dir",
                str(tmp_path),
            ]
        )
    assert rc == 0
    out = buf.getvalue()

    assert "STAGE 3" in out, f"expected STAGE 3 banner by default; got:\n{out}"
    assert "Sticky-comment flow" in out
    # The cheat-sheet must reference the HTML marker AND the gh fork command,
    # so the operator gets a runnable recipe and the recording shows the
    # marker name that the GitHub Action also uses.
    assert "eval-harness:sticky-comment" in out
    assert "gh repo fork" in out


def test_capture_demo_skip_sticky_suppresses_stage_3(tmp_path: Path) -> None:
    capture_demo = _load_capture_module()

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = capture_demo.main(
            [
                "--pause-seconds",
                "0",
                "--no-open",
                "--output-dir",
                str(tmp_path),
                "--skip-sticky-cheatsheet",
            ]
        )
    assert rc == 0
    out = buf.getvalue()

    # Stages 1 and 2 ran; Stage 3 was suppressed.
    assert "STAGE 1" in out
    assert "STAGE 2" in out
    assert "STAGE 3" not in out
    assert "Sticky-comment flow" not in out


def test_capture_demo_exposes_main_callable() -> None:
    """Same uniform contract as `examples/`: a `main(argv) -> int`
    callable so the script is importable + driveable from tests."""
    capture_demo = _load_capture_module()
    assert hasattr(capture_demo, "main"), "scripts/capture_demo.py must expose main()"
    # Verify the argv keyword is accepted (regression guard against
    # someone removing the parameter and breaking in-process drivers).
    import inspect

    sig = inspect.signature(capture_demo.main)
    assert "argv" in sig.parameters, f"main() must accept argv; current signature: {sig}"
