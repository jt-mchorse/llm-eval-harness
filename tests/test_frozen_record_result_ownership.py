"""A frozen result record owns its containers, whoever built it (#262, D-031).

D-027 (#254) closed `Example.provenance` and `CalibrationRow.provenance` and
*cleared* three more rows from the same worklist:

    CalibrationResult.rows          "calibrate() does list(rows)"
    CalibrationResult.judge_scores  "built inside calibrate()"
    DeltaReport.summary             "built locally; every to_json consumer json.dumps it"

Each reason is true of the one in-package producer and says nothing about the
class. Both classes are public and hand-built -- `render_report` and
`render_delta_markdown` take them as arguments -- so a caller who built one kept
a live handle on a frozen record:

    result = CalibrationResult(n=1, ..., judge_scores=scores, rows=rows)
    scores.append(...); rows.append(...)
    render_report(result, ...)   # "calibration set: 1 rows" over a 2-row table

and `DeltaReport.to_json()` returned the record's own `summary`, the dict the
CLI's exit code reads `n_flagged` from.

Deriving the population instead of taking the issue's three found a fourth:
`runs.StoredRun.rows`, a frozen `dict` that `load_run_result_from_json`
validates (`n_rows == len(rows)`, unique ids, finite scores) and then stored by
reference.

**What "owned" means here is D-027's line, not immutability.** The record stops
sharing its container with whoever passed it in (and, for `to_json`, with
whoever it hands a payload to). Code holding the record can still edit its own
attribute; that is not the defect class and no arm here pretends otherwise.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from eval_harness.calibration import CalibrationResult, CalibrationRow, calibrate, render_report
from eval_harness.comment import render_delta_markdown
from eval_harness.judge import JudgeScore
from eval_harness.runner import DeltaReport, diff_runs, load_run_result_from_json
from eval_harness.runs import StoredRun

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE = _ROOT / "eval_harness"


def _row(row_id: str = "r1", provenance: dict[str, Any] | None = None) -> CalibrationRow:
    return CalibrationRow(
        id=row_id,
        prompt="p",
        response="x",
        rubric="rb",
        human_score=0.5,
        provenance=provenance if provenance is not None else {},
    )


def _score(score: float = 0.5) -> JudgeScore:
    return JudgeScore(score=score, reasoning="r", raw="{}")


def _table_rows(md: str) -> list[str]:
    """The per-row table's data lines, read from the rendered report."""
    lines = md.splitlines()
    start = lines.index("|----|------:|------:|---------:|-----------|") + 1
    return [line for line in lines[start:] if line.startswith("| ")]


def _stated_n(md: str) -> int:
    line = next(line for line in md.splitlines() if line.startswith("- calibration set: "))
    return int(line.removeprefix("- calibration set: ").removesuffix(" rows"))


# ----------------------------------------------------------------------
# CalibrationResult -- the issue's measured repro, through the renderer
# ----------------------------------------------------------------------


def test_the_two_lists_are_not_the_callers_objects() -> None:
    scores, rows = [_score()], [_row()]
    result = CalibrationResult(n=1, cohens_kappa=0.5, pearson_r=0.5, judge_scores=scores, rows=rows)
    assert result.judge_scores is not scores
    assert result.rows is not rows
    assert result.judge_scores == scores
    assert result.rows == rows


def test_appending_to_both_caller_lists_no_longer_desyncs_the_report() -> None:
    """The silent half: `zip(strict=True)` is satisfied and `n` goes stale.

    Asserted on the RENDERED report, not on the record, so a fix that copies
    somewhere the renderer does not read cannot pass it.
    """
    scores, rows = [_score()], [_row("r1")]
    result = CalibrationResult(n=1, cohens_kappa=0.5, pearson_r=0.5, judge_scores=scores, rows=rows)
    scores.append(_score(0.9))
    rows.append(_row("r2"))
    md = render_report(result, judge_model="stub", threshold_kappa=0.6)
    assert _stated_n(md) == 1
    assert len(_table_rows(md)) == 1


def test_appending_to_one_caller_list_no_longer_raises_out_of_the_renderer() -> None:
    """The loud half: before the copy this was `ValueError: zip() argument 2 is
    longer than argument 1`, raised by `render_report`."""
    scores, rows = [_score()], [_row()]
    result = CalibrationResult(n=1, cohens_kappa=0.5, pearson_r=0.5, judge_scores=scores, rows=rows)
    scores.append(_score(0.9))
    md = render_report(result, judge_model="stub", threshold_kappa=0.6)
    assert len(_table_rows(md)) == 1


def test_a_tuple_is_accepted_and_stored_as_the_annotated_list() -> None:
    result = CalibrationResult(
        n=1, cohens_kappa=0.5, pearson_r=0.5, judge_scores=(_score(),), rows=(_row(),)
    )
    assert type(result.judge_scores) is list
    assert type(result.rows) is list


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        # `list("ab")` is ['a', 'b']: the coercing copy must not run first.
        ("rows", "ab", "rows must be a list; got str"),
        ("judge_scores", "ab", "judge_scores must be a list; got str"),
        # A generator is iterable and `list()` would drain it; refused by shape.
        ("rows", (r for r in [_row()]), "rows must be a list; got generator"),
        ("rows", {"r1": _row()}, "rows must be a list; got dict"),
        # The element check is what makes the SHALLOW copy the whole depth.
        ("rows", [{"id": "r1"}], "rows[0] must be a CalibrationRow; got dict"),
        ("judge_scores", [0.5], "judge_scores[0] must be a JudgeScore; got float"),
        ("judge_scores", [_row()], "judge_scores[0] must be a JudgeScore; got CalibrationRow"),
    ],
    ids=["str-rows", "str-scores", "generator", "dict", "dict-element", "float", "swapped"],
)
def test_a_wrong_shape_is_refused_before_it_is_copied(
    field: str, value: object, fragment: str
) -> None:
    kwargs: dict[str, Any] = {"judge_scores": [_score()], "rows": [_row()], field: value}
    with pytest.raises(TypeError) as excinfo:
        CalibrationResult(n=1, cohens_kappa=0.5, pearson_r=0.5, **kwargs)
    assert str(excinfo.value) == fragment


@pytest.mark.parametrize(
    ("n", "n_scores", "n_rows"),
    [(10, 0, 0), (2, 1, 1), (1, 2, 1), (1, 1, 2), (0, 1, 1)],
    ids=["n-over-empty", "n-high", "scores-long", "rows-long", "n-low"],
)
def test_n_must_agree_with_both_lists(n: int, n_scores: int, n_rows: int) -> None:
    """`n=10, rows=[]` used to render "calibration set: 10 rows" over an empty
    table. A repo fixture did exactly that until #262."""
    with pytest.raises(ValueError, match=r"n=\d+ must equal len\(rows\)"):
        CalibrationResult(
            n=n,
            cohens_kappa=0.5,
            pearson_r=0.5,
            judge_scores=[_score() for _ in range(n_scores)],
            rows=[_row(f"r{i}") for i in range(n_rows)],
        )


def test_an_empty_result_is_still_coherent() -> None:
    CalibrationResult(n=0, cohens_kappa=0.5, pearson_r=0.5, judge_scores=[], rows=[])


def test_calibrate_still_builds_a_coherent_result() -> None:
    """Through the one in-package producer: the new invariant must hold for it."""

    class _Judge:
        def score(self, prompt: str, response: str, *, rubric: str) -> JudgeScore:
            return _score()

    rows = [_row(f"r{i}") for i in range(3)]
    result = calibrate(_Judge(), rows)
    assert result.n == len(result.rows) == len(result.judge_scores) == 3


def test_the_shallow_copy_still_has_its_premise() -> None:
    """Shallow is complete only while both element types are frozen and own
    their containers. If either stops being true, the copy above is no longer
    the whole depth and this is the arm that says so."""
    assert JudgeScore.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert CalibrationRow.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert {f.type for f in dataclasses.fields(JudgeScore)} == {"float", "str"}
    provenance = {"annotator": {"name": "a"}}
    row = _row(provenance=provenance)
    provenance["annotator"]["name"] = "MUTATED"
    assert row.provenance == {"annotator": {"name": "a"}}


# ----------------------------------------------------------------------
# DeltaReport.summary -- both directions
# ----------------------------------------------------------------------


def _report(summary: dict[str, Any]) -> DeltaReport:
    return DeltaReport(
        current_run_id="current1",
        baseline_run_id="baseline1",
        suite="s",
        threshold_drop=0.1,
        rows=(),
        summary=summary,
    )


def test_a_callers_later_edit_does_not_reach_the_exit_code_field() -> None:
    """`cli` returns `1 if report.summary["n_flagged"] > 0 else 0`."""
    summary: dict[str, Any] = {"mean_delta": 0.0, "n_flagged": 0}
    report = _report(summary)
    summary["n_flagged"] = 5
    assert report.summary["n_flagged"] == 0


def test_a_callers_later_edit_does_not_reach_the_sticky_comment() -> None:
    summary: dict[str, Any] = {"mean_delta": 0.0, "n_flagged": 0}
    report = _report(summary)
    before = render_delta_markdown(report)
    summary["mean_delta"] = 999.0
    summary["n_flagged"] = 7
    assert render_delta_markdown(report) == before


def test_the_copy_is_deep_because_summary_is_dict_str_any() -> None:
    summary: dict[str, Any] = {"extra": {"nested": [1, 2]}}
    report = _report(summary)
    summary["extra"]["nested"].append(3)
    assert report.summary == {"extra": {"nested": [1, 2]}}


def test_an_edit_to_the_to_json_payload_does_not_reach_the_report() -> None:
    """The outbound half D-027's arm pinned as 'not exploited'."""
    report = _report({"mean_delta": 0.0, "n_flagged": 0, "extra": {"k": 1}})
    payload = report.to_json()
    payload["summary"]["n_flagged"] = 9
    payload["summary"]["extra"]["k"] = 2
    assert report.summary == {"mean_delta": 0.0, "n_flagged": 0, "extra": {"k": 1}}


def test_the_payload_still_round_trips() -> None:
    report = _report({"mean_delta": -0.25, "n_flagged": 1})
    again = DeltaReport.from_json(json.loads(json.dumps(report.to_json())))
    assert again == report


def test_through_diff_runs_the_report_owns_its_summary() -> None:
    """The in-package producer, end to end: build the runs, diff, then edit
    the payload the CLI would write."""
    current = _stored({"a": (0.2, "r")})
    baseline = _stored({"a": (0.9, "r")})
    report = diff_runs(current, baseline, threshold_drop=0.1)
    assert report.summary["n_flagged"] == 1
    report.to_json()["summary"]["n_flagged"] = 0
    assert report.summary["n_flagged"] == 1


@pytest.mark.parametrize("value", [[], "x", 3, None], ids=["list", "str", "int", "none"])
def test_a_non_dict_summary_is_refused(value: object) -> None:
    with pytest.raises(TypeError, match="summary must be a dict"):
        _report(value)  # type: ignore[arg-type]


def test_from_json_still_owns_its_error_for_a_non_object_summary() -> None:
    """The parse boundary's ValueError (the CLI's exit-2 contract) is not
    replaced by the constructor's TypeError: `from_json` checks first."""
    with pytest.raises(ValueError, match="'summary' must be a JSON object"):
        DeltaReport.from_json({"summary": [1]})


# ----------------------------------------------------------------------
# StoredRun.rows -- found by the population, not by the issue
# ----------------------------------------------------------------------


def _stored(rows: dict[str, tuple[float, str]], run_id: str = "run1") -> StoredRun:
    return StoredRun(
        run_id=run_id,
        started_at="2026-01-01T00:00:00Z",
        suite="s",
        dataset_version="v1",
        judge_model=None,
        judge_kappa=None,
        mean_score=sum(s for s, _ in rows.values()) / max(len(rows), 1),
        n_rows=len(rows),
        git_sha=None,
        rows=rows,
    )


def test_a_hand_built_stored_run_does_not_keep_the_callers_map() -> None:
    """Through `diff_runs`, which joins on this map: an edit after construction
    used to add a row the baseline never had while `n_rows` still said 1."""
    rows = {"a": (0.9, "r")}
    current = _stored(rows)
    rows["b"] = (0.1, "r")
    report = diff_runs(current, _stored({"a": (0.9, "r")}, run_id="run0"))
    assert [r.example_id for r in report.rows] == ["a"]
    assert current.n_rows == len(current.rows)


def test_the_loader_path_still_yields_the_same_rows(tmp_path: Path) -> None:
    payload = {
        "run_id": "r1",
        "started_at": "2026-01-01T00:00:00Z",
        "suite": "s",
        "mean_score": 0.5,
        "n_rows": 2,
        "rows": [
            {"example_id": "a", "score": 0.4, "reasoning": "x"},
            {"example_id": "b", "score": 0.6, "reasoning": "y"},
        ],
    }
    path = tmp_path / "run.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    stored = load_run_result_from_json(path)
    assert stored.rows == {"a": (0.4, "x"), "b": (0.6, "y")}
    assert all(type(v) is tuple for v in stored.rows.values())


@pytest.mark.parametrize("value", [[("a", (0.1, "r"))], "a", None], ids=["pairs", "str", "none"])
def test_a_non_dict_rows_is_refused(value: object) -> None:
    with pytest.raises(TypeError, match="rows must be a dict"):
        dataclasses.replace(_stored({}), rows=value)


# ----------------------------------------------------------------------
# The population -- derived, with both halves pinned by value
# ----------------------------------------------------------------------

_MUTABLE_CONTAINERS = ("dict", "list", "set", "Mapping", "MutableMapping")


def _frozen_dataclasses() -> list[tuple[str, ast.ClassDef]]:
    out = []
    # `rglob`, not `glob`: a subpackage would otherwise be outside the corpus
    # and a pass over it would say nothing.
    for path in sorted(_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            decorators = [ast.unparse(d) for d in node.decorator_list]
            if any("dataclass" in d for d in decorators) and any(
                "frozen=True" in d for d in decorators
            ):
                out.append((path.name, node))
    return out


def _container_fields(node: ast.ClassDef) -> list[str]:
    return [
        stmt.target.id
        for stmt in node.body
        if isinstance(stmt, ast.AnnAssign)
        and isinstance(stmt.target, ast.Name)
        and ast.unparse(stmt.annotation).split("[", 1)[0].split(".")[-1] in _MUTABLE_CONTAINERS
    ]


def _owned_by_post_init(node: ast.ClassDef) -> set[str]:
    """Fields `__post_init__` rebinds, read from its `object.__setattr__` calls
    by AST rather than by text, so a field *named* in a comment or docstring
    does not count as owned."""
    post_init = next(
        (n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__post_init__"),
        None,
    )
    if post_init is None:
        return set()
    owned = set()
    for call in ast.walk(post_init):
        if (
            isinstance(call, ast.Call)
            and ast.unparse(call.func) == "object.__setattr__"
            and len(call.args) >= 2
            and isinstance(call.args[1], ast.Constant)
        ):
            owned.add(call.args[1].value)
    return owned


def test_every_frozen_record_owns_its_mutable_container_fields() -> None:
    offenders = [
        f"{module}:{node.name}.{name}"
        for module, node in _frozen_dataclasses()
        for name in _container_fields(node)
        if name not in _owned_by_post_init(node)
    ]
    assert not offenders, (
        f"these frozen records hold a mutable container they do not copy: {offenders}. "
        f"`frozen=True` stops a rebind and nothing else (#254, #262)."
    )


def test_the_population_is_the_six_rows_and_not_an_empty_pass() -> None:
    """A pass over an empty set is not a pass. Pinned by value so a new row is
    decided rather than silently inherited."""
    found = {
        f"{node.name}.{name}"
        for _, node in _frozen_dataclasses()
        for name in _container_fields(node)
    }
    assert found == {
        "CalibrationRow.provenance",
        "CalibrationResult.judge_scores",
        "CalibrationResult.rows",
        "Example.provenance",
        "DeltaReport.summary",
        "StoredRun.rows",
    }, f"the walk found {sorted(found)}"


def test_the_validated_half_of_the_pair_is_empty_here_and_says_so() -> None:
    """`chunking-strategies-lab` D-019: a field must be owned if its annotation
    is a mutable container *or* `__post_init__` validates it, and neither
    condition is a superset. This arm pins that no frozen record validates a
    tuple/Sequence field without owning it. It used to say the second half was
    *empty*; it is not any more -- `RunResult.rows` (#264) and `DeltaReport.rows`
    (#266) are validated, and both are copied to a tuple, which is why this
    still passes. Reverting either copy turns it red."""
    immutable_annotated = ("tuple", "Sequence", "frozenset")
    validated_not_owned = []
    for module, node in _frozen_dataclasses():
        post_init = next(
            (n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__post_init__"),
            None,
        )
        if post_init is None:
            continue
        # Names read as `self.<field>` in the body, by AST: a docstring or
        # comment mentioning a field is not a check on it.
        read = {
            n.attr
            for n in ast.walk(post_init)
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "self"
        }
        owned = _owned_by_post_init(node)
        for stmt in node.body:
            if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                continue
            base = ast.unparse(stmt.annotation).split("[", 1)[0].split(".")[-1]
            name = stmt.target.id
            if base in immutable_annotated and name in read and name not in owned:
                validated_not_owned.append(f"{module}:{node.name}.{name}")
    assert validated_not_owned == []


def test_the_ownership_detector_is_not_vacuous() -> None:
    """Controls for the detector itself: a class that copies is owned, one that
    only *mentions* the field is not."""
    src = '''
@dataclass(frozen=True)
class Copies:
    items: list[int]
    def __post_init__(self) -> None:
        object.__setattr__(self, "items", list(self.items))

@dataclass(frozen=True)
class Mentions:
    items: list[int]
    def __post_init__(self) -> None:
        """object.__setattr__(self, "items", ...)"""
        if not self.items:
            raise ValueError("items")
'''
    classes = {n.name: n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ClassDef)}
    assert _owned_by_post_init(classes["Copies"]) == {"items"}
    assert _owned_by_post_init(classes["Mentions"]) == set()
    assert _container_fields(classes["Mentions"]) == ["items"]
