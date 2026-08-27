"""`_write_output` translated one of `atomic_write_text`'s two error classes (#217).

`_write_output` exists because "every `--out` write site called
`atomic_write_text` bare, so an unwritable `--out` escaped as a raw `OSError`
traceback at exit 1". It caught `OSError`. `atomic_write_text` raises exactly two
things, and `UnicodeEncodeError` is a `ValueError`, not an `OSError` -- so
content the target encoding cannot represent still escaped.

This is the same asymmetry `_run_validate` already names on the **read** side ("a
`ValueError` subclass, NOT an `OSError`, which the narrow catches above miss");
the write side never got the matching arm.

Driven through the real CLI, with no judge and no API key: `load_run_result_from_json`
reads the run-JSON artifact the Action uploads and downloads, and nothing on that
path checks representability. Measured before this change, on two pure-ASCII run
files whose `example_id` carries a lone surrogate::

    diff-json --format markdown --out o.md    -> exit 1, UnicodeEncodeError
    diff-json --format ascii    --out o.txt   -> exit 1, UnicodeEncodeError
    diff-json --format json     --out o.json  -> exit 1, clean

Two of three crashed, and the third exited 1 for the *legitimate* regression
reason -- so from CI the crash and the regression were the same signal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness.cli import main

LONE = chr(0xD800)


def _run_json(path: Path, *, example_ids: list[str], score: float) -> Path:
    payload = {
        "run_id": path.stem,
        "started_at": "2026-08-27T00:00:00Z",
        "suite": "s",
        "dataset_version": "v1",
        "judge_model": "m",
        "judge_kappa": 0.8,
        "mean_score": score,
        "n_rows": len(example_ids),
        "git_sha": None,
        "rows": [{"example_id": i, "score": score, "reasoning": "x"} for i in example_ids],
    }
    # `ensure_ascii=True` (the default): the file on disk is pure ASCII, the
    # surrogate is the six-character escape. Nothing about the bytes is malformed.
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def bad_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    ids = ["ok-1", f"bad-{LONE}-2"]
    cur = _run_json(tmp_path / "cur.json", example_ids=ids, score=0.4)
    base = _run_json(tmp_path / "base.json", example_ids=ids, score=0.9)
    assert cur.read_bytes().isascii()
    return cur, base, tmp_path


@pytest.mark.parametrize("fmt", ["markdown", "ascii"])
def test_unencodable_render_exits_2_with_one_line(
    bad_pair: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str], fmt: str
) -> None:
    cur, base, tmp_path = bad_pair
    out = tmp_path / f"out-{fmt}.txt"
    rc = main(
        [
            "diff-json",
            "--current",
            str(cur),
            "--baseline",
            str(base),
            "--format",
            fmt,
            "--out",
            str(out),
        ]
    )
    # 2 = I/O or usage error. 1 would be "regression found", which is exactly
    # what this input also legitimately is -- hence the whole point.
    assert rc == 2
    err = capsys.readouterr().err.strip()
    assert err.count("::error::") == 1
    assert err.splitlines()[0].startswith("::error::")
    assert "not encodable as UTF-8" in err
    assert "Traceback" not in err
    # The diagnostic must itself survive the encoding it is complaining about.
    err.encode("utf-8")
    assert LONE not in err
    assert not out.exists()


def test_json_format_still_exits_1_for_the_real_reason(
    bad_pair: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """`json.dumps` escapes the surrogate, so this format never had the defect and
    must not acquire a false one: mean 0.4 vs 0.9 IS a regression."""
    cur, base, tmp_path = bad_pair
    out = tmp_path / "out.json"
    rc = main(
        [
            "diff-json",
            "--current",
            str(cur),
            "--baseline",
            str(base),
            "--format",
            "json",
            "--out",
            str(out),
        ]
    )
    assert rc == 1
    assert "::error::" not in capsys.readouterr().err
    assert out.exists()
    assert out.read_bytes().isascii()


def test_encodable_output_is_untouched(tmp_path: Path) -> None:
    """Anti-vacuous the other way: the arm must not fire on ordinary content."""
    ids = ["ok-1", "ok-2"]
    cur = _run_json(tmp_path / "cur.json", example_ids=ids, score=0.9)
    base = _run_json(tmp_path / "base.json", example_ids=ids, score=0.9)
    out = tmp_path / "out.md"
    rc = main(
        [
            "diff-json",
            "--current",
            str(cur),
            "--baseline",
            str(base),
            "--format",
            "markdown",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    assert out.exists()


def test_oserror_arm_still_translates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The pre-existing arm keeps working -- the new `except` sits beside it, not
    in front of it."""
    ids = ["ok-1"]
    cur = _run_json(tmp_path / "cur.json", example_ids=ids, score=0.9)
    base = _run_json(tmp_path / "base.json", example_ids=ids, score=0.9)
    a_dir = tmp_path / "adir"
    a_dir.mkdir()
    rc = main(
        [
            "diff-json",
            "--current",
            str(cur),
            "--baseline",
            str(base),
            "--format",
            "markdown",
            "--out",
            str(a_dir),
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::failed to write" in err
    assert "not encodable" not in err
