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

from eval_harness.calibration import validate_calibration
from eval_harness.dataset import (
    ValidationFinding,
    ValidationReport,
    validate_dataset,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FACTUALITY_FIXTURE = REPO_ROOT / "fixtures" / "sample_factuality_v1.jsonl"
CALIBRATION_FIXTURE = REPO_ROOT / "fixtures" / "calibration.jsonl"


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


def test_unhashable_kind_row_is_one_schema_finding_not_a_crash(tmp_path: Path) -> None:
    """#138: a row whose `expected_outputs.kind` is an unhashable JSON value
    (list/dict) used to throw a raw `TypeError` that aborted the whole
    collecting pass. It must instead surface as a single `schema` finding while
    the surrounding valid rows still validate."""
    path = tmp_path / "unhashable_kind.jsonl"
    rows = [
        _good_row(id="valid_before"),
        _good_row(id="bad_kind", expected_outputs=[{"kind": ["exact"], "value": "x"}]),
        _good_row(id="valid_after"),
    ]
    _write_jsonl(path, rows)

    report = validate_dataset(path)
    assert not report.ok
    assert report.n_rows == 3
    assert report.n_valid == 2, "the two well-formed rows must still validate"
    assert len(report.findings) == 1, f"expected 1 finding, got {report.findings}"
    assert report.findings[0].line_no == 2
    assert report.findings[0].code == "schema"
    assert "invalid expected_output kind" in report.findings[0].reason


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


def test_id_reused_after_version_drift_is_valid_not_a_duplicate(tmp_path: Path) -> None:
    """A version-drifted row is dropped and must NOT reserve its id: a later
    valid row that reuses the dropped row's id is a legitimate valid example,
    not a ``duplicate_id`` finding pointing at a discarded row (#114).

    This mirrors the schema-rejection path, which already `continue`s before
    the id is recorded — only rows that become valid should claim an id.
    """
    path = tmp_path / "reuse.jsonl"
    _write_jsonl(
        path,
        [
            _good_row(id="a", dataset_version="v1"),  # valid
            _good_row(id="b", dataset_version="v2"),  # version drift -> dropped
            _good_row(id="b", dataset_version="v1"),  # valid; reuses the dropped id
        ],
    )
    report = validate_dataset(path)
    assert report.dataset_version == "v1"
    # The line-3 row is valid; only the line-2 drift should be a finding.
    assert report.n_valid == 2, "the reused-id row on line 3 is a valid example"
    codes = [f.code for f in report.findings]
    assert codes == ["version_drift"], "no spurious duplicate_id for the reused id"
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


# --- CLI: --out sink parity (#66) -------------------------------------------


def test_cli_out_writes_human_summary_to_file_not_stdout(tmp_path: Path) -> None:
    """``--out`` writes the human-readable summary to disk; stdout stays
    silent (mirrors `list / diff / diff-json` --out behavior). The file
    contains the same one-line summary the stdout-only path would print,
    with a trailing newline."""
    out = tmp_path / "report.txt"
    result = _run_cli(str(FACTUALITY_FIXTURE), "--out", str(out))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", f"stdout must be silent when --out is set; got {result.stdout!r}"
    body = out.read_text(encoding="utf-8")
    assert body.startswith("ok:"), body
    assert body.endswith("\n"), "trailing newline required for parity with siblings"


def test_cli_out_writes_json_payload_to_file(tmp_path: Path) -> None:
    """``--out`` + ``--json`` writes the report dict as JSON to disk;
    stdout silent; the file parses cleanly and carries the expected shape."""
    bad = tmp_path / "bad.jsonl"
    _write_jsonl(bad, [_good_row(id="a"), _good_row(id="a")])
    out = tmp_path / "report.json"
    result = _run_cli(str(bad), "--json", "--out", str(out))
    assert result.returncode == 1
    assert result.stdout == ""
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["findings"][0]["code"] == "duplicate_id"


def test_cli_out_creates_parent_dirs(tmp_path: Path) -> None:
    """``atomic_write_text`` does ``parent.mkdir(parents=True)``; confirm
    the validate path inherits that behavior so a nested observability
    directory doesn't need pre-creation."""
    out = tmp_path / "nested" / "sink" / "report.txt"
    result = _run_cli(str(FACTUALITY_FIXTURE), "--out", str(out))
    assert result.returncode == 0
    assert out.exists()
    assert out.parent.is_dir()


def test_cli_out_overwrites_atomically(tmp_path: Path) -> None:
    """Two successive writes to the same path leave the second payload —
    not the concatenation, not a half-written file. No tempfile leftovers
    under the destination's parent."""
    out = tmp_path / "report.txt"
    _run_cli(str(FACTUALITY_FIXTURE), "--out", str(out))
    body1 = out.read_text(encoding="utf-8")

    bad = tmp_path / "bad.jsonl"
    _write_jsonl(bad, [_good_row(id="a"), _good_row(id="a")])
    _run_cli(str(bad), "--out", str(out))
    body2 = out.read_text(encoding="utf-8")
    assert body1 != body2
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], leftovers
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".report.txt.")]
    assert leftovers == [], leftovers


def test_cli_out_findings_still_print_to_stderr(tmp_path: Path) -> None:
    """``--out`` covers stdout only — stderr stays the operator's
    diagnostic channel so a CI step capturing stdout to a file still sees
    per-finding lines on stderr. Parity with the existing
    no-``--out``/findings/stderr contract."""
    bad = tmp_path / "bad.jsonl"
    _write_jsonl(bad, [_good_row(id="a"), _good_row(id="a", tags=["dup"])])
    out = tmp_path / "report.txt"
    result = _run_cli(str(bad), "--out", str(out))
    assert result.returncode == 1
    assert "duplicate_id" in result.stderr
    assert result.stdout == ""
    body = out.read_text(encoding="utf-8")
    assert body.startswith("fail:"), body


def test_cli_out_not_written_on_file_not_found(tmp_path: Path) -> None:
    """Exit-2 (file-not-found) path raises before rendering, so ``--out``
    must NOT touch disk — keeps the failure mode honest (no zero-byte
    sentinel a CI step could mistake for "ran successfully")."""
    out = tmp_path / "report.txt"
    result = _run_cli("/this/path/does/not/exist.jsonl", "--out", str(out))
    assert result.returncode == 2
    assert not out.exists(), "exit-2 must not create the --out file"


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


# --- calibration validator (#58) -------------------------------------------


def _good_calib_row(**overrides) -> dict:
    base = {
        "id": "cap_001",
        "prompt": "What is the capital of France?",
        "response": "Paris.",
        "rubric": "Score how faithful the RESPONSE is to the PROMPT.",
        "human_score": 1.0,
        "provenance": {"labeled_by": "test"},
    }
    base.update(overrides)
    return base


def test_calibration_happy_path_shipped_fixture_returns_clean_report() -> None:
    """The shipped ``fixtures/calibration.jsonl`` is well-formed; the
    calibration validator returns ``ok=True``, ``dataset_version=None``,
    ``tag_counts=()``."""
    report = validate_calibration(CALIBRATION_FIXTURE)
    assert report.ok, f"calibration fixture should validate clean; got findings={report.findings}"
    assert report.findings == ()
    assert report.n_rows == report.n_valid
    assert report.n_rows > 0
    assert report.dataset_version is None
    assert report.tag_counts == ()


def test_calibration_accumulates_every_bad_row(tmp_path: Path) -> None:
    """One pass surfaces parse + schema + score_range + valid in order."""
    path = tmp_path / "mixed_calib.jsonl"
    rows: list[dict] = [
        _good_calib_row(id="line1_placeholder"),  # spliced to garbage
        {"id": "missing_fields", "prompt": "p"},  # line 2: schema
        _good_calib_row(id="bad_score", human_score=1.5),  # line 3: score_range
        _good_calib_row(id="valid_one"),  # line 4: valid
    ]
    _write_jsonl(path, rows)
    body = path.read_text(encoding="utf-8").splitlines()
    body[0] = "{not valid json"
    path.write_text("\n".join(body) + "\n", encoding="utf-8")

    report = validate_calibration(path)
    assert not report.ok
    assert report.n_rows == 4
    assert report.n_valid == 1
    assert [f.code for f in report.findings] == ["parse", "schema", "score_range"]
    assert [f.line_no for f in report.findings] == [1, 2, 3]


def test_calibration_score_range_bool_is_not_a_number(tmp_path: Path) -> None:
    """``human_score: true`` is rejected as schema (the loader uses
    ``isinstance(score, bool)`` to keep bool from sneaking in as int).

    The reason text mentions ``human_score must be a number`` so the
    code stays ``schema`` (not ``score_range``) — the range check
    fires only for true numeric out-of-bounds values.
    """
    path = tmp_path / "boolscore.jsonl"
    _write_jsonl(path, [_good_calib_row(id="boolscore", human_score=True)])
    report = validate_calibration(path)
    assert not report.ok
    assert len(report.findings) == 1
    assert report.findings[0].code == "schema"
    assert "human_score must be a number" in report.findings[0].reason


def test_calibration_duplicate_id_is_a_finding(tmp_path: Path) -> None:
    """Calibration-side duplicate-id detection mirrors validate_dataset."""
    path = tmp_path / "calib_dups.jsonl"
    _write_jsonl(
        path,
        [
            _good_calib_row(id="cap_001"),
            _good_calib_row(id="cap_002"),
            _good_calib_row(id="cap_001"),  # duplicate
        ],
    )
    report = validate_calibration(path)
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.code == "duplicate_id"
    assert finding.line_no == 3
    assert "first seen at line 1" in finding.reason
    assert report.n_valid == 2  # shadow row excluded


def test_calibration_schema_missing_required_field(tmp_path: Path) -> None:
    """Missing required field surfaces as schema finding (one per row)."""
    path = tmp_path / "missing.jsonl"
    row = _good_calib_row()
    del row["rubric"]
    _write_jsonl(path, [row])
    report = validate_calibration(path)
    assert not report.ok
    assert len(report.findings) == 1
    assert report.findings[0].code == "schema"
    assert "rubric" in report.findings[0].reason


def test_calibration_schema_unknown_top_level_field(tmp_path: Path) -> None:
    """Calibration's loader rejects unknown top-level keys (no tags
    column on this schema). Same code, distinct reason text."""
    path = tmp_path / "extra.jsonl"
    _write_jsonl(path, [_good_calib_row(extra_key="surprise")])
    report = validate_calibration(path)
    assert not report.ok
    assert report.findings[0].code == "schema"
    assert "extra_key" in report.findings[0].reason or "unknown" in report.findings[0].reason


def test_calibration_schema_non_object_row(tmp_path: Path) -> None:
    """A JSON array (or scalar) row is a schema finding, not a parse
    finding — JSON parsed fine, the shape is wrong."""
    path = tmp_path / "non_object.jsonl"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    report = validate_calibration(path)
    assert not report.ok
    assert report.findings[0].code == "schema"
    assert "not a JSON object" in report.findings[0].reason


def test_calibration_empty_file_is_one_empty_finding(tmp_path: Path) -> None:
    """Zero-row file → ``empty`` finding with ``line_no=0``, matching
    validate_dataset semantics."""
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    report = validate_calibration(path)
    assert not report.ok
    assert report.n_rows == 0
    assert len(report.findings) == 1
    assert report.findings[0].code == "empty"
    assert report.findings[0].line_no == 0


def test_calibration_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    """Missing path raises ``FileNotFoundError`` (the CLI translates to
    exit 2; the library lets it bubble)."""
    with pytest.raises(FileNotFoundError):
        validate_calibration(tmp_path / "missing.jsonl")


def test_calibration_report_to_dict_shape_matches_dataset_contract(tmp_path: Path) -> None:
    """``validate_calibration`` returns the same ``ValidationReport``
    dataclass as ``validate_dataset`` so machine consumers can treat
    both outputs uniformly."""
    path = tmp_path / "ok_calib.jsonl"
    _write_jsonl(path, [_good_calib_row(id="a"), _good_calib_row(id="b")])
    report = validate_calibration(path)
    payload = report.to_dict()
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
    assert payload["dataset_version"] is None
    assert payload["tag_counts"] == []
    assert payload["findings"] == []


# --- CLI: --calibration end-to-end ------------------------------------------


def test_cli_calibration_flag_on_shipped_fixture_exits_zero() -> None:
    """``eval-harness validate --calibration fixtures/calibration.jsonl``
    is the gating pre-flight before ``eval-harness calibrate``."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "validate",
            "--calibration",
            str(CALIBRATION_FIXTURE),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("ok:"), result.stdout
    # The summary line references the calibration kind so the operator
    # can tell at a glance which validator ran.
    assert "version=calibration" in result.stdout


def test_cli_calibration_flag_surfaces_score_range_finding(tmp_path: Path) -> None:
    """A malformed calibration file routes through the right validator;
    exit 1 with the calibration-specific ``score_range`` code on stderr."""
    path = tmp_path / "bad_calib.jsonl"
    _write_jsonl(
        path,
        [
            _good_calib_row(id="a"),
            _good_calib_row(id="b", human_score=1.7),
        ],
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "validate",
            "--calibration",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "score_range" in result.stderr
    assert result.stdout.startswith("fail:")


def test_cli_calibration_json_emits_report_dict(tmp_path: Path) -> None:
    """``--calibration --json`` emits the same ``to_dict()`` shape as
    the golden-dataset path; CI consumers can route uniformly."""
    path = tmp_path / "bad_calib.jsonl"
    _write_jsonl(
        path,
        [_good_calib_row(id="a", human_score=-0.1)],
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "validate",
            "--calibration",
            "--json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["findings"][0]["code"] == "score_range"
    # Calibration-specific contract: no version, no tags.
    assert payload["dataset_version"] is None
    assert payload["tag_counts"] == []


def test_cli_calibration_missing_file_exits_two_with_calibration_kind() -> None:
    """Missing-file path under ``--calibration`` surfaces the
    calibration kind in the error message so operators don't think
    they're running the golden-dataset validator."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "validate",
            "--calibration",
            "/this/path/does/not/exist.jsonl",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "calibration not found" in result.stderr
