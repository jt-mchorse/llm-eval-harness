"""The harness is the judge's only retry layer: N attempts are N requests (#299).

`AnthropicBackend` documents `max_attempts` as its total call budget
("1 = no retries, just the initial call") and reports an exhausted budget as
"unreachable after 4 attempts". Its client was `anthropic.Anthropic()`, which
keeps the SDK's own `max_retries=2`, so each harness attempt was up to three
HTTP requests: a stub answering 529 counted 12 requests behind that message,
and the SDK's inner retries slept on their own clock rather than the injected
`sleep`.
"""

from __future__ import annotations

import os
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from eval_harness.judge import AnthropicBackend, JudgeBackendError


def test_the_client_is_built_with_sdk_retries_off(monkeypatch: pytest.MonkeyPatch) -> None:
    # Runs without the `judge` extra (CI installs only `[dev]`): a stand-in
    # `anthropic` module records how the backend constructs its client.
    made: list[dict] = []

    class _Anthropic:
        def __init__(self, **kwargs: object) -> None:
            made.append(kwargs)

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    AnthropicBackend()
    assert made == [{"max_retries": 0}]


@pytest.mark.parametrize("attempts", [1, 4])
def test_n_attempts_send_n_requests_through_the_real_sdk(
    attempts: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("anthropic")
    seen: list[str | None] = []

    class _Overloaded(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("content-length", 0)))
            seen.append(self.headers.get("x-stainless-retry-count"))
            body = b'{"type":"error","error":{"type":"overloaded_error","message":"stub"}}'
            self.send_response(529)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Overloaded)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for name in [k for k in os.environ if k.startswith("ANTHROPIC_")]:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-not-a-key")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")
        sleeps: list[float] = []
        backend = AnthropicBackend(max_attempts=attempts, sleep=sleeps.append)
        with pytest.raises(JudgeBackendError, match=rf"unreachable after {attempts} attempts?"):
            backend.complete("system", "user")
    finally:
        server.shutdown()
        server.server_close()
    assert len(seen) == attempts, f"{attempts} attempt(s) sent {len(seen)} requests: {seen}"
    # Every backoff went through the injected clock: one per retry.
    assert len(sleeps) == attempts - 1
