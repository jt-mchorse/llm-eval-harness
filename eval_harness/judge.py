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

import math
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar


def clamp_judge_score(x: float) -> float:
    """Clamp a judge score into ``[0, 1]``, rejecting corruption.

    The single implementation of the judge-score contract. Clamping is for
    *finite*-but-out-of-range values — a model returning ``1.05`` or ``-0.1``
    is rounding noise, and squashing it is correct. A **non-finite** score is
    corruption, not something to clamp: ``NaN`` later crashes
    ``drift._judge_histogram`` cryptically at ``int(s * 10)``, and ``±Inf``
    silently becomes a perfect ``1.0`` / a total ``0.0``, poisoning
    ``mean_score``, ``diff_runs``' ``mean_delta`` and the CI regression gate.
    A present-but-non-numeric value (``str``/``None``/``list`` off a BYO
    ``judge_score_fn``, or ``bool``) is rejected for the same reason.

    ``drift._clamp01`` guarded exactly this and ``judge.parse_judge_output``
    hand-rolled the same ``max(0.0, min(1.0, …))`` without the finiteness half
    — so the model-output parser, the seam closest to the actual judge, was the
    one place ±Inf still clamped silently (#192). Both now call this, so the
    two cannot drift apart again.

    Matches the finiteness guards in ``runner.load_run_result_from_json``
    (#86) and ``calibration.binarize`` (#45).
    """
    if not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x):
        raise ValueError(f"judge score must be finite; got {x!r}")
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


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


#: Credential failures. 401 is a missing/invalid key, 403 a key without
#: access to the requested model — both are operator misconfiguration, not
#: a bug in this harness, so both belong on the exit-2 path.
_AUTH_STATUS_CODES = frozenset({401, 403})

#: Matched by class name for the same reason ``_TRANSIENT_EXC_NAMES`` is:
#: the classifier must stay import-free so it works (and is testable)
#: without the optional ``judge`` extra installed.
_AUTH_EXC_NAMES = frozenset({"AuthenticationError", "PermissionDeniedError"})

#: The SDK raises a bare ``TypeError`` — no status code, no dedicated class —
#: when it cannot resolve *any* credential, because that happens while
#: building request headers, before a request is ever sent. This substring is
#: the only handle on it. Kept deliberately short (the message continues with
#: a list of accepted header names) and lowercased at the comparison site.
_AUTH_TYPEERROR_MARKER = "could not resolve authentication method"


class JudgeAuthError(ValueError):
    """The judge backend could not authenticate. Operator misconfiguration.

    A ``ValueError`` subclass so it lands on the same side of the CLI's
    exit-code contract as every other bad-input failure (``JudgeParseError``
    is a ``ValueError`` for the same reason).
    """


def is_auth_error(exc: BaseException) -> bool:
    """True when ``exc`` is a credential failure, not a bug or a blip.

    Sibling of :func:`is_transient_error`, same duck-typed / import-free
    design, and deliberately consulted *after* the request has already
    failed rather than predicted before it (#194).

    A construction-time ``ANTHROPIC_API_KEY`` check was the obvious
    alternative and is wrong: ``anthropic>=0.116`` resolves credentials from
    four channels — ``ANTHROPIC_API_KEY``, ``ANTHROPIC_AUTH_TOKEN``, a named
    ``ANTHROPIC_PROFILE``, and workload-identity federation — and the
    ``judge`` extra's floor is ``>=0.32``, so this repo cannot pin that list.
    An env check would tell a profile-authenticated operator their key is
    missing and refuse to run: a false positive that breaks a *working*
    setup, which is worse than the traceback it replaces. Classifying an
    actual failure can only ever fire on a request that already failed.

    Three handles, in decreasing robustness:

    - ``status_code`` 401/403 — the invalid-key and no-model-access cases.
    - Class name — ``AuthenticationError`` / ``PermissionDeniedError``, for
      an SDK that ever stops exposing ``status_code``.
    - A ``TypeError`` naming credential resolution — the *no* credential
      case, which fails while building headers, so it has neither a status
      code nor a dedicated class. If a future SDK rewords it this stops
      matching and the failure degrades to the pre-#194 raw traceback,
      never to a false rejection of a working setup.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, bool):
        # Same `bool`-subclasses-`int` guard `is_transient_error` carries.
        status = None
    if isinstance(status, int):
        return status in _AUTH_STATUS_CODES
    if type(exc).__name__ in _AUTH_EXC_NAMES:
        return True
    # Narrow to TypeError: the marker must not reclassify, say, a ValueError
    # from our own code that happens to quote the phrase.
    return isinstance(exc, TypeError) and _AUTH_TYPEERROR_MARKER in str(exc).lower()


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
            import anthropic
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

        try:
            return retry_call(
                _once,
                max_attempts=self.max_attempts,
                base_delay=self.base_retry_delay,
                max_delay=self.max_retry_delay,
                sleep=self._sleep,
            )
        except Exception as exc:
            # A credential failure is operator misconfiguration, not a harness
            # bug — but the SDK reports "no credential resolved" as a bare
            # `TypeError` (raised while building headers, so it never gets a
            # status code). `TypeError` is not a `ValueError`, so it walked
            # straight past the CLI's exit-2 translation and out as a raw
            # traceback at exit 1 — from four frames deep, on the very first
            # row of a run, for the single most likely misconfiguration of a
            # harness whose whole test suite is designed to run *without* a key
            # (#194). Retag it so the CLI can fail cleanly. Everything else
            # propagates untouched, including a genuine `TypeError` from our own
            # code: `is_auth_error` only claims one whose message names
            # credential resolution.
            if is_auth_error(exc):
                raise JudgeAuthError(
                    "judge backend could not authenticate with the Anthropic API "
                    f"({type(exc).__name__}: {exc}). Set ANTHROPIC_API_KEY (or another "
                    "credential the SDK accepts), or use the hermetic judge stub — "
                    "`eval-harness drift --judge-stub`, or pass your own callable to "
                    "the library API — which needs no key at all."
                ) from exc
            raise


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
#
# The numeric group is `[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)` — three shapes:
# no-dot (`1`), leading-dot (`.5`), AND trailing-dot (`1.`). The pre-#132
# pattern (`[+-]?[0-9]*\.?[0-9]+`) required a digit *after* the optional dot,
# so a trailing-dot integer (`SCORE: 1.`, a natural way to write the integer
# one — `float("1.") == 1.0`) failed the whole SCORE-line match and surfaced
# as the same misleading "missing SCORE: line" error #71 set out to kill,
# aborting a whole multi-row run. `float()` then reaches the symmetric clamp
# in `parse_judge_output`. Genuinely malformed forms (bare `.`, sign-only
# `-`, `1.2.3`, sci-notation `1e0`) still fail the `\s*$`-anchored match (#132).
_SCORE_RE = re.compile(
    r"^\s*SCORE:\s*([+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+))\s*$", re.MULTILINE | re.IGNORECASE
)
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
    # Clamp out-of-range scores symmetrically: the model occasionally returns
    # just over 1.0 (e.g. 1.05) or, less often, just under 0.0 (e.g. -0.1).
    # The SCORE regex now matches a leading sign (#71) so both ends reach here.
    #
    # Via `clamp_judge_score`, not a second hand-rolled `max(0.0, min(1.0, …))`:
    # the regex's digit run is unbounded (`[0-9]+`) and `float()` does NOT raise
    # on a long one — `float("9" * 309)` is `inf`. Clamped naively that became a
    # **perfect 1.0**, so a judge stuck in a degenerate repetition loop — the
    # exact pathology this harness exists to catch — scored full marks and made
    # the CI regression gate greener (#192). Finite out-of-range values still
    # clamp exactly as before; only the non-finite case is rejected, matching
    # the contract `drift._clamp01` already stated.
    try:
        score = clamp_judge_score(float(score_match.group(1)))
    except ValueError as e:
        raise JudgeParseError(
            f"non-finite SCORE in judge output ({score_match.group(1)[:32]}…): {e}"
        ) from e
    reasoning = reason_match.group(1).strip()
    return JudgeScore(score=score, reasoning=reasoning, raw=raw)
