"""Usage / I/O contract for `scripts/capture_demo.py` (#198).

`tests/test_capture_demo_smoke.py` drives the script three times, always with
`--pause-seconds 0` and a writable tmp `--output-dir`, and always asserts
`rc == 0`. Every assertion there is on the happy path, which is why four
hostile-input seams sat unguarded: a `type=float` `--pause-seconds` with no
validation, a bare `output_dir.mkdir(...)`, and a bare `shutil.copy2(...)`.

The script is an entry point in its own right (`main(argv) -> int` under
`raise SystemExit(main())`), so it owes the same
`0 = clean / 1 = findings / 2 = I/O or usage error` contract every
`eval-harness` subcommand honors — the reason `drift.cli` places its guard in
the module rather than in `cli._run_drift`.

Each test is anchored to the *corruption*, not to an exception type: the `nan`
case asserts no pause was taken, and the pause-validation cases assert the
guard fires before STAGE 1 emits its banner. Anchoring on `pytest.raises(...)`
would keep passing if someone later widened a catch and let the silent path
back in.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from tests.test_capture_demo_smoke import _load_capture_module


def _drive(argv: list[str]) -> tuple[int, str]:
    """Run `capture_demo.main(argv)`, returning `(rc, stdout)`."""
    capture_demo = _load_capture_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = capture_demo.main(argv)
    return rc, buf.getvalue()


def _base_argv(output_dir: Path) -> list[str]:
    return [
        "--no-open",
        "--skip-sticky-cheatsheet",
        "--output-dir",
        str(output_dir),
    ]


# ----------------------------------------------------------------------
# --pause-seconds: `type=float` is not validation
# ----------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "-1", "-0.5"])
def test_non_finite_or_negative_pause_seconds_exits_2_before_stage_1(
    bad: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pre-fix, `inf` raised a raw OverflowError from `time.sleep` *after*
    STAGE 1 had already run, and `nan` / negatives silently took no pause and
    exited 0. Both are usage errors and both must cost the operator nothing."""
    # `--pause-seconds -1` is eaten by argparse as an unknown flag before the
    # guard ever sees it, so the `=` form is the only one that reaches the
    # validator for negative values. Use it uniformly.
    rc, out = _drive([f"--pause-seconds={bad}", *_base_argv(tmp_path)])

    assert rc == 2, f"--pause-seconds {bad} should be a usage error (exit 2); got {rc}"
    # The guard runs before any stage: no work was done and no artifact written.
    assert "STAGE 1" not in out, (
        f"--pause-seconds {bad} must be rejected before STAGE 1 runs; stdout:\n{out}"
    )
    assert not (tmp_path / "drift_report.html").exists(), (
        "a rejected --pause-seconds must not leave a partial capture behind"
    )

    err = capsys.readouterr().err
    assert "::error::" in err, f"expected a clean ::error:: line on stderr; got:\n{err}"
    assert "--pause-seconds" in err, f"the error must name the offending flag; got:\n{err}"


def test_nan_pause_seconds_took_no_pause_pre_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anchor on the corruption itself, independent of the exit code.

    `_pause` guards `if seconds > 0`, and `nan > 0` is False — so before the
    fix a `nan` produced a clean exit-0 run that never paused between stages.
    The inter-stage pauses are the script's only reason to exist ("cue points
    to cut on"), so that silent run yields an unusable recording. This test
    pins the mechanism directly: `_pause(nan)` calls `time.sleep` zero times,
    which is exactly why a `nan` cannot be allowed to reach it.
    """
    capture_demo = _load_capture_module()

    calls: list[float] = []
    monkeypatch.setattr(capture_demo.time, "sleep", lambda s: calls.append(s))

    capture_demo._pause(float("nan"))
    assert calls == [], "nan silently skips the pause — hence the parse-time guard"

    capture_demo._pause(0.25)
    assert calls == [0.25], "a valid pause must still reach time.sleep"


def test_validate_pause_seconds_rejects_bool() -> None:
    """`True` is an `int` subclass worth `1.0`, so an in-process driver calling
    `main` with a bool would otherwise get a one-second pause it never asked
    for. Same bool exclusion as `calibration.binarize` / `render_report`."""
    capture_demo = _load_capture_module()
    assert capture_demo._validate_pause_seconds(True) is not None
    assert capture_demo._validate_pause_seconds(False) is not None
    assert capture_demo._validate_pause_seconds(0) is None
    assert capture_demo._validate_pause_seconds(2.0) is None


# ----------------------------------------------------------------------
# --output-dir: the two bare write seams
# ----------------------------------------------------------------------


def test_output_dir_that_is_a_file_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bare `mkdir` raised FileExistsError as a raw traceback at exit 1."""
    target = tmp_path / "not_a_dir"
    target.write_text("", encoding="utf-8")

    rc, out = _drive(["--pause-seconds=0", *_base_argv(target)])

    assert rc == 2, f"an --output-dir that is a file should exit 2; got {rc}"
    assert "STAGE 1" not in out, "the mkdir guard must fire before STAGE 1 runs"
    err = capsys.readouterr().err
    assert "::error::" in err, f"expected a clean ::error:: line on stderr; got:\n{err}"
    assert str(target) in err, f"the error must name the offending path {target}; got:\n{err}"


def test_output_dir_under_a_file_parent_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bare `mkdir` raised NotADirectoryError as a raw traceback at exit 1."""
    parent = tmp_path / "file_parent"
    parent.write_text("", encoding="utf-8")
    target = parent / "sub"

    rc, _ = _drive(["--pause-seconds=0", *_base_argv(target)])

    assert rc == 2, f"an --output-dir under a file parent should exit 2; got {rc}"
    err = capsys.readouterr().err
    assert "::error::" in err, f"expected a clean ::error:: line on stderr; got:\n{err}"
    assert str(target) in err, f"the error must name the offending path {target}; got:\n{err}"


@pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX directory permissions; chmod is a no-op on Windows"
)
def test_read_only_output_dir_exits_2_at_the_copy_seam(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A read-only `--output-dir` already exists, so `mkdir(exist_ok=True)`
    succeeds and the failure lands on the *second* write seam,
    `shutil.copy2` — after both hermetic examples have already run. Bare, it
    surfaced as a raw PermissionError traceback at exit 1.
    """
    target = tmp_path / "readonly"
    target.mkdir()
    target.chmod(0o500)
    try:
        rc, out = _drive(["--pause-seconds=0", *_base_argv(target)])
    finally:
        target.chmod(0o700)

    assert rc == 2, f"a read-only --output-dir should exit 2; got {rc}"
    # This one genuinely gets past both stages — that's what makes it the
    # expensive seam, and why it needs its own guard rather than relying on
    # the mkdir check above.
    assert "STAGE 2" in out, (
        "the copy seam is reached only after both examples run; if STAGE 2 is "
        f"missing this test is no longer exercising that seam. stdout:\n{out}"
    )
    err = capsys.readouterr().err
    assert "::error::" in err, f"expected a clean ::error:: line on stderr; got:\n{err}"
    assert "drift_report.html" in err, (
        f"the error must name the artifact it failed to write; got:\n{err}"
    )


def test_valid_invocation_still_exits_0(tmp_path: Path) -> None:
    """The guards must not change any valid run — the smoke tests cover the
    output in detail, this just pins that adding them cost nothing."""
    rc, out = _drive(["--pause-seconds=0", *_base_argv(tmp_path)])
    assert rc == 0, f"a valid invocation must still exit 0; stdout:\n{out}"
    assert (tmp_path / "drift_report.html").exists()
