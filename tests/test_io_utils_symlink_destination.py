"""`atomic_write_text` writes THROUGH a symlinked destination (#327).

`os.replace` renames onto the link itself. A symlinked `--out` used to become a
regular file, and the file it pointed at kept its old contents.
`Path.write_text`, which this helper replaced and whose file-mode behaviour
#274 restored, writes through the link. Each write-through case runs
`Path.write_text` on an identical layout as well, so the lock checks parity
with it instead of a hand-written expectation. Sibling of
python-async-llm-pipelines#157.

`check_writable` (#287) has to resolve the link the same way, or the preflight
tries a different directory from the one the real write uses.
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

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation needs privileges on Windows"
)

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "fixtures" / "sample_factuality_v1.jsonl"

needs_permissions = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions"
)


def _layout(root: Path, *, absolute: bool, name: str = "out.md") -> tuple[Path, Path]:
    real_dir = root / "real"
    real_dir.mkdir(parents=True)
    real = real_dir / name
    real.write_text("old\n")
    real.chmod(0o640)
    link = root / "link.md"
    link.symlink_to(real if absolute else Path("real") / name)
    return link, real


@pytest.mark.parametrize("absolute", [False, True], ids=["relative-link", "absolute-link"])
@pytest.mark.parametrize("writer", ["atomic", "write_text"])
def test_write_goes_through_the_link(tmp_path: Path, absolute: bool, writer: str) -> None:
    link, real = _layout(tmp_path, absolute=absolute)
    if writer == "atomic":
        atomic_write_text(link, "new\n")
    else:
        link.write_text("new\n")
    assert link.is_symlink(), "the link was replaced by a regular file"
    assert real.read_text() == "new\n", "the linked file kept its old contents"
    assert link.read_text() == "new\n"
    # The linked file's mode is kept (#274), on the file that was written.
    assert stat.S_IMODE(os.stat(real).st_mode) == 0o640
    # No temp file left behind beside the link or beside the linked file.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["link.md", "real"]
    assert sorted(p.name for p in real.parent.iterdir()) == ["out.md"]


@pytest.mark.parametrize("writer", ["atomic", "write_text"])
def test_dangling_link_creates_its_target(tmp_path: Path, writer: str) -> None:
    (tmp_path / "real").mkdir()
    real = tmp_path / "real" / "new.md"
    link = tmp_path / "link.md"
    link.symlink_to(Path("real") / "new.md")
    if writer == "atomic":
        atomic_write_text(link, "fresh\n")
    else:
        link.write_text("fresh\n")
    assert link.is_symlink()
    assert real.read_text() == "fresh\n"


@pytest.mark.parametrize("call", ["atomic", "check_writable"])
def test_link_loop_raises_eloop_and_leaves_no_temp(tmp_path: Path, call: str) -> None:
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.symlink_to("b.md")
    b.symlink_to("a.md")
    fn = (lambda: atomic_write_text(a, "x\n")) if call == "atomic" else (lambda: check_writable(a))
    with pytest.raises(OSError, match="symbolic links") as exc:
        fn()
    assert exc.value.errno == errno.ELOOP
    assert a.is_symlink()
    assert b.is_symlink()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.md", "b.md"]


def test_long_linked_name_still_gets_a_capped_temp_name(tmp_path: Path) -> None:
    """The temp name is built from the RESOLVED basename, so the NAME_MAX cap applies to it."""
    link, real = _layout(tmp_path, absolute=False, name="r" * 250 + ".md")
    atomic_write_text(link, "new\n")
    assert link.is_symlink()
    assert real.read_text() == "new\n"


def test_plain_destination_is_unchanged_behaviour(tmp_path: Path) -> None:
    dest = tmp_path / "plain.md"
    dest.write_text("old\n")
    dest.chmod(0o640)
    atomic_write_text(dest, "new\n")
    check_writable(dest)
    assert not dest.is_symlink()
    assert dest.read_text() == "new\n"
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o640
    assert sorted(p.name for p in tmp_path.iterdir()) == ["plain.md"]


def test_validate_out_through_a_link_updates_the_linked_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end: `validate --out link.md` updates the file the link names."""
    link, real = _layout(tmp_path, absolute=False)
    assert main(["validate", str(DATASET), "--out", str(link)]) == 0
    capsys.readouterr()
    assert link.is_symlink()
    assert real.read_text() != "old\n"
    assert stat.S_IMODE(os.stat(real).st_mode) == 0o640


@pytest.fixture
def link_into_readonly_dir(tmp_path: Path) -> Iterator[Path]:
    """A link in a WRITABLE directory whose target sits in a read-only one."""
    ro = tmp_path / "ro"
    ro.mkdir()
    (ro / "run.json").write_text("{}\n")
    ro.chmod(0o555)
    link = tmp_path / "run.json"
    link.symlink_to(Path("ro") / "run.json")
    try:
        yield link
    finally:
        ro.chmod(0o755)


class _CountingBackend:
    calls = 0

    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake"

    def complete(self, system: str, user: str) -> str:
        type(self).calls += 1
        return "SCORE: 1.0\nREASONING: ok\n"


@needs_permissions
def test_preflight_agrees_with_the_writer_on_a_link_into_a_readonly_dir(
    link_into_readonly_dir: Path,
) -> None:
    link = link_into_readonly_dir
    with pytest.raises(PermissionError):
        atomic_write_text(link, "x\n")
    with pytest.raises(PermissionError):
        check_writable(link)
    assert link.is_symlink()


@needs_permissions
def test_run_out_link_into_readonly_dir_is_refused_before_any_judge_call(
    link_into_readonly_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _CountingBackend.calls = 0
    with patch("eval_harness.cli.AnthropicBackend", _CountingBackend):
        rc = main(
            [
                "run",
                "--suite",
                "s",
                "--dataset",
                str(DATASET),
                "--db",
                str(tmp_path / "h.db"),
                "--no-diff",
                "--out",
                str(link_into_readonly_dir),
            ]
        )
    err = capsys.readouterr().err
    assert rc == 2
    assert _CountingBackend.calls == 0, "the judge was paid before the write failed"
    assert "failed to write" in err
    assert link_into_readonly_dir.is_symlink()
