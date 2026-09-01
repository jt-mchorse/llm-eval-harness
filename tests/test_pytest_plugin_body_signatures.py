"""The eval marker parametrizes every body signature, not just the ones that
happen to name `eval_row` (#223, D-019).

This file is a **variant table**, not a set of hand-written cases: every row in
``_BODY_SIGNATURES`` is one shape a user's test body can take, and each is
driven end-to-end through ``pytester`` so the assertion is on observed
collection and outcomes rather than on a reading of the fixture closure. Adding
a seventh shape is a one-line addition here.

Before #223 the plugin parametrized only ``if "eval_row" in
metafunc.fixturenames``. Three of the six rows below then collected **one**
unparametrized item and errored in setup with ``fixture 'eval_row' not found``
— and the population was wider than the issue title's "no-arg body" suggested:
an unrelated fixture and a ``**kwargs`` body break identically. ``judge_score``
alone worked only incidentally, because that fixture *declares* ``eval_row``
and so drags it into the closure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


_SAMPLE_DATASET_LINES = [
    {
        "id": "qa_001",
        "input": "What color is the sky?",
        "expected_outputs": [{"kind": "exact", "value": "blue"}],
        "tags": ["geography"],
        "dataset_version": "demo-v0.1",
        "provenance": {"source": "self", "added_on": "2026-05-16"},
    },
    {
        "id": "qa_002",
        "input": "What is 2+2?",
        "expected_outputs": [{"kind": "exact", "value": "4"}],
        "tags": ["math"],
        "dataset_version": "demo-v0.1",
        "provenance": {"source": "self", "added_on": "2026-05-16"},
    },
]

_ROW_IDS = [row["id"] for row in _SAMPLE_DATASET_LINES]


def _write_sample_dataset(path: Path) -> None:
    path.write_text("\n".join(json.dumps(r) for r in _SAMPLE_DATASET_LINES) + "\n")


# (label, body source). The body always passes; what is under test is whether
# the plugin produced one item per row and could resolve them, not the body.
_BODY_SIGNATURES = [
    # Named `eval_row` directly — the shape that already worked.
    ("row_and_score", "def test_demo(eval_row, judge_score):\n            pass"),
    ("row_only", "def test_demo(eval_row):\n            pass"),
    # Worked only because `judge_score` declares `eval_row`.
    ("score_only", "def test_demo(judge_score):\n            pass"),
    # The three that broke before #223.
    ("no_arguments", "def test_demo():\n            pass"),
    ("unrelated_fixture_only", "def test_demo(tmp_path):\n            pass"),
    ("kwargs_only", "def test_demo(**kwargs):\n            pass"),
]


def _make_eval_module(pytester: pytest.Pytester, body: str) -> None:
    dataset = pytester.path / "sample.jsonl"
    _write_sample_dataset(dataset)
    pytester.makepyfile(
        f"""
        import pytest
        from eval_harness.runner import DatasetEchoSource

        class _PassBackend:
            def complete(self, system, user):
                return "SCORE: 1.0\\nREASONING: perfect."

        @pytest.mark.eval(
            suite="demo",
            dataset=r"{dataset}",
            answer_source=DatasetEchoSource(),
            judge_backend=_PassBackend(),
            threshold=0.5,
        )
        {body}
        """
    )


@pytest.mark.parametrize(
    ("label", "body"), _BODY_SIGNATURES, ids=[label for label, _ in _BODY_SIGNATURES]
)
def test_every_body_signature_is_parametrized_per_row(
    pytester: pytest.Pytester, label: str, body: str
) -> None:
    """One item per dataset row, with the row id as the label, for every shape."""
    _make_eval_module(pytester, body)

    collected = pytester.runpytest("--collect-only", "-q", "-p", "eval_harness")
    collected_ids = [line for line in collected.outlines if "::test_demo" in line]
    assert len(collected_ids) == len(_SAMPLE_DATASET_LINES), (
        f"{label}: expected one item per row, got {collected_ids}"
    )
    for row_id in _ROW_IDS:
        assert any(f"[{row_id}]" in line for line in collected_ids), (
            f"{label}: no item labelled with row id {row_id!r} in {collected_ids}"
        )

    result = pytester.runpytest("-p", "eval_harness")
    result.assert_outcomes(passed=len(_SAMPLE_DATASET_LINES), errors=0, failed=0)


@pytest.mark.parametrize(
    ("label", "body"), _BODY_SIGNATURES, ids=[label for label, _ in _BODY_SIGNATURES]
)
def test_every_body_signature_still_scores_and_can_fail(
    pytester: pytest.Pytester, label: str, body: str
) -> None:
    """The judge runs — and the threshold gate fires — for every shape too.

    Parametrizing a body that ignores `eval_row` would be worth little if the
    marker went inert for it: the point of `_ensure_judge_score_runs` is that a
    body which references nothing still gets scored. A backend that always
    returns 0.0 against a 0.5 threshold must therefore fail *both* rows, in
    every shape. Before #223 the three broken shapes reported `errors=2` here
    for the wrong reason (unresolvable fixture), so this asserts `failed`
    explicitly rather than "not passed".
    """
    dataset = pytester.path / "sample.jsonl"
    _write_sample_dataset(dataset)
    pytester.makepyfile(
        f"""
        import pytest
        from eval_harness.runner import DatasetEchoSource

        class _FailBackend:
            def complete(self, system, user):
                return "SCORE: 0.0\\nREASONING: nope."

        @pytest.mark.eval(
            suite="demo",
            dataset=r"{dataset}",
            answer_source=DatasetEchoSource(),
            judge_backend=_FailBackend(),
            threshold=0.5,
        )
        {body}
        """
    )

    result = pytester.runpytest("-p", "eval_harness")
    result.assert_outcomes(failed=len(_SAMPLE_DATASET_LINES), errors=0, passed=0)
    result.stdout.fnmatch_lines(["*score=0.000*threshold=0.500*"])


def test_the_table_covers_the_shapes_that_used_to_break(pytester: pytest.Pytester) -> None:
    """Anti-vacuous arm: the table must contain shapes that omit `eval_row`.

    A variant table is only worth its runtime if it still holds the rows that
    motivated it. If someone trims `_BODY_SIGNATURES` down to the shapes that
    always worked, the two tests above keep passing while covering nothing —
    the exact failure mode #223 was reported from. `pytester` is unused here
    but requested so this arm sits in the same plugin-loaded context as the
    rows it guards.
    """
    bodies = {label: body for label, body in _BODY_SIGNATURES}
    for required in ("no_arguments", "unrelated_fixture_only", "kwargs_only"):
        assert required in bodies, f"variant table lost the {required!r} shape"
        assert "eval_row" not in bodies[required], (
            f"{required!r} is supposed to omit `eval_row`; it no longer does"
        )
    assert "eval_row" not in bodies["score_only"], (
        "score_only must reach `eval_row` only through `judge_score`'s declaration"
    )
