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
from typing import Any, cast

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
    # Validate `threshold` at collection time. A non-finite (`nan`/`±inf`) or
    # out-of-[0,1] threshold reached the gate `score.score < spec.threshold`
    # unchecked: a `nan`/`-inf` threshold makes that comparison always False, so
    # the assertion never fires and a broken judge scoring 0.0 passes green — the
    # worst failure mode for an eval gate. `1.5` silently makes every eval
    # impossible to pass. The bounds check catches nan/±inf/out-of-range (all
    # `nan` comparisons are False) — but ONLY after the type is nailed down:
    # `bool` is an `int` subclass, so `float(True)==1.0` / `float(False)==0.0`
    # slip through the bounds check silently, `threshold=False` disabling the gate
    # exactly like `-inf`. The sibling guards this comment claims to mirror
    # (`calibration.py`, `judge.py`) reject `bool` and non-numerics explicitly for
    # this reason ("`bool` was silently coerced to 0/1"); do the same here before
    # coercing so `@pytest.mark.eval(threshold=True/False)` — a plausible operator
    # typo — is a loud collection-time error, not a silently mis-set gate.
    raw_threshold = kw.get("threshold", 0.6)
    if isinstance(raw_threshold, bool) or not isinstance(raw_threshold, (int, float)):
        raise ValueError(
            f"@pytest.mark.eval threshold must be a finite number in [0, 1]; got {raw_threshold!r}"
        )
    threshold = float(raw_threshold)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(
            f"@pytest.mark.eval threshold must be a finite number in [0, 1]; got {threshold!r}"
        )
    return _EvalSpec(
        suite=str(kw["suite"]),
        dataset_path=str(kw["dataset"]),
        answer_source=kw["answer_source"],
        judge_backend=kw["judge_backend"],
        threshold=threshold,
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
    # Stash each datum at the moment it becomes known, not all three at the
    # end (#222). All three assignments used to sit below both calls, so an
    # answer-source failure reported nothing and a judge failure reported
    # nothing *even though the response existed* — and the response is the
    # single most useful datum when a judge fails to parse. `pytest_runtest_
    # makereport` renders whatever subset is present.
    request.node._eval_row = eval_row
    response = _eval_spec.answer_source.answer(eval_row)
    request.node._eval_response = response
    score = judge.score(eval_row.input, response, _eval_spec.rubric)
    request.node._eval_judge_score = score
    return score


@pytest.hookimpl(wrapper=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function):
    """Wrap each eval-marked test call to add the threshold assertion.

    Using ``pytest_pyfunc_call`` (instead of an autouse fixture's
    teardown) keeps the threshold check inside the test's "call" phase,
    so a violation surfaces as a ``failed`` outcome rather than an
    ``error`` (which is what a fixture-teardown AssertionError counts as).

    This is a **new-style** wrapper (``wrapper=True``): ``result = yield``
    re-raises a body failure directly, and a threshold ``raise`` here
    propagates as an ordinary call-phase exception. The earlier
    ``hookwrapper=True`` (old-style) form raised the ``AssertionError``
    *after* ``yield``, i.e. during the wrapper's teardown — which modern
    pluggy (>= 1.6, bundled with pytest 8/9) reports as a
    ``PluggyTeardownRaisedWarning`` on every violation, and under
    ``-W error`` / ``filterwarnings = error`` re-surfaces the failure as
    that warning class, burying the structured row/score/reasoning block
    the plugin exists to deliver (#152). New-style keeps the failure a
    clean ``AssertionError`` on all warning configs.
    """
    marker = pyfuncitem.get_closest_marker("eval")
    if marker is None:
        # Not an eval test — pass through unchanged.
        return (yield)

    # Run the user's test body. In a new-style wrapper, ``yield`` re-raises
    # a body failure directly, so the body-failure path needs no explicit
    # re-raise: the row + score context stashed by the judge_score fixture
    # is surfaced by pytest's normal failure rendering.
    result = yield

    # Body passed (or was empty). Run the threshold check now, inside
    # the call phase, so a violation is a `failed` outcome.
    # `funcargs` is typed `dict[str, object]`; the `judge_score` fixture
    # yields a `JudgeScore` (or is absent, hence the `| None`).
    score = cast(
        "JudgeScore | None",
        pyfuncitem.funcargs.get("judge_score") or getattr(pyfuncitem, "_eval_judge_score", None),
    )
    if score is None:
        return result  # judge_score fixture wasn't triggered (e.g., no body referenced it)
    spec: _EvalSpec = getattr(pyfuncitem, "_eval_spec_cached", None) or _read_marker(marker)
    if score.score < spec.threshold:
        row = getattr(pyfuncitem, "_eval_row", None)
        response = getattr(pyfuncitem, "_eval_response", None)
        expected = [eo.value for eo in row.expected_outputs] if row is not None else []
        row_id = row.id if row is not None else None
        # The message below already carries id / score / expected / actual /
        # reasoning, so `pytest_runtest_makereport` must not append a second
        # copy of the same fields (#222). Flag the item rather than matching on
        # the message text or on `AssertionError` — a user's own `assert` in
        # the body is also an AssertionError and *should* get the block.
        #
        # (The flag is also why this comment avoids naming the section header:
        # these source lines are rendered inside the failing test's traceback,
        # so a header spelled here would defeat any test asserting the header
        # is absent.)
        pyfuncitem._eval_threshold_reported = True  # type: ignore[attr-defined]
        raise AssertionError(
            f"eval_row.id={row_id!r} score={score.score:.3f} "
            f"< threshold={spec.threshold:.3f}\n"
            f"  expected outputs: {expected}\n"
            f"  actual response:  {response!r}\n"
            f"  judge reasoning:  {score.reasoning!r}"
        )
    return result


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


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):
    """Attach the eval context to a failing eval test's report.

    This hook exists for the failure paths the threshold assertion does *not*
    cover — a raising answer source, a judge timeout, a `JudgeParseError`, a
    plain `assert` in the user's own body. Before #222 it surfaced nothing on
    any of them, for three independent reasons, each sufficient on its own:

    - It returned unless ``call.when == "call"``. But ``_ensure_judge_score_runs``
      is autouse and pulls ``judge_score`` via ``getfixturevalue``, so the
      answer source and the judge always run in **setup** — the hook returned
      before doing anything on precisely the paths it was written for. Both
      phases are handled now; teardown still isn't, because nothing
      eval-specific runs there.
    - The row / response / score were stashed only *after* both calls returned,
      so the failure paths had nothing to read. The fixture now stashes each
      value at the moment it becomes known.
    - The block it built was assigned to ``item._eval_failure_extra`` and read
      by nothing: the ``pytest_runtest_logreport`` consumer its comment pointed
      at had an empty body. (A mypy pass had even hung a
      ``# type: ignore[attr-defined]`` on that assignment — the attribute was
      type-checked but never read.) Both the stash and the empty consumer are
      gone; the block goes straight onto the report.

    ``longrepr.addsection`` rather than ``report.sections``: the latter is the
    captured-output channel and the terminal reporter filters it by
    ``--show-capture``, so ``--show-capture=no`` (or ``=stdout``) would drop
    this block and quietly restore the bug. ``ExceptionRepr.toterminal`` writes
    its own sections unconditionally, right under the traceback.
    """
    report = yield
    if call.when not in ("setup", "call"):
        return report
    if call.excinfo is None or not hasattr(item, "_eval_row"):
        return report
    # The threshold assertion renders these same fields in its own message.
    if getattr(item, "_eval_threshold_reported", False):
        return report
    # `longrepr` is a plain string for some outcomes (and None for passes);
    # only the exception-repr forms carry `addsection`.
    add_section = getattr(report.longrepr, "addsection", None)
    if add_section is None:
        return report
    add_section("Eval context", _eval_context_block(item))
    return report


def _eval_context_block(item: pytest.Item) -> str:
    """Render whatever eval context the item has reached, one field per line.

    Deliberately partial: an answer-source failure has a row and no response, a
    judge failure has a row and a response and no score. Reporting the subset
    that exists is the whole point — the caller knows which stage it died in
    from the traceback, and needs the inputs that got it there.
    """
    # `_eval_row` is checked by the caller, not here, so it still needs the
    # escape hatch; the two below do not — mypy narrows `item` through the
    # `hasattr` guards and flags a redundant ignore under `warn_unused_ignores`.
    row = item._eval_row  # type: ignore[attr-defined]
    lines = [
        f"row_id:           {row.id}",
        f"input:            {row.input!r}",
        f"expected outputs: {[eo.value for eo in row.expected_outputs]}",
    ]
    if hasattr(item, "_eval_response"):
        lines.append(f"actual response:  {item._eval_response!r}")
    if hasattr(item, "_eval_judge_score"):
        score = item._eval_judge_score
        lines.append(f"judge score:      {score.score:.3f}")
        lines.append(f"judge reasoning:  {score.reasoning!r}")
    return "\n".join(lines)
