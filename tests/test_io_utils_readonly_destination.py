"""A read-only existing destination is refused, by the writer and its pre-flight (#457).

`atomic_write_text` renames a temp file over the target. A rename swaps the
directory entry, so the target's own write bit was never consulted and a
``chmod 444`` file was silently rewritten, mode still 0444 -- while
`Path.write_text`, the call the helper replaced, raises ``PermissionError``.
The write seams (`_write_output`, `drift.cli`) document a read-only path as
``::error::`` + exit 2. Helper cases run both writers on the same layout, so
the lock is parity with `Path.write_text`. `check_writable` must refuse the
same file, or `run --out` / `calibrate --report` approve a path and then pay
a judge call per row before the write refuses it.

Root bypasses permission bits (`Path.write_text` succeeds too), so these skip
as root. GitHub's ubuntu runners run as the non-root ``runner`` user, so CI
exercises them. Port of prompt-regression-suite#318.
"""

from __future__ import annotations

import errno
import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import main
from eval_harness.io_utils import atomic_write_text, check_writable

pytestmark = [
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits"),
    pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses file permission bits, so a 0444 file stays writable",
    ),
]

ROOT = Path(__file__).resolve().parent.parent
CALIBRATION = ROOT / "fixtures" / "calibration.jsonl"
DATASET = ROOT / "fixtures" / "sample_factuality_v1.jsonl"


def _write(writer: str, path: Path, text: str) -> None:
    if writer == "atomic":
        atomic_write_text(path, text)
    elif writer == "check_writable":
        check_writable(path)
    else:
        path.write_text(text)


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def frozen(tmp_path: Path) -> Iterator[Path]:
    """A 0444 file holding ``old``; made writable again for tmp_path cleanup."""
    path = tmp_path / "r.json"
    path.write_text("old\n")
    path.chmod(0o444)
    yield path
    path.chmod(0o644)


@pytest.mark.parametrize("writer", ["atomic", "write_text", "check_writable"])
def test_readonly_file_is_refused(frozen: Path, writer: str) -> None:
    with pytest.raises(PermissionError) as excinfo:
        _write(writer, frozen, "new\n")
    assert excinfo.value.errno == errno.EACCES
    assert frozen.read_text() == "old\n"
    assert _mode(frozen) == 0o444


@pytest.mark.parametrize("writer", ["atomic", "check_writable"])
def test_refusal_leaves_no_temp_file(frozen: Path, writer: str) -> None:
    with pytest.raises(PermissionError):
        _write(writer, frozen, "new\n")
    assert sorted(p.name for p in frozen.parent.iterdir()) == ["r.json"]


@pytest.mark.parametrize("writer", ["atomic", "write_text", "check_writable"])
def test_readonly_file_behind_a_symlink_is_refused(tmp_path: Path, writer: str) -> None:
    # The check runs on the RESOLVED file (#327): a writable link name over a
    # read-only file must not get through.
    real = tmp_path / "real.md"
    real.write_text("old\n")
    real.chmod(0o444)
    link = tmp_path / "link.md"
    link.symlink_to(real)
    try:
        with pytest.raises(PermissionError):
            _write(writer, link, "new\n")
        assert real.read_text() == "old\n"
        assert link.is_symlink()
    finally:
        real.chmod(0o644)


@pytest.mark.parametrize("writer", ["atomic", "write_text"])
def test_writable_and_missing_targets_still_write(tmp_path: Path, writer: str) -> None:
    # Controls: the refusal is scoped to an existing unwritable file.
    owner_only = tmp_path / "owner.md"
    owner_only.write_text("old\n")
    owner_only.chmod(0o600)
    check_writable(owner_only)
    _write(writer, owner_only, "new\n")
    assert owner_only.read_text() == "new\n"
    assert _mode(owner_only) == 0o600

    missing = tmp_path / "new.md"
    check_writable(missing)
    _write(writer, missing, "fresh\n")
    assert missing.read_text() == "fresh\n"


# --- CLI write seams ---------------------------------------------------------


class _CountingBackend:
    calls = 0

    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake"

    def complete(self, system: str, user: str) -> str:
        type(self).calls += 1
        return "SCORE: 1.0\nREASONING: ok\n"


def test_run_out_on_a_readonly_file_exits_2_before_any_judge_call(
    frozen: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _CountingBackend.calls = 0
    with patch("eval_harness.cli.AnthropicBackend", _CountingBackend):
        rc = main(
            [
                *["run", "--suite", "s", "--dataset", str(DATASET)],
                *["--db", str(tmp_path / "runs.db"), "--no-diff", "--out", str(frozen)],
            ]
        )
    assert rc == 2
    assert _CountingBackend.calls == 0
    assert f"failed to write {frozen}" in capsys.readouterr().err
    assert frozen.read_text() == "old\n"


def test_calibrate_report_on_a_readonly_file_exits_2_before_any_judge_call(
    frozen: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _CountingBackend.calls = 0
    with patch("eval_harness.cli.AnthropicBackend", _CountingBackend):
        rc = main(["calibrate", "--calibration", str(CALIBRATION), "--report", str(frozen)])
    assert rc == 2
    assert _CountingBackend.calls == 0
    assert f"failed to write {frozen}" in capsys.readouterr().err
    assert frozen.read_text() == "old\n"


def test_validate_out_on_a_readonly_file_exits_2(
    frozen: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["validate", str(DATASET), "--out", str(frozen)])
    err = capsys.readouterr().err
    assert rc == 2
    assert f"failed to write {frozen}" in err
    assert "Traceback" not in err
    assert frozen.read_text() == "old\n"


def test_drift_output_on_a_readonly_file_exits_2(
    frozen: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = tmp_path / "in.jsonl"
    inputs.write_text('"a quick brown fox"\n"the lazy dog sleeps here"\n', encoding="utf-8")
    rc = main(
        [
            *["drift", "--golden", str(inputs), "--candidate", str(inputs)],
            *["--output", str(frozen), "--judge-stub"],
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert f"failed to write {frozen}" in err
    assert frozen.read_text() == "old\n"
