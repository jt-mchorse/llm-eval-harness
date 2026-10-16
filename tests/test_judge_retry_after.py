"""The judge waits the delay a failed response asks for (#372).

#299 built the client with `max_retries=0`, so the SDK no longer honoured
`retry-after` and `retry_call` waited its own 0.5 s / 1 s / 2 s whatever the
server said. Measured on main through the real SDK against a loopback stub
answering `429` + `retry-after: 5` for 5 s:

    harness (max_attempts=4)    4 requests in 3.53 s, exit 2 "unreachable"
    anthropic.Anthropic()       2 requests, second at 5.05 s, scored

The rule is the `anthropic>=0.32` floor's: `retry-after-ms`, else
`retry-after` as seconds, else as an HTTP-date, honoured when `0 < wait <= 60`.
"""

from __future__ import annotations

import email.utils
import json
import os
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from eval_harness.judge import AnthropicBackend, retry_after_seconds, retry_call

_NOW = 1_800_000_000.0


def _failed(headers: dict[str, str] | None) -> Exception:
    exc = Exception("status 429")
    exc.status_code = 429  # type: ignore[attr-defined]
    if headers is not None:
        exc.response = types.SimpleNamespace(headers=headers)  # type: ignore[attr-defined]
    return exc


def _date(offset: float) -> str:
    return email.utils.formatdate(_NOW + offset, usegmt=True)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"retry-after": "5"}, 5.0),
        ({"retry-after": "2.5"}, 2.5),
        ({"retry-after": "60"}, 60.0),
        ({"retry-after-ms": "1500"}, 1.5),
        # A parseable `retry-after-ms` is the answer; `retry-after` is not read.
        ({"retry-after-ms": "250", "retry-after": "30"}, 0.25),
        # An unparseable `retry-after-ms` falls through to `retry-after`.
        ({"retry-after-ms": "soon", "retry-after": "7"}, 7.0),
        ({"retry-after": _date(10)}, 10.0),
    ],
)
def test_a_usable_header_is_the_wait(headers: dict[str, str], expected: float) -> None:
    assert retry_after_seconds(_failed(headers), now=lambda: _NOW) == pytest.approx(expected)


@pytest.mark.parametrize(
    "headers",
    [
        None,
        {},
        {"retry-after": "0"},
        {"retry-after": "-3"},
        {"retry-after": "61"},
        {"retry-after": "nan"},
        {"retry-after": "inf"},
        {"retry-after": "soon"},
        {"retry-after": ""},
        {"retry-after": _date(-10)},
        {"retry-after": _date(3600)},
        # Out of range in ms is still the answer (SDK order), so no fallback.
        {"retry-after-ms": "0", "retry-after": "5"},
        {"retry-after-ms": "120000"},
    ],
)
def test_an_unusable_header_leaves_the_backoff(headers: dict[str, str] | None) -> None:
    assert retry_after_seconds(_failed(headers), now=lambda: _NOW) is None


def test_retry_call_sleeps_the_requested_wait_then_the_backoff() -> None:
    errors = [_failed({"retry-after": "5"}), _failed({}), _failed({"retry-after": "1.25"})]
    sleeps: list[float] = []

    def fn() -> str:
        if errors:
            raise errors.pop(0)
        return "ok"

    out = retry_call(fn, max_attempts=4, base_delay=0.5, max_delay=8.0, sleep=sleeps.append)
    assert out == "ok"
    # Retry 0 waits the server's 5 s, retry 1 its own 1 s, retry 2 the 1.25 s.
    assert sleeps == [5.0, 1.0, 1.25]


_MESSAGE = {
    "id": "msg_stub",
    "type": "message",
    "role": "assistant",
    "model": "stub",
    "content": [{"type": "text", "text": "SCORE: 0.9\nREASONING: stub"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


@pytest.mark.parametrize(
    ("header", "value", "expected"),
    [("retry-after", "5", 5.0), ("retry-after-ms", "2500", 2.5)],
)
def test_a_429_waits_the_servers_delay_through_the_real_sdk(
    header: str, value: str, expected: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("anthropic")
    seen: list[int] = []

    class _RateLimited(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("content-length", 0)))
            seen.append(len(seen))
            if len(seen) == 1:
                status = 429
                body = b'{"type":"error","error":{"type":"rate_limit_error","message":"stub"}}'
            else:
                status = 200
                body = json.dumps(_MESSAGE).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            if status == 429:
                self.send_header(header, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _RateLimited)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for name in [k for k in os.environ if k.startswith("ANTHROPIC_")]:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-not-a-key")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")
        sleeps: list[float] = []
        backend = AnthropicBackend(max_attempts=4, sleep=sleeps.append)
        out = backend.complete("system", "user")
    finally:
        server.shutdown()
        server.server_close()
    assert out.startswith("SCORE: 0.9")
    assert len(seen) == 2
    assert sleeps == [expected]
