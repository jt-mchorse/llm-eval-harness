"""A non-2xx GitHub body is described, not echoed, in the error line (#380).

`_do_request` interpolated the whole decoded body of an `HTTPError` into its
`RuntimeError`, which the CLI prints as `::error::`. A gateway's HTML page went
into the job log line by line, and GitHub ends an annotation at the first
newline, so the PR check read `-> 502: <html>`. That is #378's defect on the
GitHub backend; #378/#379 changed only `judge.py`.

Driven through a real loopback server rather than a patched `urlopen`, so the
body reaches `_do_request` the way urllib delivers it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from eval_harness import comment

ROOT = Path(__file__).resolve().parent.parent

_PAGE = (
    "<html>\n<body>\n<h1>502 Bad Gateway</h1>\n<!-- upstream token=abc123 -->\n</body>\n</html>\n"
)


def _serve(status: int, body: str, ctype: str) -> tuple[HTTPServer, str]:
    payload = body.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def serve() -> Iterator:
    servers: list[HTTPServer] = []

    def start(status: int, body: str, ctype: str = "text/html") -> str:
        server, base = _serve(status, body, ctype)
        servers.append(server)
        return base

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _message(base: str) -> str:
    with pytest.raises(RuntimeError) as info:
        comment._do_request("GET", f"{base}/x", "tok")
    return str(info.value)


def test_an_html_error_page_is_named_by_status_and_size(serve) -> None:  # type: ignore[no-untyped-def]
    msg = _message(serve(502, _PAGE))
    assert msg.endswith(f"-> 502: HTTP 502 with a non-JSON body of {len(_PAGE)} characters")
    assert "\n" not in msg
    assert "token=abc123" not in msg
    assert "<html>" not in msg


def test_an_empty_error_body_says_so(serve) -> None:  # type: ignore[no-untyped-def]
    assert _message(serve(503, "")).endswith("-> 503: HTTP 503 with an empty body")


def test_githubs_json_error_keeps_its_message(serve) -> None:  # type: ignore[no-untyped-def]
    body = json.dumps(
        {"message": "Not Found", "documentation_url": "https://docs.github.com/rest"}, indent=2
    )
    msg = _message(serve(404, body, "application/json"))
    # Pretty-printed by the server, one line in the message.
    assert msg.endswith(
        '-> 404: {"message":"Not Found","documentation_url":"https://docs.github.com/rest"}'
    )


def test_an_escaped_newline_in_a_json_string_stays_escaped(serve) -> None:  # type: ignore[no-untyped-def]
    # Control: green before the fix too. JSON text never holds a raw newline
    # inside a string, and the re-serialisation must not decode one into it.
    body = json.dumps({"message": "Validation Failed\nbody is too long", "status": "422"})
    msg = _message(serve(422, body, "application/json"))
    assert "\n" not in msg
    assert "Validation Failed\\nbody is too long" in msg


def test_non_ascii_json_detail_is_kept_as_written(serve) -> None:  # type: ignore[no-untyped-def]
    body = json.dumps({"message": "Ressource introuvable — dépôt"}, ensure_ascii=False)
    assert _message(serve(404, body, "application/json")).endswith(
        '-> 404: {"message":"Ressource introuvable — dépôt"}'
    )


def test_the_cli_prints_one_error_line_at_exit_2(serve, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    base = serve(502, _PAGE)
    delta = tmp_path / "d.json"
    subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "diff-json",
            "--current",
            str(ROOT / "fixtures/demo_current.json"),
            "--baseline",
            str(ROOT / "fixtures/demo_baseline.json"),
            "--format",
            "json",
            "--out",
            str(delta),
        ],
        check=False,
        capture_output=True,
    )
    assert delta.exists()
    # The CLI always talks to api.github.com; point the two functions at the
    # loopback server the same way a caller passing `api_base` would.
    code = (
        "import sys\n"
        "from eval_harness import cli, comment\n"
        f"comment.find_sticky_comment.__kwdefaults__['api_base'] = {base!r}\n"
        f"comment.upsert_sticky_comment.__kwdefaults__['api_base'] = {base!r}\n"
        "sys.exit(cli.main(sys.argv[1:]))\n"
    )
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-c",
            code,
            "comment",
            "--repo",
            "o/r",
            "--pr",
            "1",
            "--delta-json",
            str(delta),
        ],
        capture_output=True,
        text=True,
        env={"GITHUB_TOKEN": "t", "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert proc.returncode == 2, proc.stderr
    out = proc.stdout + proc.stderr
    error_lines = [line for line in out.splitlines() if line.strip()]
    assert len(error_lines) == 1, out
    assert error_lines[0].startswith("::error::GitHub API GET ")
    assert error_lines[0].endswith(
        f"-> 502: HTTP 502 with a non-JSON body of {len(_PAGE)} characters"
    )
