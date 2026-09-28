"""`dump_jsonl` cannot write a file `load_jsonl` refuses — the schema half (#235).

#234/D-021 put the *representability* rule on the write path and its docstring
scoped this half out by name. `_validate_record` runs on the load path only, so
a `Dataset` assembled in Python — `Example` is exported, has no `__post_init__`,
and building goldens programmatically is the ordinary use of this package —
wrote files the loader would not read back.

Measured on `main` before this shipped, by building a `Dataset`, dumping, and
reloading with this package's own loader::

    id=123                          wrote a file the loader refuses
    id=""                           wrote a file the loader refuses
    input=123                       wrote a file the loader refuses
    dataset_version=123             wrote a file the loader refuses
    dataset_version=""              wrote a file the loader refuses
    expected_outputs=()             wrote a file the loader refuses
    tags=(1,)                       wrote a file the loader refuses
    two examples sharing an id      wrote a file the loader refuses
    mixed dataset_version           wrote a file the loader refuses
    zero examples                   wrote a file the loader refuses
    provenance=[]                   ROUND-TRIPPED, silently coerced to {}
    tags="urgent"                   ROUND-TRIPPED, exploded to six 1-char tags
    Dataset.version != row version  ROUND-TRIPPED, reloaded as the OTHER version

Ten of thirteen are loud failures a user would at least *see*. The last three
are the ones worth the file: `Example.to_dict()` performs `dict(self.provenance)`
and `list(self.tags)`, so a string `tags` arrives at the record as a perfectly
well-formed list of six strings with nothing left to object to. That is why the
write-side check runs against the `Example`'s attributes and not against
`to_dict()`'s output, and it is the property the "check the record instead"
neighbour at the bottom of this file fails.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from eval_harness import dataset as dataset_module
from eval_harness.dataset import (
    Dataset,
    DatasetLoadError,
    Example,
    ExpectedOutput,
    load_jsonl,
)


def _eo() -> tuple[ExpectedOutput, ...]:
    return (ExpectedOutput(kind="exact", value="x"),)


def _example(**overrides: Any) -> Example:
    base: dict[str, Any] = {
        "id": "ex-1",
        "input": "what is 2+2?",
        "expected_outputs": _eo(),
        "dataset_version": "v1",
        "provenance": {"author": "test"},
        "tags": (),
    }
    base.update(overrides)
    return Example(**base)


# (label, Dataset factory, substring the refusal must contain). Every row was
# verified to WRITE a file on `main`; the third column is what the loader said
# when that file was read back, or — for the three silent rows — what the new
# rule says instead.
REJECT_ROWS: tuple[tuple[str, Any, str], ...] = (
    (
        "id is not a string",
        lambda: Dataset("v1", [_example(id=123)]),
        "'id' must be a non-empty string",
    ),
    (
        "id is empty",
        lambda: Dataset("v1", [_example(id="")]),
        "'id' must be a non-empty string",
    ),
    (
        "input is not a string",
        lambda: Dataset("v1", [_example(input=123)]),
        "'input' must be a string",
    ),
    (
        "dataset_version is not a string",
        lambda: Dataset("v1", [_example(dataset_version=123)]),
        "'dataset_version' must be a non-empty string",
    ),
    (
        "dataset_version is empty",
        lambda: Dataset("", [_example(dataset_version="")]),
        "'dataset_version' must be a non-empty string",
    ),
    (
        "provenance is not a mapping",
        lambda: Dataset("v1", [_example(provenance=[])]),
        "'provenance' must be an object",
    ),
    (
        "expected_outputs is empty",
        lambda: Dataset("v1", [_example(expected_outputs=())]),
        "'expected_outputs' must be a non-empty list",
    ),
    (
        "tags holds a non-string",
        lambda: Dataset("v1", [_example(tags=(1,))]),
        "'tags' must be a list of strings",
    ),
    (
        "tags is a bare string",
        lambda: Dataset("v1", [_example(tags="urgent")]),
        "'tags' must be a list of strings",
    ),
    (
        "two examples share an id",
        lambda: Dataset("v1", [_example(id="a"), _example(id="a")]),
        "duplicate id 'a'",
    ),
    (
        "rows disagree on dataset_version",
        lambda: Dataset("v1", [_example(id="a"), _example(id="b", dataset_version="v2")]),
        "does not match file version",
    ),
    (
        "Dataset.version disagrees with its rows",
        lambda: Dataset("v1", [_example(dataset_version="v2")]),
        "does not match the dataset_version",
    ),
    ("no examples at all", lambda: Dataset("v1", []), "no examples"),
)

# The anti-vacuous control. Without these the table above could be satisfied by
# a `dump_jsonl` that refused everything.
ACCEPT_ROWS: tuple[tuple[str, Any], ...] = (
    ("the ordinary case", lambda: Dataset("v1", [_example()])),
    ("tags as a tuple of strings", lambda: Dataset("v1", [_example(tags=("a", "b"))])),
    ("tags as a list of strings", lambda: Dataset("v1", [_example(tags=["a", "b"])])),
    ("no tags at all", lambda: Dataset("v1", [_example(tags=())])),
    ("empty provenance", lambda: Dataset("v1", [_example(provenance={})])),
    ("empty input", lambda: Dataset("v1", [_example(input="")])),
    (
        "many rows sharing one version",
        lambda: Dataset("v1", [_example(id="a"), _example(id="b"), _example(id="c")]),
    ),
    (
        "non-ASCII everywhere",
        lambda: Dataset(
            "v1", [_example(id="ident-é", input="café \U0001f389", tags=("étiquette",))]
        ),
    ),
)


@pytest.mark.parametrize(
    ("label", "factory", "expected"), REJECT_ROWS, ids=[r[0] for r in REJECT_ROWS]
)
def test_dump_refuses_what_load_would(
    tmp_path: Path, label: str, factory: Any, expected: str
) -> None:
    out = tmp_path / "goldens.jsonl"
    with pytest.raises(ValueError, match=expected):
        factory().dump_jsonl(out)


@pytest.mark.parametrize(
    ("label", "factory"),
    [(r[0], r[1]) for r in REJECT_ROWS],
    ids=[r[0] for r in REJECT_ROWS],
)
def test_a_refusal_leaves_the_destination_untouched(
    tmp_path: Path, label: str, factory: Any
) -> None:
    """Rejection happens before any bytes, so a bad dataset cannot truncate an
    existing file to a good prefix — the same posture #234 established.

    `match` on the example locator rather than a bare `ValueError`: an
    unguarded writer's own `UnicodeEncodeError` IS a `ValueError`, so a bare
    `raises` would pass against unfixed code for some rows. The two rows with
    no single example to point at match their own reason instead.
    """
    out = tmp_path / "goldens.jsonl"
    Dataset("v1", [_example()]).dump_jsonl(out)
    before = out.read_bytes()
    expected = {
        "no examples at all": "no examples",
        "Dataset.version disagrees with its rows": r"Dataset\.version",
    }.get(label, r"examples\[\d+\]")
    with pytest.raises(ValueError, match=expected):
        factory().dump_jsonl(out)
    assert out.read_bytes() == before


@pytest.mark.parametrize(("label", "factory"), ACCEPT_ROWS, ids=[r[0] for r in ACCEPT_ROWS])
def test_a_valid_dataset_still_round_trips(tmp_path: Path, label: str, factory: Any) -> None:
    """The control. Every accept row must dump AND reload, so the reject table
    above is evidence about the rule rather than about a writer that refuses.
    """
    out = tmp_path / "goldens.jsonl"
    ds = factory()
    ds.dump_jsonl(out)
    reloaded = load_jsonl(out)
    assert reloaded.version == ds.version
    assert [e.id for e in reloaded] == [e.id for e in ds.examples]
    assert [tuple(e.tags) for e in reloaded] == [tuple(e.tags) for e in ds.examples]


def test_the_table_has_teeth_on_both_sides() -> None:
    """Anti-vacuous for the tables themselves."""
    assert len(REJECT_ROWS) >= 13
    assert len(ACCEPT_ROWS) >= 6


# ---------------------------------------------------------------------------
# The three rows that used to be SILENT, stated individually
# ---------------------------------------------------------------------------


def test_a_string_tags_is_not_six_tags(tmp_path: Path) -> None:
    """The sharpest row, and the reason the check reads the `Example`.

    `Example.to_dict()` does `list(self.tags)`, so `tags="urgent"` became
    `["u","r","g","e","n","t"]` — a valid list of strings that round-tripped
    cleanly as six tags. Nothing stated over the *record* can see it.
    """
    assert list("urgent") == ["u", "r", "g", "e", "n", "t"]
    record = _example(tags="urgent").to_dict()
    assert record["tags"] == ["u", "r", "g", "e", "n", "t"], (
        "to_dict still explodes a string; the write-side rule must read the Example"
    )
    with pytest.raises(ValueError, match="'tags' must be a list of strings"):
        Dataset("v1", [_example(tags="urgent")]).dump_jsonl(tmp_path / "g.jsonl")


def test_a_sequence_provenance_is_not_an_empty_object(tmp_path: Path) -> None:
    """A list `provenance` is rejected, and is no longer reshaped on the way there.

    `to_dict()` did `dict(self.provenance)`, so `provenance=[]` became `{}` and
    `provenance=[("a", 1)]` became `{"a": 1}` — the caller's data silently lost
    or reshaped before anything could object to it. #254 replaced that with
    `copy_json_value`, which is faithful, so `to_dict()` now hands back the list
    it was given.

    The arm still asserts the rejection, because that is what protects the file
    on disk. What it no longer asserts is the coercion: the sibling `tags` arm
    above still carries the "the write-side rule must read the `Example`"
    argument, and it carries it on a case that is still live — `list(self.tags)`
    really does explode `"urgent"` into six tags.
    """
    assert dict([]) == {}, "the coercion this once relied on is still what dict() does"
    assert _example(provenance=[]).to_dict()["provenance"] == [], (
        "to_dict must not reshape a caller's provenance before the write-side "
        "rule gets to object to it (#254)"
    )
    with pytest.raises(ValueError, match="'provenance' must be an object"):
        Dataset("v1", [_example(provenance=[])]).dump_jsonl(tmp_path / "g.jsonl")


def test_dataset_version_must_match_its_rows(tmp_path: Path) -> None:
    """D-022. `Dataset.version` is documented as "the value of
    `dataset_version` carried by every line in the file"; nothing checked it on
    the way out, so this wrote a file that reloaded as the *other* version.

    Rejected rather than silently overwritten: overwriting every row with
    `self.version` is a lossy write no reader could detect, and the loader's own
    message for the neighbouring case says "split mixed-version data into
    separate files".
    """
    out = tmp_path / "g.jsonl"
    with pytest.raises(ValueError, match="does not match the dataset_version"):
        Dataset("v1", [_example(dataset_version="v2")]).dump_jsonl(out)
    assert not out.exists()
    # And the honest case still works, so this is not a blanket refusal.
    Dataset("v2", [_example(dataset_version="v2")]).dump_jsonl(out)
    assert load_jsonl(out).version == "v2"


def test_an_empty_dataset_names_the_real_problem(tmp_path: Path) -> None:
    """`"\\n".join([]) + "\\n"` is one blank line, which the loader rejects with
    "blank line; dataset must have one JSON object per line" — a diagnosis about
    line 1 of a file whose actual problem is that it has no rows.
    """
    assert "\n".join([]) + "\n" == "\n"
    with pytest.raises(ValueError, match="no examples"):
        Dataset("v1", []).dump_jsonl(tmp_path / "g.jsonl")


# ---------------------------------------------------------------------------
# One definition, not a copy
# ---------------------------------------------------------------------------


def test_dump_jsonl_names_the_shared_definitions() -> None:
    """The neighbour #234 measured is a *copy* of the rules inside the writer,
    which passes every behavioural row above. Only a structural check separates
    it, so the source is asserted to reference the shared names.
    """
    src = inspect.getsource(Dataset.dump_jsonl)
    assert "_find_field_violation" in src
    assert "_DatasetInvariants" in src
    assert "_find_unrepresentable" in src


def test_each_reason_string_is_written_once() -> None:
    """A copy would duplicate the reason text. Counted over the module's string
    literals, so the module comment quoting a rule does not create a false hit —
    the exact trap recorded when #234's `once` lock first shipped as a grep.
    """
    import ast

    tree = ast.parse(Path(dataset_module.__file__).read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    literals = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]
    for reason in (
        "field 'id' must be a non-empty string",
        "field 'input' must be a string",
        "field 'provenance' must be an object",
        "field 'tags' must be a list of strings",
    ):
        assert literals.count(reason) == 1, (
            f"{reason!r} appears {literals.count(reason)} times as a string literal; "
            "the rule should live once, in _FIELD_RULES"
        )


def test_the_loader_still_reports_the_item_not_the_tag() -> None:
    """Extraction must not re-rank the diagnosis.

    `_validate_record` checks `tags` *after* the `expected_outputs` item loop,
    so a record with both a bad tag and a bad item reports the item.
    `_find_field_violation` takes its field order as a parameter for exactly
    this reason; a single all-fields call would have flipped it silently.
    """
    import json as _json

    line = _json.dumps(
        {
            "id": "a",
            "input": "i",
            "expected_outputs": [{"kind": "nope", "value": "x"}],
            "dataset_version": "v1",
            "provenance": {},
            "tags": [1],
        }
    )
    with pytest.raises(DatasetLoadError, match="invalid expected_output kind"):
        dataset_module._validate_record(_json.loads(line), 1)
