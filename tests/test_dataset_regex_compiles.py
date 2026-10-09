"""A `regex` expected output must compile (#321).

`ExpectedOutput.kind == "regex"` is documented as "a Python regex pattern; match
anywhere in output", and validation never compiled it: a hunt agent ran
`validate_dataset` over the docs' own rows plus `{"kind":"regex","value":"(unclosed"}`
and got 3 of 3 valid. (Whether the kinds are evaluated at all is #320.)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness.dataset import DatasetLoadError, ExpectedOutput, load_jsonl, validate_dataset


def _row(i: int, kind: str, value: str) -> dict:
    return {
        "id": f"r{i}",
        "input": "q",
        "expected_outputs": [{"kind": kind, "value": value}],
        "dataset_version": "v1",
        "provenance": {"source": "test"},
    }


@pytest.mark.parametrize("pattern", ["(unclosed", "[a-", "*x", "(?P<n>a)(?P<n>b)"])
def test_a_regex_that_does_not_compile_is_refused(pattern: str) -> None:
    with pytest.raises(ValueError, match="does not compile"):
        ExpectedOutput(kind="regex", value=pattern)


def test_validate_dataset_reports_it_and_load_refuses_it(tmp_path: Path) -> None:
    p = tmp_path / "d.jsonl"
    rows = [
        _row(1, "regex", r"\b1989\b"),
        _row(2, "regex", "(unclosed"),
        _row(3, "exact", "(unclosed"),
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    report = validate_dataset(p)
    assert not report.ok
    assert [f.line_no for f in report.findings if "does not compile" in f.reason] == [2]
    with pytest.raises(DatasetLoadError, match="does not compile"):
        load_jsonl(p)


@pytest.mark.parametrize(
    ("kind", "value"), [("regex", r"\b1989\b"), ("exact", "(unclosed"), ("semantic", "[a-")]
)
def test_valid_patterns_and_other_kinds_are_unaffected(kind: str, value: str) -> None:
    assert ExpectedOutput(kind=kind, value=value).value == value
