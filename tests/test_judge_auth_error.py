"""A credential failure exits 2, not a raw SDK traceback (#194).

`anthropic.Anthropic()` resolves credentials **lazily**: construction
succeeds with `api_key=None`, and the failure surfaces at the first
`messages.create` as a bare `TypeError` raised while building request
headers. `TypeError` is not a `ValueError`, so it walked straight past
every translation in `cli._run_run` / `cli._run_calibrate` and out as a
raw traceback at exit 1 — four frames deep, on the first row of a run,
for the single most likely misconfiguration of a harness whose entire
test suite is built to run *without* a key.

Coverage matrix:

- `is_auth_error` classification: 401/403, the two SDK class names, the
  credential-resolution `TypeError`, and — the half that matters — every
  neighbour it must **not** claim (400/404/429/500, a connection error,
  a genuine `TypeError` from our own code, a `ValueError` quoting the
  marker phrase, a `bool` masquerading as a status code).
- `AnthropicBackend.complete()` retagging, and the no-retry property.
- Both CLI seams (`run`, `calibrate`) end-to-end at exit 2 with no
  traceback.
- One test pinning the message marker against the **real** SDK, skipped
  when `anthropic` isn't importable (CI installs `.[dev]`, not `[judge]`).

Everything except the last test is hermetic and import-free, matching
`is_transient_error`'s design.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from eval_harness import judge as judge_module
from eval_harness.judge import (
    AnthropicBackend,
    JudgeAuthError,
    is_auth_error,
    is_transient_error,
)


class _FakeStatusError(Exception):
    """Stand-in for `anthropic.APIStatusError`: carries an int `status_code`."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class AuthenticationError(Exception):
    """Name-matched by the classifier; no `status_code` attribute on purpose."""


class PermissionDeniedError(Exception):
    """Name-matched by the classifier; no `status_code` attribute on purpose."""


class APIConnectionError(Exception):
    """A transient neighbour that must not be claimed as an auth failure."""


_SDK_NO_CREDENTIAL_MESSAGE = (
    '"Could not resolve authentication method. Expected one of api_key, '
    "auth_token, or credentials to be set. Or for one of the `X-Api-Key` or "
    '`Authorization` headers to be explicitly omitted"'
)


# --- classification: what IS an auth failure -------------------------------


@pytest.mark.parametrize("code", [401, 403])
def test_auth_status_codes_are_auth_errors(code: int) -> None:
    assert is_auth_error(_FakeStatusError(code)) is True


@pytest.mark.parametrize("exc", [AuthenticationError("nope"), PermissionDeniedError("nope")])
def test_sdk_auth_class_names_are_auth_errors(exc: Exception) -> None:
    """Name-matched so the classifier needs no `anthropic` import — the
    same reason `is_transient_error` matches `APIConnectionError` by name."""
    assert is_auth_error(exc) is True


def test_credential_resolution_typeerror_is_an_auth_error() -> None:
    """The *no* credential case has neither a status code nor a dedicated
    class — it is raised while building headers — so the message is the
    only handle on it."""
    assert is_auth_error(TypeError(_SDK_NO_CREDENTIAL_MESSAGE)) is True


# --- classification: what is NOT (the half that matters) -------------------


@pytest.mark.parametrize("code", [400, 404, 422, 429, 500, 503])
def test_non_auth_status_codes_are_not_auth_errors(code: int) -> None:
    """A bad request or a server blip is not a credential problem. 429/500
    in particular are *transient* and must keep their retry behaviour."""
    assert is_auth_error(_FakeStatusError(code)) is False


def test_connection_error_is_transient_not_auth() -> None:
    exc = APIConnectionError("dns")
    assert is_transient_error(exc) is True
    assert is_auth_error(exc) is False


def test_a_genuine_typeerror_from_our_own_code_is_not_reclassified() -> None:
    """The whole risk of a message sniff is over-claiming. A real
    `TypeError` — the kind that signals a bug in this harness — must
    propagate as itself so it isn't silently reported as the operator's
    misconfiguration."""
    assert is_auth_error(TypeError("unsupported operand type(s) for +: 'int' and 'str'")) is False


def test_marker_phrase_in_a_non_typeerror_is_not_an_auth_error() -> None:
    """The sniff is narrowed to `TypeError`, so our own error messages can
    quote the SDK's phrase (this module's docstring does) without any
    exception carrying it being reclassified."""
    assert is_auth_error(ValueError(_SDK_NO_CREDENTIAL_MESSAGE)) is False


def test_bool_status_code_does_not_land_in_the_int_branch() -> None:
    """`bool` subclasses `int`, so `True` would compare into the status
    branch. Same guard `is_transient_error` carries."""

    class _Weird(Exception):
        status_code = True

    assert is_auth_error(_Weird()) is False


# --- complete() retags, and does not retry ---------------------------------


class _RaisingMessages:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.calls = 0

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise self._exc


class _Client:
    def __init__(self, messages: _RaisingMessages) -> None:
        self.messages = messages


def _backend(messages: _RaisingMessages, sleeps: list[float]) -> AnthropicBackend:
    """Bypass `__init__` so no `anthropic` install / API key is needed."""
    be = AnthropicBackend.__new__(AnthropicBackend)
    be.client = _Client(messages)
    be.model = "claude-haiku-4-5-20251001"
    be.max_tokens = 512
    be.max_attempts = 4
    be.base_retry_delay = 0.5
    be.max_retry_delay = 8.0
    be._sleep = sleeps.append
    return be


@pytest.mark.parametrize(
    "exc",
    [
        TypeError(_SDK_NO_CREDENTIAL_MESSAGE),
        _FakeStatusError(401),
        _FakeStatusError(403),
        AuthenticationError("bad key"),
    ],
)
def test_complete_retags_auth_failures_and_does_not_retry(exc: BaseException) -> None:
    sleeps: list[float] = []
    msgs = _RaisingMessages(exc)
    with pytest.raises(JudgeAuthError) as excinfo:
        _backend(msgs, sleeps).complete("sys", "user")
    assert msgs.calls == 1, "a credential failure must not burn the retry budget"
    assert sleeps == []
    assert excinfo.value.__cause__ is exc, "original exception preserved as __cause__"
    assert "ANTHROPIC_API_KEY" in str(excinfo.value)
    assert "--judge-stub" in str(excinfo.value)


def test_judge_auth_error_is_a_valueerror() -> None:
    """So it lands on the same side of the CLI's exit-code contract as every
    other bad-input failure — `JudgeParseError` subclasses `ValueError` for
    exactly this reason."""
    assert issubclass(JudgeAuthError, ValueError)


def test_complete_leaves_a_non_auth_failure_untouched() -> None:
    """A 500 is transient: it must still exhaust the retry budget and
    re-raise as itself, not be swallowed by the new arm."""
    sleeps: list[float] = []
    exc = _FakeStatusError(500)
    msgs = _RaisingMessages(exc)
    with pytest.raises(_FakeStatusError):
        _backend(msgs, sleeps).complete("sys", "user")
    assert msgs.calls == 4
    assert sleeps == [0.5, 1.0, 2.0]


# --- CLI: both seams exit 2 with no traceback ------------------------------


class _NoCredentialBackend:
    """Stands in for `AnthropicBackend` at the CLI seam. Raises at the same
    place the real one does — the first judge call, not construction —
    because construction succeeding is precisely what let this escape."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.model = "claude-haiku-4-5-20251001"

    def complete(self, system: str, user: str) -> str:
        raise JudgeAuthError(
            "judge backend could not authenticate with the Anthropic API "
            "(TypeError: could not resolve authentication method). Set "
            "ANTHROPIC_API_KEY ..., or use the hermetic judge stub — "
            "`eval-harness drift --judge-stub` ..."
        )


def test_cli_run_exits_two_on_a_credential_failure(tmp_path, monkeypatch) -> None:
    from eval_harness import cli

    monkeypatch.setattr(cli, "AnthropicBackend", _NoCredentialBackend)
    rc = cli.main(
        [
            "run",
            "--suite",
            "faithfulness",
            "--dataset",
            "fixtures/sample_factuality_v1.jsonl",
            "--db",
            str(tmp_path / "runs.db"),
            "--no-diff",
        ]
    )
    assert rc == 2


def test_cli_calibrate_exits_two_on_a_credential_failure(tmp_path, monkeypatch) -> None:
    from eval_harness import cli

    monkeypatch.setattr(cli, "AnthropicBackend", _NoCredentialBackend)
    rc = cli.main(
        [
            "calibrate",
            "--calibration",
            "fixtures/calibration.jsonl",
            "--report",
            str(tmp_path / "report.md"),
        ]
    )
    assert rc == 2


def test_cli_run_without_a_key_prints_error_line_not_a_traceback(tmp_path) -> None:
    """End-to-end in a subprocess with every credential env var cleared —
    the closest thing to the fresh-clone experience that produced #194.
    Skipped when `anthropic` isn't installed, since without it the backend
    raises ImportError first (a different, already-handled failure)."""
    pytest.importorskip("anthropic")
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("ANTHROPIC_")}
    env["PATH"] = __import__("os").environ.get("PATH", "")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "run",
            "--suite",
            "faithfulness",
            "--dataset",
            "fixtures/sample_factuality_v1.jsonl",
            "--db",
            str(tmp_path / "runs.db"),
            "--no-diff",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert "Traceback" not in result.stderr, result.stderr
    assert "::error::" in result.stderr
    assert "ANTHROPIC_API_KEY" in result.stderr


def test_marker_still_matches_the_installed_sdk(monkeypatch) -> None:
    """Pins the message sniff against the **real** SDK. If a future release
    rewords it this test fails loudly here rather than silently regressing
    `eval-harness run` to a raw traceback in the field.

    Skipped without the optional `judge` extra — CI installs `.[dev]`.

    Every `ANTHROPIC_*` var is cleared first, and that is load-bearing, not
    hygiene: `Anthropic(api_key=None)` still consults the environment, so on
    a developer machine with a key exported this test made a **real network
    call** and failed with a live 401. With them cleared, credential
    resolution fails while building headers — before any I/O — which is the
    exact seam under test.
    """
    anthropic = pytest.importorskip("anthropic")
    for name in [k for k in __import__("os").environ if k.startswith("ANTHROPIC_")]:
        monkeypatch.delenv(name, raising=False)
    client = anthropic.Anthropic()
    with pytest.raises(TypeError) as excinfo:
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8,
            messages=[{"role": "user", "content": "hi"}],
        )
    assert is_auth_error(excinfo.value) is True, (
        "the SDK's credential-resolution message no longer matches "
        f"{judge_module._AUTH_TYPEERROR_MARKER!r}: {excinfo.value}"
    )
