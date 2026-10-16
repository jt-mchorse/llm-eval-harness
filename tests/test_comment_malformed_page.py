"""A malformed 200 from the comments API is refused at exit 2, never a write (#382).

`find_sticky_comment` trusted the page's shape. On main:

    GET -> 200 ["x"]                 AttributeError at exit 1
    GET -> 200 [{"id":7,"body":5}]   TypeError at exit 1
    GET -> 200 {"message": "..."}    read as "no comments", so a SECOND sticky
                                     comment was POSTed
    PATCH -> 200 {"id": null}        TypeError at exit 1, after the write

Driven through a real loopback server that records every request it receives.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from eval_harness import comment
from eval_harness.comment import STICKY_MARKER

BODY = f"{STICKY_MARKER}\nreport"


class _Server:
    def __init__(self, page: Any, write_response: Any = None) -> None:
        self.requests: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def _send(self, payload: Any) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                outer.requests.append("GET")
                self._send(page)

            def _write(self) -> None:
                self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append(self.command)
                self._send(write_response if write_response is not None else {"id": 99})

            do_PATCH = _write  # noqa: N815
            do_POST = _write  # noqa: N815

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def upsert(self) -> int:
        return comment.upsert_sticky_comment("o/r", 1, BODY, token="t", api_base=self.base)

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def serve() -> Iterator:
    servers: list[_Server] = []

    def start(page: Any, write_response: Any = None) -> _Server:
        s = _Server(page, write_response)
        servers.append(s)
        return s

    yield start
    for s in servers:
        s.close()


MALFORMED = {
    "page-is-an-object": ({"message": "Moved"}, "returned dict, not a list of comments"),
    "page-is-null": (None, "returned NoneType, not a list of comments"),
    "item-is-a-string": (["x"], "a comment that is a str, not an object"),
    "item-is-null": ([None], "a comment that is a NoneType, not an object"),
    "body-is-an-int": ([{"id": 7, "body": 5}], "comment body that is a int, not a string"),
    "sticky-id-is-null": ([{"id": None, "body": BODY}], "with id None, not an integer"),
    "sticky-id-is-a-bool": ([{"id": True, "body": BODY}], "with id True, not an integer"),
}


@pytest.mark.parametrize(("page", "needle"), list(MALFORMED.values()), ids=list(MALFORMED))
def test_a_malformed_page_is_a_runtime_error_and_nothing_is_written(
    serve, page: Any, needle: str
) -> None:  # type: ignore[no-untyped-def]
    server = serve(page)
    with pytest.raises(RuntimeError, match="GitHub API GET ") as info:
        server.upsert()
    assert needle in str(info.value)
    assert server.requests == ["GET"]


def test_a_null_body_still_reads_as_empty(serve) -> None:  # type: ignore[no-untyped-def]
    server = serve([{"id": 7, "body": None}])
    assert server.upsert() == 99
    assert server.requests == ["GET", "POST"]


def test_a_well_formed_page_still_finds_and_patches_the_sticky(serve) -> None:  # type: ignore[no-untyped-def]
    server = serve([{"id": 3, "body": "other"}, {"id": 7, "body": BODY}])
    assert server.upsert() == 99
    assert server.requests == ["GET", "PATCH"]


def test_an_empty_page_still_creates_the_sticky(serve) -> None:  # type: ignore[no-untyped-def]
    server = serve([])
    assert server.upsert() == 99
    assert server.requests == ["GET", "POST"]


@pytest.mark.parametrize("reported", [None, "99", True, -1, {}], ids=repr)
def test_an_unreadable_written_id_falls_back_like_a_missing_one(serve, reported: Any) -> None:  # type: ignore[no-untyped-def]
    patched = serve([{"id": 7, "body": BODY}], write_response={"id": reported})
    assert patched.upsert() == 7
    posted = serve([], write_response={"id": reported})
    assert posted.upsert() == 0


def test_a_written_response_without_an_id_falls_back_as_before(serve) -> None:  # type: ignore[no-untyped-def]
    server = serve([{"id": 7, "body": BODY}], write_response={"url": "x"})
    assert server.upsert() == 7
