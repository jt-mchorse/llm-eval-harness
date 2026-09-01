"""The plugin's failure-context block, on the paths it was written for (#222).

`pytest_runtest_makereport`'s docstring promised that when "something *else*
in the test path raised (a judge timeout, a parse error, an answer-source
failure), the row id and the response are still surfaced". It surfaced nothing
on any of them, for three independent reasons — wrong phase (`call` only, but
the judge runs in `setup`), data stashed only after both calls succeeded, and a
block written to `item._eval_failure_extra` that no code read.

The threshold path — the one path with prior coverage — was the one path that
never needed the hook, which is exactly why the gap stayed invisible.
`tests/test_pytest_plugin.py` keeps that path; this file covers the other four.

Assertions match the rendered section separator (`--- Eval context ---`) rather
than the bare words: the plugin's own source lines are rendered inside a
failing test's traceback, so a bare substring scan false-matches the module's
prose. Same hazard `test_threshold_violation_emits_no_teardown_warning`
documents.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_SECTION = "*- Eval context -*"

_ROWS = [
    {
        "id": "qa_001",
        "input": "What color is the sky?",
        "expected_outputs": [{"kind": "exact", "value": "blue"}],
        "tags": ["geography"],
        "dataset_version": "demo-v0.1",
        "provenance": {"source": "self", "added_on": "2026-05-16"},
    },
]


def _write_dataset(path: Path) -> None:
    path.write_text("\n".join(json.dumps(r) for r in _ROWS) + "\n")


def _make_eval_file(
    pytester: pytest.Pytester,
    *,
    answer_source: str,
    backend: str,
    body: str = "pass",
    threshold: float = 0.5,
) -> None:
    dataset = pytester.path / "sample.jsonl"
    _write_dataset(dataset)
    pytester.makepyfile(
        f"""
        import pytest
        from eval_harness.runner import DatasetEchoSource

        class _PassBackend:
            def complete(self, system, user):
                return "SCORE: 1.0\\nREASONING: perfect."

        class _GarbageBackend:
            def complete(self, system, user):
                return "I refuse to follow the format."

        class _BoomSource:
            def answer(self, example):
                raise RuntimeError("answer source exploded")

        @pytest.mark.eval(
            suite="demo",
            dataset=r"{dataset}",
            answer_source={answer_source},
            judge_backend={backend},
            threshold={threshold},
        )
        def test_demo(eval_row, judge_score):
            {body}
        """
    )


def test_answer_source_failure_surfaces_row_context(pytester: pytest.Pytester) -> None:
    """An answer source that raises reports the row it died on.

    This failure happens in `setup` (the autouse `_ensure_judge_score_runs`
    fixture pulls `judge_score` before the call phase), so it is the direct
    regression test for the `call.when != "call"` early return.
    """
    _make_eval_file(pytester, answer_source="_BoomSource()", backend="_PassBackend()")
    result = pytester.runpytest("-v", "-p", "eval_harness")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines([_SECTION])
    out = result.stdout.str()
    assert "row_id:           qa_001" in out
    assert "expected outputs: ['blue']" in out
    # No response exists yet — the block reports the subset that does, and does
    # not invent an empty one.
    assert "actual response:" not in out
    assert "judge score:" not in out


def test_judge_failure_surfaces_the_response_it_could_not_parse(
    pytester: pytest.Pytester,
) -> None:
    """A `JudgeParseError` reports the answer that produced it.

    The response is the single most useful datum on this path, and it was the
    one the old ordering threw away: `_eval_response` was assigned after
    `judge.score()` returned, so a judge failure lost a value that had already
    been computed.
    """
    _make_eval_file(pytester, answer_source="DatasetEchoSource()", backend="_GarbageBackend()")
    result = pytester.runpytest("-v", "-p", "eval_harness")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines([_SECTION])
    out = result.stdout.str()
    assert "row_id:           qa_001" in out
    assert "actual response:  'blue'" in out
    # The judge never produced a score, so no score line is fabricated.
    assert "judge score:" not in out


def test_body_failure_surfaces_the_full_block(pytester: pytest.Pytester) -> None:
    """A plain `assert` in the user's own body gets every field.

    This one fails in the `call` phase with all three values stashed, so it
    covers the other half of the phase widening — and it is why the
    double-print suppression keys off a flag rather than off `AssertionError`:
    a user's assertion is an AssertionError too and *should* get the block.
    """
    _make_eval_file(
        pytester,
        answer_source="DatasetEchoSource()",
        backend="_PassBackend()",
        body="assert judge_score.score < 0.0, 'deliberate body failure'",
    )
    result = pytester.runpytest("-v", "-p", "eval_harness")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines([_SECTION])
    out = result.stdout.str()
    assert "row_id:           qa_001" in out
    assert "actual response:  'blue'" in out
    assert "judge score:      1.000" in out
    assert "judge reasoning:  'perfect.'" in out


def test_threshold_violation_reports_its_context_exactly_once(
    pytester: pytest.Pytester,
) -> None:
    """The threshold `AssertionError` already renders these fields; no second copy.

    Without the suppression the reader would get the assertion message and an
    identical section stacked under it on every violation — the most common
    failure of all.
    """
    # A low-scoring backend isn't one of `_make_eval_file`'s two, so write the
    # file directly.
    dataset = pytester.path / "sample.jsonl"
    _write_dataset(dataset)
    pytester.makepyfile(
        f"""
        import pytest
        from eval_harness.runner import DatasetEchoSource

        class _LowBackend:
            def complete(self, system, user):
                return "SCORE: 0.1\\nREASONING: weak."

        @pytest.mark.eval(
            suite="demo",
            dataset=r"{dataset}",
            answer_source=DatasetEchoSource(),
            judge_backend=_LowBackend(),
            threshold=0.5,
        )
        def test_demo(eval_row):
            pass
        """
    )
    result = pytester.runpytest("-v", "-p", "eval_harness")
    result.assert_outcomes(failed=1)
    out = result.stdout.str()
    # The assertion message still carries everything.
    assert "score=0.100" in out
    assert "threshold=0.500" in out
    # …and the section is not stacked under it.
    result.stdout.no_fnmatch_line(_SECTION)


def test_passing_eval_gets_no_context_section(pytester: pytest.Pytester) -> None:
    """Anti-vacuous arm: the block is attached on failure, not unconditionally.

    Without this, a hook that appended the section to every report would pass
    all four tests above.
    """
    _make_eval_file(pytester, answer_source="DatasetEchoSource()", backend="_PassBackend()")
    result = pytester.runpytest("-v", "-p", "eval_harness")
    result.assert_outcomes(passed=1)
    result.stdout.no_fnmatch_line(_SECTION)


def test_context_survives_show_capture_no(pytester: pytest.Pytester) -> None:
    """`--show-capture=no` must not drop the block.

    `report.sections` is the captured-output channel and the terminal reporter
    filters it by `--show-capture`, so attaching there would let a common CI
    noise-reduction flag silently restore the bug. `longrepr.addsection` writes
    unconditionally.
    """
    _make_eval_file(pytester, answer_source="DatasetEchoSource()", backend="_GarbageBackend()")
    result = pytester.runpytest("-v", "-p", "eval_harness", "--show-capture=no")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines([_SECTION])


def test_non_eval_test_failure_is_untouched(pytester: pytest.Pytester) -> None:
    """A failing test with no `eval` marker gets no section and no crash."""
    pytester.makepyfile(
        """
        def test_plain():
            assert 1 == 2
        """
    )
    result = pytester.runpytest("-v", "-p", "eval_harness")
    result.assert_outcomes(failed=1)
    result.stdout.no_fnmatch_line(_SECTION)
