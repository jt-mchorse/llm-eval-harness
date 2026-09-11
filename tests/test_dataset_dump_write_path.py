"""`dump_jsonl` must not write a record `load_jsonl` would reject (#234, #231).

#213 fixed one side of this seam. `load_jsonl` stopped admitting the two classes
of value the canonical writer cannot faithfully emit, and
`tests/test_dataset_representability.py` pinned it over a table. The writer kept
its docstring sentence — "That guarantee is enforced, not merely asserted" — and
no check: `_validate_record` runs on the *load* path, so it says nothing about a
`Dataset` assembled in Python. `Example` is exported from the package, is a
frozen dataclass with no `__post_init__`, and building goldens programmatically
is the ordinary use of a reusable eval framework.

Measured on `main`, no loader involved:

* ``provenance={"cost_usd": inf}`` was written as a bare ``Infinity`` token and
  `load_jsonl` of the file *just written* raised `DatasetLoadError`.
* ``input="a\\ud800b"`` raised a raw `UnicodeEncodeError` reporting "position
  94" — an offset into the serialized line, naming neither record nor field.
* ``provenance={1: "one"}`` was written ``{"1": "one"}`` **silently** and
  reloaded with the key changed from `int` to `str`. That third shape is why
  #231 had to be fixed here too: the write path is the first caller that can
  hand `find_unrepresentable` a non-string key, and it used to answer with
  `AttributeError: 'int' object has no attribute 'encode'`.

The ACCEPT rows are the anti-vacuous control and are load-bearing in both
directions: a write-side check written too broadly would satisfy every REJECT
row while breaking every real dataset this package writes.
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import json
import math
from pathlib import Path
from typing import Any

import pytest

from eval_harness import dataset as dataset_module
from eval_harness.dataset import Dataset, DatasetLoadError, Example, ExpectedOutput, load_jsonl
from eval_harness.io_utils import _ALL_KINDS, find_unrepresentable

# Built from the codepoint, never written as a literal: `tests/
# test_source_representability.py` refuses a lone surrogate in any source file
# in this repo, and it is right to — a non-docstring literal compiles fine and
# the module then carries a string it cannot itself write out.
LONE = chr(0xD800)


def _example(**overrides: Any) -> Example:
    base: dict[str, Any] = {
        "id": "qa_001",
        "input": "What is the capital of France?",
        "expected_outputs": (ExpectedOutput(kind="exact", value="Paris"),),
        "dataset_version": "factuality-v0.1",
        "provenance": {"source": "public_domain_trivia"},
    }
    base.update(overrides)
    return Example(**base)


def _dataset(**overrides: Any) -> Dataset:
    return Dataset(version="factuality-v0.1", examples=[_example(**overrides)])


def _has_non_string_key(node: Any) -> bool:
    if isinstance(node, dict):
        return any(not isinstance(k, str) for k in node) or any(
            _has_non_string_key(v) for v in node.values()
        )
    if isinstance(node, list):
        return any(_has_non_string_key(v) for v in node)
    return False


# (label, dataset, substring the message must name). The substring is never just
# the word "invalid": each row asserts the message points at the *field*, so a
# guard that rejected everything with one blanket sentence fails the table.
_REJECT: list[tuple[str, Dataset, str]] = [
    ("provenance inf", _dataset(provenance={"cost_usd": math.inf}), "provenance.cost_usd"),
    ("provenance -inf", _dataset(provenance={"cost_usd": -math.inf}), "provenance.cost_usd"),
    ("provenance nan", _dataset(provenance={"score": math.nan}), "provenance.score"),
    (
        "nested inf",
        _dataset(provenance={"run": {"latency": {"p95": math.inf}}}),
        "provenance.run.latency.p95",
    ),
    (
        "inf in a list",
        _dataset(provenance={"samples": [1.0, math.nan]}),
        "provenance.samples[1]",
    ),
    ("surrogate in id", _dataset(id=f"a{LONE}b"), "'id'"),
    ("surrogate in input", _dataset(input=f"a{LONE}b"), "'input'"),
    (
        "surrogate in expected value",
        _dataset(expected_outputs=(ExpectedOutput(kind="exact", value=f"a{LONE}b"),)),
        "expected_outputs[0].value",
    ),
    ("surrogate in dataset_version", _dataset(dataset_version=f"v{LONE}1"), "dataset_version"),
    ("surrogate in a tag", _dataset(tags=(f"a{LONE}b",)), "tags[0]"),
    ("surrogate in provenance value", _dataset(provenance={"src": LONE}), "provenance.src"),
    (
        "surrogate in provenance key",
        _dataset(provenance={f"a{LONE}b": "x"}),
        "object key",
    ),
    ("int provenance key", _dataset(provenance={1: "one"}), "non-string object key"),
    ("bool provenance key", _dataset(provenance={True: "one"}), "non-string object key"),
    ("float provenance key", _dataset(provenance={1.5: "one"}), "non-string object key"),
    ("None provenance key", _dataset(provenance={None: "one"}), "non-string object key"),
    ("tuple provenance key", _dataset(provenance={(1, 2): "x"}), "non-string object key"),
    (
        "nan provenance key",
        _dataset(provenance={math.nan: "x"}),
        "non-string object key",
    ),
    (
        "non-string key nested under a good one",
        _dataset(provenance={"run": {7: "seven"}}),
        "non-string object key",
    ),
]

# Every one of these must keep writing. U+2028, U+0085, NBSP, an astral emoji
# and a NUL are all encodable; a check that rejected "unusual" text rather than
# *unrepresentable* text would pass the table above and break real files.
_ACCEPT: list[tuple[str, Dataset]] = [
    ("plain ascii", _dataset()),
    ("non-ascii latin", _dataset(input="café über")),
    ("astral emoji", _dataset(input="\U0001f389 party")),
    ("valid surrogate pair source", _dataset(input="\U0001f389")),
    ("U+2028 line separator", _dataset(input="a" + chr(0x2028) + "b")),
    ("U+0085 next line", _dataset(input="a" + chr(0x85) + "b")),
    ("U+00A0 no-break space", _dataset(input="a" + chr(0xA0) + "b")),
    ("embedded NUL", _dataset(input="a\x00b")),
    ("newline", _dataset(input="a\nb")),
    ("finite floats at the edges", _dataset(provenance={"big": 1.7976931348623157e308})),
    ("negative zero", _dataset(provenance={"z": -0.0})),
    ("large int", _dataset(provenance={"n": 2**70})),
    ("bool value", _dataset(provenance={"ok": True})),
    ("null value", _dataset(provenance={"missing": None})),
    ("empty provenance", _dataset(provenance={})),
    ("nested containers", _dataset(provenance={"a": [{"b": ["c", 1, None]}]})),
    ("non-ascii key", _dataset(provenance={"caté": "x"})),
    ("tags", _dataset(tags=("geography", "factuality"))),
]


@pytest.mark.parametrize(("label", "ds", "must_name"), _REJECT, ids=[r[0] for r in _REJECT])
def test_dump_jsonl_rejects_what_the_loader_would_reject(
    label: str, ds: Dataset, must_name: str, tmp_path: Path
) -> None:
    out = tmp_path / "goldens.jsonl"
    with pytest.raises(ValueError, match=r"examples\[0\]") as excinfo:
        ds.dump_jsonl(out)
    message = str(excinfo.value)
    assert must_name in message, f"{label}: message does not name the field: {message}"
    assert not out.exists(), f"{label}: rejected dump left a file behind"


@pytest.mark.parametrize(("label", "ds"), _ACCEPT, ids=[r[0] for r in _ACCEPT])
def test_dump_jsonl_accepts_representable_records(label: str, ds: Dataset, tmp_path: Path) -> None:
    out = tmp_path / "goldens.jsonl"
    ds.dump_jsonl(out)
    reloaded = load_jsonl(out)
    assert len(reloaded) == 1
    # Round-trip identity, which is what the guard exists to make true: a
    # constructed dataset dumps, reloads, and dumps to the identical bytes.
    again = tmp_path / "again.jsonl"
    reloaded.dump_jsonl(again)
    assert again.read_bytes() == out.read_bytes(), label


@pytest.mark.parametrize(("label", "ds", "_name"), _REJECT, ids=[r[0] for r in _REJECT])
def test_rejected_dump_leaves_an_existing_destination_byte_identical(
    label: str, ds: Dataset, _name: str, tmp_path: Path
) -> None:
    """Validate-then-write, not write-then-validate.

    A check placed after the serialization loop would still raise, and would
    still pass the rejection table above, while having already replaced the
    operator's previous goldens. This is the row that separates the two.
    """
    out = tmp_path / "goldens.jsonl"
    previous = b'{"id":"kept"}\n'
    out.write_bytes(previous)
    with pytest.raises(ValueError, match=r"examples\[0\]"):
        ds.dump_jsonl(out)
    assert out.read_bytes() == previous, label


def test_a_bad_record_late_in_the_file_writes_nothing_at_all(tmp_path: Path) -> None:
    """Not even the good prefix.

    Serializing lazily and validating per-record as it goes would emit
    examples 0 and 1 before raising on 2 — a truncated file that loads clean
    and is silently missing a row, which is worse than the original defect.
    """
    ds = Dataset(
        version="factuality-v0.1",
        examples=[
            _example(id="a"),
            _example(id="b"),
            _example(id="c", provenance={"cost_usd": math.inf}),
        ],
    )
    out = tmp_path / "goldens.jsonl"
    with pytest.raises(ValueError, match=r"examples\[2\] \(id='c'\)"):
        ds.dump_jsonl(out)
    assert not out.exists()


def test_the_message_names_the_index_and_the_id(tmp_path: Path) -> None:
    ds = Dataset(
        version="factuality-v0.1",
        examples=[_example(id="fine"), _example(id="broken", input=f"a{LONE}b")],
    )
    with pytest.raises(ValueError, match=r"examples\[1\]") as excinfo:
        ds.dump_jsonl(tmp_path / "goldens.jsonl")
    message = str(excinfo.value)
    assert "examples[1]" in message
    assert "id='broken'" in message


def test_an_unprintable_id_does_not_break_the_message_that_reports_it(tmp_path: Path) -> None:
    """The id is itself a candidate for the failure being reported.

    `f"{ex.id!r}"` returns the lone surrogate verbatim, so writing the message
    to a UTF-8 stream raises `UnicodeEncodeError` *from the error path* — the
    exact trap `io_utils._safe_path_segment` exists for, one layer up. The
    assertion is that the message survives an encode, not merely that it is
    raised.
    """
    ds = _dataset(id=f"a{LONE}b")
    with pytest.raises(ValueError, match="not encodable as UTF-8") as excinfo:
        ds.dump_jsonl(tmp_path / "goldens.jsonl")
    message = str(excinfo.value)
    assert LONE not in message
    message.encode("utf-8")  # would raise if the id had been interpolated raw
    assert "\\ud800" in message
    # `UnicodeEncodeError` is itself a `ValueError`, so the unguarded writer
    # raises something this test would otherwise accept — with a byte offset
    # into the serialized line and no record named. Pin the record.
    assert "examples[0]" in message


# --- the seam: reader and writer answer identically -------------------------


@pytest.mark.parametrize(("label", "ds", "_name"), _REJECT, ids=[r[0] for r in _REJECT])
def test_writer_rejects_everything_the_reader_rejects(
    label: str, ds: Dataset, _name: str, tmp_path: Path
) -> None:
    """Parity, over the shapes both sides can express.

    Both halves route through `_find_unrepresentable`, so the interesting
    assertion is not that each rejects its own table but that neither can be
    handed something the other accepts. The non-string-key rows are the one
    asymmetry and it is structural, not an oversight: `json.dumps` coerces such
    a key to a string before any reader sees the file, so the loader *cannot*
    be given one. That asymmetry is asserted below rather than assumed.
    """
    record = ds.examples[0].to_dict()
    path = tmp_path / "from_writer.jsonl"

    # `ensure_ascii=True`, deliberately, and it is the whole reason this test
    # is not a wall of skips: a lone surrogate has no UTF-8 encoding but it has
    # a perfectly ASCII JSON *escape*, `\ud800`, which is exactly the spelling
    # a broken UTF-16 producer upstream emits and the one #213's own fixtures
    # use. Serializing with `ensure_ascii=False` instead would make every
    # surrogate row unwritable and skip the strongest half of the table.
    if _has_non_string_key(record):
        try:
            line = json.dumps(record, ensure_ascii=True)
        except TypeError:
            # `json.dumps` refuses the key outright, so no bytes reach a reader
            # at all — the writer-side rule is the only thing that can report
            # it, and it does, with the field named rather than a bare
            # TypeError out of the serializer.
            return
        path.write_text(line + "\n", encoding="utf-8")
        loaded = load_jsonl(path)
        assert loaded.examples[0].provenance != record["provenance"], (
            f"{label}: expected the key to have been coerced across the round trip"
        )
        return

    line = json.dumps(record, ensure_ascii=True)
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(DatasetLoadError):
        load_jsonl(path)


@pytest.mark.parametrize(("label", "ds"), _ACCEPT, ids=[r[0] for r in _ACCEPT])
def test_reader_accepts_everything_the_writer_accepts(
    label: str, ds: Dataset, tmp_path: Path
) -> None:
    out = tmp_path / "goldens.jsonl"
    ds.dump_jsonl(out)
    load_jsonl(out)


# --- #231: the walk answers with a finding, never with a foreign exception ---


def test_find_unrepresentable_reports_a_non_string_key_instead_of_raising() -> None:
    found = find_unrepresentable({"provenance": {1: "one"}})
    assert found is not None
    path, kind, detail = found
    assert kind == "non_string_key"
    assert path == "provenance"
    assert detail == "1 (int)"


def test_a_non_string_key_at_the_record_root_is_named_not_left_blank() -> None:
    found = dataset_module._find_unrepresentable({1: "one"})
    assert found is not None
    assert found[0] == "(record root)"


@pytest.mark.parametrize(
    "key",
    [1, True, 1.5, None, (1, 2), math.nan, 2**70, frozenset({1}), b"bytes"],
    ids=lambda k: type(k).__name__ + repr(k),
)
def test_every_non_string_key_type_becomes_a_finding(key: Any) -> None:
    found = find_unrepresentable({"p": {key: "v"}})
    assert found is not None
    assert found[1] == "non_string_key"


def test_a_container_key_holding_a_surrogate_does_not_poison_the_message() -> None:
    """`ascii()`, not `repr()`.

    A key can be a *container* of strings, so `repr((LONE,))` puts the
    unencodable character straight back into the detail this function exists
    to keep printable.
    """
    found = find_unrepresentable({"p": {(LONE,): "v"}})
    assert found is not None
    detail = found[2]
    assert LONE not in detail
    detail.encode("utf-8")


def test_a_caller_enforcing_one_axis_still_walks_below_a_non_string_key() -> None:
    """Not enforcing an axis is not the same as abandoning the subtree.

    `calibration._row_from_dict` selects UNENCODABLE only. Skipping the whole
    entry on a non-string key would silently stop it finding surrogates
    underneath one — a guard narrowing from "this axis is off" to "this
    subtree is invisible".
    """
    node = {"p": {1: {"inner": LONE}}}
    found = find_unrepresentable(node, kinds=frozenset({"unencodable"}))
    assert found is not None
    assert found[1] == "unencodable"


@pytest.mark.parametrize(
    "record",
    [
        {"a": {1: "one"}},
        {"a": {(1, 2): "x"}},
        {"a": [{"b": {None: 1}}]},
        {"a": {b"k": 1}},
        {"a": {frozenset(): 1}},
        {"a": {1: LONE}},
        {"a": {LONE: 1}},
        {"a": {1: math.inf}},
    ],
)
@pytest.mark.parametrize(
    "kinds",
    [
        frozenset({"unencodable"}),
        frozenset({"non_finite"}),
        frozenset({"non_string_key"}),
        _ALL_KINDS,
        frozenset(),
    ],
)
def test_the_walk_never_raises_a_foreign_exception(
    record: dict[str, Any], kinds: frozenset[str]
) -> None:
    """The contract #231 was filed against.

    The walk's own docstring justifies being iterative because a
    `RecursionError` "is not a `ValueError`, so it would escape a caller's
    `except ValueError` and abort a collecting validation pass instead of
    becoming one finding". An `AttributeError` did exactly that by a different
    road. This asserts the general property over every axis selection, not
    only the one the fix was written against.
    """
    # A `ValueError` is in contract — `find_unrepresentable` does not raise one
    # today, but a caller's `except ValueError` absorbs it, so it is not the
    # failure this asserts against. Anything else escapes and propagates here.
    with contextlib.suppress(ValueError):
        find_unrepresentable(record, kinds=kinds)


# --- structural: one definition, not two ------------------------------------


def _string_literals(module: Any) -> list[str]:
    """Every `str` constant in *module* that is not a docstring."""
    tree = ast.parse(inspect.getsource(module))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _dump_jsonl_ast() -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(dataset_module))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "dump_jsonl":
            return node
    raise AssertionError("dump_jsonl not found in eval_harness/dataset.py")


def test_dump_jsonl_calls_the_shared_walk_rather_than_restating_the_rules() -> None:
    """The neighbour this catches passes every behavioural test above.

    Copying the checks into `dump_jsonl` — an `isfinite` here, an `encode`
    there — satisfies the whole rejection table, the whole accept table and
    every message assertion, and re-creates precisely the drift that produced
    #213 and then #234: two paths describing each other instead of sharing a
    rule.
    """
    called = {
        node.func.id
        for node in ast.walk(_dump_jsonl_ast())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_find_unrepresentable" in called
    for restated in ("isfinite", "find_unencodable", "find_unrepresentable"):
        assert restated not in called, f"dump_jsonl restates the rule via {restated}"


@pytest.mark.parametrize(
    "fragment",
    [
        "is not encodable as UTF-8",
        "dataset values must be finite",
        "has the non-string object key",
        "which `json.dumps` cannot emit faithfully",
    ],
)
def test_each_reason_is_written_once(fragment: str) -> None:
    """Counted over string *literals*, not over the file's text.

    `dataset.py`'s module comment explains the surrogate class in prose and
    happens to contain the same words, so a `source.count(...)` lock fires on
    the paragraph documenting the fix. Parse, do not grep: comments are not in
    the AST, and docstrings are excluded explicitly.
    """
    hits = [text for text in _string_literals(dataset_module) if fragment in text]
    assert len(hits) == 1, f"{fragment!r} appears in {len(hits)} string literals"


def test_every_kind_the_walk_can_return_has_a_reason() -> None:
    """Discovered from `_ALL_KINDS`, not listed here.

    A hand-written list would keep passing when a fourth axis is added and left
    unhandled — the fallthrough this function raises on. The floor asserts the
    discovery found something, so a rename cannot make this test vacuous.
    """
    assert len(_ALL_KINDS) >= 4
    samples: dict[str, dict[str, Any]] = {
        "unencodable": {"f": LONE},
        "non_finite": {"f": math.inf},
        "non_string_key": {"f": {1: "x"}},
        # #238. This lock is what caught the fourth axis arriving: the sample
        # set was 3 and `_ALL_KINDS` became 4, so the run went red at the
        # discovery rather than at some later caller printing a wrong sentence.
        "unserializable_type": {"f": (1, 2)},
    }
    assert set(samples) == set(_ALL_KINDS), (
        "a representability kind has no sample here; add one and a reason in "
        "dataset._find_unrepresentable"
    )
    for kind, record in samples.items():
        found = dataset_module._find_unrepresentable(record)
        assert found is not None, kind
        assert found[1], kind


def test_the_scope_boundary_moved_to_the_expected_output_item_type(tmp_path: Path) -> None:
    """Where the boundary is NOW, updated rather than deleted (#235).

    This test used to assert the opposite: that `dump_jsonl` enforced
    representability only, so `Example(id=123)` wrote a file `load_jsonl`
    refused. #235 moved the line — the schema is enforced on both sides now,
    from the same `_FIELD_RULES` and the same `_DatasetInvariants`.

    What is still asymmetric, deliberately, is the per-item
    `ExpectedOutput` rule, because the two sides have different domains: the
    loader receives JSON objects and constructs `ExpectedOutput`s from them, so
    `__post_init__` validates `kind`/`value` there; this side already holds
    instances. The writer therefore has its own rule for the one thing it can
    be handed that the loader cannot — a non-`ExpectedOutput` item — and does
    not restate `kind`/`value` validation that construction already did.

    Leaving the boundary undeclared is how the next reader concludes the write
    path is fully guarded when it is not, so it is asserted from both ends.
    """
    # The moved half: what used to write now refuses, before any bytes.
    out = tmp_path / "goldens.jsonl"
    with pytest.raises(ValueError, match="'id' must be a non-empty string"):
        Dataset(version="v1", examples=[_example(id=123)]).dump_jsonl(out)
    assert not out.exists()

    # The half that stays asymmetric: `kind`/`value` are validated at
    # construction, so the writer does not re-check them...
    with pytest.raises(ValueError, match="invalid expected_output kind"):
        ExpectedOutput(kind="nope", value="x")

    # ...but a non-`ExpectedOutput` item is the writer's own domain, and it
    # raises this package's `ValueError` rather than reaching `to_dict()` as a
    # bare `AttributeError`.
    ds = Dataset(version="v1", examples=[_example(expected_outputs=(1,))])
    with pytest.raises(ValueError, match="must be an ExpectedOutput"):
        ds.dump_jsonl(out)
    assert not out.exists()
