"""End-to-end CLI tests for `eval-harness diff --format` and `--out`.

`diff` (SQLite-backed) was missing `--format markdown` and `--out`, both of
which `diff-json` already had. These tests pin the parity: the SQLite path
must render through the same `render_delta_markdown` and write through the
same parent-dir-creating `--out` plumbing as `diff-json`.

Pattern mirrors `tests/test_cli_run.py` — `_run_cli` swaps `AnthropicBackend`
for a deterministic stub so the suite runs hermetically.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import main

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATASET = Path("fixtures/sample_factuality_v1.jsonl")


class _HighBackend:
    """Scores every prompt 1.0 — the baseline."""

    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake"
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        return "SCORE: 1.0\nREASONING: high\n"


class _LowBackend:
    """Scores every prompt 0.5 — drop > threshold, every row flagged."""

    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake"
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        return "SCORE: 0.5\nREASONING: low\n"


@pytest.fixture(autouse=True)
def _at_repo_root(monkeypatch):
    monkeypatch.chdir(ROOT)


def _seed_two_runs(db: Path) -> tuple[str, str]:
    """Run baseline (high) then current (low); return (baseline_id, current_id)."""
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
        # `--no-diff` so this run's auto-diff doesn't shape the test fixtures.
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
    assert len(rows) == 2, f"expected two seeded runs, got {len(rows)}"
    return rows[0][0], rows[1][0]


def test_diff_format_ascii_default(tmp_path: Path, capsys) -> None:
    db = tmp_path / "runs.db"
    baseline_id, current_id = _seed_two_runs(db)
    capsys.readouterr()  # drain run output

    rc = main(
        [
            "diff",
            "--current",
            current_id,
            "--baseline",
            baseline_id,
            "--db",
            str(db),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1, "regression should flag and exit nonzero"
    # ASCII renderer's header line uses dashes / vertical bars in a tabular layout.
    assert "FLAG" in captured.out
    # Not the markdown format — no leading `| ` header convention.
    assert not captured.out.lstrip().startswith("|")


def test_diff_format_json_parses_back_to_delta_report(tmp_path: Path, capsys) -> None:
    db = tmp_path / "runs.db"
    baseline_id, current_id = _seed_two_runs(db)
    capsys.readouterr()

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
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    payload = json.loads(captured.out)
    # Same shape `diff-json --format json` emits; smoke-check the load-bearing keys.
    assert "rows" in payload
    assert "summary" in payload
    assert payload["summary"]["n_flagged"] >= 1
    assert all({"example_id", "status"} <= set(row) for row in payload["rows"])


def test_diff_format_markdown_renders_table_header(tmp_path: Path, capsys) -> None:
    db = tmp_path / "runs.db"
    baseline_id, current_id = _seed_two_runs(db)
    capsys.readouterr()

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
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    # The markdown renderer used by `diff-json` and `comment` writes a
    # GFM-style table whose row lines start with `| ` — that's the parity
    # signal worth pinning. Don't pin the exact column count; that's the
    # renderer's contract, not this CLI's.
    table_lines = [line for line in captured.out.splitlines() if line.startswith("| ")]
    assert table_lines, f"expected at least one markdown table row, got:\n{captured.out}"


def test_diff_out_writes_to_nested_path(tmp_path: Path, capsys) -> None:
    db = tmp_path / "runs.db"
    baseline_id, current_id = _seed_two_runs(db)
    capsys.readouterr()

    out_path = tmp_path / "nested" / "subdir" / "delta.md"
    assert not out_path.parent.exists(), "precondition: parent dirs should not exist yet"

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
            str(out_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == "", "with --out, nothing should be written to stdout"
    assert out_path.exists(), "--out should create parent dirs and write the rendered delta"
    contents = out_path.read_text(encoding="utf-8")
    assert any(line.startswith("| ") for line in contents.splitlines())


def test_diff_out_with_json_format(tmp_path: Path, capsys) -> None:
    """`--out` works for `--format json` too, not just markdown."""
    db = tmp_path / "runs.db"
    baseline_id, current_id = _seed_two_runs(db)
    capsys.readouterr()

    out_path = tmp_path / "delta.json"
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
            "json",
            "--out",
            str(out_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert "rows" in payload
    assert "summary" in payload
