"""Calibration: does the judge agree with humans?

Loads a calibration dataset (`fixtures/calibration.jsonl`), runs the judge
over every row, and reports two agreement metrics: Cohen's κ on binarized
scores (threshold 0.5) and Pearson r on continuous scores. Both go in the
calibration report; only κ gates CI (D-005).

Self-contained: no scipy/numpy dependency. The math here is small enough to
write by hand and small enough to test against textbook examples.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from eval_harness.judge import FAITHFULNESS_RUBRIC, Judge, JudgeScore


@dataclass(frozen=True)
class CalibrationRow:
    id: str
    prompt: str
    response: str
    rubric: str
    human_score: float  # in [0, 1]
    provenance: dict


@dataclass(frozen=True)
class CalibrationResult:
    n: int
    cohens_kappa: float
    pearson_r: float
    judge_scores: list[JudgeScore]
    rows: list[CalibrationRow]


# ----------------------------------------------------------------------
# Loader
# ----------------------------------------------------------------------


class CalibrationLoadError(ValueError):
    def __init__(self, line_no: int, reason: str) -> None:
        self.line_no = line_no
        self.reason = reason
        super().__init__(f"line {line_no}: {reason}")


def load_calibration(path: str | Path) -> list[CalibrationRow]:
    """Load a JSONL calibration file. One row per line; required fields validated."""
    rows: list[CalibrationRow] = []
    seen_ids: set[str] = set()
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.rstrip("\n")
            if line == "":
                # Blank lines are usually pipeline accidents; reject them so
                # the loader doesn't silently swallow data.
                raise CalibrationLoadError(line_no, "unexpected blank line")
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise CalibrationLoadError(line_no, f"invalid JSON: {e.msg}") from e
            if not isinstance(obj, dict):
                raise CalibrationLoadError(line_no, "row is not a JSON object")
            row = _row_from_dict(line_no, obj)
            if row.id in seen_ids:
                raise CalibrationLoadError(line_no, f"duplicate id {row.id!r}")
            seen_ids.add(row.id)
            rows.append(row)
    return rows


def _row_from_dict(line_no: int, obj: dict) -> CalibrationRow:
    required = {"id", "prompt", "response", "rubric", "human_score", "provenance"}
    missing = required - obj.keys()
    if missing:
        raise CalibrationLoadError(line_no, f"missing required fields: {sorted(missing)}")
    extra = obj.keys() - required
    if extra:
        raise CalibrationLoadError(line_no, f"unknown top-level field(s): {sorted(extra)}")

    if not isinstance(obj["id"], str) or not obj["id"]:
        raise CalibrationLoadError(line_no, "id must be a non-empty string")
    if not isinstance(obj["prompt"], str):
        raise CalibrationLoadError(line_no, "prompt must be a string")
    if not isinstance(obj["response"], str):
        raise CalibrationLoadError(line_no, "response must be a string")
    if not isinstance(obj["rubric"], str):
        raise CalibrationLoadError(line_no, "rubric must be a string")
    if not isinstance(obj["provenance"], dict):
        raise CalibrationLoadError(line_no, "provenance must be an object")

    score = obj["human_score"]
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise CalibrationLoadError(line_no, "human_score must be a number")
    score_f = float(score)
    if not (0.0 <= score_f <= 1.0):
        raise CalibrationLoadError(line_no, f"human_score must be in [0, 1]; got {score_f}")

    return CalibrationRow(
        id=obj["id"],
        prompt=obj["prompt"],
        response=obj["response"],
        rubric=obj["rubric"],
        human_score=score_f,
        provenance=obj["provenance"],
    )


# ----------------------------------------------------------------------
# Metrics: Cohen's κ on binarized scores, Pearson r on continuous
# ----------------------------------------------------------------------


def binarize(score: float, threshold: float = 0.5) -> int:
    """Map a continuous score to {0, 1} via threshold. >= threshold maps to 1."""
    return 1 if score >= threshold else 0


def cohens_kappa(rater_a: list[int], rater_b: list[int]) -> float:
    """Cohen's κ for two raters on a binary scale.

    κ = (po - pe) / (1 - pe) where po is observed agreement and pe is
    chance agreement based on each rater's marginal class frequencies.

    Returns 0.0 in the degenerate case where pe == 1 (both raters
    constant and equal — undefined kappa, conventionally reported as 0).
    """
    if len(rater_a) != len(rater_b):
        raise ValueError("rater lists must have the same length")
    if not rater_a:
        raise ValueError("cannot compute kappa on empty input")

    n = len(rater_a)
    po = sum(1 for a, b in zip(rater_a, rater_b, strict=True) if a == b) / n

    a_pos = sum(rater_a) / n
    b_pos = sum(rater_b) / n
    pe = a_pos * b_pos + (1 - a_pos) * (1 - b_pos)

    if pe == 1.0:
        return 0.0
    return (po - pe) / (1 - pe)


def pearson_r(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation coefficient. Returns 0.0 if either input has zero variance."""
    if len(xs) != len(ys):
        raise ValueError("input lists must have the same length")
    if not xs:
        raise ValueError("cannot compute r on empty input")

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    den = math.sqrt(var_x * var_y)
    if den == 0:
        return 0.0
    return num / den


# ----------------------------------------------------------------------
# Calibration runner
# ----------------------------------------------------------------------


def calibrate(judge: Judge, rows: Iterable[CalibrationRow]) -> CalibrationResult:
    """Run the judge over every row and compute κ and r against human scores."""
    rows_list = list(rows)
    if not rows_list:
        raise ValueError("no rows to calibrate against")

    judge_scores: list[JudgeScore] = []
    for row in rows_list:
        judge_scores.append(
            judge.score(row.prompt, row.response, rubric=row.rubric or FAITHFULNESS_RUBRIC)
        )

    human_continuous = [r.human_score for r in rows_list]
    judge_continuous = [s.score for s in judge_scores]

    human_binary = [binarize(s) for s in human_continuous]
    judge_binary = [binarize(s) for s in judge_continuous]

    return CalibrationResult(
        n=len(rows_list),
        cohens_kappa=cohens_kappa(human_binary, judge_binary),
        pearson_r=pearson_r(human_continuous, judge_continuous),
        judge_scores=judge_scores,
        rows=rows_list,
    )


def render_report(
    result: CalibrationResult, *, judge_model: str, threshold_kappa: float = 0.6
) -> str:
    """Format the calibration result as the markdown that lands in `docs/calibration_report.md`."""
    pass_fail = "PASS" if result.cohens_kappa >= threshold_kappa else "FAIL"
    lines = [
        "# Judge calibration report",
        "",
        f"- judge model: `{judge_model}`",
        f"- calibration set: {result.n} rows",
        f"- threshold for κ: {threshold_kappa}",
        f"- result: **{pass_fail}**",
        "",
        "| metric | value | interpretation |",
        "|--------|-------|----------------|",
        f"| Cohen's κ (binarized at 0.5) | {result.cohens_kappa:.3f} | {_interpret_kappa(result.cohens_kappa)} |",
        f"| Pearson r (continuous)       | {result.pearson_r:.3f} | {_interpret_pearson(result.pearson_r)} |",
        "",
        "## Per-row scores",
        "",
        "| id | human | judge | abs_diff | reasoning |",
        "|----|------:|------:|---------:|-----------|",
    ]
    for row, js in zip(result.rows, result.judge_scores, strict=True):
        lines.append(
            f"| `{row.id}` | {row.human_score:.2f} | {js.score:.2f} | {abs(row.human_score - js.score):.2f} | {js.reasoning} |"
        )
    lines.append("")
    return "\n".join(lines)


def _interpret_kappa(k: float) -> str:
    if k < 0.0:
        return "worse than chance"
    if k < 0.2:
        return "slight"
    if k < 0.4:
        return "fair"
    if k < 0.6:
        return "moderate"
    if k < 0.8:
        return "substantial"
    return "almost perfect"


def _interpret_pearson(r: float) -> str:
    if abs(r) < 0.1:
        return "negligible"
    if abs(r) < 0.3:
        return "weak"
    if abs(r) < 0.5:
        return "moderate"
    if abs(r) < 0.7:
        return "strong"
    return "very strong"
