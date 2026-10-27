"""A delta row's score cells are its scores' decimals, not the binary floats (#443).

#350 widened the baseline / current pair until it reads as the row's verdict,
and #437 renders the Δ cell beside it from the scores' exact decimal difference
(D-034). The pair itself was still ``.Nf`` of the float, which at the 16-17
places a boundary row widens to prints the double's digits. Measured on main
(042d6e3), ``--threshold-drop 0.1``::

    regressed  b  0.20000000000000001  0.09999999999999999  -0.10000000000000001  FLAG
    regressed  d   0.6000000000000000   0.4999999999999999   -0.1000000000000001  FLAG

Row b's cells subtract to ``-0.10000000000000002``, not the Δ cell beside them;
row d's current cell reads back as a double the run does not contain. Cells are
read back here with ``Fraction``, which is what the verdict is decided on.
"""

from __future__ import annotations

import itertools
import re
from fractions import Fraction

import pytest

from eval_harness.comment import render_delta_markdown
from eval_harness.comparison import render_delta_cell, render_score_pair
from eval_harness.runner import DeltaReport, diff_runs, render_delta_ascii
from eval_harness.runs import StoredRun

# Past DBL_DIG (15) places a fixed-width cell is at the double's resolution.
_DOUBLE_DIGITS = 15


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


def _ascii_cells(report: DeltaReport) -> dict[str, tuple[str, str, str]]:
    out = {}
    for line in render_delta_ascii(report).splitlines():
        m = re.match(r"^(?:regressed|improved|unchanged)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)", line)
        if m:
            out[m.group(1)] = (m.group(2), m.group(3), m.group(4))
    return out


def _markdown_cells(report: DeltaReport) -> dict[str, tuple[str, str, str]]:
    out = {}
    for line in render_delta_markdown(report).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0] in {"regressed", "improved", "unchanged"}:
            out[cells[1].strip("`")] = (cells[2], cells[3], cells[4])
    return out


_RENDERERS = pytest.mark.parametrize(
    "cells_of", [_ascii_cells, _markdown_cells], ids=["ascii", "markdown"]
)

_ISSUE_ROWS = {"b": (0.2, 0.09999999999999999), "d": (0.6, 0.49999999999999994)}


def _places(cell: str) -> int:
    return len(cell.split(".")[1])


@_RENDERERS
def test_the_issue_rows_print_their_scores(cells_of) -> None:
    assert cells_of(_report(_ISSUE_ROWS)) == {
        "b": ("0.20000000000000000", "0.09999999999999999", "-0.10000000000000001"),
        "d": ("0.60000000000000000", "0.49999999999999994", "-0.10000000000000006"),
    }


@_RENDERERS
def test_the_issue_cells_read_back_as_the_scores_and_subtract_to_the_delta(cells_of) -> None:
    for ex_id, (base, cur, delta) in cells_of(_report(_ISSUE_ROWS)).items():
        want_base, want_cur = _ISSUE_ROWS[ex_id]
        assert Fraction(base) == Fraction(repr(want_base)), (ex_id, base)
        assert Fraction(cur) == Fraction(repr(want_cur)), (ex_id, cur)
        assert Fraction(cur) - Fraction(base) == Fraction(delta), (ex_id, base, cur, delta)


def _boundary_pairs(threshold: float) -> dict[str, tuple[float, float]]:
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


def _band(d: Fraction, t: Fraction) -> int:
    return -2 if d < -t else -1 if d < 0 else 0 if d == 0 else 1


@_RENDERERS
@pytest.mark.parametrize("threshold", [0.1, 0.2, 0.3])
def test_a_widened_row_prints_its_scores_exactly(cells_of, threshold: float) -> None:
    # Search, not construct: the rows whose published delta is the threshold
    # itself, which is where the pair and the Δ cell widen to 16-17 places.
    pairs = _boundary_pairs(threshold)
    t = Fraction(repr(threshold))
    widened = 0
    for ex_id, (base, cur, delta) in cells_of(_report(pairs, threshold)).items():
        want_base, want_cur = (Fraction(repr(v)) for v in pairs[ex_id])
        exact = want_cur - want_base
        # #350's rule still holds on the decimals.
        assert _band(Fraction(cur) - Fraction(base), t) == _band(exact, t), ex_id
        assert _places(base) == _places(cur), ex_id
        if _places(base) > _DOUBLE_DIGITS:
            widened += 1
            assert (Fraction(base), Fraction(cur)) == (want_base, want_cur), (ex_id, base, cur)
        if _places(delta) > _DOUBLE_DIGITS:
            assert Fraction(delta) == exact, (ex_id, delta)
            assert Fraction(cur) - Fraction(base) == exact, (ex_id, base, cur, delta)
    # Non-vacuous: the search reaches the double-resolution widths.
    assert widened, threshold


@pytest.mark.parametrize(
    ("baseline", "current", "rendered"),
    [
        # Unchanged at three decimals or fewer.
        (0.8, 0.7, ("0.800", "0.700")),
        (0.5, 0.5004, ("0.5000", "0.5004")),
        # The decimal rounds half to even, like the Δ cell: the float 0.0005
        # is a hair above its decimal, so `.3f` printed 0.001.
        (0.0005, 0.5, ("0.000", "0.500")),
        (0.0025, 0.0035, ("0.002", "0.004")),
        # Past 15 places, the score's own decimal.
        (0.2, 0.09999999999999999, ("0.20000000000000000", "0.09999999999999999")),
        (0.1 + 0.2, 0.2, ("0.30000000000000004", "0.20000000000000000")),
        # No width up to 17 is exact: both decimals, whole, at one width.
        (0.11, 0.009999999999999993, ("0.110000000000000000", "0.009999999999999993")),
        (1e-20, 0.0, ("0.00000000000000000001", "0.00000000000000000000")),
    ],
)
def test_render_score_pair(baseline: float, current: float, rendered: tuple[str, str]) -> None:
    assert render_score_pair(baseline, current, 0.1) == rendered


def test_a_pair_in_band_at_three_places_widens_with_its_delta_cell() -> None:
    # At 0.3, `0.310 | 0.010` is already in the regressed band, but the Δ cell
    # beside it is -0.299999999999999998: the pair goes to that resolution too.
    base, cur = render_score_pair(0.31, 0.010000000000000002, 0.3)
    delta = render_delta_cell(0.31, 0.010000000000000002, 0.3)
    assert (base, cur, delta) == (
        "0.310000000000000000",
        "0.010000000000000002",
        "-0.299999999999999998",
    )
    assert Fraction(cur) - Fraction(base) == Fraction(delta)


@pytest.mark.parametrize(
    ("baseline", "current", "rendered"),
    [
        # 16 places reads as a different double; the exact difference does not.
        (0.6, 0.49999999999999994, "-0.10000000000000006"),
        # Unchanged where 17 places already was the exact difference.
        (0.2, 0.09999999999999999, "-0.10000000000000001"),
        (0.8, 0.7, "-0.100"),
    ],
)
def test_render_delta_cell_past_fifteen_places_is_exact(
    baseline: float, current: float, rendered: str
) -> None:
    assert render_delta_cell(baseline, current, 0.1) == rendered
