"""Tests for the Judge wrapper.

The judge is a thin wrapper around an LLM call. The interesting bits to test
hermetically are: (a) the prompt template is formatted correctly, (b) the
response parser is strict about the SCORE/REASONING format, (c) the score is
clamped to [0, 1], (d) Judge composes with a stub Backend without any
network access.
"""

from __future__ import annotations

import pytest

from eval_harness.judge import (
    FAITHFULNESS_RUBRIC,
    Judge,
    JudgeParseError,
    JudgeScore,
    parse_judge_output,
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
