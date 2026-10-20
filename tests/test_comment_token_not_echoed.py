"""A GitHub token that cannot be a header value is refused unseen (#406).

A `GITHUB_TOKEN`/`GH_TOKEN` ending in a newline (a secret pasted with one, or a
CRLF `.env`) made `http.client` refuse the Authorization header with
`ValueError("Invalid header value b'Bearer <token>\\n'")`, and #394's arm in
`_do_request` copied that message, token included, into the `::error::` line.
#378/#380 established that a credential-bearing body is never echoed there.
The token is now checked in `_resolve_token` before any request, and the
ValueError arm no longer interpolates a message that can quote a header.

Nothing here reaches GitHub. The CLI cases send through a dead loopback proxy
(port 9), which `http.client` would only connect to after building the
headers, and every `urlopen` call is recorded so "nothing was sent" is
checked as well as the output.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from eval_harness import comment
from eval_harness.cli import main

SECRET = "ghp_SECRETSECRETSECRET1234"

NEWLINES = [
    pytest.param("\n", id="lf"),
    pytest.param("\r", id="cr"),
    pytest.param("\r\n", id="crlf"),
]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every `urlopen` call, then let the real one run."""
    calls: list[str] = []
    real = comment.request.urlopen

    def recording_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        calls.append(req.full_url)
        return real(req, timeout=timeout)

    monkeypatch.setattr(comment.request, "urlopen", recording_urlopen)
    return calls


@pytest.fixture
def delta(tmp_path: Path) -> Path:
    p = tmp_path / "delta.json"
    p.write_text(json.dumps({"threshold": 0.05, "mean_delta": 0.0, "rows": []}), encoding="utf-8")
    return p


@pytest.fixture
def no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("newline", NEWLINES)
@pytest.mark.parametrize("var", ["GITHUB_TOKEN", "GH_TOKEN"])
def test_cli_refuses_a_token_with_a_newline_without_printing_it(
    var: str,
    newline: str,
    delta: Path,
    sent: list[str],
    no_tokens: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv(var, SECRET + newline)
    rc = main(["comment", "--repo", "o/r", "--pr", "1", "--delta-json", str(delta)])
    captured = capsys.readouterr()
    assert rc == 2
    assert SECRET not in captured.err
    assert SECRET not in captured.out
    assert captured.err.startswith(f"::error::GitHub token from {var} contains a newline")
    assert sent == []


def test_an_empty_github_token_falls_through_to_gh_token_and_names_it(
    delta: Path,
    sent: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # `GITHUB_TOKEN or GH_TOKEN`: an empty GITHUB_TOKEN is skipped, so the
    # message has to blame GH_TOKEN, the one that was read.
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GH_TOKEN", SECRET + "\n")
    rc = main(["comment", "--repo", "o/r", "--pr", "1", "--delta-json", str(delta)])
    err = capsys.readouterr().err
    assert rc == 2
    assert SECRET not in err
    assert "from GH_TOKEN contains a newline" in err
    assert sent == []


@pytest.mark.parametrize("newline", NEWLINES)
@pytest.mark.parametrize("entry", ["find", "upsert"])
def test_library_refuses_a_token_with_a_newline_without_quoting_it(
    entry: str, newline: str, sent: list[str]
) -> None:
    token = "ghp_LIBRARYSECRET" + newline
    base = "http://127.0.0.1:9"
    if entry == "find":
        with pytest.raises(RuntimeError) as exc:
            comment.find_sticky_comment("o/r", 1, token=token, api_base=base)
    else:
        with pytest.raises(RuntimeError) as exc:
            comment.upsert_sticky_comment(
                "o/r", 1, comment.STICKY_MARKER, token=token, api_base=base
            )
    assert "ghp_LIBRARYSECRET" not in str(exc.value)
    assert "GitHub token from token= contains a newline" in str(exc.value)
    assert sent == []


@pytest.mark.parametrize(
    "bad",
    [
        # A newline then a space is an obs-fold: `http.client` let it through
        # and sent a folded Authorization header.
        pytest.param("\n x", id="folded-newline"),
        pytest.param("\tx", id="tab"),
        pytest.param(" x", id="space"),
        pytest.param("\x00x", id="nul"),
        pytest.param("\x7fx", id="del"),
        pytest.param("é", id="latin-1"),
        pytest.param(" ", id="line-separator"),
    ],
)
def test_other_header_unsafe_characters_are_refused_before_sending(
    bad: str, sent: list[str]
) -> None:
    token = "ghp_OTHERSECRET" + bad
    with pytest.raises(RuntimeError, match=r"GitHub token from token= contains") as exc:
        comment.find_sticky_comment("o/r", 1, token=token, api_base="http://127.0.0.1:9")
    assert "ghp_OTHERSECRET" not in str(exc.value)
    assert sent == []


def test_the_value_error_arm_does_not_quote_the_header() -> None:
    # The second guard: `_do_request` called with a token that skipped
    # `_resolve_token`. http.client refuses the header before connecting.
    with pytest.raises(RuntimeError, match="is not a valid request") as exc:
        comment._do_request("GET", "http://127.0.0.1:9/x", "ghp_ARMSECRET\n")
    assert "ghp_ARMSECRET" not in str(exc.value)


def test_missing_token_message_is_unchanged(no_tokens: None) -> None:
    """Control: no token at all is still the #303 message."""
    with pytest.raises(RuntimeError, match="GitHub token missing"):
        comment.find_sticky_comment("o/r", 1, api_base="http://127.0.0.1:9")


@pytest.fixture
def github() -> Iterator[tuple[str, list[str]]]:
    """A loopback stand-in for the comments API that records Authorization."""
    auth: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, payload: object) -> None:
            auth.append(self.headers.get("Authorization", ""))
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            data = json.dumps(payload).encode()
            self.send_response(200 if self.command == "GET" else 201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            self._reply([])

        def do_POST(self) -> None:  # noqa: N802
            self._reply({"id": 77})

        def log_message(self, *args: object) -> None:
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", auth
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


@pytest.fixture
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.usefixtures("_no_proxy")
@pytest.mark.parametrize(
    "token",
    ["ghp_clean_TOKEN1234", "github_pat_11ABC_def-ghi.jkl~mn+op/q=="],
    ids=["classic", "every-b64token-char"],
)
def test_a_clean_token_still_posts(token: str, github: tuple[str, list[str]]) -> None:
    """Control: a token of visible ASCII reaches the server as the Bearer value."""
    base, auth = github
    cid = comment.upsert_sticky_comment("o/r", 1, comment.STICKY_MARKER, token=token, api_base=base)
    assert cid == 77
    assert auth == [f"Bearer {token}", f"Bearer {token}"]


@pytest.mark.usefixtures("_no_proxy")
def test_github_token_wins_over_a_bad_gh_token(
    github: tuple[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: GH_TOKEN is only read when GITHUB_TOKEN is unset or empty."""
    base, auth = github
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fromGITHUB")
    monkeypatch.setenv("GH_TOKEN", "ghp_fromGH\n")
    assert comment.find_sticky_comment("o/r", 1, api_base=base) is None
    assert auth == ["Bearer ghp_fromGITHUB"]
