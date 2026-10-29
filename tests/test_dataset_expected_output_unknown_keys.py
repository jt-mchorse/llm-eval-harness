"""An unknown key inside an `expected_outputs` item is refused (#453).

The loader refused an unknown *top-level* field "so that a typo doesn't
silently no-op", but inside each item it only checked that `kind` and `value`
were present. `ExpectedOutput` keeps exactly those two, so `{"valu": ...}` or a
guessed `{"flags": ...}` validated clean and `dump_jsonl` dropped it without a
word. `load_jsonl`, `validate_dataset` and the `validate` CLI all route through
`_validate_record`, so each is pinned here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval_harness.dataset import DatasetLoadError, load_jsonl, validate_dataset

# The issue's file, byte for byte.
ISSUE_LINE = (
    '{"dataset_version":"v","expected_outputs":[{"kind":"regex","value":"paris",'
    '"flags":"IGNORECASE"},{"kind":"exact","valu":"Paris","value":""}],"id":"a",'
    '"input":"q","provenance":{"s":"x"}}'
)


def _row(expected_outputs: list, **overrides: object) -> dict:
    base: dict = {
        "id": "a",
        "input": "q",
        "expected_outputs": expected_outputs,
        "dataset_version": "v",
        "provenance": {"source": "test"},
    }
    base.update(overrides)
    return base


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "d.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _load_reason(tmp_path: Path, rows: list[dict]) -> str:
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(_write(tmp_path, rows))
    assert exc.value.line_no == 1
    return exc.value.reason


EXTRA_ITEMS = [
    pytest.param({"kind": "exact", "value": "Paris", "valu": "x"}, ["valu"], id="typo"),
    pytest.param({"kind": "regex", "value": "p", "flags": "I"}, ["flags"], id="guessed-flag"),
    pytest.param({"kind": "exact", "value": "a", "Kind": "semantic"}, ["Kind"], id="case"),
    pytest.param({"kind": "exact", "value": "a", "": 1}, [""], id="empty-key"),
    pytest.param(
        {"kind": "exact", "value": "a", "z": None, "b": [], "m": {}}, ["b", "m", "z"], id="many"
    ),
]


@pytest.mark.parametrize(("item", "keys"), EXTRA_ITEMS)
def test_loader_refuses_an_unknown_item_key(tmp_path: Path, item: dict, keys: list[str]) -> None:
    reason = _load_reason(tmp_path, [_row([item])])
    assert reason == f"expected_outputs[0]: unknown field(s): {keys}"


@pytest.mark.parametrize(("item", "keys"), EXTRA_ITEMS)
def test_validator_reports_an_unknown_item_key(tmp_path: Path, item: dict, keys: list[str]) -> None:
    report = validate_dataset(_write(tmp_path, [_row([item])]))
    assert report.n_valid == 0
    assert [(f.line_no, f.code, f.reason) for f in report.findings] == [
        (1, "schema", f"expected_outputs[0]: unknown field(s): {keys}")
    ]


def test_the_index_named_is_the_offending_item(tmp_path: Path) -> None:
    items = [
        {"kind": "exact", "value": "a"},
        {"kind": "exact", "value": "b"},
        {"kind": "exact", "value": "c", "x": 1},
    ]
    assert _load_reason(tmp_path, [_row(items)]) == "expected_outputs[2]: unknown field(s): ['x']"


def test_issue_file_is_refused_by_cli_validate(tmp_path: Path) -> None:
    path = tmp_path / "eo.jsonl"
    path.write_text(ISSUE_LINE + "\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "eval_harness.cli", "validate", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert result.stdout.startswith("fail:"), result.stdout
    # The first offending item wins, the way the item loop already reports.
    assert "expected_outputs[0]: unknown field(s): ['flags']" in result.stderr


def test_issue_file_is_refused_by_load_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "eo.jsonl"
    path.write_text(ISSUE_LINE + "\n", encoding="utf-8")
    with pytest.raises(
        DatasetLoadError, match=r"expected_outputs\[0\]: unknown field\(s\): \['flags'\]"
    ):
        load_jsonl(path)


def test_a_bad_kind_still_wins_over_an_unknown_key(tmp_path: Path) -> None:
    """Same order as the top level: the item's own shape error is the diagnosis."""
    reason = _load_reason(tmp_path, [_row([{"kind": "fuzzy", "value": "a", "x": 1}])])
    assert reason.startswith("expected_outputs[0]: invalid expected_output kind 'fuzzy'")


def test_a_missing_value_still_wins_over_an_unknown_key(tmp_path: Path) -> None:
    """`valu` alone is a missing `value` first: the existing message is kept."""
    reason = _load_reason(tmp_path, [_row([{"kind": "exact", "valu": "a"}])])
    assert reason == "expected_outputs[0] missing 'kind' or 'value'"


def test_an_unknown_item_key_wins_over_an_unknown_top_level_field(tmp_path: Path) -> None:
    """Items are checked inside the shape pass, before the top-level key check."""
    reason = _load_reason(tmp_path, [_row([{"kind": "exact", "value": "a", "x": 1}], extra=1)])
    assert reason == "expected_outputs[0]: unknown field(s): ['x']"


# -- controls ---------------------------------------------------------------


def test_well_formed_items_still_load_and_round_trip(tmp_path: Path) -> None:
    items = [{"kind": k, "value": "p"} for k in ("exact", "semantic", "regex")]
    path = _write(tmp_path, [_row(items)])
    ds = load_jsonl(path)
    out = tmp_path / "out.jsonl"
    ds.dump_jsonl(out)
    assert json.loads(out.read_text(encoding="utf-8"))["expected_outputs"] == items
    assert validate_dataset(path).findings == ()


def test_provenance_keys_stay_free_form(tmp_path: Path) -> None:
    """`provenance` is "Free-form keys" by contract and is written back whole."""
    prov = {"source": "s", "valu": 1, "flags": "I", "nested": {"anything": [1]}}
    path = _write(tmp_path, [_row([{"kind": "exact", "value": "a"}], provenance=prov)])
    ds = load_jsonl(path)
    out = tmp_path / "out.jsonl"
    ds.dump_jsonl(out)
    assert json.loads(out.read_text(encoding="utf-8"))["provenance"] == prov
    assert validate_dataset(path).findings == ()
