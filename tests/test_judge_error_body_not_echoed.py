"""A non-2xx whose body is not JSON is named, not echoed, in the operator line (#378).

For a gateway's HTML page the SDK's exception message *is* the body text, so the
`::error::` line carried every line of the page -- the echo #352 rules out for a
200 -- and a GitHub annotation, which ends at the first newline, read
`(InternalServerError: <html>` without the sentence saying whether to re-run.
A JSON error body is one line (`Error code: N - {...}`) and keeps its detail.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from eval_harness.judge import AnthropicBackend, JudgeAuthError, JudgeBackendError

_PAGE = "<html>\n<body>\n<h1>Bad Gateway</h1>\n<!-- upstream token=abc123 -->\n</body>\n</html>"


class _StatusError(Exception):
    """Shaped like `anthropic.APIStatusError` built from a non-JSON body."""

    def __init__(self, status: int, body: object, message: str) -> None:
        super().__init__(message)
        self.status_code = status
        self.body = body
        self.response = SimpleNamespace(headers={})


class _Raising:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def create(self, **_kw: object) -> object:
        raise self.exc


def _backend(messages: object) -> AnthropicBackend:
    b = AnthropicBackend.__new__(AnthropicBackend)
    b.client = SimpleNamespace(messages=messages)  # type: ignore[attr-defined]
    b.model = "m"
    b.max_tokens = 16
    b.max_attempts = 2
    b.base_retry_delay = 0.0
    b.max_retry_delay = 0.0
    b._sleep = lambda _s: None
    return b


@pytest.mark.parametrize(
    ("status", "exc_type", "sentence"),
    [
        (502, JudgeBackendError, "re-running may succeed"),
        (404, JudgeBackendError, "Check --model"),
        (401, JudgeAuthError, "Set ANTHROPIC_API_KEY"),
    ],
)
def test_a_non_json_error_body_is_named_not_echoed(
    status: int, exc_type: type[Exception], sentence: str
) -> None:
    with pytest.raises(exc_type) as info:
        _backend(_Raising(_StatusError(status, _PAGE, _PAGE))).complete("s", "u")
    message = str(info.value)
    assert "abc123" not in message
    assert "<html>" not in message
    assert "\n" not in message  # one workflow-command line
    assert f"HTTP {status} with a non-JSON body of {len(_PAGE)} characters" in message
    assert sentence in message


def test_an_empty_error_body_is_named() -> None:
    with pytest.raises(JudgeBackendError) as info:
        _backend(_Raising(_StatusError(503, "", "Error code: 503"))).complete("s", "u")
    assert "HTTP 503 with an empty body" in str(info.value)


def test_a_json_error_body_keeps_the_sdk_detail() -> None:
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad max"}}
    message = f"Error code: 400 - {body}"
    with pytest.raises(JudgeBackendError) as info:
        _backend(_Raising(_StatusError(400, body, message))).complete("s", "u")
    assert message in str(info.value)


# --- the real SDK over a mock transport -----------------------------------------


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [(502, JudgeBackendError), (404, JudgeBackendError), (401, JudgeAuthError)],
)
def test_the_real_sdk_html_error_is_named_not_echoed(
    status: int, exc_type: type[Exception]
) -> None:
    anthropic = pytest.importorskip("anthropic")
    try:
        import httpx2 as httpx  # anthropic >= 1.0
    except ImportError:  # anthropic 0.x
        import httpx  # type: ignore[no-redef]

    response = httpx.Response(status, headers={"content-type": "text/html"}, text=_PAGE)
    b = _backend(None)
    b.client = anthropic.Anthropic(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(lambda _req: response)),
    )
    with pytest.raises(exc_type) as info:
        b.complete("sys", "user")
    message = str(info.value)
    assert "abc123" not in message
    assert "\n" not in message
    assert f"HTTP {status} with a non-JSON body" in message
