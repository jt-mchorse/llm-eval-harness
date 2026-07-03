"""Tests for the golden-dataset JSONL format (issue #1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness.dataset import (
    Dataset,
    DatasetLoadError,
    Example,
    ExpectedOutput,
    load_jsonl,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_factuality_v1.jsonl"


# -- happy path --------------------------------------------------------------


def test_fixture_loads_with_expected_shape() -> None:
    ds = load_jsonl(FIXTURE)
    assert isinstance(ds, Dataset)
    assert ds.version == "factuality-v0.1"
    assert len(ds) == 10
    assert all(isinstance(ex, Example) for ex in ds)
    assert all(ex.dataset_version == "factuality-v0.1" for ex in ds)
    # Every example should declare provenance — the format requires it, but
    # we double-check semantically here so a future bug that defaults it
    # silently doesn't slip past.
    assert all("source" in ex.provenance for ex in ds)


def test_round_trip_byte_identity(tmp_path: Path) -> None:
    """load → dump → re-load → byte-equal canonical JSON."""
    ds = load_jsonl(FIXTURE)
    out = tmp_path / "round_trip.jsonl"
    ds.dump_jsonl(out)
    ds2 = load_jsonl(out)

    # Re-dump from the second load and compare bytes — this is the property
    # the format promises (canonical-on-dump means stable across releases).
    out2 = tmp_path / "round_trip_2.jsonl"
    ds2.dump_jsonl(out2)
    assert out.read_bytes() == out2.read_bytes()
    # And: the canonical form of the fixture itself is byte-equal to the dump.
    assert FIXTURE.read_bytes() == out.read_bytes()


# -- malformed-line cases ----------------------------------------------------


def _write(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "bad.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _good_line(id_: str = "x_001", version: str = "v1") -> str:
    return json.dumps(
        {
            "id": id_,
            "input": "q",
            "expected_outputs": [{"kind": "exact", "value": "a"}],
            "dataset_version": version,
            "provenance": {"source": "test"},
        },
        sort_keys=True,
    )


def test_invalid_json_reports_correct_line(tmp_path: Path) -> None:
    path = _write(tmp_path, [_good_line("a"), "{not valid json", _good_line("b")])
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(path)
    assert exc.value.line_no == 2
    assert "invalid JSON" in exc.value.reason


def test_missing_required_field_reports_correct_line(tmp_path: Path) -> None:
    bad = json.dumps({"id": "x", "input": "q"})  # missing several required fields
    path = _write(tmp_path, [_good_line("a"), bad])
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(path)
    assert exc.value.line_no == 2
    assert "missing required field" in exc.value.reason


def test_wrong_type_for_input_field_reports_correct_line(tmp_path: Path) -> None:
    bad = json.dumps(
        {
            "id": "x",
            "input": 42,  # should be a string
            "expected_outputs": [{"kind": "exact", "value": "a"}],
            "dataset_version": "v1",
            "provenance": {},
        }
    )
    path = _write(tmp_path, [bad])
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(path)
    assert exc.value.line_no == 1
    assert "'input'" in exc.value.reason


def test_unknown_expected_output_kind_is_rejected(tmp_path: Path) -> None:
    bad = json.dumps(
        {
            "id": "x",
            "input": "q",
            "expected_outputs": [{"kind": "vibes", "value": "good"}],
            "dataset_version": "v1",
            "provenance": {},
        }
    )
    path = _write(tmp_path, [bad])
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(path)
    assert exc.value.line_no == 1
    assert "invalid expected_output kind" in exc.value.reason


@pytest.mark.parametrize("bad_kind", [["exact"], {"k": "v"}])
def test_unhashable_expected_output_kind_is_a_clean_error_not_a_typeerror(
    tmp_path: Path, bad_kind: object
) -> None:
    # #138: an unhashable `kind` (JSON array/object) used to leak a raw
    # `TypeError` from the `frozenset` membership test — escaping
    # `_validate_record`'s `except ValueError` — instead of the clean
    # per-line `DatasetLoadError` a hashable wrong kind (123) already got.
    bad = json.dumps(
        {
            "id": "x",
            "input": "q",
            "expected_outputs": [{"kind": bad_kind, "value": "good"}],
            "dataset_version": "v1",
            "provenance": {},
        }
    )
    path = _write(tmp_path, [bad])
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(path)
    assert exc.value.line_no == 1
    assert "invalid expected_output kind" in exc.value.reason


def test_empty_expected_outputs_is_rejected(tmp_path: Path) -> None:
    bad = json.dumps(
        {
            "id": "x",
            "input": "q",
            "expected_outputs": [],
            "dataset_version": "v1",
            "provenance": {},
        }
    )
    path = _write(tmp_path, [bad])
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(path)
    assert exc.value.line_no == 1
    assert "non-empty list" in exc.value.reason


def test_duplicate_id_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, [_good_line("dup"), _good_line("dup")])
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(path)
    assert exc.value.line_no == 2
    assert "duplicate id" in exc.value.reason


def test_mixed_dataset_version_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, [_good_line("a", version="v1"), _good_line("b", version="v2")])
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(path)
    assert exc.value.line_no == 2
    assert "does not match file version" in exc.value.reason


def test_unknown_top_level_field_is_rejected(tmp_path: Path) -> None:
    bad = json.dumps(
        {
            "id": "x",
            "input": "q",
            "expected_outputs": [{"kind": "exact", "value": "a"}],
            "dataset_version": "v1",
            "provenance": {},
            "expected_output": "typo",  # singular; common copy-paste mistake
        }
    )
    path = _write(tmp_path, [bad])
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(path)
    assert exc.value.line_no == 1
    assert "unknown top-level field" in exc.value.reason


def test_blank_line_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "blank.jsonl"
    path.write_text(_good_line("a") + "\n\n" + _good_line("b") + "\n", encoding="utf-8")
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(path)
    assert exc.value.line_no == 2
    assert "blank line" in exc.value.reason


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(DatasetLoadError):
        load_jsonl(path)


def test_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_jsonl(tmp_path / "nope.jsonl")


# -- ExpectedOutput unit checks ---------------------------------------------


def test_expected_output_rejects_bad_kind() -> None:
    with pytest.raises(ValueError, match="kind"):
        ExpectedOutput(kind="bogus", value="x")


def test_expected_output_rejects_unhashable_kind_as_valueerror() -> None:
    # #138: a list/dict kind must raise the same `ValueError` as any other bad
    # kind, not a `TypeError` from the set membership test.
    with pytest.raises(ValueError, match="kind"):
        ExpectedOutput(kind=["exact"], value="x")  # type: ignore[arg-type]


def test_expected_output_value_must_be_str() -> None:
    with pytest.raises(ValueError, match="value"):
        ExpectedOutput(kind="exact", value=42)  # type: ignore[arg-type]
