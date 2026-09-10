"""`dump_jsonl` refuses a value whose *type* JSON cannot carry faithfully (#238).

`find_unrepresentable` type-checked a record's **keys** — that is what
`NON_STRING_KEY` is — and only three *axes* of its **values**: is this string
encodable, is this float finite, is this key a string. A value of any other
type fell straight through the walk, so the canonical writer had both of the
harms that arm's own docstring names for keys, on the value side, with neither
closed.

Measured on `5276777` (i.e. with #235 merged), building a `Dataset` in Python,
dumping, and reloading with this package's own loader:

    provenance={"k": (1, 2)}          ROUND-TRIPPED -> {'k': [1, 2]}   NOT equal
    provenance={"k": {"n": ("a","b")}} ROUND-TRIPPED -> {'k': {'n': ['a','b']}}
    provenance={"k": {1, 2}}          TypeError: Object of type set is not ...
    provenance={"k": frozenset({1})}  TypeError: ... frozenset ...
    provenance={"k": b"ab"}           TypeError: ... bytes ...
    provenance={"k": date(2026,1,1)}  TypeError: ... date ...
    provenance={"k": mappingproxy}    TypeError: ... mappingproxy ...
    provenance={"k": Decimal("1.5")}  TypeError: ... Decimal ...
    provenance={"k": object()}        TypeError: ... object ...

The tuple rows are the sharp ones and the reason this is a *type* check. A
tuple serializes without erroring, so no exception fires, the file validates,
the line reloads — and the value that comes back is a `list`. That is the
round-trip identity `dump_jsonl`'s own docstring exists to guarantee, broken
silently. It is not an exotic input in this dataclass either:
`Example.expected_outputs` and `Example.tags` are both **declared as tuples**,
so a tuple-valued `provenance` entry is the house idiom, and `provenance` is
documented free-form (`dict[str, Any]`) — the one field where an arbitrary
Python object is the ordinary input.

The seven `TypeError` rows are the shape this module has now fixed three times:
#231 (an `AttributeError` from `k.encode` on an int key), #235 (a
non-`ExpectedOutput` item reaching `to_dict()` as an `AttributeError`), and
this. None of them is a `ValueError`, so none is caught by a caller's
`except ValueError`, and none names the example, the id or the field.

The ACCEPT rows are the anti-vacuous control and are load-bearing in both
directions. Five of them are *subclasses* of faithful types — `Counter`,
`OrderedDict`, `IntEnum`, a `str` subclass, a `list` subclass — and all five
round-trip **equal** through this writer (measured), so all five must pass.
Only one of them, the `IntEnum`, actually reaches the new type check; the
other four are consumed by the `isinstance` arms above it. That split is what
`test_the_faithful_set_is_enforced_by_two_arms_that_have_to_agree` pins, and
it is written down because I got it wrong first: the obvious claim is that an
identity test would refuse all five, and when the neighbour was built and run
it was red on one.

Both plausible wrong fixes were built and run against this file:

    except TypeError around json.dumps   ->  9 of 14 REJECT rows pass; red on
                                             exactly the five tuple-shaped
                                             ones, which are the point
    type(v) in _FAITHFUL_JSON_TYPES      ->  red on 2 tests, both IntEnum
"""

from __future__ import annotations

import datetime
import decimal
import enum
from collections import Counter, OrderedDict, namedtuple
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from eval_harness.dataset import Dataset, Example, ExpectedOutput, load_jsonl
from eval_harness.io_utils import (
    _ALL_KINDS,
    _FAITHFUL_JSON_TYPES,
    UNSERIALIZABLE_TYPE,
    find_unrepresentable,
)


class _Level(enum.IntEnum):
    HIGH = 2


class _MyStr(str):
    pass


class _MyList(list):
    pass


_Point = namedtuple("_Point", "x y")


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


# (label, provenance, the JSON path the message must name, the type name it
# must name). Asserting the *path* and the *type* — never just "it raised" —
# is what separates this from a blanket refusal: a guard that rejected every
# provenance with one sentence would satisfy "raises ValueError" on all eleven
# rows and fail every row here.
REJECT: list[tuple[str, dict[str, Any], str, str]] = [
    ("tuple", {"k": (1, 2)}, "provenance.k", "tuple"),
    ("tuple nested in dict", {"k": {"n": ("a", "b")}}, "provenance.k.n", "tuple"),
    ("tuple nested in list", {"k": [("a",)]}, "provenance.k[0]", "tuple"),
    ("empty tuple", {"k": ()}, "provenance.k", "tuple"),
    ("namedtuple", {"k": _Point(1, 2)}, "provenance.k", "_Point"),
    ("set", {"k": {1, 2}}, "provenance.k", "set"),
    ("frozenset", {"k": frozenset({1})}, "provenance.k", "frozenset"),
    ("bytes", {"k": b"ab"}, "provenance.k", "bytes"),
    ("bytearray", {"k": bytearray(b"ab")}, "provenance.k", "bytearray"),
    ("date", {"k": datetime.date(2026, 1, 1)}, "provenance.k", "date"),
    ("mappingproxy nested", {"k": MappingProxyType({"a": 1})}, "provenance.k", "mappingproxy"),
    ("Decimal", {"k": decimal.Decimal("1.5")}, "provenance.k", "Decimal"),
    ("plain object", {"k": object()}, "provenance.k", "object"),
    ("complex", {"k": 1 + 2j}, "provenance.k", "complex"),
]

# (label, provenance). Every one of these must still be written AND must reload
# **equal** to what went in — the assertion is on the value, not on the absence
# of an exception, because a writer that silently rewrote the value would
# satisfy the weaker one.
ACCEPT: list[tuple[str, dict[str, Any]]] = [
    ("plain dict", {"k": {"a": 1}}),
    ("plain list", {"k": [1, 2]}),
    ("int and None", {"k": 1, "n": None}),
    ("float", {"k": 1.5}),
    ("bool", {"k": True}),
    ("nested dict of lists", {"k": {"a": [1, {"b": "c"}]}}),
    ("empty dict", {"k": {}}),
    ("empty list", {"k": []}),
    # The five subclass rows. Each is an `isinstance` of a faithful type but
    # not `type(v) in` it, and each round-trips equal.
    ("Counter (dict subclass)", {"k": Counter({"a": 1})}),
    ("OrderedDict (dict subclass)", {"k": OrderedDict(b=1, a=2)}),
    ("IntEnum (int subclass)", {"k": _Level.HIGH}),
    ("str subclass", {"k": _MyStr("hi")}),
    ("list subclass", {"k": _MyList([1, 2])}),
]


@pytest.mark.parametrize(
    ("label", "provenance", "json_path", "type_name"), REJECT, ids=[r[0] for r in REJECT]
)
def test_dump_refuses_unfaithful_value_type(
    tmp_path: Path, label: str, provenance: dict[str, Any], json_path: str, type_name: str
) -> None:
    out = tmp_path / "d.jsonl"
    with pytest.raises(ValueError, match="cannot emit faithfully") as exc:
        _dataset(provenance=provenance).dump_jsonl(out)
    msg = str(exc.value)
    assert json_path in msg, f"{label}: message does not name the field path: {msg}"
    assert type_name in msg, f"{label}: message does not name the type: {msg}"
    assert "examples[0]" in msg, f"{label}: message does not name the index: {msg}"
    assert "qa_001" in msg, f"{label}: message does not name the id: {msg}"


@pytest.mark.parametrize(
    ("label", "provenance"), [(r[0], r[1]) for r in REJECT], ids=[r[0] for r in REJECT]
)
def test_dump_writes_no_bytes_when_it_refuses(
    tmp_path: Path, label: str, provenance: dict[str, Any]
) -> None:
    """The refusal must leave the destination untouched, not truncated to the
    good prefix. `dump_jsonl` documents this; the walk runs before
    `atomic_write_text`, and this pins that the new arm did not move.
    """
    out = tmp_path / "d.jsonl"
    out.write_text("PRIOR CONTENT\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot emit faithfully"):
        _dataset(provenance=provenance).dump_jsonl(out)
    assert out.read_text(encoding="utf-8") == "PRIOR CONTENT\n"


@pytest.mark.parametrize(("label", "provenance"), ACCEPT, ids=[r[0] for r in ACCEPT])
def test_dump_accepts_and_round_trips_faithful_values(
    tmp_path: Path, label: str, provenance: dict[str, Any]
) -> None:
    out = tmp_path / "d.jsonl"
    _dataset(provenance=provenance).dump_jsonl(out)
    reloaded = load_jsonl(out).examples[0].provenance
    assert reloaded == provenance, f"{label}: {reloaded!r} != {provenance!r}"


def test_the_silent_row_is_the_reason_this_is_a_type_check() -> None:
    """A tuple is refused *because it would otherwise succeed*.

    This is the row that separates the fix from the plausible wrong one. A
    `try: json.dumps(record) except TypeError -> ValueError` wrapper is green
    on every REJECT row above except the five tuple-shaped ones, because a
    tuple serializes fine. Reproduce that neighbour's verdict here so the
    difference is a committed fact and not a paragraph in a PR body.
    """
    import json

    record = _example(provenance={"k": (1, 2)}).to_dict()
    # The neighbour's whole test: does json.dumps raise?
    serialized = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert '"k":[1,2]' in serialized, "a tuple serializes without error — that is the hazard"
    # And the value does not survive it.
    assert json.loads(serialized)["provenance"]["k"] == [1, 2]
    assert json.loads(serialized)["provenance"]["k"] != (1, 2)


def test_the_faithful_set_is_enforced_by_two_arms_that_have_to_agree() -> None:
    """Which spelling protects which subclass — measured, not assumed.

    The five subclass rows in `ACCEPT` all round-trip equal, and they do not
    all pass for the same reason. Four never reach the type check at all: the
    arms above it are spelled with `isinstance`, so a `Counter` is consumed by
    the `dict` arm and a `str` subclass by the `str` arm. Only an `int`
    subclass reaches the type check, `int` having no arm of its own.

    So there are two plausible wrong spellings and each breaks a *different*
    subset, which is exactly why writing "use isinstance" in one place is not
    enough:

    * `type(v) in _FAITHFUL_JSON_TYPES` at the type check — built and run,
      red on 1 of 14 rows (`IntEnum`) and green on the other four subclasses.
    * `type(v) ==` in the arms above — would be red on the other four.

    The counts are the point. A test that asserted "all five would break"
    would be overstating a real defence, and I had written exactly that before
    running the neighbour.
    """
    reaches_the_type_check: list[Any] = [_Level.HIGH]
    consumed_by_an_earlier_arm: list[Any] = [
        Counter({"a": 1}),
        OrderedDict(b=1),
        _MyStr("hi"),
        _MyList([1]),
    ]

    for v in reaches_the_type_check + consumed_by_an_earlier_arm:
        assert find_unrepresentable({"provenance": {"k": v}}, kinds=_ALL_KINDS) is None, (
            f"{type(v).__name__} round-trips equal through this writer and must not be a finding"
        )
        # The property the identity spelling would lose, for every one of them.
        assert isinstance(v, _FAITHFUL_JSON_TYPES)
        assert type(v) not in _FAITHFUL_JSON_TYPES, (
            f"{type(v).__name__} is a member by identity too, so it no longer "
            "separates the two spellings and this row has stopped testing anything"
        )

    # The split itself: only the int subclass is unhandled by an earlier arm.
    for v in consumed_by_an_earlier_arm:
        assert isinstance(v, (str, float, dict, list, bool)), (
            f"{type(v).__name__} no longer matches an arm above the type check — "
            "the two-mechanism split this test documents has moved"
        )
    for v in reaches_the_type_check:
        assert not isinstance(v, (str, float, dict, list, bool))
        assert isinstance(v, int)


def test_the_new_axis_is_unreachable_from_json_loads_output() -> None:
    """The axis must be a no-op on the two loader sites, exactly as
    `NON_STRING_KEY` is.

    `json.loads` can only produce `str`, `int`, `float`, `bool`, `None`, `dict`
    and `list` — every one of them faithful — so enforcing the axis on the load
    path cannot change a verdict. That is a claim about the *parser*, so it is
    tested by feeding the parser rather than by asserting it in prose.

    The anti-vacuous arm matters here: a walk that returned `None` for
    everything would pass the loop below trivially. `_HOSTILE` is a document
    that the walk MUST still reject, on a different axis.
    """
    import json

    benign = json.loads(
        '{"s":"x","i":1,"f":1.5,"b":true,"n":null,"o":{"k":[1,2,{"d":"e"}]},"a":[[],{}]}'
    )
    assert find_unrepresentable(benign, kinds=_ALL_KINDS) is None

    # Every type json.loads can construct, collected from a real parse.
    seen: set[type] = set()
    stack: list[Any] = [benign]
    while stack:
        node = stack.pop()
        seen.add(type(node))
        if isinstance(node, dict):
            stack.extend(node.keys())
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    assert len(seen) >= 6, f"the probe document exercises too few types: {seen}"
    for t in seen:
        assert t is type(None) or issubclass(t, _FAITHFUL_JSON_TYPES), (
            f"json.loads produced {t.__name__}, which is not in the faithful set — "
            "the new axis is NOT a no-op on the load path and this test is the "
            "only thing that would have said so"
        )

    # Anti-vacuous: the walk still finds a real problem in a parsed document.
    hostile = json.loads('{"k":NaN}')
    found = find_unrepresentable(hostile, kinds=_ALL_KINDS)
    assert found is not None
    assert found[1] != UNSERIALIZABLE_TYPE


def test_unenforced_axis_still_descends_into_a_tuple() -> None:
    """A caller enforcing a subset must not lose a subtree.

    `calibration._row_from_dict` passes `kinds={UNENCODABLE}`. When this axis
    is switched off the tuple is not a finding, but a lone surrogate *inside*
    it still is — the same call the non-string-key arm makes one branch up.
    """
    from eval_harness.io_utils import UNENCODABLE

    record = {"provenance": {"k": (chr(0xD800),)}}
    off = find_unrepresentable(record, kinds=frozenset({UNENCODABLE}))
    assert off is not None, "the surrogate under a tuple was lost when the axis was off"
    assert off[1] == UNENCODABLE
    assert off[0] == "provenance.k[0]"

    on = find_unrepresentable(record, kinds=_ALL_KINDS)
    assert on is not None
    assert on[1] == UNSERIALIZABLE_TYPE
