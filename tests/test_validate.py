"""Tests for ``validate_dataset`` and the ``eval-harness validate`` CLI (#56).

Coverage matrix:

- happy path on the shipped factuality fixture → ``ok=True``, no findings,
  populated ``tag_counts`` and ``dataset_version``.
- accumulating-errors path: a synthetic file with three different bad
  rows + one valid row surfaces three findings in line-number order
  (not failing fast on the first).
- duplicate-``id`` detection: the validator reports the duplicate
  without including the shadowed row in the tag histogram.
- version-drift detection: rows whose ``dataset_version`` doesn't match
  the first valid row's version are flagged.
- empty-file handling: zero data lines surfaces one ``empty`` finding
  with ``line_no=0``.
- missing file: ``FileNotFoundError`` propagates from the library; CLI
  surfaces exit code 2.
- ``ValidationReport.to_dict`` JSON shape is stable (top-level keys,
  per-finding keys, descending tag_counts order).
- CLI: clean fixture exits 0 with a one-line ``ok:`` summary.
- CLI: malformed fixture exits 1 with one stderr line per finding.
- CLI: ``--json`` emits the report dict and still respects the exit code.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval_harness.dataset import (
    ValidationFinding,
    ValidationReport,
    validate_dataset,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FACTUALITY_FIXTURE = REPO_ROOT / "fixtures" / "sample_factuality_v1.jsonl"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    """Write a list of JSON-shaped dicts to ``path`` as JSONL.

    One row per line, compact separators; mirrors the on-disk shape
    ``Dataset.dump_jsonl`` produces (keys may differ but compactness
    matches). The validator only cares about line-level structure, so
    we don't need sort-key parity here.
    """
    body = "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else "")
    path.write_text(body, encoding="utf-8")


def _good_row(**overrides) -> dict:
    base = {
        "id": "qa_001",
        "input": "What is the capital of France?",
        "expected_outputs": [{"kind": "exact", "value": "Paris"}],
        "dataset_version": "v1",
        "provenance": {"source": "test"},
        "tags": ["geography"],
    }
    base.update(overrides)
    return base


# --- library: happy path ----------------------------------------------------


def test_happy_path_factuality_fixture_returns_clean_report() -> None:
    """The shipped factuality fixture is well-formed; the validator
    returns ``ok=True`` with no findings and the file's tag histogram."""
    report = validate_dataset(FACTUALITY_FIXTURE)
    assert report.ok, f"factuality fixture should validate clean; got findings={report.findings}"
    assert report.findings == ()
    assert report.n_rows == report.n_valid
    assert report.n_rows > 0, "fixture should contain rows"
    assert report.dataset_version == "factuality-v0.1"
    # Tag histogram is descending by count; the fixture has at least one
    # `factuality` tag on every row, so it should be the most common.
    assert report.tag_counts[0][0] == "factuality"


# --- library: accumulating errors -------------------------------------------


def test_accumulates_every_bad_row_not_just_the_first(tmp_path: Path) -> None:
    """Loader fails fast on the first bad row; validator must collect them all.

    Three different bad shapes interleaved with a valid row → three
    findings reported in line-number order.
    """
    path = tmp_path / "mixed.jsonl"
    rows: list[dict] = [
        # line 1: parse fails (we'll splice this in manually below)
        _good_row(id="line1_placeholder"),
        # line 2: missing required field 'input'
        {
            "id": "missing_input",
            "expected_outputs": [{"kind": "exact", "value": "Paris"}],
            "dataset_version": "v1",
            "provenance": {"source": "test"},
        },
        # line 3: unknown kind
        _good_row(id="bad_kind", expected_outputs=[{"kind": "imaginary", "value": "x"}]),
        # line 4: valid (anchor)
        _good_row(id="valid_one"),
    ]
    _write_jsonl(path, rows)
    # Splice line 1 to be invalid JSON.
    body = path.read_text(encoding="utf-8").splitlines()
    body[0] = "{not valid json"
    path.write_text("\n".join(body) + "\n", encoding="utf-8")

    report = validate_dataset(path)
    assert not report.ok
    assert report.n_rows == 4
    assert report.n_valid == 1, "only the line-4 row should count as valid"
    assert len(report.findings) == 3, f"expected 3 findings, got {report.findings}"
    line_nos = [f.line_no for f in report.findings]
    assert line_nos == sorted(line_nos), "findings must be reported in source order"
    codes = [f.code for f in report.findings]
    assert codes == ["parse", "schema", "schema"]


# --- library: duplicate id --------------------------------------------------


def test_duplicate_id_is_a_finding_and_excluded_from_tag_histogram(tmp_path: Path) -> None:
    """A duplicate-``id`` row is reported with the first-seen line number
    in its reason and does not contribute to the tag histogram (it would
    double-count the original)."""
    path = tmp_path / "dups.jsonl"
    _write_jsonl(
        path,
        [
            _good_row(id="qa_001", tags=["geography"]),
            _good_row(id="qa_002", tags=["history"]),
            _good_row(id="qa_001", tags=["bogus_tag"]),  # duplicate
        ],
    )
    report = validate_dataset(path)
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.code == "duplicate_id"
    assert finding.line_no == 3
    assert "line 1" in finding.reason, "reason should reference the first-seen line"
    # bogus_tag from the duplicate row must NOT appear in the histogram.
    tags = dict(report.tag_counts)
    assert "bogus_tag" not in tags
    assert tags == {"geography": 1, "history": 1}


# --- library: version drift -------------------------------------------------


def test_version_drift_row_is_flagged_and_excluded(tmp_path: Path) -> None:
    """Rows whose ``dataset_version`` differs from the first valid row's
    version are flagged and excluded from valid count."""
    path = tmp_path / "drift.jsonl"
    _write_jsonl(
        path,
        [
            _good_row(id="a", dataset_version="v1"),
            _good_row(id="b", dataset_version="v2"),
            _good_row(id="c", dataset_version="v1"),
        ],
    )
    report = validate_dataset(path)
    assert report.dataset_version == "v1"
    assert report.n_valid == 2, "the v2 row is dropped from valid count"
    codes = [f.code for f in report.findings]
    assert codes == ["version_drift"]
    assert report.findings[0].line_no == 2


# --- library: empty file ----------------------------------------------------


def test_empty_file_surfaces_single_empty_finding(tmp_path: Path) -> None:
    """A file with zero lines surfaces one ``empty`` finding at line 0."""
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    report = validate_dataset(path)
    assert not report.ok
    assert len(report.findings) == 1
    assert report.findings[0].code == "empty"
    assert report.findings[0].line_no == 0


# --- library: missing file --------------------------------------------------


def test_missing_file_raises_filenotfounderror(tmp_path: Path) -> None:
    """The library propagates ``FileNotFoundError``; CLI translates to exit 2."""
    with pytest.raises(FileNotFoundError):
        validate_dataset(tmp_path / "does_not_exist.jsonl")


# --- library: to_dict shape -------------------------------------------------


def test_report_to_dict_shape_is_stable(tmp_path: Path) -> None:
    """``ValidationReport.to_dict()`` shape is the JSON contract; lock it.

    Top-level keys, per-finding keys, and tag_counts ordering must stay
    stable so machine consumers can parse the output without surprises.
    """
    path = tmp_path / "ok.jsonl"
    _write_jsonl(
        path,
        [
            _good_row(id="a", tags=["x", "y"]),
            _good_row(id="b", tags=["y"]),
        ],
    )
    payload = validate_dataset(path).to_dict()
    assert set(payload) == {
        "path",
        "ok",
        "n_rows",
        "n_valid",
        "dataset_version",
        "tag_counts",
        "findings",
    }
    assert payload["ok"] is True
    assert payload["n_rows"] == 2
    # Descending count, then alpha tiebreak.
    assert payload["tag_counts"] == [
        {"tag": "y", "count": 2},
        {"tag": "x", "count": 1},
    ]
    # Findings list is empty but the key still exists (consumers can
    # iterate without a key-presence check).
    assert payload["findings"] == []


# --- CLI: end-to-end --------------------------------------------------------


def _run_cli(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "eval_harness.cli", "validate", *argv],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_clean_fixture_exits_zero_with_ok_summary() -> None:
    """Clean fixture → exit 0, summary line begins ``ok:``."""
    result = _run_cli(str(FACTUALITY_FIXTURE))
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("ok:"), result.stdout


def test_cli_malformed_fixture_exits_one_with_findings_on_stderr(tmp_path: Path) -> None:
    """Malformed fixture → exit 1, one stderr line per finding."""
    path = tmp_path / "bad.jsonl"
    _write_jsonl(path, [_good_row(id="a"), _good_row(id="a", tags=["dup"])])
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "duplicate_id" in result.stderr
    assert result.stdout.startswith("fail:")


def test_cli_json_flag_emits_report_dict_and_respects_exit_code(tmp_path: Path) -> None:
    """``--json`` emits the ``to_dict()`` shape on stdout; exit code
    unchanged (1 because the fixture has a duplicate-id finding)."""
    path = tmp_path / "bad.jsonl"
    _write_jsonl(path, [_good_row(id="a"), _good_row(id="a")])
    result = _run_cli(str(path), "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["findings"][0]["code"] == "duplicate_id"


def test_cli_missing_file_exits_two() -> None:
    """Missing-file path → exit 2, matching ``scripts/audit_phase_a.py``
    convention (clean / findings / fetch-or-IO-error)."""
    result = _run_cli("/this/path/does/not/exist.jsonl")
    assert result.returncode == 2
    assert "dataset not found" in result.stderr


# --- finding dataclass spot check -------------------------------------------


def test_validation_finding_is_hashable_for_set_dedup() -> None:
    """Frozen dataclass → hashable → callers can dedup findings if they
    aggregate across files. Lock this lightly to prevent accidental
    ``frozen=True`` removal."""
    a = ValidationFinding(line_no=1, reason="bad", code="parse")
    b = ValidationFinding(line_no=1, reason="bad", code="parse")
    assert {a, b} == {a}


def test_report_ok_is_false_when_no_valid_rows(tmp_path: Path) -> None:
    """An all-bad file is never ``ok`` even if every row has a finding —
    this is the failure mode that triggered #56 in the first place
    (silent zero-row run consuming setup time)."""
    path = tmp_path / "allbad.jsonl"
    path.write_text("garbage\nmore garbage\n", encoding="utf-8")
    report = validate_dataset(path)
    assert not report.ok
    assert report.n_valid == 0
    assert all(f.code == "parse" for f in report.findings)


def test_validation_report_dataclass_round_trip(tmp_path: Path) -> None:
    """``ValidationReport`` is frozen; ``to_dict`` is the round-trip lens.

    Once a report is built we never mutate it — downstream consumers
    pin the JSON shape, not the dataclass.
    """
    path = tmp_path / "ok.jsonl"
    _write_jsonl(path, [_good_row(id="a")])
    report = validate_dataset(path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.n_rows = 999  # type: ignore[misc]
    # Sanity: a brand-new report with the same inputs is equal.
    again = validate_dataset(path)
    assert again == report
    # And dataclass field types match the contract.
    assert isinstance(report, ValidationReport)
