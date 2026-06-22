"""Pytest plugin: register eval suites as test items (issue #5).

Usage::

    from eval_harness.dataset import load_jsonl
    from eval_harness.judge import AnthropicBackend
    from eval_harness.runner import DatasetEchoSource

    @pytest.mark.eval(
        suite="faithfulness",
        dataset="fixtures/sample.jsonl",
        answer_source=DatasetEchoSource(),
        judge_backend=AnthropicBackend(),   # or a stub for hermetic runs
        threshold=0.6,
        rubric=None,                         # defaults to FAITHFULNESS_RUBRIC
    )
    def test_faithfulness_eval(eval_row, judge_score):
        # body is optional; the plugin asserts threshold automatically. A
        # body can run extra checks if needed.
        pass

The plugin parametrizes the marked test once per row in the dataset (so
`pytest -v` shows one item per example, with row id as the parametrize
label). For each row it:

1. Calls the configured ``answer_source.answer(example)`` to get the
   candidate response.
2. Calls ``judge.score(prompt, response, rubric)`` to get a score.
3. Asserts ``score >= threshold``.
4. On failure, attaches a structured block to the test's failure output
   containing the row id, expected output(s), actual response, the
   judge's score, and the judge's reasoning so reviewers don't have to
   dig through stdout.

Why parametrize over `pytest_collection_modifyitems`: the parametrize
seam plays well with `pytest -k`, `--collect-only`, parallel runners
(pytest-xdist), and pytest's per-item caching. Synthesizing items in
`modifyitems` would have given us more control but at the cost of
breaking those integrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from eval_harness.dataset import Example, load_jsonl
from eval_harness.judge import FAITHFULNESS_RUBRIC, Backend, Judge, JudgeScore


def pytest_configure(config: pytest.Config) -> None:
    """Register the `eval` marker so users don't see PytestUnknownMarkWarning."""
    config.addinivalue_line(
        "markers",
        "eval(suite, dataset, answer_source, judge_backend, threshold=0.6, "
        "rubric=None): run the marked test as one item per dataset row, "
        "scored by the judge_backend against the rubric, asserting score >= threshold.",
    )


@dataclass(frozen=True)
class _EvalSpec:
    """Resolved kwargs from a `@pytest.mark.eval(...)` decorator."""

    suite: str
    dataset_path: str
    answer_source: Any
    judge_backend: Backend
    threshold: float
    rubric: str


def _read_marker(mark: pytest.Mark) -> _EvalSpec:
    kw = dict(mark.kwargs)
    missing = [k for k in ("suite", "dataset", "answer_source", "judge_backend") if k not in kw]
    if missing:
        raise ValueError(
            f"@pytest.mark.eval is missing required kwargs: {missing}. "
            "Required: suite, dataset, answer_source, judge_backend. "
            "Optional: threshold (default 0.6), rubric (default FAITHFULNESS_RUBRIC)."
        )
    # Rubric is optional: an *absent* rubric defaults to FAITHFULNESS_RUBRIC.
    # But an explicitly-provided empty/whitespace rubric is a mistake, not a
    # request for the default — `kw.get("rubric") or DEFAULT` silently swallowed
    # it (#75). Distinguish None (default) from "" (raise).
    raw_rubric = kw.get("rubric")
    if raw_rubric is None:
        rubric = FAITHFULNESS_RUBRIC
    else:
        rubric = str(raw_rubric)
        if not rubric.strip():
            raise ValueError(
                "@pytest.mark.eval rubric must be a non-empty string when provided; "
                "omit the kwarg to use the default FAITHFULNESS_RUBRIC."
            )
    return _EvalSpec(
        suite=str(kw["suite"]),
        dataset_path=str(kw["dataset"]),
        answer_source=kw["answer_source"],
        judge_backend=kw["judge_backend"],
        threshold=float(kw.get("threshold", 0.6)),
        rubric=rubric,
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """If a test has `@pytest.mark.eval(...)`, parametrize it with one row per dataset entry."""
    marker = metafunc.definition.get_closest_marker("eval")
    if marker is None:
        return
    spec = _read_marker(marker)
    dataset = load_jsonl(spec.dataset_path)
    examples = list(dataset.examples)
    if not examples:
        # An empty dataset is a real problem worth surfacing — fail
        # collection rather than passing zero tests silently.
        raise pytest.UsageError(
            f"@pytest.mark.eval points at an empty dataset: {spec.dataset_path}"
        )

    if "eval_row" in metafunc.fixturenames:
        metafunc.parametrize("eval_row", examples, ids=[ex.id for ex in examples], scope="function")
    if "judge_score" in metafunc.fixturenames:
        # `judge_score` is computed inside the test via the eval_row fixture;
        # this parametrize is just to make pytest aware the fixture varies.
        # The actual scoring happens in the autouse fixture below.
        pass


@pytest.fixture
def _eval_spec(request: pytest.FixtureRequest) -> _EvalSpec:
    marker = request.node.get_closest_marker("eval")
    if marker is None:
        raise pytest.UsageError("_eval_spec fixture used without @pytest.mark.eval on the test")
    return _read_marker(marker)


@pytest.fixture
def judge_score(
    request: pytest.FixtureRequest, _eval_spec: _EvalSpec, eval_row: Example
) -> JudgeScore:
    """Score the current row via the judge configured on the marker.

    Cached on the request node so the test body and the autouse assertion
    fixture see the same score (and the same call cost). The score is
    attached to the node so `pytest_runtest_makereport` can surface it on
    failure.
    """
    judge = Judge(backend=_eval_spec.judge_backend)
    response = _eval_spec.answer_source.answer(eval_row)
    score = judge.score(eval_row.input, response, _eval_spec.rubric)
    request.node._eval_judge_score = score
    request.node._eval_response = response
    request.node._eval_row = eval_row
    return score


@pytest.hookimpl(hookwrapper=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function):
    """Wrap each eval-marked test call to add the threshold assertion.

    Using ``pytest_pyfunc_call`` (instead of an autouse fixture's
    teardown) keeps the threshold check inside the test's "call" phase,
    so a violation surfaces as a ``failed`` outcome rather than an
    ``error`` (which is what a fixture-teardown AssertionError counts as).
    """
    marker = pyfuncitem.get_closest_marker("eval")
    if marker is None:
        # Not an eval test — pass through unchanged.
        yield
        return

    outcome = yield  # run the user's test body
    # If the body already failed, surface that — the row + score context
    # is already attached by the judge_score fixture, so pytest's normal
    # failure rendering shows the AssertionError plus our stashed extras.
    try:
        outcome.get_result()
    except BaseException:  # noqa: BLE001 — re-raise after body-failure path
        raise

    # Body passed (or was empty). Run the threshold check now, inside
    # the call phase, so a violation is a `failed` outcome.
    score: JudgeScore = pyfuncitem.funcargs.get("judge_score") or getattr(
        pyfuncitem, "_eval_judge_score", None
    )
    if score is None:
        return  # judge_score fixture wasn't triggered (e.g., no body referenced it)
    spec: _EvalSpec = getattr(pyfuncitem, "_eval_spec_cached", None) or _read_marker(marker)
    if score.score < spec.threshold:
        row = getattr(pyfuncitem, "_eval_row", None)
        response = getattr(pyfuncitem, "_eval_response", None)
        expected = [eo.value for eo in row.expected_outputs] if row is not None else []
        raise AssertionError(
            f"eval_row.id={row.id!r} score={score.score:.3f} "
            f"< threshold={spec.threshold:.3f}\n"
            f"  expected outputs: {expected}\n"
            f"  actual response:  {response!r}\n"
            f"  judge reasoning:  {score.reasoning!r}"
        )


@pytest.fixture(autouse=True)
def _ensure_judge_score_runs(request: pytest.FixtureRequest):
    """For eval tests whose body doesn't reference `judge_score`, trigger it.

    Without this, the user could write ``def test_demo(eval_row): pass`` and
    skip the judge entirely — the marker would be inert. Triggering the
    fixture via ``getfixturevalue`` makes the scoring run for every
    eval-marked test regardless of body signature.
    """
    marker = request.node.get_closest_marker("eval")
    if marker is None:
        return
    # The marker is present; force the score (its fixture handles caching).
    request.getfixturevalue("judge_score")


def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):
    """Attach eval context to the failure report if present.

    pytest's default failure output points at the AssertionError raised
    in `_enforce_threshold`, which already carries the row id + score +
    reasoning in its message. This hook is a belt-and-braces step: if
    something *else* in the test path raised (a judge timeout, a parse
    error, an answer-source failure), the row id and the response are
    still surfaced.
    """
    if call.when != "call":
        return
    if not hasattr(item, "_eval_row"):
        return
    if call.excinfo is None:
        return
    extra = [
        "",
        "Eval context:",
        f"  row_id:           {item._eval_row.id}",
        f"  expected outputs: {[eo.value for eo in item._eval_row.expected_outputs]}",
    ]
    if hasattr(item, "_eval_response"):
        extra.append(f"  actual response:  {item._eval_response!r}")
    if hasattr(item, "_eval_judge_score"):
        score = item._eval_judge_score
        extra.append(f"  judge score:      {score.score:.3f}")
        extra.append(f"  judge reasoning:  {score.reasoning!r}")
    # The hook can't directly edit the report (it hasn't been built yet
    # at when=="call"); stash the extra block on the item so the
    # `pytest_runtest_logreport` consumer below can attach it.
    item._eval_failure_extra = "\n".join(extra)


def pytest_runtest_logreport(report: pytest.TestReport):
    """Hook reserved for non-assertion failure paths.

    Threshold violations raise an AssertionError whose message already
    contains row_id / expected / actual / reasoning, so pytest's default
    longrepr renders them. This hook is left in place as a known
    extension point for future paths (judge timeouts, answer-source
    failures) that may want to enrich the report.
    """
    return
