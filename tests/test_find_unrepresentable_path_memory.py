"""`find_unrepresentable`'s memory is linear in a value's depth, not quadratic (#432).

Every push built the child's whole JSON-path string, so a node N levels down held
an O(N) string and a linear chain held O(depth^2) bytes over the walk. Measured on
origin/main e5a2915 (3.11), tracemalloc peak of the walk alone:

======  ========
depth   peak
======  ========
2000    6.5 MB
12000   218 MB
20000   605 MB
======  ========

Ten times the depth cost ~93x the memory. `loads_json` decodes ~100,000 levels on
3.11/3.12 (#333) and every such row goes through this walk.

The memory arm is red against that code. The controls pin the reported path
**character for character** against what the string-building walk returned --
the values below were taken from it -- because a lazy path is only a fix if the
string it finally builds is the old one. The table leans on the one rule the
string spelling decided on a string: a dict key drops its ``.`` when the path so
far is empty, which is true below a ``""`` key at the root as well as at the root.
"""

from __future__ import annotations

import tracemalloc
from typing import Any

import pytest

from eval_harness.io_utils import (
    CIRCULAR_REFERENCE,
    NON_FINITE,
    NON_STRING_KEY,
    UNENCODABLE,
    UNSERIALIZABLE_TYPE,
    find_unrepresentable,
)

NAN = float("nan")
# Built from its codepoint: a literal would trip `test_source_representability`.
SURROGATE = chr(0xD800)
SHALLOW = 2_000
DEEP = 20_000
# Linear growth puts the ratio near DEEP / SHALLOW = 10 (measured 11x: the
# ancestor set resizes); the quadratic walk measured 93x. 30 sits between with
# room on both sides.
MAX_PEAK_RATIO = 30


def _nest(depth: int, leaf: Any = 1) -> Any:
    v = leaf
    for _ in range(depth):
        v = [v]
    return v


def _peak(value: Any) -> int:
    tracemalloc.start()
    try:
        assert find_unrepresentable(value) is None
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_peak_memory_grows_linearly_with_depth() -> None:
    # Built before tracing starts, so the peak is the walk's and not the value's.
    shallow = {"provenance": {"p": _nest(SHALLOW)}}
    deep = {"provenance": {"p": _nest(DEEP)}}
    shallow_peak = _peak(shallow)
    deep_peak = _peak(deep)
    ratio = deep_peak / shallow_peak
    assert ratio < MAX_PEAK_RATIO, (
        f"{DEEP} levels peaked at {deep_peak / 1e6:.1f} MB, {ratio:.0f}x the "
        f"{SHALLOW}-level {shallow_peak / 1e6:.1f} MB; linear would be ~{DEEP // SHALLOW}x"
    )


def test_control_a_finding_at_real_depth_reports_the_full_path() -> None:
    # Depth is where the lazy path has to be joined; the table below is shallow.
    depth = 5_000
    found = find_unrepresentable({"provenance": {"p": _nest(depth, NAN)}})
    assert found == ("provenance.p" + "[0]" * depth, NON_FINITE, "nan")


def _cycle() -> dict[str, Any]:
    d: dict[str, Any] = {"a": []}
    d["a"].append(d)
    return d


ALL = None  # every kind enforced, the default
ONLY_UNENCODABLE = frozenset({UNENCODABLE})

# (case, record, kinds, expected) -- expected is what origin/main returned.
PATH_TABLE: list[tuple[str, Any, frozenset[str] | None, tuple[str, str, str]]] = [
    ("nested key and index", {"a": {"b": [1, NAN]}}, ALL, ("a.b[1]", NON_FINITE, "nan")),
    ("root list", [[NAN]], ALL, ("[0][0]", NON_FINITE, "nan")),
    ("empty key at root", {"": NAN}, ALL, ("", NON_FINITE, "nan")),
    ("key below empty root key", {"": {"x": NAN}}, ALL, ("x", NON_FINITE, "nan")),
    ("empty key below empty key", {"": {"": NAN}}, ALL, ("", NON_FINITE, "nan")),
    ("key two below empty keys", {"": {"": {"k": NAN}}}, ALL, ("k", NON_FINITE, "nan")),
    ("index below empty root key", {"": [NAN]}, ALL, ("[0]", NON_FINITE, "nan")),
    ("empty key below a key", {"a": {"": NAN}}, ALL, ("a.", NON_FINITE, "nan")),
    ("unprintable key", {"a\nb": NAN}, ALL, ("'a\\nb'", NON_FINITE, "nan")),
    (
        "unencodable object key",
        {"a": {SURROGATE + "k": 1}},
        ALL,
        ("a.'\\ud800k' (object key)", UNENCODABLE, "'\\ud800' at position 0"),
    ),
    (
        "unencodable root object key",
        {SURROGATE: 1},
        ALL,
        ("'\\ud800' (object key)", UNENCODABLE, "'\\ud800' at position 0"),
    ),
    ("non-string key", {"a": {1: "x"}}, ALL, ("a", NON_STRING_KEY, "1 (int)")),
    (
        "below a non-string key, not enforced",
        {"a": {1: SURROGATE}},
        ONLY_UNENCODABLE,
        ("a.1", UNENCODABLE, "'\\ud800' at position 0"),
    ),
    ("tuple value", {"t": ("a", "b")}, ALL, ("t", UNSERIALIZABLE_TYPE, "tuple")),
    (
        "inside a tuple, not enforced",
        {"t": ("ok", SURROGATE)},
        ONLY_UNENCODABLE,
        ("t[1]", UNENCODABLE, "'\\ud800' at position 0"),
    ),
    ("cycle", _cycle(), ALL, ("a[0]", CIRCULAR_REFERENCE, "dict")),
]


@pytest.mark.parametrize(
    ("record", "kinds", "expected"),
    [pytest.param(r, k, e, id=case) for case, r, k, e in PATH_TABLE],
)
def test_control_the_reported_path_is_unchanged(
    record: Any, kinds: frozenset[str] | None, expected: tuple[str, str, str]
) -> None:
    found = (
        find_unrepresentable(record) if kinds is None else find_unrepresentable(record, kinds=kinds)
    )
    assert found == expected
