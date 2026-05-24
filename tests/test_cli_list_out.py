"""Tests for `eval-harness list --out` (issue #36).

`list` already accepted `--json` (boolean → JSON array on stdout), but
the only sink was stdout. Sibling subcommands `run`, `diff`, `diff-json`
all already accepted `--out PATH` and used the same
`Path(args.out).parent.mkdir(parents=True, exist_ok=True)` plumbing.
This module pins:

- `--out PATH` writes the rendered output to a file (auto-creates parent
  dirs) and stdout stays silent.
- Both `--json` and text-table modes route through `--out` identically.
- The empty / missing-DB short-circuits route through `--out` as well —
  callers asking for an artifact get a deterministic file, not a missing
  one, even when there are no runs.
- Stdout-only mode (no `--out`) still emits, unchanged — this is the
  belt-and-braces guard against the refactor regressing the existing
  print-to-stdout behaviour.

Cross-reference: `tests/test_cli_diff_format.py` (#35) pinned the same
sink-decision shape on `diff`, after `diff-json` (#D-010) had it first.
This file finishes the four-subcommand parity on the public CLI surface.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval_harness import runs
from eval_harness.cli import main


def _seed_db(path: Path, *, entries: list[dict]) -> None:
    with runs.connect(path) as conn:
        runs.init_db_on(conn)
        for e in entries:
            runs.write_run(
                conn,
                run_id=e["run_id"],
                started_at=e["started_at"],
                suite=e["suite"],
                dataset_version="rag-qa-v0.1",
                judge_model="fake-judge",
                judge_kappa=0.8,
                mean_score=e.get("mean_score", 0.9),
                n_rows=2,
                git_sha=None,
                rows=[("ex1", 1.0, "ok"), ("ex2", 0.8, "ok")],
            )


def test_list_json_out_writes_file_and_keeps_stdout_silent(tmp_path: Path, capsys) -> None:
    db = tmp_path / "h.sqlite"
    _seed_db(
        db,
        entries=[
            {"run_id": "r_001_aaa", "started_at": "2026-05-15T10:00:00Z", "suite": "faithfulness"},
            {"run_id": "r_002_bbb", "started_at": "2026-05-16T10:00:00Z", "suite": "faithfulness"},
        ],
    )
    out_path = tmp_path / "runs.json"
    rc = main(["list", "--db", str(db), "--json", "--out", str(out_path)])
    assert rc == 0
    # Stdout is silent — the whole point of --out for CI consumers.
    assert capsys.readouterr().out == ""
    # File exists and parses as a JSON array with both runs (most-recent-first).
    body = out_path.read_text(encoding="utf-8")
    parsed = json.loads(body)
    assert isinstance(parsed, list)
    assert [r["run_id"] for r in parsed] == ["r_002_bbb", "r_001_aaa"]


def test_list_text_out_writes_table_to_file_and_keeps_stdout_silent(tmp_path: Path, capsys) -> None:
    db = tmp_path / "h.sqlite"
    _seed_db(
        db,
        entries=[
            {"run_id": "r_001_aaa", "started_at": "2026-05-15T10:00:00Z", "suite": "faithfulness"},
            {"run_id": "r_002_bbb", "started_at": "2026-05-16T10:00:00Z", "suite": "faithfulness"},
        ],
    )
    out_path = tmp_path / "runs.txt"
    rc = main(["list", "--db", str(db), "--out", str(out_path)])
    assert rc == 0
    assert capsys.readouterr().out == ""
    body = out_path.read_text(encoding="utf-8")
    # Header line plus a separator plus two data lines — at minimum.
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) >= 4
    assert "2026-05-16" in body
    assert "2026-05-15" in body


def test_list_out_creates_missing_parent_dirs(tmp_path: Path, capsys) -> None:
    db = tmp_path / "h.sqlite"
    _seed_db(
        db,
        entries=[
            {"run_id": "r_001_aaa", "started_at": "2026-05-15T10:00:00Z", "suite": "faithfulness"},
        ],
    )
    # Nested path that doesn't exist; --out should mkdir -p.
    out_path = tmp_path / "deep" / "nested" / "dir" / "runs.json"
    assert not out_path.parent.exists()
    rc = main(["list", "--db", str(db), "--json", "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()
    parsed = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(parsed) == 1
    assert parsed[0]["run_id"] == "r_001_aaa"


def test_list_out_short_circuits_missing_db_with_no_runs_artifact(tmp_path: Path, capsys) -> None:
    """A `list --json --out PATH` against a missing DB writes `[]` to PATH.

    Without --out the existing behaviour is to print a comment line or
    `[]` to stdout; under --out the artifact has to exist so a CI step
    that asserts `runs.json` is present after the call doesn't trip on
    an absent file just because the DB hasn't been created yet.
    """
    db_path = tmp_path / "never-created.sqlite"
    out_path = tmp_path / "runs.json"
    rc = main(["list", "--db", str(db_path), "--json", "--out", str(out_path)])
    assert rc == 0
    assert capsys.readouterr().out == ""
    parsed = json.loads(out_path.read_text(encoding="utf-8"))
    assert parsed == []


def test_list_stdout_only_modes_still_emit_unchanged(tmp_path: Path, capsys) -> None:
    """Regression guard: refactor must not break the no-`--out` paths.

    Pins both the `--json` stdout array and the default text-table
    stdout shape against the pre-#36 behaviour.
    """
    db = tmp_path / "h.sqlite"
    _seed_db(
        db,
        entries=[
            {"run_id": "r_001_aaa", "started_at": "2026-05-15T10:00:00Z", "suite": "faithfulness"},
        ],
    )
    # --json no --out → JSON array on stdout.
    rc = main(["list", "--db", str(db), "--json"])
    assert rc == 0
    out_json = capsys.readouterr().out
    parsed = json.loads(out_json)
    assert len(parsed) == 1
    assert parsed[0]["run_id"] == "r_001_aaa"

    # text no --out → table on stdout, with the expected timestamp present.
    rc = main(["list", "--db", str(db)])
    assert rc == 0
    out_text = capsys.readouterr().out
    assert "2026-05-15" in out_text
    assert "r_001_aaa"[:12] in out_text
