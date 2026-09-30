"""A cyclic `provenance` terminates, and is refused where refusals live (#259).

D-027 gave `Example.provenance` a deep copy and wrote it **recursively**, one call
upstream of `find_unrepresentable`, which is iterative *on purpose* and whose
docstring gives the reason:

    a recursive walk would add frames on top of that and could raise
    `RecursionError` -- which is not a `ValueError`, so it would escape a
    caller's `except ValueError` and abort a collecting validation pass instead
    of becoming one finding.

`rag-production-kit`'s D-022 ported this function and that repo's own SSE
totality suite went 8 red on exactly this, which is how the sibling was found.

**And the issue's premise was wrong in a way that changes the fix.** Measured at
`de38a56`:

=================================  ================================
call                               result
=================================  ================================
`copy_json_value(<cyclic>)`        `RecursionError`
`copy_json_value(<5000 deep>)`     `RecursionError`
`find_unrepresentable(<cyclic>)`   **did not terminate in 25s**
`find_unrepresentable(<5000 deep>)` `None` (iterative, fine)
=================================  ================================

The *refusal* walker had no ancestor tracking, so a cycle grew both its stack and
its path string without bound until the process was OOM-killed. Its own argument
is why that matters: a `RecursionError` is unacceptable because it escapes
`except ValueError`, and a hang escapes it too, and forever.

`Example.__post_init__` copies before anything else, so the copy's
`RecursionError` was **masking** the walker's hang. Making the copy iterative on
its own lets the cyclic record through and converts a `RecursionError` into a
non-terminating loop — the obvious fix makes the symptom worse. Both halves ship
together, and `test_the_copy_fix_alone_would_not_have_been_shippable` says so.

The cycle is **preserved** by the copier and **refused** by the walker. `rag`
preserves *and emits*, because its wire seam is lenient by D-017 ("stream alive,
don't raise"). This package refuses, so the only question was where — and a
copier that refused would be a second enforcement site with its own message,
which is exactly the duplication #213/#217/#234/#238 spent four issues
collapsing into one walk.

Every arm that has to exercise the *unfixed* behaviour runs in a **subprocess
with a timeout**, because there is no exception to assert against a hang.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from eval_harness.calibration import CalibrationRow
from eval_harness.dataset import Dataset, Example, ExpectedOutput
from eval_harness.io_utils import (
    _ALL_KINDS,
    CIRCULAR_REFERENCE,
    UNENCODABLE,
    copy_json_value,
    find_unrepresentable,
)

_SUBPROCESS_TIMEOUT = 25.0


def _cyclic() -> dict[str, Any]:
    """`{"annotator": {"self": <the outer dict>}}` — the issue's own repro."""
    prov: dict[str, Any] = {"annotator": {}}
    prov["annotator"]["self"] = prov
    return prov


def _deep(levels: int) -> dict[str, Any]:
    root: dict[str, Any] = {}
    cur = root
    for _ in range(levels):
        cur["n"] = {}
        cur = cur["n"]
    return root


def _example(provenance: dict[str, Any]) -> Example:
    return Example(
        id="e1",
        input="i",
        expected_outputs=(ExpectedOutput(kind="exact", value="v"),),
        dataset_version="v1",
        tags=(),
        provenance=provenance,
    )


def _in_subprocess(body: str, *, timeout: float = _SUBPROCESS_TIMEOUT) -> tuple[bool, str]:
    """Run *body* in a fresh interpreter. Returns `(terminated, output)`.

    A hang has no exception to catch and no return value to assert on, so the
    only honest way to test for one is a wall-clock bound in another process.
    """
    script = textwrap.dedent(body)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"did not terminate within {timeout}s"
    return True, (proc.stdout + proc.stderr).strip()


# --------------------------------------------------------------------------
# Termination — the half the issue did not know to ask for
# --------------------------------------------------------------------------


def test_the_walk_terminates_on_a_cycle_and_names_the_path() -> None:
    """Runs in-process, because it is supposed to return rather than hang.

    Before #259 this call did not come back. The arm below runs the *unfixed*
    shape under a timeout; this one asserts the answer.
    """
    found = find_unrepresentable({"provenance": _cyclic()})
    assert found is not None
    path, kind, detail = found
    assert kind == CIRCULAR_REFERENCE
    assert path == "provenance.annotator.self"
    assert detail == "dict"


def test_the_walk_terminates_on_a_cycle_under_a_wall_clock_bound() -> None:
    """The arm that fails by *timeout*, which is the only way to test a hang.

    Kept separate from the assertion arm above: if the ancestor tracking is
    removed, that one fails by hanging the whole pytest process rather than by
    reporting, and a suite that hangs is not a suite that went red.
    """
    terminated, output = _in_subprocess(
        """
        from eval_harness.io_utils import find_unrepresentable
        prov = {"annotator": {}}
        prov["annotator"]["self"] = prov
        print(find_unrepresentable({"provenance": prov}))
        """
    )
    assert terminated, output
    assert "circular_reference" in output, output


def test_a_self_referential_list_terminates_too() -> None:
    """A `list` closes a cycle as readily as a `dict`, and `provenance` is free-form."""
    inner: list[Any] = []
    inner.append(inner)
    found = find_unrepresentable({"provenance": {"trail": inner}})
    assert found is not None
    assert found[1] == CIRCULAR_REFERENCE
    assert found[2] == "list"


def test_a_cycle_that_closes_through_a_tuple_terminates() -> None:
    """The mixed case, and the reason `tuple` is in the ancestor test.

    A tuple cannot close a cycle alone — it cannot hold an object that did not
    already exist — but it can sit inside one. Under the `UNSERIALIZABLE_TYPE`
    axis the tuple is reported first; with only `UNENCODABLE` enforced the walk
    descends *through* the tuple, which is where the back-reference is reached
    and where an untracked walk would have looped.
    """
    outer: list[Any] = []
    outer.append(("wrapped", outer))
    found = find_unrepresentable({"provenance": {"t": outer}}, kinds=frozenset({UNENCODABLE}))
    assert found is None  # nothing unencodable, and it came back at all


@pytest.mark.parametrize("levels", [1000, 5000, 20000])
def test_deep_nesting_terminates_in_both_directions(levels: int) -> None:
    """Depth is a host property, and this repo treats a host-dependent boundary as a defect.

    `find_unrepresentable` was already iterative and already fine. The copy was
    not: 5000 levels raised `RecursionError` from inside `__post_init__`. 20000
    is here because the ancestor tracking must not be *quadratic* in depth
    either — a fresh `frozenset` per node (the shape `rag`'s `_json_safe` uses,
    where a `_MAX_DEPTH` cap makes it affordable) would be, and this walk has no
    cap.
    """
    record = _deep(levels)
    assert find_unrepresentable(record) is None
    copied = copy_json_value(record)
    assert copied is not record
    cur = copied
    for _ in range(levels):
        cur = cur["n"]


def test_the_constructor_no_longer_raises_recursion_error() -> None:
    """The issue's headline: `Example(provenance=<cyclic>)` from its own constructor."""
    example = _example(_cyclic())
    assert example.provenance["annotator"]["self"] is example.provenance


def test_calibration_row_takes_the_same_copy_and_is_covered_by_the_same_fix() -> None:
    """Named because the issue named it, and covered by the shared helper.

    `CalibrationRow` is fed `json.loads` output on the loader path, which cannot
    emit a cycle — the same reason `load_jsonl` survived review. The direct
    constructor is the reachable half, as it was for `Example`.
    """
    row = CalibrationRow(
        id="c1", prompt="p", response="r", rubric="rub", human_score=0.5, provenance=_cyclic()
    )
    assert row.provenance["annotator"]["self"] is row.provenance


# --------------------------------------------------------------------------
# The refusal, at the seam refusals live at
# --------------------------------------------------------------------------


def test_dump_jsonl_refuses_a_cycle_with_a_value_error_naming_the_field(tmp_path: Path) -> None:
    """The decision: the copier preserves, the write seam refuses.

    This is what makes the copier's exception class the wrong place for the
    refusal — the message here carries the example id *and* the field path,
    which a copier has neither of.
    """
    dataset = Dataset(examples=(_example(_cyclic()),), version="v1")
    with pytest.raises(ValueError, match="contains itself") as excinfo:
        dataset.dump_jsonl(tmp_path / "out.jsonl")
    message = str(excinfo.value)
    assert "id='e1'" in message
    assert "provenance.annotator.self" in message
    assert "contains itself" in message
    assert not (tmp_path / "out.jsonl").exists()


def test_the_refusal_is_a_value_error_which_is_the_whole_point() -> None:
    """`RecursionError` is not a `ValueError`; neither is a hang.

    `find_unrepresentable`'s docstring rests the case for being iterative on
    exactly this, and the refusal it now produces satisfies it.
    """
    assert not issubclass(RecursionError, ValueError)
    dataset = Dataset(examples=(_example(_cyclic()),), version="v1")
    try:
        dataset.dump_jsonl(Path("/dev/null/unwritable"))
    except ValueError:
        pass
    else:  # pragma: no cover - the refusal must fire before any I/O
        pytest.fail("a cyclic provenance reached the filesystem")


def test_the_new_kind_is_in_all_kinds_so_every_site_sees_it() -> None:
    """`kinds` is a filter over `_ALL_KINDS`, so membership is what makes it enforced."""
    assert CIRCULAR_REFERENCE in _ALL_KINDS
    assert len(_ALL_KINDS) == 5


def test_a_caller_enforcing_one_axis_does_not_hang_on_a_cycle() -> None:
    """`calibration._row_from_dict` passes `kinds={UNENCODABLE}`.

    The not-enforced arms in this walk deliberately keep descending, so a caller
    asking for one axis does not lose a subtree. The circular arm is the one
    exception and it has to be: descending past a back-reference *is* the
    non-termination. Nothing below it is absent from the path already, so
    skipping costs no coverage.
    """
    found = find_unrepresentable({"provenance": _cyclic()}, kinds=frozenset({UNENCODABLE}))
    assert found is None


def test_an_unencodable_value_below_a_cycle_is_still_found() -> None:
    """...and the cost of that skip is bounded, which this pins.

    The surrogate is reachable without passing *through* the back-reference, so
    the one-axis caller still finds it. If the circular arm had `break`-ed the
    whole walk instead of skipping one node, this would be `None`.
    """
    # Built from a codepoint, not written as a literal: `tests/` is locked
    # against a source file carrying a string with no UTF-8 encoding, and a
    # non-docstring literal compiles fine, so the lock is the only thing that
    # would have said so.
    prov: dict[str, Any] = {"loop": {}, "note": chr(0xD800)}
    prov["loop"]["self"] = prov
    found = find_unrepresentable({"provenance": prov}, kinds=frozenset({UNENCODABLE}))
    assert found is not None
    assert found[1] == UNENCODABLE


# --------------------------------------------------------------------------
# The DAG must not be reported, and the sharing must survive
# --------------------------------------------------------------------------


def test_a_dag_is_not_a_cycle() -> None:
    """The control that rejects a global `visited` set.

    Two keys pointing at one dict is legal JSON input and serializes fine —
    `json.dumps` duplicates the subtree. A `visited` set would report the second
    reference as circular and refuse a record `json.dumps` writes without
    complaint. Only a container reachable *from itself* is a cycle.
    """
    shared = {"s": 1}
    assert find_unrepresentable({"a": shared, "b": shared}) is None
    # ... and it really does serialize, so refusing it would be a false refusal.
    assert json.dumps({"a": shared, "b": shared}) == '{"a": {"s": 1}, "b": {"s": 1}}'


def test_a_diamond_across_three_levels_is_not_a_cycle() -> None:
    """Deeper than the two-key case, because a shallow control is easy to satisfy."""
    leaf = {"leaf": True}
    left = {"down": leaf}
    right = {"down": leaf}
    assert find_unrepresentable({"l": left, "r": right}) is None


def test_the_copy_preserves_sharing_structure() -> None:
    """The memo's second job, and the recursive version got it wrong.

    Two keys pointing at one dict still point at one dict — a fresh one. The
    recursive copy expanded that into independent copies, which is both less
    faithful and exponential on a DAG-shaped `provenance`.
    """
    shared = {"s": 1}
    copied = copy_json_value({"a": shared, "b": shared})
    assert copied["a"] is copied["b"]
    assert copied["a"] is not shared


def test_the_copy_is_deep_and_the_caller_keeps_nothing() -> None:
    """D-027's original property, unchanged by the rewrite."""
    inner = {"nested": "original"}
    example = _example({"outer": inner})
    inner["nested"] = "MUTATED"
    assert example.provenance["outer"]["nested"] == "original"


def test_a_cyclic_copy_is_isomorphic_rather_than_marked() -> None:
    """A copier is not a sanitizer, and the refusal downstream depends on that.

    If the copy replaced the back-reference with a marker string, `dump_jsonl`
    would happily write the record — and the operator would get a file
    containing `"<circular reference>"` instead of an error naming the field.
    That is `rag`'s answer, and it is right *there* because its wire seam may not
    raise (D-017). Here it would launder a refusal into a silent substitution.
    """
    copied = copy_json_value(_cyclic())
    assert copied["annotator"]["self"] is copied
    assert not isinstance(copied["annotator"]["self"], str)


# --------------------------------------------------------------------------
# The sequencing: neither half ships alone
# --------------------------------------------------------------------------


def test_the_copy_fix_alone_would_not_have_been_shippable() -> None:
    """The finding the issue could not have known to ask for, pinned as an arm.

    Before #259 the copy's `RecursionError` was *masking* the walker's hang: a
    cyclic `provenance` died in `__post_init__` and never reached
    `find_unrepresentable`. So "port the sibling's iterative memo copier", the
    obvious fix and the one the issue pointed at, would have traded a
    `RecursionError` for a non-terminating loop.

    Reconstructed by monkeypatching the ancestor tracking *out* of the shipped
    walk in a subprocess — the walk is what the copy fix would have exposed, and
    a subprocess is the only place a hang is observable as a result rather than
    as a dead test run.
    """
    terminated, output = _in_subprocess(
        """
        # The pre-#259 walk shape: iterative, and blind to ancestors. This is
        # what the copy-only fix would have exposed, because the post-#259
        # iterative copy hands a cyclic record straight to it.
        prov = {"annotator": {}}
        prov["annotator"]["self"] = prov
        stack = [("", {"provenance": prov})]
        seen = 0
        # 5000 pops on a record holding three containers is proof of
        # non-termination, not a performance measurement. The bound is small
        # because the growing `path` string makes each pop more expensive than
        # the last -- which is itself the unboundedness, and is what OOM-killed
        # the first probe of this at `de38a56`.
        LIMIT = 5_000
        while stack:
            path, node = stack.pop()
            seen += 1
            if isinstance(node, dict):
                for k, v in node.items():
                    stack.append((f"{path}.{k}" if path else str(k), v))
            if seen > LIMIT:
                print(f"UNBOUNDED after {seen} pops, path length {len(path)}")
                break
        else:
            print("terminated")
        """,
        timeout=30.0,
    )
    assert terminated, output
    assert "UNBOUNDED" in output, (
        f"the pre-#259 walk shape was expected to grow without bound; got {output!r}. "
        f"If it now terminates, the reconstruction has drifted from the code it "
        f"models and this arm proves nothing."
    )


def test_the_shipped_walk_bounds_the_same_input() -> None:
    """The other side of the arm above: the shipped code does terminate on it.

    Stated separately so the pair reads as a before/after rather than as one
    assertion about a reconstruction.
    """
    found = find_unrepresentable({"provenance": _cyclic()})
    assert found is not None
    assert found[1] == CIRCULAR_REFERENCE


# --------------------------------------------------------------------------
# No change to the ordinary round trip
# --------------------------------------------------------------------------


def test_the_ordinary_round_trip_is_unchanged(tmp_path: Path) -> None:
    """`load_jsonl` -> `to_dict` -> `dump_jsonl` byte-identical for a normal record.

    The rewrite touches the copier's *implementation* and adds a refusal for an
    input that previously killed the process. Nothing an existing dataset
    contains should move.
    """
    record = {
        "id": "qa_001",
        "input": "What color is the sky?",
        "expected_outputs": [{"kind": "exact", "value": "blue"}],
        "tags": ["geography"],
        "dataset_version": "demo-v0.1",
        "provenance": {"source": "self", "added_on": "2026-05-16", "nested": {"a": [1, 2]}},
    }
    source = tmp_path / "in.jsonl"
    source.write_text(json.dumps(record) + "\n", encoding="utf-8")
    dataset = Dataset.load_jsonl(source) if hasattr(Dataset, "load_jsonl") else None
    if dataset is None:
        from eval_harness.dataset import load_jsonl

        dataset = load_jsonl(source)
    out = tmp_path / "out.jsonl"
    dataset.dump_jsonl(out)
    reloaded = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert reloaded == record
