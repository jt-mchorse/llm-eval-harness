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

from eval_harness.dataset import ValidationFinding, ValidationReport
from eval_harness.judge import Judge, JudgeScore
from eval_harness.markdown import md_code_cell, md_code_span, md_table_cell


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
    def __init__(self, line_no: int, reason: str, code: str = "schema") -> None:
        self.line_no = line_no
        self.reason = reason
        # `code` distinguishes shape — schema | score_range — so the
        # collecting-mode validator can route findings without re-parsing
        # the reason text. Default "schema" covers missing/extra/type.
        self.code = code
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
    if not isinstance(obj["rubric"], str) or not obj["rubric"].strip():
        # Rubric is the judge instruction — an empty/whitespace one is malformed,
        # not a request to fall back to the default. Pre-fix it passed the type
        # check and then `calibrate` silently swapped in FAITHFULNESS_RUBRIC via
        # `row.rubric or ...`, so κ was computed against the wrong rubric with no
        # diagnostic. Reject it loud, same standard as `id` above.
        raise CalibrationLoadError(line_no, "rubric must be a non-empty string")
    if not isinstance(obj["provenance"], dict):
        raise CalibrationLoadError(line_no, "provenance must be an object")

    score = obj["human_score"]
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise CalibrationLoadError(line_no, "human_score must be a number")
    score_f = float(score)
    if not (0.0 <= score_f <= 1.0):
        raise CalibrationLoadError(
            line_no,
            f"human_score must be in [0, 1]; got {score_f}",
            code="score_range",
        )

    return CalibrationRow(
        id=obj["id"],
        prompt=obj["prompt"],
        response=obj["response"],
        rubric=obj["rubric"],
        human_score=score_f,
        provenance=obj["provenance"],
    )


# ----------------------------------------------------------------------
# Validator (#58) — calibration-side analog of `validate_dataset` (#56)
# ----------------------------------------------------------------------


def validate_calibration(path: str | Path) -> ValidationReport:
    """Walk a calibration JSONL file in *collecting* mode.

    Mirrors ``eval_harness.dataset.validate_dataset``: returns one
    ``ValidationFinding`` per malformed row in a single pass, so an
    operator can fix every issue before ``eval-harness calibrate`` spends
    judge tokens up to the first bad row.

    Finding codes:

    - ``parse``         — blank line or JSON decode failure.
    - ``schema``        — missing/extra required fields, wrong types,
                          or a row that isn't a JSON object.
    - ``duplicate_id``  — a row's ``id`` collides with a prior row's.
    - ``score_range``   — ``human_score`` outside ``[0, 1]``.
    - ``empty``         — file contains zero valid rows (the loader
                          treats this as a hard error and so does the
                          validator — one finding with ``line_no=0``).

    ``dataset_version`` is always ``None`` (calibration has no version
    field) and ``tag_counts`` is always ``()`` (no tags). Reusing the
    same ``ValidationReport`` keeps the JSON contract and CLI exit codes
    uniform with the golden-dataset validator.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    findings: list[ValidationFinding] = []
    seen_ids: dict[str, int] = {}
    n_rows = 0
    n_valid = 0

    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            n_rows += 1
            stripped = raw_line.strip()
            if not stripped:
                findings.append(
                    ValidationFinding(
                        line_no=line_no,
                        reason="blank line; calibration must have one JSON object per line",
                        code="parse",
                    )
                )
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as e:
                findings.append(
                    ValidationFinding(
                        line_no=line_no, reason=f"invalid JSON: {e.msg}", code="parse"
                    )
                )
                continue
            if not isinstance(parsed, dict):
                findings.append(
                    ValidationFinding(
                        line_no=line_no, reason="row is not a JSON object", code="schema"
                    )
                )
                continue
            try:
                row = _row_from_dict(line_no, parsed)
            except CalibrationLoadError as e:
                findings.append(ValidationFinding(line_no=line_no, reason=e.reason, code=e.code))
                continue

            if row.id in seen_ids:
                findings.append(
                    ValidationFinding(
                        line_no=line_no,
                        reason=(
                            f"duplicate id {row.id!r}; first seen at line "
                            f"{seen_ids[row.id]}; ids must be unique within a file"
                        ),
                        code="duplicate_id",
                    )
                )
                # Don't count the shadow row as valid; mirrors validate_dataset.
                continue
            seen_ids[row.id] = line_no
            n_valid += 1

    if n_valid == 0 and not findings:
        findings.append(
            ValidationFinding(
                line_no=0,
                reason=f"calibration file {path} contains no rows",
                code="empty",
            )
        )

    return ValidationReport(
        path=str(path),
        n_rows=n_rows,
        n_valid=n_valid,
        findings=tuple(findings),
        dataset_version=None,
        tag_counts=(),
    )


# ----------------------------------------------------------------------
# Metrics: Cohen's κ on binarized scores, Pearson r on continuous
# ----------------------------------------------------------------------


def binarize(score: float, threshold: float = 0.5) -> int:
    """Map a continuous score to {0, 1} via threshold. >= threshold maps to 1.

    `threshold` must be a finite number in `[0, 1]` — the same value domain
    as `JudgeScore.score`. NaN previously caused every comparison to be
    False so every row binarized to 0 (silent κ=0 via the degenerate
    `pe == 1.0` branch in `cohens_kappa`). `bool` was silently coerced to
    0/1. Out-of-range values gave a silent constant-rater result.
    """
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or math.isnan(threshold)
        or math.isinf(threshold)
    ):
        raise ValueError(f"threshold must be a finite number; got {threshold!r}")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be in [0, 1]; got {threshold!r}")
    # `score` shares the same `[0, 1]` domain as `threshold` (and
    # `JudgeScore.score`), but #45 only guarded `threshold`. An unguarded NaN
    # score made `score >= threshold` False and silently binarized to 0; inf or
    # an out-of-range value silently binarized to a constant — either collapses
    # a rater and corrupts κ to a silent 0.0 (the degenerate `pe == 1.0` branch),
    # exactly the failure mode the threshold guard closes. Validate it the same
    # way so the documented contract holds on both arguments.
    if (
        not isinstance(score, (int, float))
        or isinstance(score, bool)
        or math.isnan(score)
        or math.isinf(score)
    ):
        raise ValueError(f"score must be a finite number; got {score!r}")
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be in [0, 1]; got {score!r}")
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


def _require_finite_numbers(values: list[float], label: str) -> None:
    """Reject non-numeric / bool / non-finite elements, like `binarize` (#45, #102).

    A non-finite element silently propagates through the means and the
    covariance to a `NaN` result (`den == 0` is False for NaN, so the
    zero-variance guard doesn't catch it), and `_interpret_pearson(NaN)`
    then renders it as a confidently-wrong "very strong" correlation. Fail
    loud here instead. No range check: Pearson is scale-invariant, so the
    `[0, 1]` domain `binarize` enforces does not apply to a correlation helper.
    """
    for i, v in enumerate(values):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(f"{label}[{i}] must be a number; got {v!r}")
        if not math.isfinite(v):
            raise ValueError(f"{label}[{i}] must be finite; got {v!r}")


def pearson_r(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation coefficient. Returns 0.0 if either input has zero variance."""
    if len(xs) != len(ys):
        raise ValueError("input lists must have the same length")
    if not xs:
        raise ValueError("cannot compute r on empty input")
    _require_finite_numbers(xs, "xs")
    _require_finite_numbers(ys, "ys")

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
        # `row.rubric` is guaranteed non-empty by `_validate`, so pass it
        # verbatim — the old `or FAITHFULNESS_RUBRIC` silently swapped an empty
        # rubric for the default and corrupted the calibration (#75).
        judge_scores.append(judge.score(row.prompt, row.response, rubric=row.rubric))

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
    """Format the calibration result as the markdown that lands in `docs/calibration_report.md`.

    `threshold_kappa` gates the report's PASS/FAIL. Cohen's κ ranges in
    `[-1, 1]`; finite values outside that range cannot ever match (`> 1`
    always FAIL; `< -1` always PASS) so the gate is silently broken.
    `NaN` made every comparison False (always FAIL); `inf`/`-inf` were
    similarly silent. Reject all of those at the boundary so a CI
    misconfig surfaces as a clear ValueError instead of a misleading
    PASS/FAIL line in the markdown.
    """
    if (
        not isinstance(threshold_kappa, (int, float))
        or isinstance(threshold_kappa, bool)
        or math.isnan(threshold_kappa)
        or math.isinf(threshold_kappa)
    ):
        raise ValueError(f"threshold_kappa must be a finite number; got {threshold_kappa!r}")
    if not -1.0 <= threshold_kappa <= 1.0:
        raise ValueError(f"threshold_kappa must be in [-1, 1]; got {threshold_kappa!r}")
    pass_fail = "PASS" if result.cohens_kappa >= threshold_kappa else "FAIL"
    lines = [
        "# Judge calibration report",
        "",
        f"- judge model: {md_code_span(judge_model)}",
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
        # `row.id` (arbitrary calibration-file string) and `js.reasoning`
        # (free-form one-sentence judge output) land in a GFM table cell.
        # Backticks protect neither GFM delimiter: an unescaped `|` injects an
        # extra column (#134) and a literal newline splits the row across two
        # physical lines (#142) — both before inline-code spans are parsed.
        # `row.id` is additionally WRAPPED in a code span, so a backtick in it
        # would close the span early and leak the middle out as prose (#180);
        # `md_code_cell` escapes pipe + newline, neutralizes interior backticks,
        # and wraps the result in a single span. `row.id` can carry a newline (the
        # loader only requires a non-empty string). `js.reasoning` is a bare cell
        # (single-line-guaranteed by `_REASON_RE` today but wired through
        # `md_table_cell` defensively so a future path can't regress the table).
        row_id = md_code_cell(row.id)
        reasoning = md_table_cell(js.reasoning)
        lines.append(
            f"| {row_id} | {row.human_score:.2f} | {js.score:.2f} | {abs(row.human_score - js.score):.2f} | {reasoning} |"
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
