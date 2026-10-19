"""A malformed `comment --repo` is a usage error at exit 2, not exit 1 (#394).

A space, a non-ASCII character or a newline in `--repo` reached `http.client`,
which raised `InvalidURL` / `UnicodeEncodeError` while building the request
line -- a traceback at exit 1, the code `eval.yml` reads as "regression
flagged". The CLI now checks the `owner/name` grammar before it reads the delta
JSON, and `_do_request` turns a request it cannot build into #303's
RuntimeError for library callers.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from eval_harness import comment
from eval_harness.cli import main

BAD_REPOS = [
    pytest.param("jt-mchorse/llm eval-harness", id="space"),
    pytest.param("jt-mchorse/llm-éval", id="non-ascii"),
    pytest.param("jt-mchorse/x\ny", id="newline"),
    pytest.param("o/n\n", id="trailing-newline"),
    pytest.param("o/n?x=1", id="query"),
    pytest.param("o/n/extra", id="extra-segment"),
    pytest.param("noslash", id="no-slash"),
    pytest.param("o/", id="empty-name"),
    pytest.param("o/..", id="dotdot"),
    pytest.param("-o/n", id="leading-hyphen-owner"),
]


class _Resp(io.BytesIO):
    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _record_urlopen(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []

    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        sent.append((req.get_method(), req.full_url))
        return _Resp(b"[]" if req.get_method() == "GET" else b'{"id": 5}')

    monkeypatch.setattr(comment.request, "urlopen", fake_urlopen)
    return sent


@pytest.mark.parametrize("dry_run", [False, True], ids=["post", "dry-run"])
@pytest.mark.parametrize("repo", BAD_REPOS)
def test_a_malformed_repo_exits_two_before_reading_the_delta(
    repo: str,
    dry_run: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "dummy")
    sent = _record_urlopen(monkeypatch)
    # The delta does not exist: the --repo error must come first.
    argv = ["comment", f"--repo={repo}", "--pr", "1", "--delta-json", str(tmp_path / "nope.json")]
    if dry_run:
        argv.append("--dry-run")
    rc = main(argv)
    err = capsys.readouterr().err
    assert rc == 2
    assert err.startswith('::error::--repo must be a GitHub "owner/name"')
    assert sent == []


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/repos/o/n x/issues/1/comments", id="space"),
        pytest.param("/repos/o/né/issues/1/comments", id="non-ascii"),
        pytest.param("/repos/o/x\ny/issues/1/comments", id="newline"),
    ],
)
def test_do_request_turns_an_unbuildable_url_into_a_runtime_error(path: str) -> None:
    # Port 9 (discard) on loopback: http.client refuses these request lines
    # before it connects, so nothing is sent.
    with pytest.raises(RuntimeError, match="is not a valid request"):
        comment._do_request("GET", f"http://127.0.0.1:9{path}", "tok")


def test_upsert_with_a_malformed_repo_is_a_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="is not a valid request"):
        comment.upsert_sticky_comment(
            "o/n x", 1, comment.STICKY_MARKER, token="tok", api_base="http://127.0.0.1:9"
        )


@pytest.mark.parametrize("repo", ["jt-mchorse/llm-eval-harness", "O-1/repo.name_x-1", "o/.github"])
def test_a_valid_repo_still_posts(
    repo: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Control: real repo names pass the check and reach the API."""
    monkeypatch.setenv("GITHUB_TOKEN", "dummy")
    sent = _record_urlopen(monkeypatch)
    delta = tmp_path / "delta.json"
    delta.write_text(
        json.dumps({"threshold": 0.05, "mean_delta": 0.0, "rows": []}), encoding="utf-8"
    )
    rc = main(["comment", "--repo", repo, "--pr", "1", "--delta-json", str(delta)])
    assert rc == 0, capsys.readouterr().err
    assert [m for m, _ in sent] == ["GET", "POST"]
    assert all(f"/repos/{repo}/issues/1/comments" in url for _, url in sent)
