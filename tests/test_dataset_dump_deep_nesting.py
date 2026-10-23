"""`dump_jsonl` refuses a value too deep to encode with `ValueError`, not `RecursionError` (#430).

The docstring promises `ValueError` naming the example's index, its `id` and
the field. A `provenance` of 20000 nested lists raised a raw `RecursionError`
from `json.dumps` instead -- on 3.11 *and* 3.12, the interpreters CI runs --
which escapes a caller's `except ValueError`. `Example(...)` accepts the value,
so nothing earlier refuses it.

The depth at which the encoder gives up is the interpreter's (about 1000 on
3.11, 10000 on 3.12; 3.14 writes 20000 levels), so the primary arm patches
`json.dumps` to raise `RecursionError` for one marked record. That arm is red
against the unfixed code on every interpreter. The real-depth arm runs the
issue's repro where the encoder really overflows, and skips -- loudly, through
its precondition -- where it does not.

Controls: a moderately nested `provenance` still round-trips, and the patched
encoder passes every unmarked record through untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from eval_harness.dataset import Dataset, Example, ExpectedOutput, load_jsonl

# The marker the patched encoder overflows on. A string, not an object
# identity: `Example.to_dict` deep-copies `provenance`, so identity is lost.
MARKER = "__too_deep_to_encode__"

# Fails on 3.11 (~1000) and 3.12 (~10000). Kept at 12000 because that is all
# the arm needs. It used to be a memory cap too: `find_unrepresentable` built a
# path string per level, quadratic in depth (~250 MB here), until #432 made it
# linear (`tests/test_find_unrepresentable_path_memory.py`).
REAL_DEPTH = 12_000

# Well under every interpreter's limit, including 3.11 inside pytest's stack.
MODERATE_DEPTH = 200

EXISTING = "existing content, must survive\n"


def _nest(depth: int, leaf: Any = 1) -> Any:
    v = leaf
    for _ in range(depth):
        v = [v]
    return v


def _example(ex_id: str, provenance: dict[str, Any]) -> Example:
    return Example(
        id=ex_id,
        input="hi",
        expected_outputs=(ExpectedOutput("exact", "hi"),),
        dataset_version="v1",
        provenance=provenance,
    )


@pytest.fixture
def overflowing_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    """`json.dumps` raising `RecursionError` on any value that carries MARKER."""
    real = json.dumps

    def fake(obj: Any, *args: Any, **kwargs: Any) -> str:
        if MARKER in repr(obj):
            raise RecursionError("maximum recursion depth exceeded while encoding a JSON object")
        return real(obj, *args, **kwargs)

    monkeypatch.setattr(json, "dumps", fake)


def test_an_encoder_recursion_error_is_a_value_error_naming_index_id_and_field(
    tmp_path: Path, overflowing_encoder: None
) -> None:
    dest = tmp_path / "d.jsonl"
    dest.write_text(EXISTING, encoding="utf-8")
    ds = Dataset(
        version="v1",
        examples=[_example("ok", {"src": "a"}), _example("deep", {"p": [MARKER]})],
    )
    with pytest.raises(ValueError, match="nested too deep") as info:
        ds.dump_jsonl(dest)
    msg = str(info.value)
    assert "examples[1] (id='deep')" in msg
    assert "field 'provenance'" in msg
    assert "nested too deep" in msg
    # Nothing written: the destination is exactly what it was.
    assert dest.read_text(encoding="utf-8") == EXISTING


def test_the_issue_repro_raises_value_error_at_real_depth(tmp_path: Path) -> None:
    deep = _nest(REAL_DEPTH)
    try:
        json.dumps({"provenance": {"p": deep}})
    except RecursionError:
        pass
    else:
        pytest.skip(
            f"this interpreter's encoder handles {REAL_DEPTH} levels; the patched arm covers it"
        )
    dest = tmp_path / "d.jsonl"
    dest.write_text(EXISTING, encoding="utf-8")
    ds = Dataset(version="v1", examples=[_example("b", {"p": deep})])
    with pytest.raises(ValueError, match=r"examples\[0\] \(id='b'\): field 'provenance'"):
        ds.dump_jsonl(dest)
    assert dest.read_text(encoding="utf-8") == EXISTING


def test_control_a_moderately_nested_provenance_round_trips(tmp_path: Path) -> None:
    dest = tmp_path / "d.jsonl"
    prov = {"p": _nest(MODERATE_DEPTH)}
    Dataset(version="v1", examples=[_example("b", prov)]).dump_jsonl(dest)
    assert load_jsonl(dest).examples[0].provenance == prov


def test_control_the_patched_encoder_passes_unmarked_records_through(
    tmp_path: Path, overflowing_encoder: None
) -> None:
    dest = tmp_path / "d.jsonl"
    prov = {"src": "a", "nested": {"k": [1, 2]}}
    Dataset(version="v1", examples=[_example("b", prov)]).dump_jsonl(dest)
    assert load_jsonl(dest).examples[0].provenance == prov
