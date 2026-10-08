"""The sticky comment fits GitHub's 65,536-character limit (#312).

`render_delta_markdown` emitted one row per example and `comment` posted all of
it. GitHub answers a longer body with a 422 ("Body is too long") on POST and on
the PATCH that updates the sticky comment, so a suite of roughly 1,100+ rows
could never post one, and a PR that already had a comment from an earlier,
smaller run kept that stale verdict. Measured before the fix: 1,200 rows made a
72,493-character body, 2,000 rows 120,493.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness.cli import main as cli_main
from eval_harness.comment import COMMENT_BODY_BUDGET, STICKY_MARKER, render_delta_markdown
from eval_harness.runner import DeltaReport, RowDelta

GITHUB_LIMIT = 65_536


def _row(
    i: int, status: str = "unchanged", *, flagged: bool = False, eid: str | None = None
) -> RowDelta:
    base, cur = {
        "unchanged": (0.8, 0.8),
        "improved": (0.6, 0.8),
        "regressed": (0.8, 0.6),
    }.get(status, (0.8, 0.8))
    if status == "new":
        return RowDelta(eid or f"ex-{i:05d}", None, cur, None, "new", False)
    if status == "removed":
        return RowDelta(eid or f"ex-{i:05d}", base, None, None, "removed", False)
    return RowDelta(eid or f"ex-{i:05d}", base, cur, round(cur - base, 6), status, flagged)


def _report(rows: list[RowDelta]) -> DeltaReport:
    counts = {
        s: sum(1 for r in rows if r.status == s)
        for s in ("regressed", "improved", "unchanged", "new", "removed")
    }
    return DeltaReport(
        current_run_id="cur_runid_abcdef0123",
        baseline_run_id="base_runid_0123abcdef",
        suite="big-suite",
        threshold_drop=0.1,
        rows=tuple(rows),
        summary={
            "mean_score_current": 0.8,
            "mean_score_baseline": 0.8,
            "mean_delta": 0.0,
            "n_flagged": sum(1 for r in rows if r.flagged),
            "n_regressed": counts["regressed"],
            "n_improved": counts["improved"],
            "n_unchanged": counts["unchanged"],
            "n_new": counts["new"],
            "n_removed": counts["removed"],
        },
    )


def _big(n: int) -> list[RowDelta]:
    # The flagged row sorts LAST by example_id, the shape the hunt measured.
    rows = [_row(i) for i in range(n - 1)]
    rows.append(_row(n - 1, "regressed", flagged=True, eid="zz-the-regression"))
    return rows


def test_the_budget_is_under_githubs_limit() -> None:
    assert COMMENT_BODY_BUDGET < GITHUB_LIMIT


@pytest.mark.parametrize("n", [1_200, 2_000, 20_000])
def test_a_large_report_fits_and_keeps_its_flagged_row(n: int) -> None:
    body = render_delta_markdown(_report(_big(n)), max_bytes=COMMENT_BODY_BUDGET)
    assert len(body.encode("utf-8")) <= COMMENT_BODY_BUDGET
    assert len(body) < GITHUB_LIMIT
    assert STICKY_MARKER in body
    assert "zz-the-regression" in body
    assert body.rstrip().endswith("this comment is updated in-place on every push</sub>")


def test_the_omission_line_counts_what_was_left_out() -> None:
    n = 2_000
    body = render_delta_markdown(_report(_big(n)), max_bytes=COMMENT_BODY_BUDGET)
    shown = sum(
        1
        for line in body.splitlines()
        if line.startswith("| ") and ("`ex-" in line or "zz-the" in line)
    )
    omitted_line = next(line for line in body.splitlines() if "rows not shown" in line)
    total = int(omitted_line.split()[0].lstrip("_"))
    assert f"of {n} rows not shown ({total} unchanged)" in omitted_line
    assert shown + total == n


def test_priority_order_regressed_new_removed_improved_then_unchanged() -> None:
    rows = (
        [_row(i) for i in range(1_000)]
        + [_row(1_000 + i, "improved") for i in range(400)]
        + [_row(2_000 + i, "removed") for i in range(5)]
        + [_row(3_000 + i, "new") for i in range(5)]
        + [_row(4_000 + i, "regressed") for i in range(5)]
    )
    body = render_delta_markdown(_report(rows), max_bytes=COMMENT_BODY_BUDGET)
    for i in range(5):
        assert f"ex-{2_000 + i:05d}" in body
        assert f"ex-{3_000 + i:05d}" in body
        assert f"ex-{4_000 + i:05d}" in body
    # Every improved row is shown before any unchanged one is.
    assert all(f"ex-{1_000 + i:05d}" in body for i in range(400))
    assert "unchanged)" in next(line for line in body.splitlines() if "rows not shown" in line)


def test_kept_rows_stay_in_their_original_order() -> None:
    body = render_delta_markdown(_report(_big(2_000)), max_bytes=COMMENT_BODY_BUDGET)
    ids = [
        line.split("`")[1] for line in body.splitlines() if line.startswith("| ") and "`" in line
    ]
    assert ids == sorted(ids)
    assert ids[-1] == "zz-the-regression"


@pytest.mark.parametrize("n", [0, 1, 50, 900])
def test_under_the_cap_the_body_is_unchanged(n: int) -> None:
    report = _report(_big(n) if n else [])
    assert render_delta_markdown(report, max_bytes=COMMENT_BODY_BUDGET) == render_delta_markdown(
        report
    )


def test_the_cap_is_measured_in_bytes_not_characters() -> None:
    # 3-byte characters: 30,000 chars of ids would pass a character count.
    rows = [_row(i, eid="例" * 20 + f"{i:05d}") for i in range(1_500)]
    body = render_delta_markdown(_report(rows), max_bytes=COMMENT_BODY_BUDGET)
    assert len(body.encode("utf-8")) <= COMMENT_BODY_BUDGET


def test_comment_dry_run_prints_the_capped_body(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps(_report(_big(2_000)).to_json()), encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    rc = cli_main(
        ["comment", "--repo", "o/r", "--pr", "1", "--delta-json", str(delta), "--dry-run"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert len(out.encode("utf-8")) <= COMMENT_BODY_BUDGET
    assert "zz-the-regression" in out
    assert "rows not shown" in out


def test_diff_json_markdown_stays_uncapped(tmp_path: Path, capsys) -> None:
    # The file/stdout table is for reading in full; only the comment is capped.
    report = _report(_big(2_000))
    assert "rows not shown" not in render_delta_markdown(report)
    assert len(render_delta_markdown(report)) > GITHUB_LIMIT


def test_a_flagged_row_outranks_unflagged_regressions() -> None:
    # Small drops below the threshold are `regressed` but not flagged; with
    # enough of them to overflow the budget on their own, the one flagged row
    # (last by id) must still be shown -- it is the verdict.
    rows = [RowDelta(f"ex-{i:05d}", 0.80, 0.79, -0.01, "regressed", False) for i in range(1_500)]
    rows.append(RowDelta("zz-the-flagged-one", 0.9, 0.5, -0.4, "regressed", True))
    body = render_delta_markdown(_report(rows), max_bytes=COMMENT_BODY_BUDGET)
    assert "rows not shown" in body
    assert "zz-the-flagged-one" in body
