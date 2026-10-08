"""The calibration report's κ and r read back into the label printed beside them (#329).

`render_report` publishes each metric in a table row next to an interpretation
label decided at full precision by `_interpret_kappa` / `_interpret_pearson`.
At three places a value just below a ladder boundary printed *as* the boundary,
beside the label for the band below it::

    | Pearson r (continuous)       | 0.700 | strong |          r = 0.69974
    | Cohen's κ (binarized at 0.5) | 0.200 | slight |          κ = 0.19974 (n=50)

Both ladders read `0.700` / `0.200` as the band above. This is D-028's class, a
value beside its own classification. The label here comes from a function call
rather than a `status` name, so D-028's population arm never saw it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from eval_harness.calibration import (
    CalibrationResult,
    _interpret_kappa,
    _interpret_pearson,
    calibrate,
    cohens_kappa,
    load_calibration,
    render_report,
)
from eval_harness.judge import Judge

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = _ROOT / "eval_harness"

_KAPPA_ROW = re.compile(r"^\| Cohen's κ \(binarized at 0\.5\) \| (\S+) \| ([^|]+) \|$", re.M)
_PEARSON_ROW = re.compile(r"^\| Pearson r \(continuous\)\s+\| (\S+) \| ([^|]+) \|$", re.M)
_THRESHOLD_LINE = re.compile(r"^- threshold for κ: (\S+)$", re.M)

#: Two-decimal judge scores over the shipped 50-row calibration set whose Pearson r
#: against the human labels is 0.699736860811484, found by a seeded random search
#: (467 draws). Carried through `calibrate`, so the arm reads the drawn row and
#: not a constructed `CalibrationResult`.
_JUDGE_SCORES_R_JUST_BELOW_0_7 = [
    1, 1, 0.69, 0.95, 0.48, 1, 1, 0.55, 0.52, 0.54,
    1, 1, 1, 1, 1, 0.87, 0.75, 1, 0.51, 0.43,
    1, 0.49, 0.18, 0.04, 0, 0.65, 0, 0, 0, 0.83,
    0.54, 1, 1, 1, 0, 0.94, 0, 0.86, 0.81, 0.52,
    0.96, 0, 0.46, 0.57, 0, 0.45, 0, 0.17, 1, 0.56,
]  # fmt: skip


class _ScriptedBackend:
    def __init__(self, scores: list[float]) -> None:
        self._scores = iter(scores)

    def complete(self, system: str, user: str) -> str:
        return f"SCORE: {next(self._scores)}\nREASONING: scripted"


def _result(kappa: float, pearson: float) -> CalibrationResult:
    return CalibrationResult(n=0, cohens_kappa=kappa, pearson_r=pearson, judge_scores=[], rows=[])


def _rows(report: str) -> tuple[tuple[str, str], tuple[str, str], str]:
    k = _KAPPA_ROW.search(report)
    r = _PEARSON_ROW.search(report)
    t = _THRESHOLD_LINE.search(report)
    assert k, report
    assert r, report
    assert t, report
    return (k.group(1), k.group(2).strip()), (r.group(1), r.group(2).strip()), t.group(1)


def test_pearson_end_to_end_through_calibrate() -> None:
    rows = load_calibration(_ROOT / "fixtures" / "calibration.jsonl")
    assert len(rows) == len(_JUDGE_SCORES_R_JUST_BELOW_0_7) == 50
    result = calibrate(Judge(_ScriptedBackend(_JUDGE_SCORES_R_JUST_BELOW_0_7)), rows)
    # A band, not the exact double: `sum` is compensated from Python 3.12 on, so
    # 3.11 lands one ULP away (0.6997368608114839). Either is just below 0.7.
    assert 0.6995 < result.pearson_r < 0.7
    _, (value, label), _ = _rows(render_report(result, judge_model="m"))
    assert label == "strong"
    assert value != "0.700"
    assert _interpret_pearson(float(value)) == label


def test_kappa_at_the_shipped_set_size() -> None:
    # 12 both-pass, 25 human-fail / judge-pass, 13 both-fail: n = 50.
    kappa = cohens_kappa([1] * 12 + [0] * 38, [1] * 37 + [0] * 13)
    assert kappa == 0.1997439180537772
    (value, label), _, threshold = _rows(render_report(_result(kappa, 0.5), judge_model="m"))
    assert label == "slight"
    assert value != "0.200"
    assert _interpret_kappa(float(value)) == label
    # D-026: the κ cell and the threshold line still share one precision, and the
    # configured threshold still reads back as itself (D-029).
    assert len(value.split(".")[1]) == len(threshold.split(".")[1])
    assert float(threshold) == 0.6


_KAPPA_BOUNDARIES = (0.0, 0.2, 0.4, 0.6, 0.8)
_PEARSON_BOUNDARIES = (-0.7, -0.5, -0.3, -0.1, 0.1, 0.3, 0.5, 0.7)
_MARGINS = (-4e-4, -1e-6, -1e-12, 0.0, 1e-12, 1e-6, 4e-4)


@pytest.mark.parametrize("boundary", _KAPPA_BOUNDARIES)
@pytest.mark.parametrize("margin", _MARGINS)
@pytest.mark.parametrize("threshold", [0.6, 0.6004, 0.0])
def test_kappa_cell_reads_back_into_its_label(
    boundary: float, margin: float, threshold: float
) -> None:
    kappa = boundary + margin
    report = render_report(_result(kappa, 0.5), judge_model="m", threshold_kappa=threshold)
    (value, label), _, rendered_threshold = _rows(report)
    assert label == _interpret_kappa(kappa)
    assert _interpret_kappa(float(value)) == label, (kappa, value, label)
    # The PASS/FAIL gate's rendering contract is untouched.
    assert float(rendered_threshold) == threshold
    if kappa != threshold:
        assert value != rendered_threshold


@pytest.mark.parametrize("boundary", _PEARSON_BOUNDARIES)
@pytest.mark.parametrize("margin", _MARGINS)
def test_pearson_cell_reads_back_into_its_label(boundary: float, margin: float) -> None:
    r = boundary + margin
    _, (value, label), _ = _rows(render_report(_result(0.7, r), judge_model="m"))
    assert label == _interpret_pearson(r)
    assert _interpret_pearson(float(value)) == label, (r, value, label)


@pytest.mark.parametrize(
    ("kappa", "pearson"), [(0.723, 0.912), (0.35, -0.45), (0.0, 0.0), (1.0, 1.0)]
)
def test_unambiguous_values_keep_their_three_place_text(kappa: float, pearson: float) -> None:
    (k_value, _), (r_value, _), threshold = _rows(
        render_report(_result(kappa, pearson), judge_model="m")
    )
    assert k_value == f"{kappa:.3f}"
    assert r_value == f"{pearson:.3f}"
    assert threshold == "0.600"


# --------------------------------------------------------------------------
# The population: a fixed-width value in the same string as an `_interpret_*` label
# --------------------------------------------------------------------------


def _interprets(node: ast.expr) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id.startswith("_interpret")
        for n in ast.walk(node)
    )


def _interpreting_strings() -> list[tuple[str, ast.JoinedStr]]:
    found = []
    for path in sorted(_PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr) and any(
                isinstance(p, ast.FormattedValue) and _interprets(p.value) for p in node.values
            ):
                found.append((path.name, node))
    return found


def test_no_fixed_width_value_sits_beside_an_interpretation_label() -> None:
    offenders = []
    for name, node in _interpreting_strings():
        for part in node.values:
            if (
                isinstance(part, ast.FormattedValue)
                and isinstance(part.format_spec, ast.JoinedStr)
                and not _interprets(part.value)
            ):
                offenders.append(f"{name}:{node.lineno} {ast.unparse(part.value)}")
    assert not offenders, (
        f"fixed-width values beside an `_interpret_*` label: {offenders}; "
        "render them so they read back into that label (#329)"
    )


def test_the_population_arm_is_not_vacuous() -> None:
    # Both report rows: κ and Pearson r.
    assert len(_interpreting_strings()) == 2
