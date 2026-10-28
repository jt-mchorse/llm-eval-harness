"""`dump_jsonl` names the example when an integer is too long to write (#451).

The docstring promises a `ValueError` naming the example's index, its `id` and
the field. #430 kept that promise for nesting the encoder cannot reach; an int
longer than `sys.get_int_max_str_digits()` still escaped as the encoder's own
message ("Exceeds the limit (4300 digits) for integer string conversion"),
naming no example. `loads_json` refuses the same literal on the way in (#365),
so the file could not have been read back either.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from eval_harness.dataset import Dataset, Example, ExpectedOutput, load_jsonl

EXISTING = "existing content, must survive\n"
LIMIT = sys.get_int_max_str_digits()


def _example(ex_id: str, provenance: dict[str, Any]) -> Example:
    return Example(
        id=ex_id,
        input="hi",
        expected_outputs=(ExpectedOutput("exact", "hi"),),
        dataset_version="v1",
        provenance=provenance,
    )


@pytest.fixture(autouse=True)
def _a_limit_is_set() -> None:
    assert LIMIT > 0, "the int/str limit is disabled on this interpreter"


@pytest.mark.parametrize(
    "provenance",
    [
        {"n": 10**LIMIT},  # LIMIT + 1 digits
        {"n": -(10**LIMIT)},
        {"outer": {"inner": [1, 2, 10**5000]}},
    ],
    ids=["top", "negative", "nested"],
)
def test_an_over_limit_int_is_refused_naming_the_example(tmp_path: Path, provenance) -> None:
    out = tmp_path / "d.jsonl"
    out.write_text(EXISTING)
    ds = Dataset(version="v1", examples=[_example("ok", {}), _example("big", provenance)])
    with pytest.raises(ValueError, match=r"examples\[1\] \(id='big'\): field 'provenance'"):
        ds.dump_jsonl(out)
    assert out.read_text() == EXISTING


def test_the_message_names_the_limit_and_is_not_the_encoders() -> None:
    ds = Dataset(version="v1", examples=[_example("big", {"n": 10**LIMIT})])
    with pytest.raises(ValueError, match="examples") as ei:
        ds.dump_jsonl("/nonexistent/never-written.jsonl")
    msg = str(ei.value)
    assert f"{LIMIT}-digit limit" in msg
    assert "Exceeds the limit" not in msg


def test_an_int_at_the_limit_still_round_trips(tmp_path: Path) -> None:
    """Control: exactly LIMIT digits is writable and readable."""
    out = tmp_path / "d.jsonl"
    at_limit = 10 ** (LIMIT - 1)
    assert len(str(at_limit)) == LIMIT
    Dataset(version="v1", examples=[_example("edge", {"n": at_limit})]).dump_jsonl(out)
    assert load_jsonl(out).examples[0].provenance == {"n": at_limit}
