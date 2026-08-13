#!/usr/bin/env python3
"""Deterministic capture orchestrator for the llm-eval-harness 60-second demo.

Sequences the two hermetic example flows under stable artifact paths so a
screen recorder can re-capture the demo over and over and land on
identical frames. The third demo flow — the sticky-comment marker (#6) —
needs real PR webhook events and isn't Python-scriptable; it's printed
as a numbered cheat-sheet of `gh` commands the operator runs on a forked
test repo.

Usage:

    python scripts/capture_demo.py [--pause-seconds 2.0] [--no-open]
                                   [--output-dir docs/demo-artifacts]
                                   [--skip-sticky-cheatsheet]

The script lives under `scripts/` so `examples/` stays reserved for the
single-flow tutorials. The same hermetic contract as `examples/` applies:
no API key, no live network, stub backends only. Locked by
`tests/test_capture_demo_smoke.py`.

Closes the AC3 row on #20 ("Capture script committed under scripts/ so
the demo can be re-captured deterministically"). AC1 (committed
GIF/MP4) and AC2 (README embed) remain operator-only.
"""

from __future__ import annotations

import argparse
import importlib
import io
import math
import re
import shutil
import sys
import time
import webbrowser
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "demo-artifacts"

# Stable filename for the drift report once copied out of the
# example's tempfile location. The recorder's browser tab opens this
# path, so it must stay constant across re-captures.
DRIFT_REPORT_FILENAME = "drift_report.html"


def _fail(message: str) -> int:
    """Print a clean ``::error::`` line to stderr and return exit code 2.

    Same shape as ``eval_harness.cli._fail``. This script is an entry point in
    its own right (``main(argv) -> int`` under ``raise SystemExit(main())``),
    so it owes the operator the same ``0 = clean / 1 = findings /
    2 = I/O or usage error`` contract the subcommands honor — the reason
    ``drift.cli`` puts its guard in the module rather than in
    ``cli._run_drift``. ``main`` already hand-writes a failure path for a
    non-zero example ``rc``; these are the seams that were left bare (#198).
    """
    print(f"::error::{message}", file=sys.stderr)
    return 2


def _banner(stage: int, title: str) -> str:
    line = "=" * 72
    return f"\n{line}\n  STAGE {stage}  {title}\n{line}\n"


def _validate_pause_seconds(seconds: float) -> str | None:
    """Return an error message for an unusable ``--pause-seconds``, else ``None``.

    ``type=float`` is not validation. Both directions of the unguarded domain
    were live (#198):

    - ``inf`` reached ``time.sleep`` and raised a raw ``OverflowError``
      ("timestamp out of range for platform time_t") *after* STAGE 1 had
      already run, so the operator got a half-finished capture and a
      traceback at exit 1.
    - ``nan`` and negatives were the quiet half: ``_pause`` guards
      ``if seconds > 0``, and ``nan > 0`` is ``False``, so the run exited 0
      having taken no pause at all. The inter-stage pauses are the script's
      only reason to exist ("cue points to cut on"), so a silent exit-0 run
      whose recording is unusable is the worse of the two failures.

    Guard shape mirrors ``calibration.render_report``'s ``threshold_kappa``
    and ``calibration.binarize``'s ``threshold`` — the repo's established form
    for a finite-float parameter, including the ``bool`` exclusion (``True``
    would otherwise pass as ``1.0``) for callers that pass ``argv=None`` and
    reach ``main`` programmatically.
    """
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return f"--pause-seconds must be a number; got {seconds!r}"
    if math.isnan(seconds) or math.isinf(seconds):
        return f"--pause-seconds must be finite; got {seconds!r}"
    if seconds < 0:
        return f"--pause-seconds must be >= 0; got {seconds!r}"
    return None


def _pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _run_example_main(module_path: str) -> tuple[int, str]:
    """Import the example fresh and call its `main()`, capturing stdout.

    Mirrors the loader in `tests/test_examples_smoke.py` so the capture
    script and the smoke tests exercise the same import path; if an
    example bitrots, both surfaces fail together.
    """
    if module_path in sys.modules:
        del sys.modules[module_path]
    mod = importlib.import_module(module_path)
    if not hasattr(mod, "main"):
        raise RuntimeError(f"{module_path} must expose a `main()` callable")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main()
    return rc, buf.getvalue()


def _extract_html_path(stdout: str) -> Path:
    match = re.search(r"HTML report written to: (.+\.html)", stdout)
    if not match:
        raise RuntimeError(
            "could not find HTML report path in drift example stdout; "
            "examples/drift_report.py contract may have changed"
        )
    return Path(match.group(1).strip())


def _sticky_comment_cheatsheet() -> str:
    return (
        "# Sticky-comment flow (#6) — operator steps on a forked test repo.\n"
        "# Not Python-scriptable: requires real PR webhook events. Run these by\n"
        "# hand once per re-capture; the recording shows the marker comment\n"
        "# being edited in place across two pushes.\n"
        "#\n"
        "# 1. Fork + clone a throwaway copy:\n"
        "#      gh repo fork jt-mchorse/llm-eval-harness --clone --remote\n"
        "#      cd llm-eval-harness && git checkout -b demo/sticky-flow\n"
        "#\n"
        "# 2. Push an initial commit and open a PR (the GitHub Action posts\n"
        "#    a sticky-comment with the `eval-harness:sticky-comment` HTML\n"
        "#    marker on first run):\n"
        "#      git commit --allow-empty -m 'demo: sticky-comment first push'\n"
        "#      git push -u origin demo/sticky-flow\n"
        "#      gh pr create --title 'demo: sticky-comment' --body 'first run'\n"
        "#\n"
        "# 3. Push a second commit — the same comment node is edited in place,\n"
        "#    not duplicated. The recording captures the permalink staying\n"
        "#    constant across the two updates:\n"
        "#      git commit --allow-empty -m 'demo: sticky-comment second push'\n"
        "#      git push\n"
        "#\n"
        "# 4. Delete the PR / fork when the recording is done."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic 60-second demo capture orchestrator for llm-eval-harness."
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=2.0,
        help=(
            "Pause between stages so the screen recorder has cue points to cut on. "
            "Default 2.0; set to 0 for CI and tests."
        ),
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help=(
            "Skip launching the system browser on the drift HTML artifact. "
            "Required for CI; default is to open the report in the operator's "
            "default browser so the recording captures the rendered SVG."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "Where the stable artifact copy lands. Default: docs/demo-artifacts. "
            "The directory is created on first run and overwritten on re-runs; "
            "the path is what the operator's pre-positioned browser tab opens."
        ),
    )
    parser.add_argument(
        "--skip-sticky-cheatsheet",
        action="store_true",
        help=(
            "Suppress the STAGE 3 cheat-sheet (the operator-action checklist for "
            "the sticky-comment flow). Useful for CI; default is to print it."
        ),
    )
    args = parser.parse_args(argv)

    # Validate before any stage runs. The pre-fix `inf` crash fired inside
    # `_pause`, i.e. after STAGE 1 had already completed — a usage error that
    # costs the operator a partial capture. Checking here makes it free.
    if (msg := _validate_pause_seconds(args.pause_seconds)) is not None:
        return _fail(msg)

    output_dir: Path = args.output_dir
    # `mkdir` was bare: an `--output-dir` that is an existing file raised
    # FileExistsError, one under a file parent raised NotADirectoryError, and an
    # unwritable parent raised PermissionError — all as raw tracebacks at exit 1
    # (#198). Same write-seam translation as `cli._write_output` and the
    # `atomic_write_text` guard in `drift.cli`.
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return _fail(f"failed to create output directory {output_dir}: {e}")

    # STAGE 1 — regression runner + ASCII delta table.
    print(_banner(1, "Regression runner + diff (examples/regression_run_and_diff.py)"))
    rc1, out1 = _run_example_main("examples.regression_run_and_diff")
    print(out1, end="")
    if rc1 != 0:
        print(
            f"[capture] regression example exited {rc1}; aborting demo capture.",
            file=sys.stderr,
        )
        return rc1
    _pause(args.pause_seconds)

    # STAGE 2 — drift report, copied to a stable artifact path.
    print(_banner(2, "Drift report (examples/drift_report.py)"))
    rc2, out2 = _run_example_main("examples.drift_report")
    if rc2 != 0:
        print(out2, end="")
        print(
            f"[capture] drift example exited {rc2}; aborting demo capture.",
            file=sys.stderr,
        )
        return rc2

    src_html = _extract_html_path(out2)
    stable_html = output_dir / DRIFT_REPORT_FILENAME
    # The second, later write seam — a read-only `--output-dir` survives the
    # `mkdir` above (it already exists) and fails here instead, after *both*
    # hermetic examples have run. Bare, it surfaced as a raw PermissionError
    # traceback at exit 1 (#198).
    try:
        shutil.copy2(src_html, stable_html)
    except OSError as e:
        return _fail(f"failed to copy drift report to {stable_html}: {e}")
    # Replace the tempfile path in the captured stdout so the recording
    # shows the stable destination, not the random tempdir path. The
    # operator's browser tab is pre-positioned on the stable path.
    out2_stable = out2.replace(str(src_html), str(stable_html))
    print(out2_stable, end="")
    print(f"[capture] artifact copied to stable path: {stable_html}")
    if not args.no_open:
        webbrowser.open(stable_html.as_uri())
    _pause(args.pause_seconds)

    # STAGE 3 — sticky-comment cheat-sheet (operator-action, not scriptable).
    if not args.skip_sticky_cheatsheet:
        print(_banner(3, "Sticky-comment flow (#6) — operator cheat-sheet"))
        print(_sticky_comment_cheatsheet())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
