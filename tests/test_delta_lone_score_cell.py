"""A ``new`` / ``removed`` row prints its one score as a paired row prints it (#446).

Since #444 the baseline / current pair is rendered from each score's decimal,
rounded half to even. The lone cell on a ``new`` / ``removed`` row was still
``.3f`` of the binary float, so one column printed one score two ways at a
decimal tie. Measured on main (fcc9bb3), PR-comment renderer::

    | unchanged | `p` | 0.000 | 0.000 | +0.000 |  |
    | new       | `n` | —     | 0.001 | —      |  |      # both scores 0.0005

Every test here puts the same score on a paired row and on a lone row of one
report and compares the two cells' text.
"""

from __future__ import annotations

import re
from fractions import Fraction

import pytest

from eval_harness.comment import render_delta_markdown
from eval_harness.comparison import render_score, render_score_pair
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


def _report(scores: list[float]) -> DeltaReport:
    """Per score: a paired ``unchanged`` row, a ``new`` row and a ``removed`` row."""
    base: dict[str, float] = {}
    cur: dict[str, float] = {}
    for i, s in enumerate(scores):
        base[f"p{i}"] = cur[f"p{i}"] = s
        cur[f"n{i}"] = s
        base[f"r{i}"] = s
    return diff_runs(_run("curr0000", cur), _run("base0000", base), threshold_drop=0.1)


def _ascii_cells(report: DeltaReport) -> dict[str, tuple[str, str]]:
    out = {}
    for line in render_delta_ascii(report).splitlines():
        m = re.match(r"^(?:unchanged|new|removed)\s+(\S+)\s+(\S+)\s+(\S+)", line)
        if m:
            out[m.group(1)] = (m.group(2), m.group(3))
    return out


def _markdown_cells(report: DeltaReport) -> dict[str, tuple[str, str]]:
    out = {}
    for line in render_delta_markdown(report).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0] in {"unchanged", "new", "removed"}:
            out[cells[1].strip("`")] = (cells[2], cells[3])
    return out


_RENDERERS = pytest.mark.parametrize(
    "cells_of", [_ascii_cells, _markdown_cells], ids=["ascii", "markdown"]
)

#: Decimal ties at the fourth place, where `.3f` of the float and half-even on
#: the decimal disagree (the float sits above the tie), plus ties where they
#: agree and plain scores, as controls.
_DISAGREE = [0.0005, 0.0025, 0.0125, 0.1005, 0.9985]
_AGREE = [0.0015, 0.5, 0.25, 0.123, 0.0, 1.0]


def test_the_table_disagrees_where_it_says_it_does() -> None:
    for s in _DISAGREE:
        assert f"{s:.3f}" != render_score(s), s
    for s in _AGREE:
        assert f"{s:.3f}" == render_score(s), s


@_RENDERERS
@pytest.mark.parametrize("score", _DISAGREE + _AGREE)
def test_lone_cell_prints_the_score_as_the_paired_cell_does(cells_of, score) -> None:
    cells = cells_of(_report([score]))
    paired_base, paired_cur = cells["p0"]
    assert paired_base == paired_cur
    assert cells["n0"] == ("—" if cells_of is _markdown_cells else "-", paired_cur)
    assert cells["r0"] == (paired_base, "—" if cells_of is _markdown_cells else "-")


@_RENDERERS
def test_issue_repro_0_0005(cells_of) -> None:
    cells = cells_of(_report([0.0005]))
    assert cells["p0"] == ("0.000", "0.000")
    assert cells["n0"][1] == "0.000"
    assert cells["r0"][0] == "0.000"


@_RENDERERS
def test_every_fourth_place_tie_in_one_report(cells_of) -> None:
    """All 1000 ties ``0.xxx5`` at once: the lone cells and the pair agree on each."""
    scores = [float(f"0.{k:03d}5") for k in range(1000)]
    cells = cells_of(_report(scores))
    for i in range(len(scores)):
        shown = cells[f"p{i}"][0]
        assert cells[f"n{i}"][1] == shown, scores[i]
        assert cells[f"r{i}"][0] == shown, scores[i]


@pytest.mark.parametrize("score", _DISAGREE + _AGREE)
def test_render_score_is_the_pairs_starting_width_cell(score) -> None:
    assert render_score(score) == render_score_pair(score, score, 0.1)[0]


@pytest.mark.parametrize("score", [0.0005, 0.0015, 0.0025, 0.0125, 0.9995])
def test_render_score_rounds_the_decimal_half_to_even(score) -> None:
    rendered = render_score(score)
    exact = Fraction(repr(score)) * 1000
    assert Fraction(rendered) * 1000 == round(exact)
