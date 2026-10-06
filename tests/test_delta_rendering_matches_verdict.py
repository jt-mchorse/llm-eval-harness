"""A row's published delta cannot read as the other verdict (#291, D-028's rule).

Both delta renderers printed the delta at `+.3f` beside a verdict decided at
full precision against two boundaries -- `-threshold_drop` for the flag, `0`
for regressed / unchanged / improved. Measured on main (eaba81f)::

    regressed  x  0.800  0.700  -0.100  FLAG     (0.8 -> 0.6996)
    regressed  y  0.800  0.700  -0.100           (0.8 -> 0.7004)
    improved   z  0.500  0.500  +0.000           (0.5 -> 0.50004)

and the sticky PR comment published the same `-0.100 | :warning:` beside
`-0.100 |`.
"""

from __future__ import annotations

import random
import re

import pytest

from eval_harness.comment import render_delta_markdown
from eval_harness.comparison import render_signed_classified
from eval_harness.runner import diff_runs, render_delta_ascii
from eval_harness.runs import StoredRun


def _run(run_id: str, rows: dict[str, float]) -> StoredRun:
    return StoredRun(
        run_id=run_id,
        started_at="2026-01-01T00:00:00Z",
        suite="s",
        dataset_version="v",
        judge_model=None,
        judge_kappa=None,
        mean_score=0.5,
        n_rows=len(rows),
        git_sha=None,
        rows={k: (v, "r") for k, v in rows.items()},
    )


def _report(pairs: dict[str, tuple[float, float]], threshold_drop: float = 0.1):
    return diff_runs(
        _run("curr0000", {k: c for k, (_, c) in pairs.items()}),
        _run("base0000", {k: b for k, (b, _) in pairs.items()}),
        threshold_drop=threshold_drop,
    )


_ISSUE_ROWS = {
    "x": (0.8, 0.6996),
    "y": (0.8, 0.7004),
    "z": (0.5, 0.50004),
    "u": (0.3, 0.3),
}
_EXPECTED = {"x": "-0.1004", "y": "-0.0996", "z": "+0.00004", "u": "+0.000"}


def _ascii_deltas(report) -> dict[str, str]:
    out = {}
    for line in render_delta_ascii(report).splitlines():
        m = re.match(r"^(regressed|improved|unchanged)\s+(\S+)\s+\S+\s+\S+\s+(\S+)", line)
        if m:
            out[m.group(2)] = m.group(3)
    return out


def _markdown_deltas(report) -> dict[str, str]:
    out = {}
    for line in render_delta_markdown(report).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0] in {"regressed", "improved", "unchanged"}:
            out[cells[1].strip("`")] = cells[4]
    return out


@pytest.mark.parametrize("deltas_of", [_ascii_deltas, _markdown_deltas], ids=["ascii", "markdown"])
def test_the_issue_rows_publish_deltas_their_verdicts_agree_with(deltas_of) -> None:
    assert deltas_of(_report(_ISSUE_ROWS)) == _EXPECTED


@pytest.mark.parametrize("deltas_of", [_ascii_deltas, _markdown_deltas], ids=["ascii", "markdown"])
def test_every_published_delta_reads_back_as_its_own_verdict(deltas_of) -> None:
    # Search, not construct: 4-decimal scores, and a band of pairs straddling
    # each threshold, so both boundaries are exercised from both sides.
    rng = random.Random(291)
    for threshold in (0.1, 0.05, 0.25):
        pairs: dict[str, tuple[float, float]] = {}
        for i in range(400):
            base = round(rng.uniform(0.3, 1.0), 4)
            drop = threshold + rng.choice([-1, 1]) * rng.choice([0.0001, 0.0004, 0.002])
            pairs[f"t{i}"] = (base, round(base - drop, 4))
            pairs[f"r{i}"] = (round(rng.uniform(0, 1), 4), round(rng.uniform(0, 1), 4))
        pairs["z0"] = (0.5, 0.50004)
        report = _report(pairs, threshold)
        published = deltas_of(report)
        by_id = {r.example_id: r for r in report.rows}
        flagged = 0
        for ex_id, text in published.items():
            row = by_id[ex_id]
            back = float(text)
            assert (back < -threshold) is row.flagged, (ex_id, text, row)
            sign = "regressed" if back < 0 else "improved" if back > 0 else "unchanged"
            assert sign == row.status, (ex_id, text, row)
            flagged += row.flagged
        # Non-vacuous: both verdicts of the flag occur in the population.
        assert 0 < flagged < len(published)


@pytest.mark.parametrize(
    ("value", "boundaries", "rendered"),
    [
        # At a boundary: the default width, no invented difference.
        (-0.1, (0.0, -0.1), "-0.100"),
        (0.0, (0.0, -0.1), "+0.000"),
        # Signed zero is at zero, so a tiny regression widens instead.
        (-0.0001, (0.0, -0.1), "-0.0001"),
        (0.25, (0.0, -0.1), "+0.250"),
    ],
)
def test_render_signed_classified(value: float, boundaries: tuple, rendered: str) -> None:
    assert render_signed_classified(value, boundaries) == rendered
