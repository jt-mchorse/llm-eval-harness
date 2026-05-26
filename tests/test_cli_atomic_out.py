"""Atomicity contract for `eval-harness --out` writes (issue #48).

`Path.write_text` is not atomic: SIGINT/SIGTERM/disk-full/OOM between
the implicit `open(..., "w")` truncate and `close()` flush leaves the
destination zero-length or partial. Downstream `diff-json` / `comment`
then parse a half-written JSON and either crash with a cryptic
`json.JSONDecodeError` or, in the GitHub Action workflow (D-006), post
a corrupt sticky comment.

The fix routes all four CLI write sites — `run --out`,
`diff --out`, `diff-json --out`, `list --out` — through
`_atomic_write_text`, which writes to a sibling temp file in the same
directory, `fsync`s, then `os.replace`s. The temp's same-directory
placement is load-bearing: it guarantees same filesystem so the rename
can't fall back to a copy.

What this file pins:

- The helper itself: happy path, overwrite, parent-dir creation, plus
  the two invariants — destination unchanged when `os.replace` raises,
  no leftover `.tmp` siblings after failure.
- Integration through the CLI: each subcommand's `--out` survives a
  simulated `os.replace` failure without ever touching the destination,
  proving the four call sites all route through the helper.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness import cli as cli_mod
from eval_harness.cli import _atomic_write_text, main

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATASET = Path("fixtures/sample_factuality_v1.jsonl")


# ---------------------------------------------------------------------------
# Unit tests on the helper itself.
# ---------------------------------------------------------------------------


def test_atomic_write_text_happy_path(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    _atomic_write_text(out, "hello\nworld\n")
    assert out.read_text(encoding="utf-8") == "hello\nworld\n"


def test_atomic_write_text_creates_parent_dirs(tmp_path: Path) -> None:
    out = tmp_path / "deep" / "nested" / "x.json"
    assert not out.parent.exists()
    _atomic_write_text(out, "{}")
    assert out.read_text(encoding="utf-8") == "{}"


def test_atomic_write_text_overwrites_existing_file(tmp_path: Path) -> None:
    """Existing destination with stale content is replaced wholly — never appended."""
    out = tmp_path / "out.txt"
    out.write_text("STALE-CONTENT-MUST-NOT-SURVIVE", encoding="utf-8")
    _atomic_write_text(out, "fresh")
    body = out.read_text(encoding="utf-8")
    assert body == "fresh"
    assert "STALE" not in body


def test_atomic_write_text_replace_failure_leaves_destination_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Load-bearing atomicity invariant.

    If `os.replace` raises (simulating an `EXDEV` cross-device error,
    a SIGINT delivered between fsync and rename, or any
    `PermissionError`), the destination must not exist. The helper must
    never touch the destination directly — only via the atomic rename.
    """
    out = tmp_path / "result.json"

    def boom(*_args, **_kwargs):
        raise OSError("simulated mid-rename failure")

    monkeypatch.setattr(cli_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated mid-rename failure"):
        _atomic_write_text(out, '{"k": "v"}')

    assert not out.exists(), "destination must remain absent when os.replace fails"


def test_atomic_write_text_replace_failure_cleans_up_tmp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No leftover `.tmp` siblings after a failed atomic write.

    The temp file lives in the destination's parent directory so the
    rename is same-filesystem; on rename failure the helper must
    unlink it. Otherwise a long-running CI workflow accumulates
    `.<name>.<token>.tmp` litter alongside legitimate artifacts.
    """
    out = tmp_path / "artifacts" / "delta.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    def boom(*_args, **_kwargs):
        raise OSError("simulated mid-rename failure")

    monkeypatch.setattr(cli_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated mid-rename failure"):
        _atomic_write_text(out, '{"k": "v"}')

    siblings = list(out.parent.iterdir())
    assert siblings == [], f"expected no temp leftovers in {out.parent}, got {siblings}"


def test_atomic_write_text_destination_unchanged_when_overwriting_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When overwriting an existing file, a failed `os.replace` must
    leave the pre-existing destination contents intact — not zero-length,
    not partial, not the new content. This is the property the broken
    `Path.write_text` implementation can never offer.
    """
    out = tmp_path / "existing.json"
    out.write_text('{"keep": true}', encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("simulated")

    monkeypatch.setattr(cli_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated"):
        _atomic_write_text(out, '{"overwrite": true}')

    assert out.read_text(encoding="utf-8") == '{"keep": true}'


# ---------------------------------------------------------------------------
# Integration: each `--out` CLI surface routes through `_atomic_write_text`.
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
    `_atomic_write_text`.
    """
    db = tmp_path / "runs.db"
    out = tmp_path / "result.json"

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(cli_mod.os, "replace", boom)

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
    Verifies cli.py:_run_diff is wired through `_atomic_write_text`.
    """
    db = tmp_path / "runs.db"
    baseline_id, current_id = _seed_two_runs(db)
    out = tmp_path / "delta.md"

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(cli_mod.os, "replace", boom)
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

    monkeypatch.setattr(cli_mod.os, "replace", boom)
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

    monkeypatch.setattr(cli_mod.os, "replace", boom)
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
