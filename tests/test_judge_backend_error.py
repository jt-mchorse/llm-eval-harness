"""`is_backend_failure` — the provenance classifier behind #220 / D-020.

`is_transient_error` and `is_auth_error` both ask *what sort of failure is
this?*. This third sibling asks a different kind of question — **where did it
come from?** — and the whole value of the answer is what it must **not** claim.
The seam it feeds retags a claimed exception into `JudgeBackendError` and the
CLI turns that into a clean exit-2 line with no traceback, so a false positive
does not merely mislabel: it *deletes* the stack trace of a real bug in
somebody's own `Backend` and reports it as a usage error. That is strictly
worse than the raw traceback #220 replaced.

So this file is mostly negatives, and the positives are pinned as a
relationship to the two existing classifiers rather than as a hand-copied list.

Everything here is import-free of the optional `judge` extra, matching the
design constraint the two existing classifiers carry.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from eval_harness.judge import (
    _AUTH_EXC_NAMES,
    _AUTH_STATUS_CODES,
    _AUTH_TYPEERROR_MARKER,
    _REMOTE_EXC_NAMES,
    _TRANSIENT_EXC_NAMES,
    _TRANSIENT_STATUS_CODES,
    AnthropicBackend,
    JudgeAuthError,
    JudgeBackendError,
    is_auth_error,
    is_backend_failure,
    is_transient_error,
)


class _StatusError(Exception):
    """Carries an int `status_code`, like every `anthropic.APIStatusError`."""

    def __init__(self, status_code: object) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def _named(name: str) -> BaseException:
    """An exception whose *class name* is `name` and which carries no status.

    The class-name road is the only handle on a connection-level failure, so
    the fixture has to be able to forge a name without importing the SDK.
    """
    cls = type(name, (Exception,), {})
    return cls("boom")


# --------------------------------------------------------------------------
# What it must not claim. These are the rows that cost a traceback.
# --------------------------------------------------------------------------

#: Exceptions a caller's own `Backend` plausibly raises. None carries a status
#: code or an SDK class name, so none may be claimed.
_BYO_BACKEND_BUGS: list[BaseException] = [
    ValueError("backend bug"),
    TypeError("backend bug"),
    RuntimeError("backend bug"),
    KeyError("backend bug"),
    AttributeError("'NoneType' object has no attribute 'text'"),
    IndexError("list index out of range"),
    AssertionError("invariant violated"),
    NotImplementedError("stub backend"),
    ZeroDivisionError("division by zero"),
    OSError("connection reset by peer"),
]


@pytest.mark.parametrize("exc", _BYO_BACKEND_BUGS, ids=lambda e: type(e).__name__)
def test_a_caller_backend_bug_is_never_claimed(exc: BaseException) -> None:
    assert is_backend_failure(exc) is False


def test_the_byo_population_is_not_empty() -> None:
    """Anti-vacuous: a parametrize over an empty list passes on nothing."""
    assert len(_BYO_BACKEND_BUGS) >= 10
    assert len({type(e).__name__ for e in _BYO_BACKEND_BUGS}) == len(_BYO_BACKEND_BUGS)


def test_an_oserror_is_not_claimed_despite_sounding_like_a_network_failure() -> None:
    """`OSError("connection reset")` is the tempting false positive.

    It reads like a transport failure, and a classifier written from the
    English rather than from the handles would claim it. But the SDK wraps
    transport failures in `APIConnectionError`; a bare `OSError` reaching this
    seam came from a caller's own `Backend` doing its own I/O, and its
    traceback is the only thing that will tell them where. Neither existing
    sibling claims it either.
    """
    exc = OSError("connection reset by peer")
    assert is_backend_failure(exc) is False
    assert is_transient_error(exc) is False
    assert is_auth_error(exc) is False


def test_a_bool_status_code_is_not_a_status_code() -> None:
    """`bool` subclasses `int`; both siblings carry this guard, so does this one."""
    for value in (True, False):
        exc = _StatusError(value)
        assert is_backend_failure(exc) is False, value


@pytest.mark.parametrize("value", ["429", 429.0, None, object(), b"429", [429]])
def test_a_non_int_status_code_falls_through_to_the_name_road(value: object) -> None:
    """A `status_code` that is not an int is not evidence of a wire failure.

    It is evidence the object is not an `APIStatusError` at all, so the class
    name is the only remaining handle — and these fixtures do not have an SDK
    name either.
    """
    assert is_backend_failure(_StatusError(value)) is False


def test_the_credential_resolution_typeerror_is_deliberately_not_claimed() -> None:
    """The one handle of `is_auth_error` this classifier must answer False on.

    That `TypeError` is raised while building request headers — *before any
    request is sent* — so by this function's own question ("did it come from
    the remote?") it did not. Claiming it would be a category error even
    though both paths happen to exit 2, because the two carry different
    messages and only one of them tells the operator to set a credential.
    """
    exc = TypeError(f"{_AUTH_TYPEERROR_MARKER}: expected one of ...")
    assert is_auth_error(exc) is True
    assert is_backend_failure(exc) is False


# --------------------------------------------------------------------------
# What it must claim, stated as a relationship rather than a copied list
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(_TRANSIENT_STATUS_CODES))
def test_every_transient_status_is_a_remote_failure(status: int) -> None:
    """Derived from the transient set, so adding a code there covers it here."""
    assert is_backend_failure(_StatusError(status)) is True


@pytest.mark.parametrize("status", sorted(_AUTH_STATUS_CODES))
def test_every_auth_status_is_also_a_remote_failure(status: int) -> None:
    """The deliberate overlap. 401/403 *did* come back over the wire.

    The seam consults `is_auth_error` first, so the overlap changes no
    behaviour — it is asserted because the docstring claims it, and a claim in
    a docstring that nothing runs is prose.
    """
    assert is_backend_failure(_StatusError(status)) is True
    assert is_auth_error(_StatusError(status)) is True


@pytest.mark.parametrize("status", [400, 404, 405, 410, 413, 422, 451, 501, 505])
def test_a_status_the_repo_has_never_enumerated_is_still_a_remote_failure(
    status: int,
) -> None:
    """This classifier tests `isinstance(status, int)`, not set membership.

    That is the one place it deliberately diverges from both siblings, and the
    reason is the question it asks: *any* HTTP status is evidence a response
    came back. A 422 the SDK starts returning next year needs no edit here —
    whereas a membership test would silently answer False and hand the
    operator a traceback at exit 1 again, which is the exact defect #220 fixed.
    """
    # The row is only meaningful if the status is outside *both* enumerated
    # sets — otherwise a membership test would pass it too and this proves
    # nothing about the divergence the docstring claims.
    assert status not in _TRANSIENT_STATUS_CODES
    assert status not in _AUTH_STATUS_CODES
    assert is_backend_failure(_StatusError(status)) is True


@pytest.mark.parametrize("name", sorted(_REMOTE_EXC_NAMES))
def test_every_name_in_the_remote_set_is_claimed_without_a_status(name: str) -> None:
    assert is_backend_failure(_named(name)) is True


def test_the_remote_name_set_is_derived_from_its_two_sources() -> None:
    """`_REMOTE_EXC_NAMES` is a union, not a hand-copied list.

    Hand-copying would fail *quietly*: a name added to `_TRANSIENT_EXC_NAMES`
    and not mirrored here makes `is_backend_failure` answer False for a real
    connection failure, and False on this path means "not ours" — the
    traceback comes back. Deriving it makes that impossible; this pins the
    derivation so a later edit cannot flatten it into a literal.
    """
    assert _REMOTE_EXC_NAMES == _TRANSIENT_EXC_NAMES | _AUTH_EXC_NAMES
    # Anti-vacuous: an empty union would satisfy the equality above.
    assert _TRANSIENT_EXC_NAMES
    assert _AUTH_EXC_NAMES
    assert len(_REMOTE_EXC_NAMES) >= len(_TRANSIENT_EXC_NAMES)


def test_it_is_a_superset_of_the_auth_classifiers_wire_handles() -> None:
    """Two of `is_auth_error`'s three handles, and not the third.

    Stated as a partition over that function's own handles rather than as
    three separate examples, so a fourth handle added to `is_auth_error`
    without a thought here shows up as a failure rather than as a gap.
    """
    wire_handles: list[BaseException] = [
        *(_StatusError(code) for code in sorted(_AUTH_STATUS_CODES)),
        *(_named(name) for name in sorted(_AUTH_EXC_NAMES)),
    ]
    for exc in wire_handles:
        assert is_auth_error(exc) is True, exc
        assert is_backend_failure(exc) is True, exc

    pre_request = TypeError(_AUTH_TYPEERROR_MARKER)
    assert is_auth_error(pre_request) is True
    assert is_backend_failure(pre_request) is False


# --------------------------------------------------------------------------
# The seam, driven through a real `AnthropicBackend`
# --------------------------------------------------------------------------
#
# `is_backend_failure` returning False is only half the guarantee; the other
# half is that `complete` acts on it. The blanket-claim variant of this fix —
# `if True:` in place of the classifier call, which is what "`except
# Exception` at the seam" reduces to once you are already inside `complete` —
# passes every classifier assertion above, because it never calls the
# classifier. These rows are what separate the two.


class _RaisingMessages:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.calls = 0

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise self._exc


class _Client:
    def __init__(self, messages: object) -> None:
        self.messages = messages


def _backend(messages: object, *, max_attempts: int = 2) -> AnthropicBackend:
    """A real `AnthropicBackend` with a fake client; no `anthropic`, no key."""
    backend = AnthropicBackend.__new__(AnthropicBackend)
    backend.client = _Client(messages)
    backend.model = "claude-haiku-4-5-20251001"
    backend.max_tokens = 512
    backend.max_attempts = max_attempts
    backend.base_retry_delay = 0.0
    backend.max_retry_delay = 0.0
    backend._sleep = lambda _seconds: None
    return backend


#: Exceptions that can come out of `client.messages.create` without having come
#: from the remote: an SDK-version mismatch in the kwargs we pass, a bug in our
#: own construction, a client object that is not what we think it is. Every one
#: of these must keep its traceback, because the only person who can fix them
#: is us and the stack is where the answer is.
_OUR_OWN_BUGS: list[BaseException] = [
    TypeError("create() got an unexpected keyword argument 'max_tokens'"),
    AttributeError("'NoneType' object has no attribute 'messages'"),
    ValueError("model must be a non-empty string"),
    RuntimeError("event loop is closed"),
    KeyError("messages"),
]


@pytest.mark.parametrize("exc", _OUR_OWN_BUGS, ids=lambda e: type(e).__name__)
def test_a_bug_on_the_call_path_is_not_retagged_as_a_remote_failure(
    exc: BaseException,
) -> None:
    messages = _RaisingMessages(exc)
    with pytest.raises(type(exc)) as excinfo:
        _backend(messages).complete("sys", "user")
    assert excinfo.value is exc
    assert not isinstance(excinfo.value, JudgeBackendError)
    # Not retried either: none of these is transient, so the budget is not
    # burned on a bug that will reproduce identically.
    assert messages.calls == 1


def test_a_broken_content_block_loop_keeps_its_traceback() -> None:
    """The call *succeeded*; our own response handling is what broke.

    This is the row furthest from "the remote failed" that still runs inside
    `complete`'s `try`, so it is the sharpest test of the classifier actually
    being consulted.
    """

    class _BadContent:
        calls = 0

        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            type(self).calls += 1
            return SimpleNamespace(content=object())  # not iterable

    with pytest.raises(TypeError) as excinfo:
        _backend(_BadContent()).complete("sys", "user")
    assert not isinstance(excinfo.value, JudgeBackendError)


def test_a_remote_failure_on_the_same_path_is_retagged() -> None:
    """The mirror of the two tests above — without it they pass vacuously.

    A classifier that answers False for everything satisfies every negative in
    this file. This is the row that kills it.
    """
    exc = _StatusError(400)
    with pytest.raises(JudgeBackendError) as excinfo:
        _backend(_RaisingMessages(exc)).complete("sys", "user")
    assert excinfo.value.__cause__ is exc


def test_the_retry_budget_appears_in_the_exhausted_message_as_measured() -> None:
    """`after N attempts` is the backend's own budget, not a constant.

    An operator reading "after 2 attempts" is being told the number they would
    raise. A hard-coded 4 would be a fabricated measurement of a budget the
    run did not have.
    """
    for budget in (1, 2, 5):
        messages = _RaisingMessages(_StatusError(429))
        with pytest.raises(JudgeBackendError) as excinfo:
            _backend(messages, max_attempts=budget).complete("sys", "user")
        assert messages.calls == budget
        assert f"after {budget} attempt" in str(excinfo.value)
    # Singular/plural, because a message that reads "after 1 attempts" is the
    # kind of thing nobody notices until it is in a screenshot.
    messages = _RaisingMessages(_StatusError(429))
    with pytest.raises(JudgeBackendError) as excinfo:
        _backend(messages, max_attempts=1).complete("sys", "user")
    assert "after 1 attempt (" in str(excinfo.value)


# --------------------------------------------------------------------------
# The exception class itself
# --------------------------------------------------------------------------


def test_judge_backend_error_is_a_value_error_but_that_routes_nothing() -> None:
    """Same shape and same caveat as `JudgeAuthError`.

    The subclassing exists so a *library* caller can handle the bad-input
    family with one arm. It routes nothing in the CLI: neither judge seam
    catches the broad `ValueError`, which is exactly why `JudgeParseError`
    exited 1 with a traceback for as long as it did (#218). The explicit
    `except JudgeBackendError` arms are what make the contract real, and they
    are pinned in `tests/test_cli_judge_seam_exit_codes.py`.
    """
    assert issubclass(JudgeBackendError, ValueError)
    # Distinct from its sibling in both directions: an operator told to set
    # `ANTHROPIC_API_KEY` because the remote is down is worse off than one
    # told nothing.
    assert not issubclass(JudgeBackendError, JudgeAuthError)
    assert not issubclass(JudgeAuthError, JudgeBackendError)


def test_it_is_exported_on_the_public_surface() -> None:
    """A caller cannot write the `except` arm for a name they cannot import."""
    import eval_harness

    assert "JudgeBackendError" in eval_harness.__all__
    assert eval_harness.JudgeBackendError is JudgeBackendError
