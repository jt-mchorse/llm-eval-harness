"""`score` and `reasoning` must come from one block of judge output (#200).

`parse_judge_output` ran two independent `.search()` calls with nothing tying
them to the same text, and `_SCORE_RE` is line-anchored with no notion of block
context. So a `JudgeScore` could be assembled from two different parts of the
response, and a score could be lifted out of a fenced code block or out of
prose *about* scores.

Every failure here was silent and deterministic — a well-formed `JudgeScore`,
no exception, no warning. That is why it matters more than a normal parse bug:
a wrong-but-plausible judge score is the failure mode this harness exists to
catch, so it is the one failure it must not manufacture itself (#192).
"""

from __future__ import annotations

import pytest

from eval_harness.judge import JudgeParseError, parse_judge_output

# The literal text of SYSTEM_TEMPLATE's format instruction. A judge restating
# the instruction before complying is one of the most common LLM behaviours
# there is, which is what makes this the sharpest case: the harness's own
# prompt induces the input that broke its parser.
ECHOED_TEMPLATE = (
    "I'll answer in exactly this format and nothing else:\n"
    "SCORE: <number between 0 and 1>\n"
    "REASONING: <one sentence>\n"
    "\n"
)


# ---------------------------------------------------------------------------
# The three confirmed mis-parses
# ---------------------------------------------------------------------------


def test_echoed_template_does_not_split_the_pair_across_blocks():
    """Pre-fix: score 0.85 from the real answer, reasoning '<one sentence>'."""
    raw = ECHOED_TEMPLATE + "SCORE: 0.85\nREASONING: The response cites the passage.\n"

    result = parse_judge_output(raw)

    assert result.score == 0.85
    assert result.reasoning == "The response cites the passage."
    assert "<one sentence>" not in result.reasoning


def test_score_inside_a_code_fence_loses_to_the_real_one():
    """A judge quoting the rubric's worked example was scored at its value."""
    raw = (
        "```\n"
        "SCORE: 0.10\n"
        "REASONING: example from the rubric\n"
        "```\n"
        "\n"
        "SCORE: 0.90\n"
        "REASONING: actual\n"
    )

    result = parse_judge_output(raw)

    assert result.score == 0.90
    assert result.reasoning == "actual"


def test_tilde_fences_count_too():
    """CommonMark allows both fence characters."""
    raw = "~~~\nSCORE: 0.10\nREASONING: example\n~~~\n\nSCORE: 0.90\nREASONING: actual\n"

    assert parse_judge_output(raw).score == 0.90


def test_score_mentioned_in_prose_is_rejected_not_silently_used():
    """The judge is *explaining* what 0.0 means and used to be scored 0.0.

    Rejecting loudly is the right direction: refusing a score it cannot trust
    beats manufacturing a plausible wrong one.
    """
    raw = "REASONING: the rubric says\nSCORE: 0.0\nmeans refusal\n"

    with pytest.raises(JudgeParseError, match="after the SCORE"):
        parse_judge_output(raw)


def test_a_fenced_block_is_not_a_source_of_scores_at_all():
    raw = "```\nSCORE: 0.10\nREASONING: example\n```\n"

    with pytest.raises(JudgeParseError, match="missing SCORE"):
        parse_judge_output(raw)


def test_unclosed_fence_swallows_to_end_of_text():
    """The conservative direction: refuse rather than trust."""
    raw = "```\nSCORE: 0.10\nREASONING: example\n"

    with pytest.raises(JudgeParseError, match="missing SCORE"):
        parse_judge_output(raw)


def test_an_inner_shorter_fence_does_not_close_a_longer_one():
    """A ```` block is closed only by a run at least as long."""
    raw = "````\n```\nSCORE: 0.10\nREASONING: example\n```\n````\n\nSCORE: 0.9\nREASONING: real\n"

    assert parse_judge_output(raw).score == 0.9


# ---------------------------------------------------------------------------
# Locks: every shape that already worked must keep working
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "raw", "score", "reasoning"),
    [
        ("canonical", "SCORE: 0.85\nREASONING: good\n", 0.85, "good"),
        (
            "chatty preamble",
            "Here is my evaluation.\n\nSCORE: 0.85\nREASONING: good\n",
            0.85,
            "good",
        ),
        ("number on next line", "SCORE:\n0.85\nREASONING: good\n", 0.85, "good"),
        ("lowercase", "score: 0.85\nreasoning: good\n", 0.85, "good"),
        ("leading whitespace", "   SCORE: 0.85\n   REASONING: good\n", 0.85, "good"),
        ("trailing whitespace", "SCORE: 0.85   \nREASONING: good   \n", 0.85, "good"),
        ("crlf", "SCORE: 0.85\r\nREASONING: good\r\n", 0.85, "good"),
        # Clamps and numeric shapes fixed by earlier issues, re-pinned here
        # because this change moves the code that feeds them.
        ("trailing-dot int (#132)", "SCORE: 1.\nREASONING: good\n", 1.0, "good"),
        ("leading-dot (#132)", "SCORE: .5\nREASONING: good\n", 0.5, "good"),
        ("negative clamps (#71)", "SCORE: -0.1\nREASONING: below\n", 0.0, "below"),
        ("over-one clamps", "SCORE: 1.05\nREASONING: above\n", 1.0, "above"),
    ],
)
def test_previously_working_shapes_are_unchanged(label, raw, score, reasoning):
    result = parse_judge_output(raw)

    assert result.score == score, label
    assert result.reasoning == reasoning, label


def test_degenerate_repetition_still_rejected():
    """#192: `float('9' * 320)` is `inf`; clamped naively that was a perfect 1.0."""
    raw = "SCORE: " + "9" * 320 + "\nREASONING: degenerate\n"

    with pytest.raises(JudgeParseError, match="non-finite"):
        parse_judge_output(raw)


def test_missing_reasoning_still_raises():
    with pytest.raises(JudgeParseError, match="REASONING"):
        parse_judge_output("SCORE: 0.85\n")


def test_missing_score_still_raises():
    with pytest.raises(JudgeParseError, match="missing SCORE"):
        parse_judge_output("REASONING: no score here\n")


def test_raw_is_preserved_verbatim():
    raw = ECHOED_TEMPLATE + "SCORE: 0.5\nREASONING: r\n"

    assert parse_judge_output(raw).raw == raw
