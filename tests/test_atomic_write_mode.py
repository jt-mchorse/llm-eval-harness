"""File-mode contract for `atomic_write_text` (#274, portfolio-ops#81).

The helper used to create its temp file with `tempfile.NamedTemporaryFile`,
which always creates 0600, and `os.replace` carried that mode onto the target.
Measured on main with umask 022: a new file came out 0600 and an existing 0644
file was demoted to 0600 by an overwrite. `Path.write_text`, which the helper
replaced, gives `0o666 & ~umask` for a new file and leaves an existing file's
mode alone. These tests pin that behaviour:

- a new file honours the umask (022 -> 0644, and 077 -> 0600, which proves the
  umask is applied rather than a hard-coded 0644);
- an overwrite keeps the target's existing mode (0644, 0600 and 0640);
- the same holds through the NAME_MAX-capped temp-name path, through a
  non-default `encoding`, and through a real caller (`Dataset.dump_jsonl`).
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from eval_harness import io_utils as io_utils_mod
from eval_harness.dataset import load_jsonl
from eval_harness.io_utils import atomic_write_text

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="POSIX permission bits and umask semantics"
)

SetUmask = Callable[[int], None]


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def umask() -> Iterator[SetUmask]:
    """Set the process umask for one test and restore the previous one."""
    saved = os.umask(0o022)
    os.umask(saved)

    def _set(value: int) -> None:
        os.umask(value)

    try:
        yield _set
    finally:
        os.umask(saved)


def _no_temp_left(directory: Path) -> None:
    leftovers = [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_new_file_honours_umask_022(tmp_path: Path, umask: SetUmask) -> None:
    umask(0o022)
    out = tmp_path / "run.json"
    atomic_write_text(out, "{}")
    assert _mode(out) == 0o644
    _no_temp_left(tmp_path)


def test_new_file_honours_umask_077(tmp_path: Path, umask: SetUmask) -> None:
    """077 must give 0600: a hard-coded 0644 would pass the 022 test above."""
    umask(0o077)
    out = tmp_path / "run.json"
    atomic_write_text(out, "{}")
    assert _mode(out) == 0o600


def test_new_file_matches_write_text(tmp_path: Path, umask: SetUmask) -> None:
    """The mode is the one `Path.write_text` gives under the same umask."""
    umask(0o027)
    reference = tmp_path / "reference.txt"
    reference.write_text("x", encoding="utf-8")
    out = tmp_path / "atomic.txt"
    atomic_write_text(out, "x")
    assert _mode(out) == _mode(reference) == 0o640


@pytest.mark.parametrize("existing", [0o644, 0o600, 0o640])
def test_overwrite_keeps_existing_mode(tmp_path: Path, umask: SetUmask, existing: int) -> None:
    umask(0o022)
    out = tmp_path / "run.json"
    out.write_text("old", encoding="utf-8")
    out.chmod(existing)
    atomic_write_text(out, "new")
    assert out.read_text(encoding="utf-8") == "new"
    assert _mode(out) == existing
    _no_temp_left(tmp_path)


def test_overwrite_keeps_mode_through_capped_temp_name(tmp_path: Path, umask: SetUmask) -> None:
    """A basename near NAME_MAX takes the `_cap_base_for_temp` branch."""
    umask(0o022)
    out = tmp_path / ("a" * 250)
    out.write_text("old", encoding="utf-8")
    out.chmod(0o640)
    atomic_write_text(out, "new")
    assert out.read_text(encoding="utf-8") == "new"
    assert _mode(out) == 0o640


def test_non_default_encoding_keeps_mode(tmp_path: Path, umask: SetUmask) -> None:
    umask(0o022)
    out = tmp_path / "latin.txt"
    atomic_write_text(out, "café", encoding="latin-1")
    assert out.read_bytes() == "café".encode("latin-1")
    assert _mode(out) == 0o644


def test_unknown_encoding_leaves_no_temp(tmp_path: Path, umask: SetUmask) -> None:
    """A bad `encoding` fails as before (LookupError) without leaking the temp."""
    umask(0o022)
    with pytest.raises(LookupError):
        atomic_write_text(tmp_path / "x.txt", "x", encoding="no-such-codec")
    assert list(tmp_path.iterdir()) == []


def test_helper_does_not_touch_the_process_umask(
    tmp_path: Path, umask: SetUmask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading the umask needs `os.umask(0)`, which is process-global; the
    kernel applies it for us when the temp is opened with 0o666."""
    umask(0o022)

    def forbidden(_mask: int) -> int:
        raise AssertionError("atomic_write_text must not call os.umask")

    monkeypatch.setattr(io_utils_mod.os, "umask", forbidden)
    out = tmp_path / "run.json"
    atomic_write_text(out, "{}")
    assert _mode(out) == 0o644


def test_dataset_dump_jsonl_keeps_mode(tmp_path: Path, umask: SetUmask) -> None:
    """Real caller: a new golden file is 0644 under 022; an overwrite keeps 0640."""
    umask(0o022)
    src = tmp_path / "src.jsonl"
    src.write_text(
        json.dumps(
            {
                "dataset_version": "v1",
                "expected_outputs": [{"kind": "exact", "value": "2"}],
                "id": "qa_001",
                "input": "What is 1+1?",
                "provenance": {"source": "synthetic"},
                "tags": ["math"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ds = load_jsonl(src)
    out = tmp_path / "golden.jsonl"
    ds.dump_jsonl(out)
    assert _mode(out) == 0o644
    out.chmod(0o640)
    ds.dump_jsonl(out)
    assert _mode(out) == 0o640
