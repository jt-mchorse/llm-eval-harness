"""The judge retries what the SDK's own rule retried, now that it is the only layer (#340).

#299 built the client with `max_retries=0`, so `is_transient_error` replaced the
SDK's `_should_retry`, which honours `x-should-retry` and then retries
408/409/429 and every status >= 500. The hand-written set did not. Measured on
main through the real SDK, `max_attempts=3`, a loopback stub per status:

    503                       3 requests
    520 / 522 / 524           1 request
    400 + x-should-retry:true 1 request
    503 + x-should-retry:false 3 requests
"""

from __future__ import annotations

import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from eval_harness.judge import AnthropicBackend, JudgeBackendError, is_transient_error


def _status_error(status: int, header: str | None = None) -> Exception:
    exc = Exception(f"status {status}")
    exc.status_code = status  # type: ignore[attr-defined]
    exc.response = types.SimpleNamespace(  # type: ignore[attr-defined]
        headers={} if header is None else {"x-should-retry": header}
    )
    return exc


@pytest.mark.parametrize("status", [500, 501, 502, 503, 504, 520, 522, 524, 529, 599])
def test_every_5xx_is_transient(status: int) -> None:
    assert is_transient_error(_status_error(status))


@pytest.mark.parametrize("status", [408, 409, 429])
def test_the_named_4xx_are_transient(status: int) -> None:
    assert is_transient_error(_status_error(status))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422])
def test_other_4xx_are_not(status: int) -> None:
    assert not is_transient_error(_status_error(status))


def test_the_header_decides_when_present() -> None:
    assert is_transient_error(_status_error(400, "true"))
    assert not is_transient_error(_status_error(503, "false"))
    assert is_transient_error(_status_error(503, "maybe"))  # anything else: the status rule


def test_no_response_object_is_fine() -> None:
    exc = Exception("x")
    exc.status_code = 520  # type: ignore[attr-defined]
    assert is_transient_error(exc)
    assert is_transient_error(type("APIConnectionError", (Exception,), {})())


def _requests_sent(monkeypatch: pytest.MonkeyPatch, status: int, header: str | None) -> int:
    pytest.importorskip("anthropic")
    seen: list[int] = []

    class _Stub(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("content-length", 0)))
            seen.append(1)
            self.send_response(status)
            self.send_header("content-type", "application/json")
            if header is not None:
                self.send_header("x-should-retry", header)
            self.end_headers()
            self.wfile.write(b'{"type":"error","error":{"type":"api_error","message":"x"}}')

        def log_message(self, *_a: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
        backend = AnthropicBackend(max_attempts=3, base_retry_delay=0.0, sleep=lambda _s: None)
        with pytest.raises(JudgeBackendError):
            backend.complete("system", "user")
    finally:
        server.shutdown()
    return len(seen)


@pytest.mark.parametrize(
    ("status", "header", "expected"),
    [
        (520, None, 3),
        (522, None, 3),
        (524, None, 3),
        (503, None, 3),
        (400, "true", 3),
        (503, "false", 1),
        (400, None, 1),
        (404, None, 1),
    ],
)
def test_requests_sent_through_the_real_sdk(
    monkeypatch: pytest.MonkeyPatch, status: int, header: str | None, expected: int
) -> None:
    assert _requests_sent(monkeypatch, status, header) == expected
