"""A frozen record must not hand out a live handle on its own metadata (#254).

`frozen=True` prevents *rebinding* an attribute. It says nothing about the
object the attribute points at, so a `dict` field is editable in place through
any reference a caller still holds — with no `FrozenInstanceError`, because
nothing is ever rebound.

`dataset.Example` was the repo's best-defended record on this axis and still
had the hole. It copied `provenance` on the way in (`_parse_example`) *and* on
the way out (`to_dict`), and `Dataset.dump_jsonl`'s docstring calls the second
copy "load-bearing rather than incidental". Both were `dict(...)` — one level
deep — and `provenance` is documented free-form JSON. So the copy held for the
mapping and not for anything inside it:

    ex = load_jsonl(path).examples[0]
    out = ex.to_dict()
    out["provenance"]["annotator"]["name"] = "MUTATED"   # the frozen Example
    ds.dump_jsonl(other)                                  # ...and then the file

`calibration.CalibrationRow` had no copy on either side, which made a parity
this module declares repeatedly — "calibration-side analog of
`validate_dataset`", "matching the ordering `dataset._validate_record` settled
on" — false on exactly this field.

Triaged from the `portfolio-ops#71` worklist, which listed **six** candidates
in this package. Two were real; the ones that were not are pinned at the bottom
of this module so a later sweep does not re-file them (three of the four
originally cleared were re-opened by #262 -- see that arm).

The arms below are built so the fix's own defect class cannot pass them: the
central one asserts the copy is deep, because a *shallow* copy is what was
already there.
"""

from __future__ import annotations

import json
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any

import pytest

from eval_harness.calibration import CalibrationRow
from eval_harness.dataset import Dataset, Example, ExpectedOutput, load_jsonl
from eval_harness.io_utils import copy_json_value


def _example(provenance: dict[str, Any]) -> Example:
    return Example(
        id="qa_001",
        input="q",
        expected_outputs=(ExpectedOutput(kind="exact", value="Paris"),),
        dataset_version="v1",
        provenance=provenance,
    )


def _row(provenance: dict[str, Any]) -> CalibrationRow:
    return CalibrationRow(
        id="r1", prompt="p", response="x", rubric="rb", human_score=0.5, provenance=provenance
    )


# ----------------------------------------------------------------------
# The defect, end to end
# ----------------------------------------------------------------------


def test_editing_to_dicts_nested_value_cannot_reach_the_frozen_example() -> None:
    """The shape a shallow copy lets through, asserted at the nesting level.

    A `dict(...)` at this seam passes "did you copy it?" and fails this. That
    distinction is the whole point of the arm: the defect was a shallow copy,
    so an arm that only proves *a* copy happened would be satisfied by the bug.
    """
    ex = _example({"source": "clean", "annotator": {"name": "alice"}})
    out = ex.to_dict()
    assert out["provenance"]["annotator"] is not ex.provenance["annotator"]
    out["provenance"]["annotator"]["name"] = "MUTATED_VIA_TO_DICT"
    assert ex.provenance["annotator"] == {"name": "alice"}


def test_a_nested_edit_through_to_dict_cannot_reach_the_file(tmp_path: Path) -> None:
    """The harm stated as the harm: what `dump_jsonl` actually writes.

    `to_dict()` is not an isolated accessor — it is the record `dump_jsonl`
    serializes. Reading the file back is what makes this an artifact-integrity
    arm rather than an object-identity one.
    """
    ex = _example({"source": "clean", "annotator": {"name": "alice"}})
    ds = Dataset(version="v1", examples=[ex])
    stolen = ex.to_dict()
    stolen["provenance"]["annotator"]["name"] = "MUTATED_VIA_TO_DICT"

    out = tmp_path / "d.jsonl"
    ds.dump_jsonl(out)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["provenance"] == {"source": "clean", "annotator": {"name": "alice"}}


def test_the_constructors_dict_is_not_retained_by_the_caller() -> None:
    """Inbound half, at the nesting level, for both records.

    `Example` is exported in `__all__` and `CalibrationRow` is how `calibrate`
    is fed — it takes an `Iterable[CalibrationRow]` — so hand-construction is
    the ordinary public path for both, not a corner.
    """
    prov: dict[str, Any] = {"annotator": "alice", "nested": {"k": "v"}, "seq": [{"deep": 1}]}
    ex = _example(prov)
    row = _row(prov)

    prov["annotator"] = "bob"
    prov["nested"]["k"] = "INJECTED"
    prov["seq"][0]["deep"] = 999

    expected = {"annotator": "alice", "nested": {"k": "v"}, "seq": [{"deep": 1}]}
    assert ex.provenance == expected
    assert row.provenance == expected


def test_the_loader_path_is_still_protected(tmp_path: Path) -> None:
    """Regression guard on the path that was already safe.

    `_parse_example` did `dict(raw["provenance"])`, so the `load_jsonl` path
    never aliased the caller's *mapping*. The `__post_init__` copy must not
    change what that path produces.
    """
    record = {
        "id": "qa_001",
        "input": "q",
        "dataset_version": "v1",
        "provenance": {"source": "clean", "annotator": {"name": "alice"}},
        "expected_outputs": [{"kind": "exact", "value": "Paris"}],
    }
    path = tmp_path / "d.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    ex = load_jsonl(path).examples[0]
    assert ex.provenance == record["provenance"]


# ----------------------------------------------------------------------
# `copy_json_value`'s own contract
# ----------------------------------------------------------------------


def test_copy_json_value_is_deep_over_dicts_and_lists() -> None:
    original = {"a": {"b": [{"c": 1}]}, "d": [1, [2]]}
    copied = copy_json_value(original)
    assert copied == original
    assert copied["a"] is not original["a"]
    assert copied["a"]["b"] is not original["a"]["b"]
    assert copied["a"]["b"][0] is not original["a"]["b"][0]
    assert copied["d"][1] is not original["d"][1]


@pytest.mark.parametrize(
    "value",
    [
        pytest.param((1, 2), id="tuple"),
        pytest.param({1, 2}, id="set"),
        pytest.param(frozenset({1}), id="frozenset"),
        pytest.param(bytearray(b"ab"), id="bytearray"),
        pytest.param(b"ab", id="bytes"),
    ],
)
def test_copy_json_value_leaves_non_json_containers_by_reference(value: object) -> None:
    """Deliberate, and the `tuple` row is the one that caught a real mistake.

    An earlier draft of `copy_json_value` also recursed into `tuple`. That
    rebuilt a `namedtuple` through `tuple(...)`, which drops its class — so
    `test_dump_refuses_unfaithful_value_type[namedtuple]`, which asserts the
    rejection message names `_Point`, got `tuple` instead and went red.

    Every type in this list is on `dump_jsonl`'s **reject** table with its own
    type named. `set` and `bytearray` are mutable, so leaving them shared looks
    like a gap — it is not one that can reach an artifact, because
    `find_unrepresentable` refuses the record on the way in and `dump_jsonl`
    refuses it on the way out. An aliased value with no writer has no harm to
    name.
    """
    assert copy_json_value(value) is value


@pytest.mark.parametrize(
    ("value", "base"),
    [
        pytest.param(Counter({"a": 1}), dict, id="Counter"),
        pytest.param(OrderedDict(b=1, a=2), dict, id="OrderedDict"),
    ],
)
def test_a_container_subclass_is_normalised_to_its_base(value: object, base: type) -> None:
    """Stated because it is a real trade, not an accident.

    These are on `dump_jsonl`'s **accept** table and must round-trip equal.
    Normalising is safe on exactly that criterion: each compares equal to its
    base and serializes to identical JSON. Rebuilding via `type(value)(...)`
    would preserve the class here and raise for any subclass with a different
    `__init__` signature — worse, at a boundary whose contract is JSON.
    """
    copied = copy_json_value(value)
    assert copied == value
    assert type(copied) is base


def test_the_accept_table_still_round_trips_after_normalisation(tmp_path: Path) -> None:
    """Anti-vacuity for the arm above: prove the normalisation is observable
    nowhere the package promises anything.

    `test_dataset_dump_value_types` asserts these reload *equal*; this checks
    that the `__post_init__` copy sitting in front of that path did not change
    the answer.
    """
    ds = Dataset(version="v1", examples=[_example({"c": Counter({"a": 1}), "o": OrderedDict(b=1)})])
    out = tmp_path / "d.jsonl"
    ds.dump_jsonl(out)
    assert load_jsonl(out).examples[0].provenance == {"c": {"a": 1}, "o": {"b": 1}}


def test_to_dict_no_longer_reshapes_a_non_object_provenance() -> None:
    """`dict(self.provenance)` turned `[]` into `{}` and `[("a", 1)]` into
    `{"a": 1}` — a caller's data reshaped before any rule could object to it.

    `dump_jsonl` still rejects both; what changed is that the value it rejects
    is now the value it was given.
    """
    assert _example([]).to_dict()["provenance"] == []  # type: ignore[arg-type]
    # The inner tuple survives as a tuple, because `copy_json_value` leaves
    # non-JSON containers alone. That is the faithful answer: `dump_jsonl` then
    # rejects it naming `tuple`, instead of `dict(...)` having quietly turned
    # the whole thing into `{"a": 1}` — a well-formed object with nothing left
    # for a rule to object to.
    assert _example([("a", 1)]).to_dict()["provenance"] == [("a", 1)]  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# The cleared row — recorded so a later sweep does not re-file it
# ----------------------------------------------------------------------


def test_the_cleared_row_is_named_so_a_resweep_does_not_re_file_it() -> None:
    """One of the six `portfolio-ops#71` candidates in this package is not a
    defect. The sweep re-runs and will list it again; this is where the triage
    result lives so nobody re-derives it.

    This arm used to clear **four**. Three of them --
    `CalibrationResult.rows`, `CalibrationResult.judge_scores` and
    `DeltaReport.summary` -- were cleared as "built inside `calibrate()`" and
    "built locally by `diff_runs`", which was true of those two functions and
    said nothing about the classes: both are public and hand-built (a caller of
    `render_report` / `render_delta_markdown` constructs one), and
    `DeltaReport.to_json()` handed out the record's own `summary`. They are
    owned now (#262, D-031) and their arms live in
    `tests/test_frozen_record_result_ownership.py`.

    `pytest_plugin._EvalSpec.answer_source` is an `Any` holding a callable taken
    from a pytest marker, not a container. It is asserted by name rather than by
    behaviour, because "is not a mutable container" is a fact about the field's
    contract rather than something to exercise.
    """
    from eval_harness.pytest_plugin import _EvalSpec

    cleared = {
        "pytest_plugin._EvalSpec.answer_source": "an Any holding a callable, not a container",
    }
    assert len(cleared) == 1
    # Guard against the worklist's own failure mode: a name here that no longer
    # exists would leave a stale exemption nobody notices.
    assert "answer_source" in _EvalSpec.__dataclass_fields__
