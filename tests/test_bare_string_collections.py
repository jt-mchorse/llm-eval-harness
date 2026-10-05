"""A bare `str` where a collection of strings is expected is refused (#278).

A `str` is a `Sequence[str]` and an `Iterable[str]`, so the annotations on
`compute_drift`, `Example.tags` and `filter_examples_by_tags` admit it and mypy
accepts it. Before this, every coercion downstream turned `"geometry"` into its
letters and the result looked well-formed:

- `compute_drift(golden, "Who wrote Macbeth?")` ran 18 one-character
  candidates, called a paid `judge_score_fn` once per character, and reported
  letters as the representative examples.
- `Example(tags="geometry")` was invisible to a filter on its own tag.
- `filter_examples_by_tags(rows, "geometry")` selected every row tagged with
  one of those letters, so `run_suite` scored the wrong rows.

`Dataset.dump_jsonl` already refused the shape through `_FIELD_RULES["tags"]`;
these arms pin the same rule at the three entry points that ran before it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from eval_harness.dataset import (
    _FIELD_RULES_BY_NAME,
    Example,
    ExpectedOutput,
    collect_tag_inventory,
    filter_examples_by_tags,
)
from eval_harness.drift import compute_drift
from eval_harness.judge import Judge
from eval_harness.runner import DatasetEchoSource, RunSpec, run_suite

TAGS_REASON = _FIELD_RULES_BY_NAME["tags"][1]
GOLDEN = [
    "What is the capital of France?",
    "Who wrote Hamlet?",
    "How many legs does a spider have?",
    "What year did WW2 end?",
]
CANDIDATE = "Who wrote Macbeth and when?"


def _ex(id_: str, tags: Any) -> Example:
    return Example(
        id=id_,
        input="prompt",
        expected_outputs=(ExpectedOutput(kind="exact", value="x"),),
        dataset_version="v",
        provenance={"source": "test"},
        tags=tags,
    )


def _counting_judge() -> tuple[list[str], Callable[[str], float]]:
    calls: list[str] = []

    def judge(text: str) -> float:
        calls.append(text)
        return 0.5

    return calls, judge


# --- compute_drift ------------------------------------------------------------


@pytest.mark.parametrize("bare", [CANDIDATE, CANDIDATE.encode(), "x"])
def test_compute_drift_refuses_a_bare_candidate_before_any_judge_call(bare: Any) -> None:
    calls, judge = _counting_judge()
    with pytest.raises(ValueError, match="split into its characters") as exc:
        compute_drift(GOLDEN, bare, judge_score_fn=judge)
    assert calls == []
    assert "candidate_inputs" in str(exc.value)
    assert repr(bare) in str(exc.value)


@pytest.mark.parametrize("bare", [GOLDEN[0], GOLDEN[0].encode()])
def test_compute_drift_refuses_a_bare_golden_set(bare: Any) -> None:
    calls, judge = _counting_judge()
    with pytest.raises(ValueError, match="split into its characters") as exc:
        compute_drift(bare, [CANDIDATE], judge_score_fn=judge)
    assert calls == []
    assert "golden_inputs" in str(exc.value)


def test_compute_drift_message_shows_the_working_spelling() -> None:
    with pytest.raises(ValueError, match="candidate_inputs") as exc:
        compute_drift(GOLDEN, CANDIDATE)
    assert f"candidate_inputs=[{CANDIDATE!r}]" in str(exc.value)


def test_compute_drift_refuses_an_empty_string_as_a_bare_string_not_as_empty() -> None:
    # `""` used to reach the emptiness check and say "must be non-empty",
    # which reads as "add more items" -- the fix is a list, not more letters.
    with pytest.raises(ValueError, match="split into its characters"):
        compute_drift(GOLDEN, "")


def test_compute_drift_list_and_tuple_inputs_are_unchanged() -> None:
    # The working spelling from the message is honoured, and a tuple is
    # interchangeable with a list exactly as before.
    calls, judge = _counting_judge()
    as_list = compute_drift(GOLDEN, [CANDIDATE], judge_score_fn=judge)
    as_tuple = compute_drift(tuple(GOLDEN), (CANDIDATE,), judge_score_fn=judge)
    assert as_list == as_tuple
    assert as_list.n_candidate == 1
    assert [r.text for r in as_list.representative_examples] == [CANDIDATE]
    assert len(calls) == 2 * (len(GOLDEN) + 1)


# --- Example.tags -------------------------------------------------------------


@pytest.mark.parametrize("bare", ["geometry", b"geometry", bytearray(b"g"), ""])
def test_example_refuses_bare_string_tags_with_the_loaders_reason(bare: Any) -> None:
    with pytest.raises(ValueError, match="split into its characters") as exc:
        _ex("a", bare)
    assert str(exc.value).startswith(TAGS_REASON)


@pytest.mark.parametrize(
    "tags", [(), ("geometry",), ["geometry", "history"], frozenset({"geometry"})]
)
def test_example_collection_tags_are_stored_as_given(tags: Any) -> None:
    # Only the bare-string shape changed; the constructor does not normalise
    # any other collection (`dump_jsonl` still owns that rule).
    assert _ex("a", tags).tags is tags


def test_inventory_lists_tags_not_letters() -> None:
    assert collect_tag_inventory([_ex("a", ["geometry"])]) == ["geometry"]


# --- filter_examples_by_tags --------------------------------------------------

ROWS = [_ex("tagged-e", ("e",)), _ex("geometry", ("geometry",)), _ex("none", ())]


@pytest.mark.parametrize("bare", ["geometry", b"geometry", ""])
def test_filter_refuses_bare_string_tags(bare: Any) -> None:
    with pytest.raises(ValueError, match="split into its characters") as exc:
        filter_examples_by_tags(ROWS, bare)
    assert str(exc.value).startswith(TAGS_REASON)


@pytest.mark.parametrize(
    "tags",
    [
        ["geometry"],
        ("geometry",),
        {"geometry"},
        frozenset({"geometry"}),
    ],
)
def test_filter_collection_tags_are_unchanged(tags: Any) -> None:
    assert [e.id for e in filter_examples_by_tags(ROWS, tags)] == ["geometry"]


def test_filter_generator_tags_are_unchanged() -> None:
    assert [e.id for e in filter_examples_by_tags(ROWS, (t for t in ["e"]))] == ["tagged-e"]


@pytest.mark.parametrize("tags", [None, [], ()])
def test_filter_no_tags_still_means_no_filter(tags: Any) -> None:
    assert [e.id for e in filter_examples_by_tags(ROWS, tags)] == ["tagged-e", "geometry", "none"]


# --- through the runner -------------------------------------------------------


class _CountingBackend:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return "SCORE: 0.900\nREASONING: counted\n"


def test_run_suite_refuses_bare_string_tags_before_scoring_the_wrong_rows(
    tmp_path: Path,
) -> None:
    # The harm on `main`: `"geometry"` intersected the letter set {g,e,o,m,t,r,y}
    # with a row tagged `e`, so `run_suite` scored and persisted THAT row as the
    # geometry subset -- no error, a plausible one-row run. Nothing here builds
    # its own filter input; it goes through `RunSpec` -> `_load` like the CLI.
    dataset = tmp_path / "ds.jsonl"
    dataset.write_text(
        '{"dataset_version":"v","expected_outputs":[{"kind":"exact","value":"x"}],'
        '"id":"letter-e","input":"q","provenance":{},"tags":["e"]}\n',
        encoding="utf-8",
    )
    backend = _CountingBackend()
    spec = RunSpec(
        suite="s",
        dataset_path=dataset,
        judge=Judge(backend=backend),
        answer_source=DatasetEchoSource(),
        tags="geometry",  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="split into its characters"):
        run_suite(spec, db_path=tmp_path / "runs.db")
    assert backend.calls == 0
    assert not (tmp_path / "runs.db").exists() or _no_runs(tmp_path / "runs.db")


def _no_runs(db: Path) -> bool:
    from eval_harness.runs import connect

    with connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
