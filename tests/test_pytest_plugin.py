"""Tests for the eval_harness pytest plugin (issue #5).

The plugin runs in this same pytest process (via the entry point), so
we use `pytester` to run synthetic test files in subprocesses. Each
synthetic file marks one or two tests with `@pytest.mark.eval(...)`
and asserts the plugin parametrizes them as expected.
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


def _write_sample_dataset(path: Path) -> None:
    path.write_text("\n".join(json.dumps(r) for r in _SAMPLE_DATASET_LINES) + "\n")


def test_marker_parametrizes_one_item_per_row(pytester: pytest.Pytester) -> None:
    dataset = pytester.path / "sample.jsonl"
    _write_sample_dataset(dataset)

    pytester.makepyfile(
        f"""
        import pytest
        from eval_harness.judge import JudgeScore
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
        def test_demo(eval_row, judge_score):
            assert isinstance(judge_score, JudgeScore)
            assert judge_score.score == 1.0
        """
    )
    result = pytester.runpytest("-v", "-p", "eval_harness")
    result.assert_outcomes(passed=2)
    # Parametrize ids equal the row ids.
    out = result.stdout.str()
    assert "[qa_001]" in out
    assert "[qa_002]" in out


def test_marker_threshold_failure_includes_row_context(pytester: pytest.Pytester) -> None:
    dataset = pytester.path / "sample.jsonl"
    _write_sample_dataset(dataset)

    pytester.makepyfile(
        f"""
        import pytest
        from eval_harness.runner import DatasetEchoSource

        class _LowBackend:
            def complete(self, system, user):
                return "SCORE: 0.10\\nREASONING: weak."

        @pytest.mark.eval(
            suite="demo",
            dataset=r"{dataset}",
            answer_source=DatasetEchoSource(),
            judge_backend=_LowBackend(),
            threshold=0.5,
        )
        def test_demo(eval_row):
            pass  # body intentionally empty; the plugin enforces threshold
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=2)
    out = result.stdout.str()
    # Row id, expected outputs, response, and judge reasoning all surface.
    assert "qa_001" in out
    assert "score=0.100" in out
    assert "threshold=0.500" in out
    assert "weak." in out


def _write_low_scoring_eval(pytester: pytest.Pytester) -> None:
    """A single eval test scoring 0.10 against threshold 0.5 (always fails)."""
    dataset = pytester.path / "sample.jsonl"
    _write_sample_dataset(dataset)
    pytester.makepyfile(
        f"""
        import pytest
        from eval_harness.runner import DatasetEchoSource

        class _LowBackend:
            def complete(self, system, user):
                return "SCORE: 0.10\\nREASONING: weak."

        @pytest.mark.eval(
            suite="demo",
            dataset=r"{dataset}",
            answer_source=DatasetEchoSource(),
            judge_backend=_LowBackend(),
            threshold=0.5,
        )
        def test_demo(eval_row):
            pass  # body intentionally empty; the plugin enforces threshold
        """
    )


def test_threshold_violation_emits_no_teardown_warning(pytester: pytest.Pytester) -> None:
    """#152: raising the threshold assertion must not trip PluggyTeardownRaisedWarning.

    The old-style ``hookwrapper=True`` form raised the AssertionError after
    ``yield`` (in the wrapper's teardown); modern pluggy flags that on every
    violation. The new-style ``wrapper=True`` form raises inside the call
    phase, so a violation is a plain failed test with no spurious warning.
    """
    _write_low_scoring_eval(pytester)
    result = pytester.runpytest("-v")
    # A violation is a plain failed test with ZERO warnings. The old
    # teardown-raise produced one PluggyTeardownRaisedWarning per violation
    # (warnings=2 here). Asserting the warning *count* is robust — a substring
    # scan of stdout would false-match the plugin docstring rendered in the
    # failing test's traceback.
    result.assert_outcomes(failed=2, warnings=0)


def test_threshold_violation_is_clean_assertionerror_under_warnings_as_errors(
    pytester: pytest.Pytester,
) -> None:
    """#152: under ``-W error`` a violation stays a clean AssertionError.

    With the old teardown-raise, ``-W error`` re-surfaced the failure as
    ``pluggy.PluggyTeardownRaisedWarning`` and buried the structured
    row/score/reasoning block in the warning body. New-style keeps the
    failure attributed to the AssertionError with the diagnostic intact.
    """
    _write_low_scoring_eval(pytester)
    result = pytester.runpytest("-v", "-W", "error")
    result.assert_outcomes(failed=2)
    # The failure must NOT be the pluggy teardown warning promoted to an error.
    # The old code's crash line was ``E  pluggy.PluggyTeardownRaisedWarning: ...``;
    # match on the dotted ``pluggy.`` prefix, which the plugin docstring (rendered
    # in the traceback) never produces — it wraps "pluggy" and the class name onto
    # separate lines, so this is immune to docstring pollution.
    result.stdout.no_fnmatch_line("*pluggy.PluggyTeardownRaisedWarning*")
    # The structured row/score/reasoning block still surfaces in the failure body.
    out = result.stdout.str()
    assert "score=0.100" in out
    assert "threshold=0.500" in out
    assert "weak." in out


def test_marker_missing_required_kwarg_raises_at_collection(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.eval(suite="demo")  # missing dataset, answer_source, judge_backend
        def test_demo():
            pass
        """
    )
    result = pytester.runpytest("-v")
    # An exception during pytest_generate_tests surfaces as a collection error.
    result.assert_outcomes(errors=1)
    assert "missing required kwargs" in result.stdout.str()


def test_marker_explicit_empty_rubric_raises_at_collection(pytester: pytest.Pytester) -> None:
    # #75: an absent rubric defaults (covered by the other marker tests that omit
    # it), but an explicit empty/whitespace rubric is a mistake and must fail
    # loud rather than silently swap in FAITHFULNESS_RUBRIC.
    pytester.makepyfile(
        """
        import pytest
        from eval_harness.runner import DatasetEchoSource

        class _Backend:
            def complete(self, system, user):
                return "SCORE: 1.0\\nREASONING: ok."

        @pytest.mark.eval(
            suite="demo",
            dataset="unused.jsonl",
            answer_source=DatasetEchoSource(),
            judge_backend=_Backend(),
            rubric="   ",
        )
        def test_demo():
            pass
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(errors=1)
    assert "rubric must be a non-empty string" in result.stdout.str()


def test_marker_empty_dataset_fails_collection(pytester: pytest.Pytester) -> None:
    empty = pytester.path / "empty.jsonl"
    empty.write_text("")
    pytester.makepyfile(
        f"""
        import pytest
        from eval_harness.runner import DatasetEchoSource

        class _Backend:
            def complete(self, system, user):
                return "SCORE: 1.0\\nREASONING: ok."

        @pytest.mark.eval(
            suite="demo",
            dataset=r"{empty}",
            answer_source=DatasetEchoSource(),
            judge_backend=_Backend(),
        )
        def test_demo():
            pass
        """
    )
    result = pytester.runpytest("-v")
    # Empty datasets fail loudly rather than passing 0 tests silently —
    # the dataset loader's own "contains no examples" error surfaces
    # during collection.
    out = result.stdout.str()
    assert "contains no examples" in out or "empty dataset" in out


def test_marker_default_threshold_is_zero_point_six(pytester: pytest.Pytester) -> None:
    dataset = pytester.path / "sample.jsonl"
    _write_sample_dataset(dataset)
    pytester.makepyfile(
        f"""
        import pytest
        from eval_harness.runner import DatasetEchoSource

        class _Backend:
            def complete(self, system, user):
                return "SCORE: 0.65\\nREASONING: barely."

        @pytest.mark.eval(
            suite="demo",
            dataset=r"{dataset}",
            answer_source=DatasetEchoSource(),
            judge_backend=_Backend(),
        )  # no threshold kwarg; default 0.6
        def test_demo(eval_row):
            pass
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=2)


def test_non_eval_tests_unaffected_by_plugin(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_plain_arithmetic():
            assert 1 + 1 == 2

        def test_plain_string():
            assert "hello".upper() == "HELLO"
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=2)
