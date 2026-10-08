"""`re.compile` refuses some patterns without raising `re.error` (#332).

#321 caught `re.error`. A repeat count at or above MAXREPEAT raises
`OverflowError`, and deeply nested groups raise `RecursionError`. Both escaped
the collecting validator and the CLI as a traceback at exit 1, which is the
findings code for `validate` and the regression code for `run`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness.cli import main
from eval_harness.dataset import DatasetLoadError, ExpectedOutput, load_jsonl, validate_dataset

OVERFLOW = "a{4294967296}"
DEEP = "(" * 2000 + "x" + ")" * 2000
PATTERNS = [pytest.param(OVERFLOW, id="overflow"), pytest.param(DEEP, id="recursion")]


def _write(tmp_path: Path, pattern: str) -> Path:
    rows = [
        {
            "id": "r1",
            "input": "q",
            "expected_outputs": [{"kind": "regex", "value": pattern}],
            "dataset_version": "v1",
            "provenance": {},
        },
        {
            "id": "r2",
            "input": "q",
            "expected_outputs": [{"kind": "exact", "value": "y"}],
            "dataset_version": "v1",
            "provenance": {},
        },
    ]
    p = tmp_path / "d.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


@pytest.mark.parametrize("pattern", PATTERNS)
def test_the_pattern_really_is_refused_without_re_error(pattern: str) -> None:
    # Anti-vacuity: if a future Python turns these into `re.error`, the arms
    # below would pass against #321 alone and stop guarding anything.
    import re

    with pytest.raises((OverflowError, RecursionError)):
        re.compile(pattern)


@pytest.mark.parametrize("pattern", PATTERNS)
def test_expected_output_refuses_it_as_a_value_error(pattern: str) -> None:
    with pytest.raises(ValueError, match="does not compile"):
        ExpectedOutput(kind="regex", value=pattern)


@pytest.mark.parametrize("pattern", PATTERNS)
def test_the_collecting_validator_reports_it_and_keeps_going(tmp_path: Path, pattern: str) -> None:
    report = validate_dataset(_write(tmp_path, pattern))
    assert [f.line_no for f in report.findings] == [1]
    assert "does not compile" in report.findings[0].reason
    assert report.n_rows == 2
    assert report.n_valid == 1


@pytest.mark.parametrize("pattern", PATTERNS)
def test_the_loader_refuses_it(tmp_path: Path, pattern: str) -> None:
    with pytest.raises(DatasetLoadError, match="does not compile"):
        load_jsonl(_write(tmp_path, pattern))


@pytest.mark.parametrize("pattern", PATTERNS)
def test_cli_validate_exits_1_with_a_finding_not_a_traceback(
    tmp_path: Path, pattern: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["validate", str(_write(tmp_path, pattern))]) == 1
    captured = capsys.readouterr()
    assert "line 1 [schema]" in captured.err
    assert "does not compile" in captured.err
    assert "rows=2 valid=1 findings=1" in captured.out


@pytest.mark.parametrize("pattern", PATTERNS)
def test_cli_run_exits_2_before_scoring(
    tmp_path: Path, pattern: str, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "runs.db"
    rc = main(
        ["run", "--suite", "s", "--dataset", str(_write(tmp_path, pattern)), "--no-diff"]
        + ["--db", str(db)]
    )
    assert rc == 2
    assert "does not compile" in capsys.readouterr().err
