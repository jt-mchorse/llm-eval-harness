"""drift's JSONL reader splits lines like every other reader in the package (#285).

`_load_inputs_jsonl` used `str.splitlines()`, which also breaks on U+2028,
U+2029, U+0085, U+000B, U+000C and U+001C-U+001E. `json.dumps(...,
ensure_ascii=False)` writes those unescaped inside strings, so a valid row was
cut in half. Measured on `main`: a candidate row `{"input": "line one\\u2028line
two"}` -> rc 2 `::error::...:4: invalid JSON: Unterminated string`, on a file
the package's own `dump_jsonl` wrote and its own `validate` accepted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness.cli import main
from eval_harness.dataset import Dataset, Example, ExpectedOutput
from eval_harness.drift import _load_inputs_jsonl

# Every character `str.splitlines` treats as a boundary that a text file
# iterated line by line does not.
SPLITLINES_ONLY = [" ", " ", "\x85", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e"]
GOLDEN = [
    "What is the capital of France?",
    "Who wrote Hamlet?",
    "How many legs does a spider have?",
    "What year did WW2 end?",
]


@pytest.mark.parametrize("sep", SPLITLINES_ONLY, ids=[f"U+{ord(c):04X}" for c in SPLITLINES_ONLY])
def test_a_row_containing_the_separator_loads_intact(tmp_path: Path, sep: str) -> None:
    p = tmp_path / "c.jsonl"
    rows = ["first row", f"line one{sep}line two", "last row"]
    p.write_text(
        "".join(json.dumps({"input": r}, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    assert _load_inputs_jsonl(p) == rows


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"], ids=["LF", "CRLF", "CR"])
def test_real_line_endings_still_split(tmp_path: Path, newline: str) -> None:
    p = tmp_path / "c.jsonl"
    p.write_bytes(newline.join(json.dumps(r) for r in ["a b", "c d", "e f"]).encode("utf-8"))
    assert _load_inputs_jsonl(p) == ["a b", "c d", "e f"]


def test_error_line_numbers_are_unchanged(tmp_path: Path) -> None:
    p = tmp_path / "c.jsonl"
    p.write_text(json.dumps("a b", ensure_ascii=False) + "\n\n{bad\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"c\.jsonl:3: invalid JSON"):
        _load_inputs_jsonl(p)


def test_dump_validate_drift_agree_on_the_same_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    examples = [
        Example(
            id=f"q{i}",
            input=text,
            expected_outputs=(ExpectedOutput(kind="exact", value="x"),),
            dataset_version="v1",
            provenance={},
        )
        for i, text in enumerate([*GOLDEN, "Pasted from a doc: second line"])
    ]
    data = tmp_path / "goldens.jsonl"
    Dataset("v1", examples).dump_jsonl(data)
    assert main(["validate", str(data)]) == 0
    rc = main(
        [
            "drift",
            "--golden",
            str(data),
            "--candidate",
            str(data),
            "--output",
            str(tmp_path / "r.html"),
        ]
    )
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "invalid JSON" not in out.err
