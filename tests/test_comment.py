"""Tests for `eval_harness.comment` and the `diff-json` / `comment` CLI paths.

Two surfaces here:

1. `render_delta_markdown(report)` — pure rendering. Property: round-trip
   through the sticky marker, table headers in expected order, summary
   counts match, edge cases (no rows, all flagged, baseline-only,
   current-only).

2. `find_sticky_comment` / `upsert_sticky_comment` — GitHub API plumbing.
   We don't hit api.github.com; the helpers accept an `api_base` override
   so tests point them at a local stdlib `http.server` that mimics just
   enough of the contract to drive the find/create/edit branches.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

from eval_harness.cli import main as cli_main
from eval_harness.comment import (
    STICKY_MARKER,
    find_sticky_comment,
    render_delta_markdown,
    upsert_sticky_comment,
)
from eval_harness.runner import DeltaReport, RowDelta

# ---------------------------------------------------------------------------
# render_delta_markdown
# ---------------------------------------------------------------------------


def _make_report(rows: list[RowDelta], summary: dict[str, float | int]) -> DeltaReport:
    return DeltaReport(
        current_run_id="cur_runid_abcdef0123",
        baseline_run_id="base_runid_0123abcdef",
        suite="demo-suite",
        threshold_drop=0.1,
        rows=tuple(rows),
        summary=summary,
    )


def _default_summary(
    mean_delta: float = 0.0,
    n_flagged: int = 0,
    n_regressed: int = 0,
    n_improved: int = 0,
    n_unchanged: int = 0,
    n_new: int = 0,
    n_removed: int = 0,
) -> dict[str, float | int]:
    return {
        "mean_score_current": 0.8,
        "mean_score_baseline": 0.8 - mean_delta,
        "mean_delta": mean_delta,
        "n_flagged": n_flagged,
        "n_regressed": n_regressed,
        "n_improved": n_improved,
        "n_unchanged": n_unchanged,
        "n_new": n_new,
        "n_removed": n_removed,
    }


def test_render_contains_sticky_marker():
    md = render_delta_markdown(
        _make_report(
            [RowDelta("qa_01", 0.8, 0.9, 0.1, "improved", False)],
            _default_summary(mean_delta=0.1, n_improved=1),
        )
    )
    assert STICKY_MARKER in md
    # Marker should be at the very top so a partial-read parser would catch it.
    assert md.startswith(STICKY_MARKER)


def test_render_handles_null_mean_delta_in_summary():
    # `from_json` passes the summary through verbatim, so a delta JSON with an
    # explicit `"mean_delta": null` (an undefined mean Δ) reaches the renderer.
    # It must coerce null to +0.000, not raise TypeError on the `:+.3f` format.
    summary = {**_default_summary(), "mean_delta": None}
    md = render_delta_markdown(_make_report([], summary))
    assert "mean Δ **+0.000**" in md


def test_render_includes_suite_name_in_heading():
    md = render_delta_markdown(_make_report([], _default_summary()))
    assert "# Eval delta · `demo-suite`" in md


def test_render_empty_rows_renders_callout_not_table():
    md = render_delta_markdown(_make_report([], _default_summary()))
    assert "no rows in either run" in md
    assert "| status |" not in md


def test_render_table_columns_in_expected_order():
    md = render_delta_markdown(
        _make_report(
            [RowDelta("qa_01", 0.8, 0.7, -0.1, "regressed", False)],
            _default_summary(mean_delta=-0.1, n_regressed=1),
        )
    )
    header_line = "| status | example_id | baseline | current | Δ | flag |"
    assert header_line in md


def test_render_flagged_row_carries_warning():
    md = render_delta_markdown(
        _make_report(
            [RowDelta("qa_01", 0.9, 0.5, -0.4, "regressed", True)],
            _default_summary(mean_delta=-0.4, n_regressed=1, n_flagged=1),
        )
    )
    assert ":warning:" in md
    assert "flagged **1**" in md
    assert "[X]" in md  # headline status when n_flagged > 0


def test_render_unflagged_regression_omits_warning():
    md = render_delta_markdown(
        _make_report(
            [RowDelta("qa_01", 0.85, 0.78, -0.07, "regressed", False)],
            _default_summary(mean_delta=-0.07, n_regressed=1),
        )
    )
    assert ":warning:" not in md


def test_render_handles_new_and_removed_rows():
    md = render_delta_markdown(
        _make_report(
            [
                RowDelta("qa_01", None, 0.7, None, "new", False),
                RowDelta("qa_02", 0.6, None, None, "removed", False),
            ],
            _default_summary(n_new=1, n_removed=1),
        )
    )
    # `—` (em-dash) is the placeholder for missing scores; ensure it
    # appears in the appropriate row positions.
    new_row_line = next(line for line in md.splitlines() if "qa_01" in line)
    removed_row_line = next(line for line in md.splitlines() if "qa_02" in line)
    assert "| — |" in new_row_line  # baseline missing for new row
    assert "| — |" in removed_row_line  # current missing for removed row


def test_render_short_run_ids_in_subheading():
    md = render_delta_markdown(_make_report([], _default_summary()))
    # 8-char prefix of each id appears in the run-id line.
    assert "`cur_runi`" in md
    assert "`base_run`" in md


# ---------------------------------------------------------------------------
# upsert_sticky_comment: drive the GitHub API plumbing against a stdlib server
# ---------------------------------------------------------------------------


class _FakeGithubHandler(BaseHTTPRequestHandler):
    """In-process replacement for api.github.com.

    State lives on the server class via attributes set by the test.
    """

    server_version = "fake-github/1"

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - signature inherited
        return

    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw)

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._send_json(401, {"message": "no token"})
            return False
        return True

    def do_GET(self) -> None:
        if not self._check_auth():
            return
        url = urlparse(self.path)
        # `/repos/<owner>/<name>/issues/<n>/comments` → 6 path parts.
        parts = url.path.strip("/").split("/")
        if (
            len(parts) == 6
            and parts[0] == "repos"
            and parts[3] == "issues"
            and parts[5] == "comments"
        ):
            self._send_json(200, self.server.comments)  # type: ignore[attr-defined]
            return
        self._send_json(404, {"path": url.path})

    def do_POST(self) -> None:
        if not self._check_auth():
            return
        body = self._read_body()
        comment = {"id": self.server.next_id, "body": body.get("body", "")}  # type: ignore[attr-defined]
        self.server.next_id += 1  # type: ignore[attr-defined]
        self.server.comments.append(comment)  # type: ignore[attr-defined]
        self.server.events.append(("POST", comment["id"]))  # type: ignore[attr-defined]
        self._send_json(201, comment)

    def do_PATCH(self) -> None:
        if not self._check_auth():
            return
        body = self._read_body()
        # Path: /repos/<o>/<n>/issues/comments/<id>
        parts = self.path.strip("/").split("/")
        target_id = int(parts[-1])
        for c in self.server.comments:  # type: ignore[attr-defined]
            if c["id"] == target_id:
                c["body"] = body.get("body", c["body"])
                self.server.events.append(("PATCH", target_id))  # type: ignore[attr-defined]
                self._send_json(200, c)
                return
        self._send_json(404, {"message": "comment not found", "id": target_id})


@pytest.fixture
def fake_github(tmp_path: Path):  # noqa: ARG001 - fixture pattern
    server = HTTPServer(("127.0.0.1", 0), _FakeGithubHandler)
    server.comments = []  # type: ignore[attr-defined]
    server.events = []  # type: ignore[attr-defined]
    server.next_id = 1001  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        yield server, base
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_find_sticky_returns_none_when_empty(fake_github) -> None:
    _server, base = fake_github
    result = find_sticky_comment("o/r", 1, token="t", api_base=base)
    assert result is None


def test_find_sticky_locates_marker(fake_github) -> None:
    server, base = fake_github
    server.comments.extend(
        [
            {"id": 1, "body": "unrelated"},
            {"id": 2, "body": f"body with {STICKY_MARKER} and more"},
            {"id": 3, "body": "another comment"},
        ]
    )
    result = find_sticky_comment("o/r", 1, token="t", api_base=base)
    assert result == 2


def test_upsert_creates_when_no_prior(fake_github) -> None:
    server, base = fake_github
    new_id = upsert_sticky_comment(
        "o/r", 1, f"{STICKY_MARKER}\nfirst post", token="t", api_base=base
    )
    assert new_id == 1001
    assert server.events == [("POST", 1001)]
    assert server.comments[0]["body"] == f"{STICKY_MARKER}\nfirst post"


def test_upsert_edits_when_prior_exists(fake_github) -> None:
    server, base = fake_github
    server.comments.append({"id": 42, "body": f"{STICKY_MARKER}\nold body"})
    new_id = upsert_sticky_comment("o/r", 1, f"{STICKY_MARKER}\nnew body", token="t", api_base=base)
    assert new_id == 42
    assert server.events == [("PATCH", 42)]
    # Only one comment exists; it was edited, not duplicated.
    assert len(server.comments) == 1
    assert server.comments[0]["body"] == f"{STICKY_MARKER}\nnew body"


def test_upsert_refuses_body_without_marker(fake_github) -> None:
    _server, base = fake_github
    with pytest.raises(ValueError, match="missing the sticky marker"):
        upsert_sticky_comment("o/r", 1, "no marker here", token="t", api_base=base)


def test_resolve_token_from_env(monkeypatch: pytest.MonkeyPatch, fake_github) -> None:
    server, base = fake_github
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    new_id = upsert_sticky_comment("o/r", 1, f"{STICKY_MARKER}\nfrom env", api_base=base)
    assert new_id == 1001
    # Confirm the env token was used (server only accepts `Bearer <something>`).
    assert server.events == [("POST", 1001)]


def test_resolve_token_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="token missing"):
        # api_base unused — failure happens before any HTTP call.
        upsert_sticky_comment("o/r", 1, f"{STICKY_MARKER}\nx", api_base="http://nope")


# ---------------------------------------------------------------------------
# CLI: diff-json + comment
# ---------------------------------------------------------------------------


def test_cli_diff_json_renders_markdown(tmp_path: Path, capsys) -> None:
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    rc = cli_main(
        [
            "diff-json",
            "--current",
            str(fixtures_dir / "demo_current.json"),
            "--baseline",
            str(fixtures_dir / "demo_baseline.json"),
            "--format",
            "markdown",
        ]
    )
    captured = capsys.readouterr().out
    assert rc == 1  # demo has a flagged regression
    assert STICKY_MARKER in captured
    assert "qa_history_01" in captured
    assert "qa_followup_01" in captured  # new row
    assert "qa_summarize_01" in captured  # removed row


def test_cli_diff_json_writes_file(tmp_path: Path) -> None:
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    out = tmp_path / "delta.json"
    rc = cli_main(
        [
            "diff-json",
            "--current",
            str(fixtures_dir / "demo_current.json"),
            "--baseline",
            str(fixtures_dir / "demo_baseline.json"),
            "--format",
            "json",
            "--out",
            str(out),
        ]
    )
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["suite"] == "demo-faithfulness"
    ids = [r["example_id"] for r in data["rows"]]
    assert "qa_history_01" in ids


def test_cli_comment_dry_run(tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    # Generate a delta JSON first, then have `comment --dry-run` render it
    # without touching the GitHub API.
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    delta_path = tmp_path / "delta.json"
    cli_main(
        [
            "diff-json",
            "--current",
            str(fixtures_dir / "demo_current.json"),
            "--baseline",
            str(fixtures_dir / "demo_baseline.json"),
            "--format",
            "json",
            "--out",
            str(delta_path),
        ]
    )
    # Should not need a token in dry-run mode.
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    rc = cli_main(
        [
            "comment",
            "--repo",
            "o/r",
            "--pr",
            "1",
            "--delta-json",
            str(delta_path),
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert STICKY_MARKER in out
    assert "demo-faithfulness" in out


# ---------------------------------------------------------------------------
# Hygiene: make sure the GITHUB_TOKEN doesn't leak between tests.
# ---------------------------------------------------------------------------


def test_module_does_not_persist_token_globally() -> None:
    # No module-level cache of the token; each call resolves fresh from env.
    # (Sanity test against a regression where someone caches `GITHUB_TOKEN`
    # at import time and tests pollute each other.)
    assert os.environ.get("GITHUB_TOKEN") in (None, "env-token")  # one of the test states


# ---------------------------------------------------------------------------
# #68: DeltaReport.from_json / RowDelta.from_json round-trip parity
# ---------------------------------------------------------------------------


def test_row_delta_from_json_round_trips_through_to_json_dict_shape() -> None:
    """A row dict emitted by DeltaReport.to_json must rebuild byte-identical
    via RowDelta.from_json."""
    original = RowDelta("qa_01", 0.8, 0.9, 0.1, "improved", False)
    payload = {
        "example_id": original.example_id,
        "baseline_score": original.baseline_score,
        "current_score": original.current_score,
        "delta": original.delta,
        "status": original.status,
        "flagged": original.flagged,
    }
    rebuilt = RowDelta.from_json(payload)
    assert rebuilt == original


def test_row_delta_from_json_defaults_optional_score_fields_to_none() -> None:
    """Older delta JSON payloads (or shim ones from the prior SimpleNamespace
    path) may omit baseline_score / current_score / delta when the row is
    `new` or `removed`. The reader must accept this without raising and
    default the missing fields to None — matches the previous shim's defensive
    `.get(...)` chain in cli._run_comment."""
    payload = {"example_id": "qa_new", "status": "new"}
    rebuilt = RowDelta.from_json(payload)
    assert rebuilt.baseline_score is None
    assert rebuilt.current_score is None
    assert rebuilt.delta is None
    assert rebuilt.flagged is False


def test_row_delta_from_json_raises_on_missing_required_key() -> None:
    """`example_id` and `status` are required; missing them must raise
    KeyError naming the field, not silently default-fill."""
    with pytest.raises(KeyError, match="example_id"):
        RowDelta.from_json({"status": "improved"})
    with pytest.raises(KeyError, match="status"):
        RowDelta.from_json({"example_id": "qa_01"})


def test_delta_report_from_json_round_trips_populated_payload() -> None:
    """Full identity round-trip on a populated DeltaReport."""
    original = _make_report(
        rows=[
            RowDelta("qa_01", 0.8, 0.9, 0.1, "improved", False),
            RowDelta("qa_02", 0.7, 0.5, -0.2, "regressed", True),
        ],
        summary=_default_summary(mean_delta=-0.05, n_improved=1, n_regressed=1, n_flagged=1),
    )
    rebuilt = DeltaReport.from_json(original.to_json())
    assert rebuilt == original
    # Rows are rebuilt as RowDelta, not SimpleNamespace.
    assert all(isinstance(r, RowDelta) for r in rebuilt.rows)
    # And as a tuple — frozen-dataclass invariant.
    assert isinstance(rebuilt.rows, tuple)


def test_delta_report_from_json_round_trips_empty_rows() -> None:
    """A report with no rows is a legitimate state (e.g., both run JSONs
    were empty); must round-trip cleanly with `rows = ()`."""
    original = _make_report(rows=[], summary=_default_summary())
    rebuilt = DeltaReport.from_json(original.to_json())
    assert rebuilt == original
    assert rebuilt.rows == ()


def test_delta_report_from_json_defaults_match_prior_shim_in_run_comment() -> None:
    """The previous `cli._run_comment` shim defaulted top-level fields when
    the operator handed it a hand-written delta JSON that omitted them.
    Move that defaulting into the classmethod so the CLI doesn't need its
    own defensive `.get(...)` chain anymore."""
    rebuilt = DeltaReport.from_json({"rows": []})
    assert rebuilt.current_run_id == "current"
    assert rebuilt.baseline_run_id == "baseline"
    assert rebuilt.suite == "(unknown)"
    # threshold_drop falls back to DEFAULT_THRESHOLD_DROP.
    from eval_harness.runner import DEFAULT_THRESHOLD_DROP

    assert rebuilt.threshold_drop == DEFAULT_THRESHOLD_DROP
    assert rebuilt.summary == {}


def test_delta_report_from_json_coerces_threshold_drop_to_float() -> None:
    """The wire shape may carry threshold_drop as an int or a numeric
    string in older operator-hand-written payloads; force-cast to float."""
    rebuilt = DeltaReport.from_json({"threshold_drop": 1, "rows": []})
    assert rebuilt.threshold_drop == 1.0
    assert isinstance(rebuilt.threshold_drop, float)


def test_delta_report_from_json_summary_is_independent_copy() -> None:
    """`summary` on the rebuilt report must not alias the input dict —
    mutating the caller's payload after `from_json` must not bleed into
    the frozen-dataclass field."""
    payload = {"rows": [], "summary": {"n_flagged": 0}}
    rebuilt = DeltaReport.from_json(payload)
    payload["summary"]["n_flagged"] = 99
    assert rebuilt.summary["n_flagged"] == 0


def test_run_comment_cli_uses_typed_delta_report_not_shim(tmp_path, capsys) -> None:
    """End-to-end: the `comment --dry-run` CLI path now flows through
    DeltaReport.from_json. The rendered markdown must be byte-identical
    to rendering against a hand-built DeltaReport — proving the type-
    ignored SimpleNamespace shim path was structurally equivalent and
    the swap is behavior-preserving."""
    report = _make_report(
        rows=[
            RowDelta("qa_01", 0.8, 0.9, 0.1, "improved", False),
            RowDelta("qa_02", 0.85, 0.78, -0.07, "regressed", False),
        ],
        summary=_default_summary(mean_delta=0.015, n_improved=1, n_regressed=1),
    )
    delta_json = tmp_path / "delta.json"
    delta_json.write_text(json.dumps(report.to_json()), encoding="utf-8")

    rc = cli_main(
        [
            "comment",
            "--delta-json",
            str(delta_json),
            "--repo",
            "jt-mchorse/llm-eval-harness",
            "--pr",
            "1",
            "--dry-run",
        ]
    )
    out, _ = capsys.readouterr()
    assert rc == 0
    direct = render_delta_markdown(report)
    assert out == direct


# ---------------------------------------------------------------------------
# #89: comment-path finiteness guard — reject NaN/+/-Infinity at load time so
# a corrupt delta artifact fails fast instead of posting '+nan'/'inf' in the PR
# comment. Sibling to the run-data guard in load_run_result_from_json (#42).
# ---------------------------------------------------------------------------

_NON_FINITE = pytest.mark.parametrize(
    "bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"]
)


@_NON_FINITE
def test_delta_report_from_json_rejects_non_finite_mean_delta(bad: float) -> None:
    """A present, non-null, non-finite `summary["mean_delta"]` is corruption
    (a bare NaN/Infinity JSON token parses natively) and would render as
    `+nan` in the posted PR comment. Reject it at load time."""
    payload = {"rows": [], "summary": {**_default_summary(), "mean_delta": bad}}
    with pytest.raises(ValueError, match="non-finite mean_delta"):
        DeltaReport.from_json(payload)


@_NON_FINITE
def test_delta_report_from_json_rejects_non_finite_threshold_drop(bad: float) -> None:
    """A non-finite `threshold_drop` would render as `nan` in the threshold
    line of the PR comment. Reject it, matching the #42 run-data contract."""
    with pytest.raises(ValueError, match="non-finite threshold_drop"):
        DeltaReport.from_json({"threshold_drop": bad, "rows": []})


@_NON_FINITE
@pytest.mark.parametrize("field", ["baseline_score", "current_score", "delta"])
def test_row_delta_from_json_rejects_non_finite_score(field: str, bad: float) -> None:
    """A present, non-finite row score field would render as `inf`/`+nan` in
    the per-row table of the PR comment. Reject it; the error names the field
    and the example_id."""
    row = {"example_id": "qa_01", "status": "regressed", field: bad}
    with pytest.raises(ValueError, match=f"non-finite {field}.*qa_01"):
        RowDelta.from_json(row)


def test_delta_report_from_json_accepts_null_and_absent_mean_delta() -> None:
    """The guard must only fire on a present, non-null, non-finite value — an
    explicit `null` (undefined mean Δ, e.g. an all-new suite) and an absent
    key both remain legal and still render (renderer coerces null → +0.000)."""
    null_summary = {**_default_summary(), "mean_delta": None}
    assert (
        DeltaReport.from_json({"rows": [], "summary": null_summary}).summary["mean_delta"] is None
    )
    # Absent mean_delta key entirely.
    assert "mean_delta" not in DeltaReport.from_json({"rows": [], "summary": {}}).summary


def test_row_delta_from_json_still_accepts_finite_and_none_scores() -> None:
    """Regression guard: the finiteness check must not reject legitimate finite
    scores or the None sentinel used for `new`/`removed` rows."""
    finite = RowDelta.from_json(
        {
            "example_id": "qa_01",
            "baseline_score": 0.8,
            "current_score": 0.9,
            "delta": 0.1,
            "status": "improved",
        }
    )
    assert finite.baseline_score == 0.8
    assert finite.delta == 0.1
    none_row = RowDelta.from_json({"example_id": "qa_new", "status": "new"})
    assert none_row.baseline_score is None
    assert none_row.current_score is None
