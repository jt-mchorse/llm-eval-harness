"""Tests for the tag-filter helper (`filter_examples_by_tags`) — issue #15."""

from __future__ import annotations

from eval_harness.dataset import (
    Example,
    ExpectedOutput,
    collect_tag_inventory,
    filter_examples_by_tags,
)


def _ex(id_: str, tags: tuple[str, ...]) -> Example:
    return Example(
        id=id_,
        input="prompt",
        expected_outputs=(ExpectedOutput(kind="exact", value="x"),),
        dataset_version="v",
        provenance={"source": "test"},
        tags=tags,
    )


EXAMPLES = [
    _ex("a", ("geography", "factuality")),
    _ex("b", ("geometry", "factuality")),
    _ex("c", ("history",)),
    _ex("d", ()),  # untagged row — must never match a tag filter
]


def test_no_tags_returns_every_example() -> None:
    assert [e.id for e in filter_examples_by_tags(EXAMPLES, None)] == ["a", "b", "c", "d"]
    assert [e.id for e in filter_examples_by_tags(EXAMPLES, [])] == ["a", "b", "c", "d"]


def test_single_tag_filters_to_subset() -> None:
    assert [e.id for e in filter_examples_by_tags(EXAMPLES, ["geometry"])] == ["b"]


def test_multi_tag_is_set_union_not_intersection() -> None:
    # Operator asks for `geography` OR `history` — both 'a' and 'c' match.
    assert [e.id for e in filter_examples_by_tags(EXAMPLES, ["geography", "history"])] == ["a", "c"]


def test_factuality_tag_matches_every_tagged_row() -> None:
    # `d` has no tags so it doesn't match even a tag every other row carries —
    # documents the schema-level guarantee that empty-tag rows never sneak in.
    assert [e.id for e in filter_examples_by_tags(EXAMPLES, ["factuality"])] == ["a", "b"]


def test_unknown_tag_returns_empty_list() -> None:
    # The helper returns []; the *error* is the CLI's job (so library callers
    # can decide whether empty-match is an error in their context).
    assert filter_examples_by_tags(EXAMPLES, ["does-not-exist"]) == []


def test_collect_tag_inventory_is_sorted_and_deduped() -> None:
    assert collect_tag_inventory(EXAMPLES) == [
        "factuality",
        "geography",
        "geometry",
        "history",
    ]


def test_collect_tag_inventory_empty_input() -> None:
    assert collect_tag_inventory([]) == []
