"""A 200 whose body is not a Message is a backend failure, exit 2 (#352).

The SDK returns the raw text as a `str` when a response is not JSON (a gateway
page), raises `JSONDecodeError` on malformed JSON, and builds a Message with
`content=None` from JSON without it (`{}`, an error envelope sent with 200), and
hands back any non-object JSON (`[]`, `null`, `123`, `true`) unchanged (#376).
Each escaped `complete` as AttributeError / JSONDecodeError / TypeError, and
`run` exited 1, its "a row regressed" code. #303 fixed the same class in the
`comment` command. A real Message our own loop cannot read keeps its traceback
(`test_a_broken_content_block_loop_keeps_its_traceback`).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from eval_harness.judge import AnthropicBackend, JudgeBackendError

_SECRET_PAGE = "<html>gateway login: token=abc123</html>"


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


class _Returning:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def create(self, **_kw: object) -> object:
        self.calls += 1
        return self.value


@pytest.mark.parametrize(
    "value",
    [_SECRET_PAGE, SimpleNamespace(content=None)],
    ids=["str-body", "content-none"],
)
def test_a_non_message_200_is_a_backend_error_and_not_retried(value: object) -> None:
    messages = _Returning(value)
    with pytest.raises(JudgeBackendError) as info:
        _backend(messages).complete("sys", "user")
    assert "not a Message" in str(info.value)
    assert "abc123" not in str(info.value)  # the body is never echoed
    assert messages.calls == 1


@pytest.mark.parametrize(
    "value",
    [[], None, 123, 1.5, True, False, [{"type": "text", "text": "SCORE: 1"}]],
    ids=["empty-array", "null", "int", "float", "true", "false", "array-of-blocks"],
)
def test_a_non_object_json_200_is_a_backend_error_and_not_retried(value: object) -> None:
    """The SDK builds a Message only from a JSON object; any other value comes back as-is (#376)."""
    messages = _Returning(value)
    with pytest.raises(JudgeBackendError) as info:
        _backend(messages).complete("sys", "user")
    assert "not a Message" in str(info.value)
    assert "SCORE" not in str(info.value)  # the body is never echoed
    assert messages.calls == 1


def test_a_real_message_is_still_read() -> None:
    block = SimpleNamespace(text="SCORE: 0.9")
    assert _backend(_Returning(SimpleNamespace(content=[block]))).complete("s", "u") == "SCORE: 0.9"


# --- the real SDK over a mock transport -----------------------------------------

_SHAPES = {
    "html": (200, {"content-type": "text/html"}, _SECRET_PAGE, None),
    "bad-json": (200, {"content-type": "application/json"}, "{not json", None),
    "empty-object": (200, None, None, {}),
    "content-null": (
        200,
        None,
        None,
        {
            "id": "m",
            "type": "message",
            "role": "assistant",
            "model": "x",
            "content": None,
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    ),
    "error-envelope": (
        200,
        None,
        None,
        {"type": "error", "error": {"type": "overloaded_error", "message": "x"}},
    ),
    # JSON that is not an object: the SDK returns the parsed value unchanged (#376).
    "json-array": (200, {"content-type": "application/json"}, "[]", None),
    "json-null": (200, {"content-type": "application/json"}, "null", None),
    "json-number": (200, {"content-type": "application/json"}, "123", None),
    "json-true": (200, {"content-type": "application/json"}, "true", None),
}


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_the_real_sdk_shapes_are_backend_errors(shape: str) -> None:
    anthropic = pytest.importorskip("anthropic")
    try:
        import httpx2 as httpx  # anthropic >= 1.0
    except ImportError:  # anthropic 0.x
        import httpx  # type: ignore[no-redef]

    status, headers, text, body = _SHAPES[shape]
    response = (
        httpx.Response(status, json=body)
        if body is not None
        else httpx.Response(status, headers=headers, text=text)
    )
    b = _backend(None)
    b.client = anthropic.Anthropic(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(lambda _req: response)),
    )
    with pytest.raises(JudgeBackendError) as info:
        b.complete("sys", "user")
    assert "not a Message" in str(info.value)
    assert "abc123" not in str(info.value)
