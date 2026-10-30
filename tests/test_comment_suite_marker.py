"""The sticky marker names its suite (#455).

#455: one marker for every suite. A downstream workflow that runs
``diff-json`` + ``comment`` once per suite (the README's snippet is per
suite) ended with one comment on the PR, and the last suite to post
overwrote the other's delta. On main, ``faithfulness`` regressed (0.9 -> 0.3)
then ``factuality`` held at 0.9: ``[('POST', 1), ('PATCH', 1)]``, one
comment, headed ``factuality``.

The marker is now ``<!-- eval-harness:sticky-comment suite=<escaped> -->`` on
the body's first line, and a comment that carries the bare pre-#455 marker is
taken over by the first suite to post, not orphaned. Matching is still D-009's
substring rule.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import HTTPServer
from pathlib import Path
from urllib.parse import unquote

import pytest

from eval_harness import comment
from eval_harness.cli import main as cli_main
from eval_harness.comment import (
    STICKY_MARKER,
    find_sticky_comment,
    render_delta_markdown,
    sticky_marker,
)
from eval_harness.runner import DeltaReport, RowDelta
from tests.test_comment import _FakeGithubHandler

_PREFIX = "<!-- eval-harness:sticky-comment suite="
_SUFFIX = " -->"


@pytest.fixture
def gh() -> Iterator[tuple[HTTPServer, str]]:
    server = HTTPServer(("127.0.0.1", 0), _FakeGithubHandler)
    server.comments = []  # type: ignore[attr-defined]
    server.events = []  # type: ignore[attr-defined]
    server.next_id = 1  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _report(suite: str, baseline: float, current: float) -> DeltaReport:
    delta = round(current - baseline, 6)
    regressed = delta < 0
    improved = delta > 0
    flagged = delta <= -0.1
    status = "regressed" if regressed else "improved" if improved else "unchanged"
    return DeltaReport(
        current_run_id="cur",
        baseline_run_id="base",
        suite=suite,
        threshold_drop=0.1,
        rows=(RowDelta("q1", baseline, current, delta, status, flagged),),
        summary={
            "mean_score_current": current,
            "mean_score_baseline": baseline,
            "mean_delta": delta,
            "n_flagged": int(flagged),
            "n_regressed": int(regressed),
            "n_improved": int(improved),
            "n_unchanged": int(status == "unchanged"),
            "n_new": 0,
            "n_removed": 0,
        },
    )


def _delta_json(tmp_path: Path, suite: str, baseline: float, current: float) -> Path:
    path = tmp_path / f"delta-{len(list(tmp_path.iterdir()))}.json"
    path.write_text(json.dumps(_report(suite, baseline, current).to_json()), encoding="utf-8")
    return path


def _cli_comment(
    monkeypatch: pytest.MonkeyPatch, base: str, delta: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    monkeypatch.setitem(comment.find_sticky_comment.__kwdefaults__, "api_base", base)
    monkeypatch.setitem(comment.upsert_sticky_comment.__kwdefaults__, "api_base", base)
    rc = cli_main(["comment", "--repo", "o/r", "--pr", "7", "--delta-json", str(delta)])
    assert rc == 0, capsys.readouterr().err


def _headings(server: HTTPServer) -> dict[int, str]:
    return {c["id"]: c["body"].splitlines()[2] for c in server.comments}  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #455


def test_two_suites_on_one_pr_keep_two_comments(
    gh, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    server, base = gh
    _cli_comment(monkeypatch, base, _delta_json(tmp_path, "faithfulness", 0.9, 0.3), capsys)
    _cli_comment(monkeypatch, base, _delta_json(tmp_path, "factuality", 0.9, 0.9), capsys)
    assert server.events == [("POST", 1), ("POST", 2)]
    assert _headings(server) == {
        1: "# Eval delta · `faithfulness`",
        2: "# Eval delta · `factuality`",
    }


def test_a_second_push_edits_each_suites_own_comment(
    gh, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    server, base = gh
    _cli_comment(monkeypatch, base, _delta_json(tmp_path, "faithfulness", 0.9, 0.3), capsys)
    _cli_comment(monkeypatch, base, _delta_json(tmp_path, "factuality", 0.9, 0.9), capsys)
    _cli_comment(monkeypatch, base, _delta_json(tmp_path, "factuality", 0.9, 0.5), capsys)
    _cli_comment(monkeypatch, base, _delta_json(tmp_path, "faithfulness", 0.3, 0.9), capsys)
    assert server.events == [("POST", 1), ("POST", 2), ("PATCH", 2), ("PATCH", 1)]
    bodies = {c["id"]: c["body"] for c in server.comments}
    assert bodies[1].startswith(sticky_marker("faithfulness") + "\n")
    assert "+0.600" in bodies[1]
    assert bodies[2].startswith(sticky_marker("factuality") + "\n")
    assert "-0.400" in bodies[2]


def test_a_legacy_comment_is_taken_over_by_the_first_suite_to_post(
    gh, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    # Posted before the marker named its suite: updated, not orphaned.
    server, base = gh
    server.comments.append({"id": 50, "body": f"{STICKY_MARKER}\n\n# Eval delta · `old`\n"})
    server.next_id = 60
    _cli_comment(monkeypatch, base, _delta_json(tmp_path, "faithfulness", 0.9, 0.3), capsys)
    _cli_comment(monkeypatch, base, _delta_json(tmp_path, "factuality", 0.9, 0.9), capsys)
    _cli_comment(monkeypatch, base, _delta_json(tmp_path, "faithfulness", 0.9, 0.9), capsys)
    assert server.events == [("PATCH", 50), ("POST", 60), ("PATCH", 50)]
    assert _headings(server) == {
        50: "# Eval delta · `faithfulness`",
        60: "# Eval delta · `factuality`",
    }


def test_a_suites_own_comment_wins_over_an_earlier_legacy_one(gh) -> None:
    server, base = gh
    server.comments.extend(
        [
            {"id": 1, "body": f"{STICKY_MARKER}\nlegacy"},
            {"id": 2, "body": f"{sticky_marker('b')}\nb"},
            {"id": 3, "body": f"{sticky_marker('a')}\na"},
        ]
    )
    kw = {"token": "t", "api_base": base, "legacy_marker": STICKY_MARKER}
    assert find_sticky_comment("o/r", 7, marker=sticky_marker("a"), **kw) == 3
    assert find_sticky_comment("o/r", 7, marker=sticky_marker("c"), **kw) == 1
    # Without a legacy marker, a suite with no comment of its own has none.
    assert (
        find_sticky_comment("o/r", 7, marker=sticky_marker("c"), token="t", api_base=base) is None
    )


@pytest.mark.parametrize(
    "suite",
    ["a--b", "x-->y", "--!>", "a>b", "<!--", "a b", "a\nb", "a\r\nb", "-", "--", "---", "a-"],
)
def test_the_suite_cannot_end_the_html_comment(suite: str) -> None:
    marker = sticky_marker(suite)
    assert marker.startswith(_PREFIX)
    assert marker.endswith(_SUFFIX)
    value = marker[len(_PREFIX) : -len(_SUFFIX)]
    assert "--" not in value
    assert ">" not in value
    assert "<" not in value
    assert "!" not in value
    assert not any(ch.isspace() for ch in value)
    assert unquote(value) == suite
    # The comment closes exactly once, at the end.
    assert marker.index("-->") == len(marker) - 3


def test_no_suites_marker_is_contained_in_anothers() -> None:
    suites = ["", "a", "a-", "a-b", "a--b", "a%2Db", "a-%2Db", "a b", "a%20b", "é", "a -->", "A"]
    markers = [sticky_marker(s) for s in suites]
    assert len(set(markers)) == len(suites)
    for i, m in enumerate(markers):
        for j, n in enumerate(markers):
            if i != j:
                assert m not in n, (suites[i], suites[j])
        assert STICKY_MARKER not in m
        assert m not in STICKY_MARKER


def test_a_suite_heading_is_unchanged_by_the_marker() -> None:
    md = render_delta_markdown(_report("demo-faithfulness", 0.9, 0.3))
    assert md.startswith(
        "<!-- eval-harness:sticky-comment suite=demo-faithfulness -->\n\n"
        "# Eval delta · `demo-faithfulness`\n"
    )
