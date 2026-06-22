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
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar


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
# Transient-failure retry (import-free of the `anthropic` SDK so the
# classifier and the retry tests run without the `judge` extra installed).
# ----------------------------------------------------------------------

_T = TypeVar("_T")

#: HTTP statuses worth retrying. 429 = rate limit, 529 = Anthropic
#: "overloaded", 500/502/503/504 = upstream/gateway hiccups, 408 = request
#: timeout, 409 = transient conflict. A permanent client error (400 bad
#: request, 401 auth, 403 forbidden, 404 not found) is deliberately *not*
#: here: retrying a malformed request or a bad key just burns the backoff
#: budget and delays the real failure.
_TRANSIENT_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504, 529})

#: Connection-level failures (no HTTP status) worth retrying. Matched by
#: class name so the classifier stays import-free and SDK-version-robust —
#: these `anthropic` exception names have been stable across SDK versions.
_TRANSIENT_EXC_NAMES = frozenset({"APIConnectionError", "APITimeoutError"})


def is_transient_error(exc: BaseException) -> bool:
    """True when `exc` is a transient API failure worth retrying.

    Classifies by duck-typed `status_code` (an int on `anthropic.APIStatusError`
    subclasses) and by exception class name for connection-level errors. Both
    paths avoid importing `anthropic`, so the classifier — and the retry tests
    around it — run without the `judge` extra installed. A `status_code` that
    is present but outside the transient set (e.g. 400/401) returns False so a
    permanent client error fails fast.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, bool):
        # `bool` subclasses `int`; a truthy status would falsely compare into
        # the int branch. No real status code is a bool — treat as "no status".
        status = None
    if isinstance(status, int):
        return status in _TRANSIENT_STATUS_CODES
    return type(exc).__name__ in _TRANSIENT_EXC_NAMES


def retry_call(
    fn: Callable[[], _T],
    *,
    max_attempts: int,
    base_delay: float,
    max_delay: float,
    sleep: Callable[[float], None] = time.sleep,
    is_transient: Callable[[BaseException], bool] = is_transient_error,
) -> _T:
    """Call `fn`, retrying transient failures with capped exponential backoff.

    Makes up to `max_attempts` total calls (1 initial + `max_attempts - 1`
    retries). A non-transient error, or exhausting the attempt budget,
    re-raises the last exception unchanged so the caller keeps the original
    traceback. Backoff before retry `i` (0-indexed) is
    `min(max_delay, base_delay * 2**i)` seconds, injected via `sleep` so tests
    pin a fake clock instead of waiting. `KeyboardInterrupt`/`SystemExit` are
    never swallowed — only `Exception` subclasses are candidates for retry.
    """
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            if not is_transient(exc) or attempt == max_attempts - 1:
                raise
            sleep(min(max_delay, base_delay * (2**attempt)))
    # Unreachable: the loop either returns or raises on its final attempt.
    raise AssertionError("retry_call exhausted its loop without returning or raising")


# ----------------------------------------------------------------------
# Production backend: Anthropic (lazy import; the module loads without
# the extra installed so tests can use Judge with a stub backend).
# ----------------------------------------------------------------------


class AnthropicBackend:
    """Production backend wrapping `anthropic.Anthropic.messages.create`.

    Requires the `judge` optional dependency: `pip install eval-harness[judge]`.
    """

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 512,
        *,
        max_attempts: int = 4,
        base_retry_delay: float = 0.5,
        max_retry_delay: float = 8.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
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

        # Retry knobs follow the same contract (#73). `max_attempts` is a
        # positive int (1 = no retries, just the initial call); the two delays
        # are finite non-negative floats. Reject `bool` for `max_attempts` for
        # the same reason as `max_tokens`.
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 1:
            raise ValueError(f"max_attempts must be a positive integer; got {max_attempts!r}")
        for name, val in (
            ("base_retry_delay", base_retry_delay),
            ("max_retry_delay", max_retry_delay),
        ):
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError(f"{name} must be a finite number >= 0.0; got {val!r}")
            if val != val or val in (float("inf"), float("-inf")) or val < 0.0:
                raise ValueError(f"{name} must be a finite number >= 0.0; got {val!r}")

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
        self.max_attempts = max_attempts
        self.base_retry_delay = base_retry_delay
        self.max_retry_delay = max_retry_delay
        self._sleep = sleep

    def complete(self, system: str, user: str) -> str:
        # Wrap the single API call in capped exponential-backoff retry so one
        # transient 429/529/connection blip doesn't abort a whole multi-row
        # `run_suite` (#73). Permanent client errors (400/401/...) are not
        # transient and re-raise immediately via `retry_call`.
        def _once() -> str:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            # `content` is a list of content blocks; concatenate text blocks.
            out: list[str] = []
            for block in msg.content:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    out.append(text)
            return "".join(out)

        return retry_call(
            _once,
            max_attempts=self.max_attempts,
            base_delay=self.base_retry_delay,
            max_delay=self.max_retry_delay,
            sleep=self._sleep,
        )


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
