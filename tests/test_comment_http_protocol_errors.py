"""A response that breaks at the HTTP layer is the CLI's exit-2 RuntimeError (#402).

#303 said that everything talking to GitHub can raise becomes the
`RuntimeError` that `eval-harness comment` turns into exit 2, because exit 1
means "a regression was flagged". `_do_request` caught `HTTPError`,
`OSError`, the body-decode errors and (#394) `http.client.InvalidURL`. The
rest of the `http.client.HTTPException` tree is not an `OSError`, so these
escaped as a traceback at exit 1: a body cut short, a bad chunk, a status
line that is not HTTP, a huge header line, and too many headers.

The server here is a raw socket, so each response is the actual bytes and
`urllib` raises the actual exception.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from eval_harness import comment
from eval_harness.cli import main as cli_main

ROOT = Path(__file__).resolve().parent.parent

_BROKEN: dict[str, tuple[bytes, str]] = {
    "body-short-of-content-length": (
        b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n[{"id":1',
        "IncompleteRead",
    ),
    "bad-status-line": (b"HTTP/1.1 abc OK\r\n\r\n", "BadStatusLine"),
    "not-http-at-all": (b"SSH-2.0-OpenSSH_9.0\r\n\r\n", "BadStatusLine"),
    "too-many-headers": (
        b"HTTP/1.1 200 OK\r\n"
        + b"".join(b"X-H%d: v\r\n" % i for i in range(150))
        + b"Content-Length: 2\r\n\r\n[]",
        "HTTPException",
    ),
    "header-line-too-long": (
        b"HTTP/1.1 200 OK\r\nX-Big: " + b"a" * 70000 + b"\r\nContent-Length: 2\r\n\r\n[]",
        "LineTooLong",
    ),
    "bad-chunk-size": (
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\n[]\r\n0\r\n\r\n",
        "IncompleteRead",
    ),
    "chunk-cut-short": (
        b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n10\r\n[{"i',
        "IncompleteRead",
    ),
}

_WELL_FORMED = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n[]"


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    # urllib routes through a proxy from the environment; the fake server is
    # on loopback and has to be reached directly.
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def raw_server() -> Iterator[list[bytes]]:
    """Serve whatever bytes are in the yielded one-item list to every connection."""
    reply: list[bytes] = [b""]
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(0.2)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                try:
                    conn.recv(65536)
                    conn.sendall(reply[0])
                except OSError:
                    pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    reply.append(f"http://127.0.0.1:{srv.getsockname()[1]}".encode())
    try:
        yield reply
    finally:
        stop.set()
        t.join(timeout=5)
        srv.close()


def _base(server: list[bytes]) -> str:
    return server[1].decode()


@pytest.mark.parametrize(("case"), list(_BROKEN))
def test_a_broken_http_response_is_a_runtime_error_naming_the_request(
    raw_server: list[bytes], case: str
) -> None:
    payload, exc_name = _BROKEN[case]
    raw_server[0] = payload
    url = f"{_base(raw_server)}/repos/o/r/issues/1/comments"
    with pytest.raises(RuntimeError) as info:
        comment._do_request("GET", url, "tok")
    msg = str(info.value)
    assert msg.startswith(f"GitHub API GET {url} failed: malformed HTTP response ({exc_name}")
    # One line, so the `::error::` annotation carries all of it.
    assert "\n" not in msg
    assert "\r" not in msg


@pytest.mark.parametrize(("case"), list(_BROKEN))
def test_comment_exits_2_with_one_error_line_on_a_broken_response(
    raw_server: list[bytes],
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_server[0] = _BROKEN[case][0]
    delta = tmp_path / "d.json"
    assert cli_main(
        [
            "diff-json",
            "--current",
            str(ROOT / "fixtures/demo_current.json"),
            "--baseline",
            str(ROOT / "fixtures/demo_baseline.json"),
            "--out",
            str(delta),
        ]
    ) in (0, 1)
    assert json.loads(delta.read_text())
    capsys.readouterr()
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    monkeypatch.setitem(comment.find_sticky_comment.__kwdefaults__, "api_base", _base(raw_server))
    monkeypatch.setitem(comment.upsert_sticky_comment.__kwdefaults__, "api_base", _base(raw_server))
    rc = cli_main(["comment", "--delta-json", str(delta), "--repo", "o/r", "--pr", "1"])
    err = capsys.readouterr().err
    assert rc == 2, err
    assert err.startswith("::error::GitHub API GET ")
    assert "malformed HTTP response" in err
    assert err.count("\n") == 1


def test_control_a_well_formed_response_still_decodes(raw_server: list[bytes]) -> None:
    raw_server[0] = _WELL_FORMED
    assert comment._do_request("GET", f"{_base(raw_server)}/x", "tok") == []


def test_control_an_unsendable_url_keeps_its_394_message() -> None:
    # `InvalidURL` is also an HTTPException. Its arm comes first, so a URL that
    # was never sent still says so rather than "malformed HTTP response".
    with pytest.raises(RuntimeError, match=r"is not a valid request"):
        comment._do_request("GET", "https://api.github.com/repos/o/a b/x", "tok")
