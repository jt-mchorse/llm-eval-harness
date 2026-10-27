"""The Δ cell is rendered from the decimal difference the flag is decided on (#437).

#291 made each row's Δ cell read back as its own verdict, classifying it on the
float ``delta``. D-034 then moved the flag onto the scores' *decimal* difference
and published ``delta`` as the nearest float to it, which can round onto
``-threshold_drop`` itself. Measured on main (ea25ba0), ``--threshold-drop 0.1``::

    regressed  a           0.800                0.700  -0.100
    regressed  b  0.20000000000000001  0.09999999999999999  -0.100  FLAG

with ``"delta": -0.1`` on both rows of the JSON, and the same pair in the PR
comment (``| -0.100 |  |`` and ``| -0.100 | :warning: |``).
"""

from __future__ import annotations

import itertools
import re
from fractions import Fraction

import pytest

from eval_harness.comment import render_delta_markdown
from eval_harness.comparison import COMPARISON_MAX_PLACES, render_delta_cell
from eval_harness.runner import DeltaReport, diff_runs, render_delta_ascii
from eval_harness.runs import StoredRun


def _run(run_id: str, rows: dict[str, float]) -> StoredRun:
    return StoredRun(
        run_id=run_id,
        started_at="2026-01-01T00:00:00Z",
        suite="s",
        dataset_version="v",
        judge_model=None,
        judge_kappa=None,
        mean_score=sum(rows.values()) / len(rows),
        n_rows=len(rows),
        git_sha=None,
        rows={k: (v, "r") for k, v in rows.items()},
    )


def _report(pairs: dict[str, tuple[float, float]], threshold_drop: float = 0.1) -> DeltaReport:
    return diff_runs(
        _run("curr0000", {k: c for k, (_, c) in pairs.items()}),
        _run("base0000", {k: b for k, (b, _) in pairs.items()}),
        threshold_drop=threshold_drop,
    )


def _ascii_cells(report: DeltaReport) -> dict[str, str]:
    out = {}
    for line in render_delta_ascii(report).splitlines():
        m = re.match(r"^(regressed|improved|unchanged)\s+(\S+)\s+\S+\s+\S+\s+(\S+)", line)
        if m:
            out[m.group(2)] = m.group(3)
    return out


def _markdown_cells(report: DeltaReport) -> dict[str, str]:
    out = {}
    for line in render_delta_markdown(report).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0] in {"regressed", "improved", "unchanged"}:
            out[cells[1].strip("`")] = cells[4]
    return out


_RENDERERS = pytest.mark.parametrize(
    "cells_of", [_ascii_cells, _markdown_cells], ids=["ascii", "markdown"]
)

# The issue's pair, and the hunt's 0.24 -> 0.7 * 0.2 beside it.
_ISSUE_ROWS = {
    "a": (0.8, 0.7),
    "b": (0.2, 0.09999999999999999),
    "c": (0.24, 0.7 * 0.2),
}


def test_the_issue_rows_publish_the_same_float_delta() -> None:
    # Precondition: the published JSON delta is D-034's nearest float, -0.1 on
    # every row, while only the rows past the threshold are flagged.
    report = _report(_ISSUE_ROWS)
    rows = {r.example_id: r for r in report.rows}
    assert {r.delta for r in rows.values()} == {-0.1}
    assert [rows[k].flagged for k in "abc"] == [False, True, True]
    assert {r["delta"] for r in report.to_json()["rows"]} == {-0.1}


@_RENDERERS
def test_the_issue_rows_get_cells_that_tell_the_flag_apart(cells_of) -> None:
    assert cells_of(_report(_ISSUE_ROWS)) == {
        "a": "-0.100",
        "b": "-0.10000000000000001",
        "c": "-0.10000000000000001",
    }


def _one_decimal_pairs(threshold: float) -> dict[str, tuple[float, float]]:
    """Two-decimal scores and one-decimal arithmetic whose float delta is ``-threshold``."""
    tenths = [n / 10 for n in range(1, 10)]
    values = {n / 100 for n in range(1, 100)}
    values |= {x * y for x, y in itertools.product(tenths, tenths)}
    values |= {x + y for x, y in itertools.product(tenths, tenths) if x + y <= 1}
    values |= {x - y for x, y in itertools.product(tenths, tenths) if x > y}
    pairs = {}
    for base, cur in itertools.product(sorted(values), sorted(values)):
        if float(Fraction(repr(cur)) - Fraction(repr(base))) == -threshold:
            pairs[f"{base!r}->{cur!r}"] = (base, cur)
    return pairs


@_RENDERERS
@pytest.mark.parametrize("threshold", [0.1, 0.2, 0.3])
def test_a_cell_never_reads_as_the_other_flag(cells_of, threshold: float) -> None:
    # Search, not construct: every score from one-decimal products, sums and
    # differences whose published delta is the threshold itself -- the
    # population the float classification cannot separate.
    pairs = _one_decimal_pairs(threshold)
    report = _report(pairs, threshold)
    cells = cells_of(report)
    by_id = {r.example_id: r for r in report.rows}
    limit = -Fraction(repr(threshold))
    flags_by_cell: dict[str, set[bool]] = {}
    for ex_id, text in cells.items():
        row = by_id[ex_id]
        shown = Fraction(text)
        # Read back as the decimal it is, which is what the flag is decided on.
        assert (shown < limit) is row.flagged, (ex_id, text)
        assert (shown < 0) is (row.status == "regressed"), (ex_id, text)
        flags_by_cell.setdefault(text, set()).add(row.flagged)
    assert all(len(f) == 1 for f in flags_by_cell.values()), flags_by_cell
    # Non-vacuous: the search found rows on both sides of the flag at one float.
    assert {True, False} <= {r.flagged for r in report.rows}, threshold


@pytest.mark.parametrize(
    ("baseline", "current", "threshold", "rendered"),
    [
        # Exactly at a boundary: the default width, no invented difference.
        (0.8, 0.7, 0.1, "-0.100"),
        (0.3, 0.3, 0.1, "+0.000"),
        # The #291 rows read as they did.
        (0.8, 0.6996, 0.1, "-0.1004"),
        (0.8, 0.7004, 0.1, "-0.0996"),
        (0.5, 0.50004, 0.1, "+0.00004"),
        # Rounded on the decimal: 0.6995 - 0.8 is -0.1005, not the float's
        # -0.10050000000000003, so .3f is the even -0.100 and it widens.
        (0.8, 0.6995, 0.1, "-0.1005"),
        (0.5, 0.25, 0.1, "-0.250"),
        # The configured threshold is its decimal too.
        (0.2, 0.09999999999999999, 0.1, "-0.10000000000000001"),
        (0.2, 0.1, 0.1, "-0.100"),
    ],
)
def test_render_delta_cell(
    baseline: float, current: float, threshold: float, rendered: str
) -> None:
    assert render_delta_cell(baseline, current, threshold) == rendered


def test_a_difference_finer_than_every_width_prints_whole() -> None:
    # 1e-20 below zero cannot separate from zero at 17 places, so the cell is
    # the exact decimal, which terminates because both operands do.
    cell = render_delta_cell(1e-20, 0.0, 0.1)
    assert len(cell.split(".")[1]) > COMPARISON_MAX_PLACES
    assert Fraction(cell) == -Fraction(repr(1e-20))


@_RENDERERS
def test_the_mean_headline_is_unchanged(cells_of) -> None:
    # Control: the mean Δ is classified against zero only, and the nearest
    # float to a nonzero exact difference keeps its sign, so it stays on
    # render_signed_classified and reads -0.100 for the issue rows.
    report = _report(_ISSUE_ROWS)
    assert "mean Δ=-0.100" in render_delta_ascii(report)
    assert "mean Δ **-0.100**" in render_delta_markdown(report)
