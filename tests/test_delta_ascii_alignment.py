"""Every cell of the ASCII delta table sits under its own header (#307).

Rows were padded with fixed widths (status 9, example_id 12) under a header
and dash line sized to the column NAMES (6, 10), and real example ids run past
12, so no column lined up and the FLAG marker sat under `delta`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from eval_harness.runner import DeltaReport, RowDelta, render_delta_ascii

ROOT = Path(__file__).resolve().parent.parent


def _segments(dash_line: str) -> list[tuple[int, int]]:
    out, i = [], 0
    while i < len(dash_line):
        if dash_line[i] == "-":
            j = i
            while j < len(dash_line) and dash_line[j] == "-":
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _assert_aligned(text: str, rows: list[list[str]]) -> None:
    lines = text.splitlines()
    head = next(i for i, line in enumerate(lines) if line.startswith("status"))
    segs = _segments(lines[head + 1])
    assert len(segs) == 6
    for line, expected in zip(lines[head + 2 : head + 2 + len(rows)], rows, strict=True):
        cut = [line[a:b].strip() for a, b in segs]
        assert cut == expected, f"{line!r} cut at {segs} -> {cut}"
    header_cut = [lines[head][a:b].strip() for a, b in segs]
    assert header_cut == ["status", "example_id", "baseline", "current", "delta", "flag"]


def test_the_demo_fixture_table_lines_up(tmp_path: Path) -> None:
    out = tmp_path / "d.json"
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
            str(out),
        ],
        capture_output=True,
        check=False,
    )
    report = DeltaReport.from_json(json.loads(out.read_text()))
    _assert_aligned(
        render_delta_ascii(report),
        [
            ["regressed", "qa_factuality_01", "0.850", "0.780", "-0.070", ""],
            ["new", "qa_followup_01", "-", "0.650", "-", ""],
            ["improved", "qa_geography_01", "0.950", "0.970", "+0.020", ""],
            ["unchanged", "qa_geometry_01", "0.900", "0.900", "+0.000", ""],
            ["regressed", "qa_history_01", "0.800", "0.550", "-0.250", "FLAG"],
            ["removed", "qa_summarize_01", "0.700", "-", "-", ""],
        ],
    )


def test_a_widened_delta_and_a_long_id_still_line_up() -> None:
    # #291 widens a delta that would otherwise read as the other verdict.
    rows = [
        RowDelta("an-example-id-far-longer-than-twelve", 0.9, 0.8, -0.1 - 1e-9, "regressed", True),
        RowDelta("x", 0.5, 0.5, 0.0, "unchanged", False),
    ]
    report = DeltaReport(
        current_run_id="cur",
        baseline_run_id="base",
        suite="s",
        threshold_drop=0.1,
        rows=rows,
        summary={
            "mean_delta": -0.05,
            "n_regressed": 1,
            "n_flagged": 1,
            "n_improved": 0,
            "n_unchanged": 1,
            "n_new": 0,
            "n_removed": 0,
        },
    )
    text = render_delta_ascii(report)
    lines = text.splitlines()
    head = next(i for i, line in enumerate(lines) if line.startswith("status"))
    segs = _segments(lines[head + 1])
    first = [lines[head + 2][a:b].strip() for a, b in segs]
    assert first[1] == "an-example-id-far-longer-than-twelve"
    assert first[5] == "FLAG"
    assert first[4].startswith("-0.1")
    second = [lines[head + 3][a:b].strip() for a, b in segs]
    assert second == ["unchanged", "x", "0.500", "0.500", "+0.000", ""]
