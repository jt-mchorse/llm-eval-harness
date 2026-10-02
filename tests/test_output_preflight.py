"""`calibrate --report` and `run --out` are checked before any judge call (#287).

#276/#282 moved `run`'s `--db` check ahead of the paid loop. The outputs
written after it were not: measured, `calibrate --report` into a read-only
directory paid all 50 judge calls and then failed at the write, and `run --out`
paid for every row before exiting 2.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import main
from eval_harness.io_utils import check_writable

ROOT = Path(__file__).resolve().parent.parent
CALIBRATION = ROOT / "fixtures" / "calibration.jsonl"
DATASET = ROOT / "fixtures" / "sample_factuality_v1.jsonl"


class _CountingBackend:
    calls = 0

    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake"

    def complete(self, system: str, user: str) -> str:
        type(self).calls += 1
        return "SCORE: 1.0\nREASONING: ok\n"


@pytest.fixture
def readonly_dir(tmp_path: Path) -> Iterator[Path]:
    d = tmp_path / "ro"
    d.mkdir()
    d.chmod(0o555)
    try:
        yield d
    finally:
        d.chmod(0o755)


needs_permissions = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions"
)


def _calibrate(report: Path) -> int:
    _CountingBackend.calls = 0
    with patch("eval_harness.cli.AnthropicBackend", _CountingBackend):
        return main(["calibrate", "--calibration", str(CALIBRATION), "--report", str(report)])


def _run(out: Path, db: Path) -> int:
    _CountingBackend.calls = 0
    with patch("eval_harness.cli.AnthropicBackend", _CountingBackend):
        return main(
            [
                "run",
                "--suite",
                "s",
                "--dataset",
                str(DATASET),
                "--db",
                str(db),
                "--no-diff",
                "--out",
                str(out),
            ]
        )


@needs_permissions
def test_calibrate_refuses_an_unwritable_report_before_any_judge_call(
    readonly_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _calibrate(readonly_dir / "report.md") == 2
    assert _CountingBackend.calls == 0
    assert "failed to write" in capsys.readouterr().err


@needs_permissions
def test_run_refuses_an_unwritable_out_before_any_judge_call(
    readonly_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(readonly_dir / "result.json", tmp_path / "runs.db") == 2
    assert _CountingBackend.calls == 0
    assert "failed to write" in capsys.readouterr().err


def test_a_directory_target_is_refused_before_any_judge_call(tmp_path: Path) -> None:
    target = tmp_path / "already-a-dir"
    target.mkdir()
    assert _calibrate(target) == 2
    assert _CountingBackend.calls == 0
    assert _run(target, tmp_path / "runs.db") == 2
    assert _CountingBackend.calls == 0


def test_a_writable_path_with_a_missing_parent_still_works_and_leaves_no_probe(
    tmp_path: Path,
) -> None:
    report = tmp_path / "new" / "dir" / "report.md"
    assert _calibrate(report) in (0, 1)  # 1 is the kappa gate, not an I/O failure
    assert _CountingBackend.calls == 50
    assert sorted(p.name for p in report.parent.iterdir()) == ["report.md"]


def test_check_writable_leaves_nothing_behind(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "x.json"
    check_writable(target)
    assert list(target.parent.iterdir()) == []
    target.write_text("existing")
    check_writable(target)  # an existing file is replaceable
    assert target.read_text() == "existing"
