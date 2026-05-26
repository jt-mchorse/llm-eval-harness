"""Atomicity contract for `eval-harness --out` CLI writes (issue #48).

`Path.write_text` is not atomic: SIGINT/SIGTERM/disk-full/OOM between
the implicit `open(..., "w")` truncate and `close()` flush leaves the
destination zero-length or partial. Downstream `diff-json` / `comment`
then parse a half-written JSON and either crash with a cryptic
`json.JSONDecodeError` or, in the GitHub Action workflow (D-006), post
a corrupt sticky comment.

The fix routes all four CLI write sites — `run --out`,
`diff --out`, `diff-json --out`, `list --out` — through
`atomic_write_text` (now public in `eval_harness.io_utils` per issue #50;
was private `_atomic_write_text` in `cli.py` per issue #48).

What this file pins:

- Integration through the CLI: each subcommand's `--out` survives a
  simulated `os.replace` failure without ever touching the destination,
  proving the four call sites all route through the helper.

Unit tests on the helper itself live next to the helper in
`tests/test_io_utils_atomic_write.py` (moved there when the helper was
promoted to a package-level public symbol in issue #50).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness import io_utils as io_utils_mod
from eval_harness.cli import main

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATASET = Path("fixtures/sample_factuality_v1.jsonl")


# ---------------------------------------------------------------------------
# Integration: each `--out` CLI surface routes through atomic_write_text.
#
# Pattern mirrors `tests/test_cli_diff_format.py` — swap `AnthropicBackend`
# for a deterministic stub so the suite stays hermetic.
# ---------------------------------------------------------------------------


class _HighBackend:
    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake"
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        return "SCORE: 1.0\nREASONING: high\n"


class _LowBackend:
    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake"
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        return "SCORE: 0.5\nREASONING: low\n"


@pytest.fixture(autouse=True)
def _at_repo_root(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(ROOT)


def _seed_two_runs(db: Path) -> tuple[str, str]:
    with patch("eval_harness.cli.AnthropicBackend", _HighBackend):
        rc = main(
            [
                "run",
                "--suite",
                "smoke",
                "--dataset",
                str(SAMPLE_DATASET),
                "--db",
                str(db),
                "--no-diff",
            ]
        )
    assert rc == 0
    with patch("eval_harness.cli.AnthropicBackend", _LowBackend):
        rc = main(
            [
                "run",
                "--suite",
                "smoke",
                "--dataset",
                str(SAMPLE_DATASET),
                "--db",
                str(db),
                "--no-diff",
            ]
        )
    assert rc == 0
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT run_id FROM runs WHERE suite = 'smoke' ORDER BY started_at ASC;"
        ).fetchall()
    finally:
        conn.close()
    return rows[0][0], rows[1][0]


def test_run_out_routes_through_atomic_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`eval-harness run --out` must not touch the destination on
    `os.replace` failure. Verifies cli.py:_run_run is wired through
    `atomic_write_text`.
    """
    db = tmp_path / "runs.db"
    out = tmp_path / "result.json"

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(io_utils_mod.os, "replace", boom)

    with (
        patch("eval_harness.cli.AnthropicBackend", _HighBackend),
        pytest.raises(OSError, match="simulated rename failure"),
    ):
        main(
            [
                "run",
                "--suite",
                "smoke",
                "--dataset",
                str(SAMPLE_DATASET),
                "--db",
                str(db),
                "--out",
                str(out),
                "--no-diff",
            ]
        )

    assert not out.exists(), "run --out must not write destination when replace fails"


def test_diff_out_routes_through_atomic_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`eval-harness diff --out` must route through the atomic helper.
    Verifies cli.py:_run_diff is wired through `atomic_write_text`.
    """
    db = tmp_path / "runs.db"
    baseline_id, current_id = _seed_two_runs(db)
    out = tmp_path / "delta.md"

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(io_utils_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated rename failure"):
        main(
            [
                "diff",
                "--current",
                current_id,
                "--baseline",
                baseline_id,
                "--db",
                str(db),
                "--format",
                "markdown",
                "--out",
                str(out),
            ]
        )

    assert not out.exists()


def test_diff_json_out_routes_through_atomic_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`eval-harness diff-json --out` must route through the atomic helper.

    This is the single most blast-radius-y surface: the GitHub Action
    (D-006) pipes `run --out` → `diff-json --out` → `comment`. A
    half-written delta JSON from `diff-json` lands in the next step's
    parser and corrupts the sticky PR comment.
    """
    db = tmp_path / "runs.db"
    _seed_two_runs(db)
    # Seed two JSON run files via `run --out` (with replace working), then
    # exercise diff-json --out under the failing replace.
    current_json = tmp_path / "current.json"
    baseline_json = tmp_path / "baseline.json"
    with patch("eval_harness.cli.AnthropicBackend", _HighBackend):
        rc = main(
            [
                "run",
                "--suite",
                "smoke",
                "--dataset",
                str(SAMPLE_DATASET),
                "--db",
                str(tmp_path / "db2.db"),
                "--out",
                str(baseline_json),
                "--no-diff",
            ]
        )
    assert rc == 0
    with patch("eval_harness.cli.AnthropicBackend", _LowBackend):
        rc = main(
            [
                "run",
                "--suite",
                "smoke",
                "--dataset",
                str(SAMPLE_DATASET),
                "--db",
                str(tmp_path / "db3.db"),
                "--out",
                str(current_json),
                "--no-diff",
            ]
        )
    assert rc == 0

    delta_out = tmp_path / "delta.json"

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(io_utils_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated rename failure"):
        main(
            [
                "diff-json",
                "--current",
                str(current_json),
                "--baseline",
                str(baseline_json),
                "--format",
                "json",
                "--out",
                str(delta_out),
            ]
        )

    assert not delta_out.exists()


def test_list_out_routes_through_atomic_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`eval-harness list --out` must route through the atomic helper.

    `list --out` reaches the helper via `_emit_list_output`. Both the
    populated-DB path and the empty-DB short-circuit path call the
    helper; we cover the populated branch here because it exercises
    actual content.
    """
    db = tmp_path / "runs.db"
    _seed_two_runs(db)
    out = tmp_path / "runs.json"

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(io_utils_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated rename failure"):
        main(["list", "--db", str(db), "--json", "--out", str(out)])

    assert not out.exists()


def test_all_subcommands_produce_valid_atomic_output(tmp_path: Path) -> None:
    """End-to-end happy path: each of the four `--out` surfaces produces a
    complete file with valid content. Pins that the helper integration
    didn't regress the existing rendering contracts.
    """
    db = tmp_path / "runs.db"
    baseline_id, current_id = _seed_two_runs(db)

    # `run --out`: emit a fresh run JSON.
    run_out = tmp_path / "fresh_run.json"
    with patch("eval_harness.cli.AnthropicBackend", _HighBackend):
        rc = main(
            [
                "run",
                "--suite",
                "smoke",
                "--dataset",
                str(SAMPLE_DATASET),
                "--db",
                str(tmp_path / "extra.db"),
                "--out",
                str(run_out),
                "--no-diff",
            ]
        )
    assert rc == 0
    run_parsed = json.loads(run_out.read_text(encoding="utf-8"))
    assert "run_id" in run_parsed
    assert run_parsed["suite"] == "smoke"

    # `diff --out` markdown.
    diff_out = tmp_path / "delta.md"
    rc = main(
        [
            "diff",
            "--current",
            current_id,
            "--baseline",
            baseline_id,
            "--db",
            str(db),
            "--format",
            "markdown",
            "--out",
            str(diff_out),
        ]
    )
    # rc==1 because the seeded runs include a regression; that's expected.
    assert rc == 1
    md_body = diff_out.read_text(encoding="utf-8")
    table_lines = [line for line in md_body.splitlines() if line.startswith("| ")]
    assert table_lines, f"diff markdown should contain a GFM table, got:\n{md_body}"

    # `diff-json --out` json.
    delta_json_out = tmp_path / "delta.json"
    rc = main(
        [
            "diff-json",
            "--current",
            str(run_out),
            "--baseline",
            str(run_out),
            "--format",
            "json",
            "--out",
            str(delta_json_out),
        ]
    )
    assert rc == 0  # current == baseline → no regressions
    parsed = json.loads(delta_json_out.read_text(encoding="utf-8"))
    assert "summary" in parsed
    assert "rows" in parsed

    # `list --out` json.
    list_out = tmp_path / "runs.json"
    rc = main(["list", "--db", str(db), "--json", "--out", str(list_out)])
    assert rc == 0
    list_parsed = json.loads(list_out.read_text(encoding="utf-8"))
    assert isinstance(list_parsed, list)
    assert len(list_parsed) == 2
