"""Tests for the Judge wrapper.

The judge is a thin wrapper around an LLM call. The interesting bits to test
hermetically are: (a) the prompt template is formatted correctly, (b) the
response parser is strict about the SCORE/REASONING format, (c) the score is
clamped to [0, 1], (d) Judge composes with a stub Backend without any
network access.
"""

from __future__ import annotations

import math

import pytest

from eval_harness.judge import (
    FAITHFULNESS_RUBRIC,
    AnthropicBackend,
    Judge,
    JudgeParseError,
    JudgeScore,
    clamp_judge_score,
    is_transient_error,
    parse_judge_output,
    retry_call,
)


class StubBackend:
    """Test double for the Backend protocol. Records the last (system, user) pair."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.last_system: str | None = None
        self.last_user: str | None = None

    def complete(self, system: str, user: str) -> str:
        self.last_system = system
        self.last_user = user
        return self.response


# ----------------------------------------------------------------------
# parse_judge_output
# ----------------------------------------------------------------------


def test_parse_well_formed_output():
    raw = "SCORE: 0.85\nREASONING: response was mostly grounded with one minor invention."
    parsed = parse_judge_output(raw)
    assert parsed.score == pytest.approx(0.85)
    assert parsed.reasoning == "response was mostly grounded with one minor invention."
    assert parsed.raw == raw


def test_parse_score_only_int():
    parsed = parse_judge_output("SCORE: 1\nREASONING: faithful")
    assert parsed.score == 1.0


def test_parse_clamps_above_one():
    parsed = parse_judge_output("SCORE: 1.05\nREASONING: faithful")
    assert parsed.score == 1.0


def test_parse_clamps_below_zero():
    # A negative out-of-range score is clamped symmetrically with the high
    # side, not surfaced as a misleading "missing SCORE: line" error (#71).
    parsed = parse_judge_output("SCORE: -0.2\nREASONING: contradicts the prompt")
    assert parsed.score == 0.0


def test_parse_negative_zero_is_zero():
    # `-0` / `-0.0` is in range; it must parse cleanly (and the sign branch
    # of the regex must not turn a valid in-range value into a parse error).
    parsed = parse_judge_output("SCORE: -0.0\nREASONING: zero")
    assert parsed.score == 0.0


def test_parse_explicit_plus_sign():
    parsed = parse_judge_output("SCORE: +0.4\nREASONING: partial")
    assert parsed.score == pytest.approx(0.4)


def test_parse_trailing_dot_integer():
    # `SCORE: 1.` is a natural way a model writes the integer one
    # (`float("1.") == 1.0`). The pre-#132 regex required a digit after the
    # dot, so it failed the SCORE-line match and raised the misleading
    # "missing SCORE: line" error #71 set out to kill. It must now reach the
    # clamp and parse as 1.0, symmetric with the leading-dot form `.5`.
    parsed = parse_judge_output("SCORE: 1.\nREASONING: faithful")
    assert parsed.score == 1.0


def test_parse_trailing_dot_zero():
    parsed = parse_judge_output("SCORE: 0.\nREASONING: contradicts the prompt")
    assert parsed.score == 0.0


def test_parse_negative_trailing_dot_clamps():
    # Trailing-dot form must also compose with the sign branch and the
    # symmetric clamp: `-1.` → -1.0 → clamped to 0.0 (#132, extends #71).
    parsed = parse_judge_output("SCORE: -1.\nREASONING: fully contradicts")
    assert parsed.score == 0.0


@pytest.mark.parametrize("bad", ["SCORE: .", "SCORE: -", "SCORE: 1.2.3", "SCORE: 1e0"])
def test_parse_trailing_dot_widening_still_rejects_malformed(bad):
    # Widening the numeric group for trailing-dot scores (#132) must not
    # loosen the parser: a bare dot, a sign with no digits, a double-dotted
    # value, and scientific notation all still fail the `\s*$`-anchored match.
    with pytest.raises(JudgeParseError, match="missing SCORE"):
        parse_judge_output(f"{bad}\nREASONING: hi")


def test_parse_non_numeric_score_still_raises():
    # The leading-sign allowance must not loosen the match to non-numeric
    # values: a malformed SCORE line still fails the SCORE-line match.
    with pytest.raises(JudgeParseError, match="missing SCORE"):
        parse_judge_output("SCORE: high\nREASONING: hi")


def test_parse_case_insensitive():
    parsed = parse_judge_output("score: 0.5\nreasoning: half")
    assert parsed.score == 0.5


def test_parse_with_leading_whitespace():
    parsed = parse_judge_output("\n   SCORE: 0.3\n   REASONING: weak\n")
    assert parsed.score == pytest.approx(0.3)


def test_parse_missing_score_raises():
    with pytest.raises(JudgeParseError, match="missing SCORE"):
        parse_judge_output("REASONING: hi")


def test_parse_missing_reasoning_raises():
    with pytest.raises(JudgeParseError, match="missing REASONING"):
        parse_judge_output("SCORE: 0.5")


# ----------------------------------------------------------------------
# JudgeScore validation
# ----------------------------------------------------------------------


def test_judge_score_rejects_out_of_range():
    with pytest.raises(ValueError, match="must be in"):
        JudgeScore(score=1.5, reasoning="x", raw="x")
    with pytest.raises(ValueError, match="must be in"):
        JudgeScore(score=-0.1, reasoning="x", raw="x")


# ----------------------------------------------------------------------
# Judge.score with a stub backend
# ----------------------------------------------------------------------


def test_judge_passes_prompt_response_rubric_to_backend():
    backend = StubBackend(response="SCORE: 0.7\nREASONING: mostly faithful")
    judge = Judge(backend=backend)
    result = judge.score("What's the capital of France?", "Paris.", rubric="custom rubric")

    assert result.score == pytest.approx(0.7)
    assert backend.last_user is not None
    assert "custom rubric" in backend.last_user
    assert "What's the capital of France?" in backend.last_user
    assert "Paris." in backend.last_user


def test_judge_uses_default_rubric():
    backend = StubBackend(response="SCORE: 1.0\nREASONING: ok")
    judge = Judge(backend=backend)
    judge.score("p", "r")
    assert backend.last_user is not None
    assert FAITHFULNESS_RUBRIC in backend.last_user


def test_judge_propagates_parse_error():
    backend = StubBackend(response="this is not a valid response")
    judge = Judge(backend=backend)
    with pytest.raises(JudgeParseError):
        judge.score("p", "r")


# ----------------------------------------------------------------------
# Transient-error classification (#73). Hermetic: no `anthropic` install —
# fake exceptions carry a duck-typed `status_code` or a matching class name.
# ----------------------------------------------------------------------


class _FakeAPIError(Exception):
    """Stand-in for anthropic.APIStatusError: carries an int `status_code`."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class APIConnectionError(Exception):
    """Name-matched to the SDK's connection error; no status_code attribute."""


class APITimeoutError(Exception):
    """Name-matched to the SDK's timeout error; no status_code attribute."""


@pytest.mark.parametrize("code", [408, 409, 429, 500, 502, 503, 504, 529])
def test_is_transient_true_for_transient_status(code):
    assert is_transient_error(_FakeAPIError(code)) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_is_transient_false_for_permanent_status(code):
    assert is_transient_error(_FakeAPIError(code)) is False


def test_is_transient_true_for_connection_error_names():
    assert is_transient_error(APIConnectionError("boom")) is True
    assert is_transient_error(APITimeoutError("slow")) is True


def test_is_transient_false_for_plain_exception_without_status():
    # A ValueError (e.g. a parse error) is not a transient API failure.
    assert is_transient_error(ValueError("nope")) is False


def test_is_transient_ignores_bool_status_code():
    # `bool` subclasses `int`; a status_code of True must not match the int
    # branch (and 1 isn't transient anyway). Falls through to name match.
    exc = _FakeAPIError(429)
    exc.status_code = True  # type: ignore[assignment]
    assert is_transient_error(exc) is False


# ----------------------------------------------------------------------
# retry_call (#73): capped exponential backoff with an injected clock.
# ----------------------------------------------------------------------


class _Clock:
    """Records sleep durations instead of waiting."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def test_retry_succeeds_first_try_no_sleep():
    clock = _Clock()
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    assert retry_call(fn, max_attempts=4, base_delay=0.5, max_delay=8.0, sleep=clock) == "ok"
    assert len(calls) == 1
    assert clock.sleeps == []


def test_retry_transient_then_success():
    clock = _Clock()
    attempts = {"n": 0}

    def fn():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _FakeAPIError(429)
        return "ok"

    assert retry_call(fn, max_attempts=4, base_delay=0.5, max_delay=8.0, sleep=clock) == "ok"
    assert attempts["n"] == 3
    # Two backoffs before the third (successful) attempt: 0.5, 1.0.
    assert clock.sleeps == [0.5, 1.0]


def test_retry_exhausts_and_reraises_last_transient():
    clock = _Clock()
    calls = []

    def fn():
        calls.append(1)
        raise _FakeAPIError(529)

    with pytest.raises(_FakeAPIError):
        retry_call(fn, max_attempts=3, base_delay=0.5, max_delay=8.0, sleep=clock)
    # 3 total attempts, 2 backoffs between them (no sleep after the last).
    assert len(calls) == 3
    assert clock.sleeps == [0.5, 1.0]


def test_retry_non_transient_raises_immediately():
    clock = _Clock()
    calls = []

    def fn():
        calls.append(1)
        raise _FakeAPIError(400)

    with pytest.raises(_FakeAPIError):
        retry_call(fn, max_attempts=5, base_delay=0.5, max_delay=8.0, sleep=clock)
    assert len(calls) == 1  # no retry on a permanent client error
    assert clock.sleeps == []


def test_retry_backoff_is_capped_at_max_delay():
    clock = _Clock()

    def fn():
        raise _FakeAPIError(503)

    with pytest.raises(_FakeAPIError):
        retry_call(fn, max_attempts=6, base_delay=1.0, max_delay=4.0, sleep=clock)
    # Uncapped would be 1, 2, 4, 8, 16; capped at 4.0 → 1, 2, 4, 4, 4.
    assert clock.sleeps == [1.0, 2.0, 4.0, 4.0, 4.0]


def test_retry_max_attempts_one_means_no_retry():
    clock = _Clock()
    calls = []

    def fn():
        calls.append(1)
        raise _FakeAPIError(429)

    with pytest.raises(_FakeAPIError):
        retry_call(fn, max_attempts=1, base_delay=0.5, max_delay=8.0, sleep=clock)
    assert len(calls) == 1
    assert clock.sleeps == []


# ----------------------------------------------------------------------
# AnthropicBackend retry knob validation + complete() end-to-end (#73).
# Built via __new__ so no `anthropic` install / API key is needed.
# ----------------------------------------------------------------------


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, fail_times: int, status_code: int, text: str) -> None:
        self._remaining = fail_times
        self._status_code = status_code
        self._text = text
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise _FakeAPIError(self._status_code)
        return _FakeMessage(self._text)


class _FakeClient:
    def __init__(self, messages: _FakeMessages) -> None:
        self.messages = messages


def _backend_with_fake(client: _FakeClient, *, sleep, max_attempts=4) -> AnthropicBackend:
    """Construct an AnthropicBackend bypassing __init__ (no anthropic import)."""
    be = AnthropicBackend.__new__(AnthropicBackend)
    be.client = client
    be.model = "claude-haiku-4-5-20251001"
    be.max_tokens = 512
    be.max_attempts = max_attempts
    be.base_retry_delay = 0.5
    be.max_retry_delay = 8.0
    be._sleep = sleep
    return be


def test_backend_complete_retries_transient_then_returns_text():
    clock = _Clock()
    msgs = _FakeMessages(fail_times=2, status_code=429, text="SCORE: 0.9\nREASONING: ok")
    be = _backend_with_fake(_FakeClient(msgs), sleep=clock)
    out = be.complete("sys", "user")
    assert out == "SCORE: 0.9\nREASONING: ok"
    assert msgs.calls == 3
    assert clock.sleeps == [0.5, 1.0]


def test_backend_complete_reraises_permanent_error_without_retry():
    # 400, not 401: #194 reclassifies 401/403 (credential failures) into
    # `JudgeAuthError` so the CLI can exit 2 on them. This test's subject is
    # the *no-retry* property of a permanent error, which 400 exercises
    # identically; the auth-code path gets its own test below, and pins the
    # same `calls == 1` / `sleeps == []` property so nothing is lost here.
    clock = _Clock()
    msgs = _FakeMessages(fail_times=5, status_code=400, text="unused")
    be = _backend_with_fake(_FakeClient(msgs), sleep=clock)
    with pytest.raises(_FakeAPIError):
        be.complete("sys", "user")
    assert msgs.calls == 1
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"max_attempts": True},
        {"max_attempts": 2.0},
        {"base_retry_delay": -1.0},
        {"base_retry_delay": float("inf")},
        {"base_retry_delay": float("nan")},
        {"base_retry_delay": True},
        {"max_retry_delay": -0.1},
        {"max_retry_delay": float("inf")},
    ],
)
def test_backend_rejects_bad_retry_knobs(kwargs):
    # Validation happens before the lazy `import anthropic`, so a bad knob
    # raises ValueError even without the `judge` extra installed.
    with pytest.raises(ValueError, match="must be a"):
        AnthropicBackend(**kwargs)


# ----- non-finite SCORE is corruption, not something to clamp (#192) ---------
#
# `_SCORE_RE`'s numeric group is unbounded (`[0-9]+`), and `float()` does NOT
# raise on a long digit run — `float("9" * 309)` is `inf`. The hand-rolled
# `max(0.0, min(1.0, ...))` then turned that into a PERFECT 1.0, so a judge
# stuck in a degenerate repetition loop — the exact pathology this harness
# exists to catch — scored full marks and made the CI regression gate greener.
#
# `drift._clamp01` had already drawn the line ("clamping is for
# finite-but-out-of-range values; a non-finite score is corruption"); this seam,
# the one closest to the actual model output, was the copy that kept the clamp
# and dropped the finiteness half. Both now call `clamp_judge_score`.


# 309 is where a digit run first exceeds float's range; 4400 is past CPython's
# int<->str digit cap, included to show the silent float path is the only one
# reachable here (no `int()` is involved, so nothing raises on its own).
@pytest.mark.parametrize("n_digits", [309, 400, 4400])
def test_parse_rejects_non_finite_score_instead_of_fabricating_a_perfect_one(n_digits: int):
    raw = f"SCORE: {'9' * n_digits}\nREASONING: degenerate repetition loop"
    # Anchored to the corruption: pre-fix this returned exactly 1.0.
    assert math.isinf(float("9" * n_digits))
    with pytest.raises(JudgeParseError, match="non-finite SCORE"):
        parse_judge_output(raw)


@pytest.mark.parametrize("n_digits", [309, 400])
def test_parse_rejects_non_finite_negative_score(n_digits: int):
    raw = f"SCORE: -{'9' * n_digits}\nREASONING: degenerate repetition loop"
    with pytest.raises(JudgeParseError, match="non-finite SCORE"):
        parse_judge_output(raw)


def test_non_finite_score_error_is_still_a_valueerror():
    """`JudgeParseError` subclasses `ValueError`, so callers that catch
    `ValueError` (the CLI's exit-2 translation) are unaffected by the new raise."""
    assert issubclass(JudgeParseError, ValueError)
    raw = f"SCORE: {'9' * 400}\nREASONING: loop"
    # Caught as the *broad* ValueError on purpose: that's the property keeping
    # the CLI's exit-2 translation working without a new arm.
    with pytest.raises(ValueError, match="non-finite SCORE") as excinfo:
        parse_judge_output(raw)
    assert isinstance(excinfo.value, JudgeParseError)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        # The finite clamp is deliberate and must survive untouched — these
        # mirror test_parse_clamps_above_one / _below_zero and the #132
        # trailing-dot forms.
        ("1.05", 1.0),
        ("-0.1", 0.0),
        ("+1.5", 1.0),
        ("1.", 1.0),
        ("0.7", 0.7),
        (".5", 0.5),
        # A large but FINITE score still clamps rather than raising: 1e308 is
        # representable, so it is "out of range", not "corrupt".
        ("9" * 308, 1.0),
    ],
)
def test_finite_scores_still_clamp_exactly_as_before(line: str, expected: float):
    parsed = parse_judge_output(f"SCORE: {line}\nREASONING: fine")
    assert parsed.score == pytest.approx(expected)


def test_clamp_is_one_implementation_shared_with_drift():
    """`drift._clamp01` and `judge.parse_judge_output` clamp the same domain.
    They agreed by accident before and diverged on the finiteness half; assert
    they are now literally the same callable so they can't drift again."""
    from eval_harness.drift import _clamp01

    assert _clamp01(1.5) == clamp_judge_score(1.5) == 1.0
    assert _clamp01(-0.5) == clamp_judge_score(-0.5) == 0.0
    for bad in (float("nan"), float("inf"), float("-inf"), "x", None, True):
        with pytest.raises(ValueError, match="judge score must be finite"):
            _clamp01(bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="judge score must be finite"):
            clamp_judge_score(bad)  # type: ignore[arg-type]
