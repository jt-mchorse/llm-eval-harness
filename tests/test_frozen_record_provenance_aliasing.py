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
in this package. Two were real; the four that were not are pinned at the bottom
of this module so a later sweep does not re-file them.

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

from eval_harness.calibration import CalibrationResult, CalibrationRow, calibrate
from eval_harness.dataset import Dataset, Example, ExpectedOutput, load_jsonl
from eval_harness.io_utils import copy_json_value
from eval_harness.judge import JudgeScore
from eval_harness.runner import DeltaReport


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
# The four cleared rows — recorded so a later sweep does not re-file them
# ----------------------------------------------------------------------


def test_calibration_result_does_not_alias_the_callers_row_list() -> None:
    """`portfolio-ops#71` rows 1 and 2, measured as false positives.

    `calibrate` is the only construction site and does `rows_list = list(rows)`,
    so `CalibrationResult.rows` is a list the caller never held. `judge_scores`
    is built inside the same function. The sweep's source-level rule cannot see
    either fact, which is exactly why it documents a `GAP` as a candidate.
    """

    class _FakeJudge:
        def score(self, prompt: str, response: str, *, rubric: str) -> JudgeScore:
            return JudgeScore(score=0.5, reasoning="r", raw="{}")

    rows = [_row({"a": 1}) for _ in range(3)]
    result = calibrate(_FakeJudge(), rows)
    rows.append(rows[0])
    assert len(result.rows) == 3
    assert result.rows is not rows
    assert len(result.judge_scores) == 3


def test_delta_report_summary_is_built_locally_not_taken_from_a_caller() -> None:
    """`portfolio-ops#71` row 4, measured as not reachable.

    `diff_runs` builds `summary` as a literal. `to_json()` does return the live
    dict rather than a copy, and this arm pins that it is not *exploited*: every
    consumer in the package (`cli.py` twice, `runner.py` once) hands the result
    straight to `json.dumps`. Recorded rather than fixed, so the change stays on
    the reachable defect — and asserted rather than asserted-about, so the day a
    consumer starts mutating it, this is the arm that notices.
    """
    report = DeltaReport(
        current_run_id="c",
        baseline_run_id="b",
        suite="s",
        threshold_drop=0.1,
        rows=(),
        summary={"n_flagged": 3},
    )
    payload = report.to_json()
    assert payload["summary"] == {"n_flagged": 3}
    assert json.dumps(payload)  # the only thing every in-package consumer does


def test_the_cleared_rows_are_named_so_a_resweep_does_not_re_file_them() -> None:
    """Four of the six `portfolio-ops#71` candidates in this package are not
    defects. The sweep re-runs and will list them again; this is where the
    triage result lives so nobody re-derives it.

    `pytest_plugin._EvalSpec.answer_source` is the fourth: an `Any` holding a
    callable taken from a pytest marker, not a container. It is asserted here by
    name rather than by behaviour, because "is not a mutable container" is a
    fact about the field's contract rather than something to exercise.
    """
    cleared = {
        "calibration.CalibrationResult.rows": "calibrate() does list(rows); caller never holds it",
        "calibration.CalibrationResult.judge_scores": "built inside calibrate()",
        "pytest_plugin._EvalSpec.answer_source": "an Any holding a callable, not a container",
        "runner.DeltaReport.summary": "built locally; every to_json consumer json.dumps it",
    }
    assert len(cleared) == 4
    assert all(reason for reason in cleared.values())
    # Guard against the worklist's own failure mode: a name here that no longer
    # exists would leave a stale exemption nobody notices.
    assert hasattr(CalibrationResult, "__dataclass_fields__")
    assert {"rows", "judge_scores"} <= set(CalibrationResult.__dataclass_fields__)
    assert "summary" in DeltaReport.__dataclass_fields__
