"""LLM-as-judge wrapper.

A `Judge` scores a model response against a rubric and returns a structured
verdict. The judge is just a thin wrapper around an LLM call — the value isn't
the wrapper, it's the calibration step (`eval_harness.calibration`) that
proves the wrapper agrees with humans on a held-out set.

Backends are pluggable through the `Backend` Protocol so tests can substitute a
deterministic stub without an API key. The production backend is
`AnthropicBackend` (requires `anthropic` extra installed; lazy-imported).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class JudgeScore:
    """Structured verdict from a single judge call."""

    score: float  # in [0, 1]
    reasoning: str  # one sentence explaining the score
    raw: str  # the full model response, for audit/replay

    def __post_init__(self) -> None:
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(f"score must be in [0, 1]; got {self.score}")


class Backend(Protocol):
    """Single-method backend so any caller can swap models without changing Judge."""

    def complete(self, system: str, user: str) -> str:
        """Return the model's text response to the (system, user) pair."""


# ----------------------------------------------------------------------
# Production backend: Anthropic (lazy import; the module loads without
# the extra installed so tests can use Judge with a stub backend).
# ----------------------------------------------------------------------


class AnthropicBackend:
    """Production backend wrapping `anthropic.Anthropic.messages.create`.

    Requires the `judge` optional dependency: `pip install eval-harness[judge]`.
    """

    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        # Validate before the lazy `import anthropic` so misconfig fails fast
        # without the `judge` extra installed. Mirrors `runs.list_runs.limit`
        # (#42) and the portfolio-wide positive-int contract sweep.
        # `bool` is rejected explicitly: `bool` subclasses `int`, so `True`
        # silently bound `self.max_tokens = True` → API received `max_tokens=1`
        # → 1-token judge response → `parse_judge_output` raised
        # `JudgeParseError` far from the misconfig site. `0` / negatives /
        # floats reached the API and surfaced as opaque 400s.
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
            raise ValueError(f"max_tokens must be a positive integer; got {max_tokens!r}")

        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "AnthropicBackend requires the optional `judge` extra. "
                "Install with: pip install 'eval-harness[judge]'"
            ) from e

        self._anthropic_module = anthropic
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get(
            "EVAL_HARNESS_JUDGE_MODEL", "claude-haiku-4-5-20251001"
        )
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # `content` is a list of content blocks; concatenate text-typed blocks.
        out: list[str] = []
        for block in msg.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                out.append(text)
        return "".join(out)


# ----------------------------------------------------------------------
# Default rubrics
# ----------------------------------------------------------------------

#: The faithfulness rubric: does the response stay grounded in the prompt's
#: facts? Used as the default for calibration so different judge models
#: target the same scoring axis.
FAITHFULNESS_RUBRIC = (
    "Score how faithful the RESPONSE is to the PROMPT. A faithful response "
    "answers the question without inventing facts. Score 1.0 if the response "
    "is fully faithful, 0.0 if it contradicts the prompt or invents facts, "
    "and intermediate values for partially-grounded responses."
)


# ----------------------------------------------------------------------
# Judge
# ----------------------------------------------------------------------


SYSTEM_TEMPLATE = (
    "You are an evaluation judge. You score a model response against a rubric. "
    "You answer in EXACTLY this format and nothing else:\n"
    "SCORE: <number between 0 and 1>\n"
    "REASONING: <one sentence>\n"
)

USER_TEMPLATE = "RUBRIC: {rubric}\n\nPROMPT: {prompt}\n\nRESPONSE: {response}\n"

# Strict response parser. Tolerates surrounding whitespace and case. An
# optional leading sign is accepted so an out-of-range *negative* score
# (e.g. `SCORE: -0.1`) matches the SCORE line and reaches the clamp in
# `parse_judge_output`, rather than failing the SCORE-line match and
# surfacing as a misleading "missing SCORE: line" error (#71).
_SCORE_RE = re.compile(r"^\s*SCORE:\s*([+-]?[0-9]*\.?[0-9]+)\s*$", re.MULTILINE | re.IGNORECASE)
_REASON_RE = re.compile(r"^\s*REASONING:\s*(.+)$", re.MULTILINE | re.IGNORECASE)


class JudgeParseError(ValueError):
    """Raised when the judge backend's output doesn't match the SCORE/REASONING format."""


class Judge:
    """Score (prompt, response, rubric) → JudgeScore via a pluggable backend."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def score(self, prompt: str, response: str, rubric: str = FAITHFULNESS_RUBRIC) -> JudgeScore:
        """Run one judging round-trip. Raises JudgeParseError on malformed backend output."""
        user = USER_TEMPLATE.format(rubric=rubric, prompt=prompt, response=response)
        raw = self.backend.complete(SYSTEM_TEMPLATE, user)
        return parse_judge_output(raw)


def parse_judge_output(raw: str) -> JudgeScore:
    """Parse the SCORE/REASONING format. Public so re-recorded judge fixtures can be replayed."""
    score_match = _SCORE_RE.search(raw)
    reason_match = _REASON_RE.search(raw)
    if score_match is None:
        raise JudgeParseError(f"missing SCORE: line in judge output: {raw!r}")
    if reason_match is None:
        raise JudgeParseError(f"missing REASONING: line in judge output: {raw!r}")
    score = float(score_match.group(1))
    # Clamp out-of-range scores symmetrically: the model occasionally returns
    # just over 1.0 (e.g. 1.05) or, less often, just under 0.0 (e.g. -0.1).
    # The SCORE regex now matches a leading sign (#71) so both ends reach here.
    score = max(0.0, min(1.0, score))
    reasoning = reason_match.group(1).strip()
    return JudgeScore(score=score, reasoning=reasoning, raw=raw)
