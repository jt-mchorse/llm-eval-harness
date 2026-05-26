"""Construction-time validation for `AnthropicBackend.max_tokens`.

The validator is hoisted ABOVE the lazy `import anthropic` block in
`AnthropicBackend.__init__`, so these tests run in CI without the optional
`judge` extra installed. Bad `max_tokens` raises `ValueError` before the
import is attempted; if the import were attempted first, callers without
the extra would see `ImportError` masking the real problem.

The shape mirrors `runs.list_runs.limit` from #42 and the portfolio-wide
positive-int contract sweep (`rag-production-kit#41`,
`embedding-model-shootout#34`, `llm-cost-optimizer#39`).
"""

from __future__ import annotations

import math

import pytest

from eval_harness.judge import AnthropicBackend

# ----------------------------------------------------------------------
# Reject path. Each value should raise `ValueError` with the canonical
# message shape, and should do so BEFORE the lazy anthropic import — so
# this test file is meaningful without the `judge` extra installed.
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_max_tokens",
    [
        True,  # bool: subclass of int; would silently bind max_tokens=1.
        False,  # bool: would silently bind max_tokens=0.
        0,  # zero: API rejects with opaque 400.
        -1,  # negative: API rejects.
        -512,  # negative larger magnitude.
        0.5,  # float: API rejects or coerces; non-int contract.
        1.0,  # whole float: still not int.
        512.0,  # whole float at the default value.
        math.nan,  # NaN: NaN <= 0 is False, would slip a sign-only check.
        math.inf,  # +inf: would slip sign-only and hit the API.
        -math.inf,  # -inf: matches the negative path but via float.
        None,  # explicitly typed `int`, None not allowed.
        "512",  # string of digits — not int.
        [],  # arbitrary non-int.
        (1,),
        {"value": 1},
    ],
)
def test_anthropic_backend_rejects_non_positive_int_max_tokens(bad_max_tokens):
    with pytest.raises(ValueError, match="max_tokens must be a positive integer"):
        AnthropicBackend(max_tokens=bad_max_tokens)


def test_anthropic_backend_error_message_includes_repr_of_bad_value():
    with pytest.raises(ValueError, match="0.5") as exc_info:
        AnthropicBackend(max_tokens=0.5)
    assert "max_tokens must be a positive integer" in str(exc_info.value)

    with pytest.raises(ValueError, match="True") as exc_info:
        AnthropicBackend(max_tokens=True)
    assert "max_tokens must be a positive integer" in str(exc_info.value)


# ----------------------------------------------------------------------
# Boundary acceptance: the smallest valid value is 1. The default 512 and
# arbitrarily large positive ints both pass validation. (They may still
# raise ImportError on the lazy `import anthropic` if the `judge` extra
# is not installed — that's the correct downstream behavior; the test
# documents only that validation has passed.)
# ----------------------------------------------------------------------


@pytest.mark.parametrize("good_max_tokens", [1, 2, 256, 512, 100_000])
def test_anthropic_backend_accepts_positive_int_max_tokens(good_max_tokens):
    # ValueError is the failure surface for validation; if validation passes
    # we expect either successful construction (extra installed) or
    # ImportError from the lazy import (extra not installed). Both prove
    # the validator did not raise.
    try:
        AnthropicBackend(max_tokens=good_max_tokens)
    except ValueError:
        pytest.fail(f"validator unexpectedly rejected {good_max_tokens!r}")
    except ImportError:
        # `judge` extra not installed in CI; validator passed. OK.
        pass


def test_validator_runs_before_lazy_anthropic_import():
    """Without the `judge` extra installed, a bad `max_tokens` must still
    surface as `ValueError` — not `ImportError`. The validator is hoisted
    above the lazy import for exactly this reason.
    """
    # If the validator ran AFTER the lazy import, a CI without `anthropic`
    # would see `ImportError` before ever evaluating max_tokens. Pin the
    # ordering by asserting ValueError on a definitely-bad value.
    with pytest.raises(ValueError, match="max_tokens must be a positive integer"):
        AnthropicBackend(max_tokens=0)
