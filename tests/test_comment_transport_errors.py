"""Every failed GitHub request is the CLI's exit-2 RuntimeError, not exit 1 (#303).

`_do_request` caught only `HTTPError`. A refused connection, a timeout or a
non-JSON 200 (a proxy's HTML page) escaped `eval-harness comment` as a raw
traceback at exit 1 -- the code that means "a regression was flagged".
"""

from __future__ import annotations

import io
import json
import socket
import subprocess
import sys
from pathlib import Path
from urllib import error

import pytest

from eval_harness import comment

ROOT = Path(__file__).resolve().parent.parent


class _Resp(io.BytesIO):
    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(
            error.URLError(ConnectionRefusedError(61, "Connection refused")), id="refused"
        ),
        pytest.param(TimeoutError("timed out"), id="timeout"),
        pytest.param(TimeoutError("timed out"), id="socket-timeout"),
        pytest.param(ConnectionResetError(54, "reset by peer"), id="reset"),
        pytest.param(_Resp(b"<html>proxy login</html>"), id="html-200"),
        pytest.param(_Resp(b"\xff\xfe not utf-8"), id="undecodable-200"),
    ],
)
def test_a_failed_request_is_a_runtime_error_naming_the_request(
    monkeypatch: pytest.MonkeyPatch, outcome: object
) -> None:
    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(comment.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match=r"GitHub API GET https://api\.github\.com/x"):
        comment._do_request("GET", "https://api.github.com/x", "tok")


def test_an_http_error_keeps_its_status_and_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        raise error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b'{"message":"Not Found"}'))  # type: ignore[arg-type]

    monkeypatch.setattr(comment.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match=r"-> 404: \{\"message\":\"Not Found\"\}"):
        comment._do_request("GET", "https://api.github.com/x", "tok")


def test_the_cli_exits_2_with_one_error_line_on_a_refused_connection(tmp_path: Path) -> None:
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
            "--out",
            str(delta),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert json.loads(delta.read_text())
    # A proxy on a port nothing listens on: the connection is refused locally.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
    env = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_TOKEN": "ghp_fake",
        "HTTPS_PROXY": f"http://127.0.0.1:{dead}",
        "https_proxy": f"http://127.0.0.1:{dead}",
    }
    r = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "comment",
            "--delta-json",
            str(delta),
            "--repo",
            "a/b",
            "--pr",
            "1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert r.returncode == 2, r.stderr
    assert "Traceback" not in r.stderr
    assert r.stderr.startswith("::error::GitHub API GET ")
