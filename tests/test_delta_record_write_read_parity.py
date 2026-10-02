"""The delta record's constructors enforce every rule its reader states (#266).

The #264 sibling one record over. `DeltaReport.from_json` and
`RowDelta.from_json` accumulated their rules (#42, #89, #116, #150, #190, #228,
#230) and the constructors had none. Measured at `2c946ce`:

    hand-built                     constructs   render_delta_markdown   from_json(to_json())
    threshold_drop=nan             yes          renders                 refused
    suite=None                     yes          AttributeError          refused
    summary={"n_flagged": 2.5}     yes          renders                 refused
    summary={"mean_delta": inf}    yes          renders                 refused
    row flagged="yes"              yes          renders                 refused
    row delta=nan                  yes          renders                 refused

And the reader was looser than the producer twice: it read back a negative
`threshold_drop`, which `diff_runs` refuses because it inverts the regression
test, and any `status` string, where `diff_runs` produces five.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path
from typing import Any

import pytest

from eval_harness.runner import (
    DELTA_ROW_STATUSES,
    DeltaReport,
    RowDelta,
    _status_for,
    diff_runs,
)
from eval_harness.runs import StoredRun

_RUNNER = Path(__file__).resolve().parent.parent / "eval_harness" / "runner.py"


def _row(**overrides: Any) -> RowDelta:
    kwargs: dict[str, Any] = {
        "example_id": "a",
        "baseline_score": 0.9,
        "current_score": 0.5,
        "delta": -0.4,
        "status": "regressed",
        "flagged": True,
    }
    kwargs.update(overrides)
    return RowDelta(**kwargs)


def _report(**overrides: Any) -> DeltaReport:
    kwargs: dict[str, Any] = {
        "current_run_id": "c" * 8,
        "baseline_run_id": "b" * 8,
        "suite": "s",
        "threshold_drop": 0.05,
        "rows": (_row(),),
        "summary": {"n_flagged": 1, "n_regressed": 1, "mean_delta": -0.4},
    }
    kwargs.update(overrides)
    return DeltaReport(**kwargs)


def _payload(**overrides: Any) -> dict[str, Any]:
    payload = _report().to_json()
    payload.update(overrides)
    return payload


def _row_payload(**overrides: Any) -> dict[str, Any]:
    payload = _report().to_json()["rows"][0]
    payload.update(overrides)
    return payload


# (id, report constructor overrides, the same corruption as a payload override)
_REPORT_RULES: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    ("threshold-nan", {"threshold_drop": math.nan}, {"threshold_drop": math.nan}),
    ("threshold-inf", {"threshold_drop": math.inf}, {"threshold_drop": math.inf}),
    ("threshold-negative", {"threshold_drop": -0.1}, {"threshold_drop": -0.1}),
    ("threshold-bool", {"threshold_drop": True}, {"threshold_drop": True}),
    ("suite-none", {"suite": None}, {"suite": None}),
    ("current-run-id-none", {"current_run_id": None}, {"current_run_id": None}),
    ("baseline-run-id-int", {"baseline_run_id": 7}, {"baseline_run_id": 7}),
    ("n-flagged-fraction", {"summary": {"n_flagged": 2.5}}, {"summary": {"n_flagged": 2.5}}),
    ("n-new-infinite", {"summary": {"n_new": math.inf}}, {"summary": {"n_new": math.inf}}),
    (
        "mean-delta-inf",
        {"summary": {"mean_delta": math.inf}},
        {"summary": {"mean_delta": math.inf}},
    ),
    ("mean-delta-list", {"summary": {"mean_delta": [1]}}, {"summary": {"mean_delta": [1]}}),
]

# (id, row constructor overrides, the same corruption as a row-payload override)
_ROW_RULES: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    ("example-id-none", {"example_id": None}, {"example_id": None}),
    ("example-id-empty", {"example_id": ""}, {"example_id": ""}),
    ("status-int", {"status": 3}, {"status": 3}),
    ("status-unknown", {"status": "bogus"}, {"status": "bogus"}),
    ("status-case", {"status": "Regressed"}, {"status": "Regressed"}),
    ("flagged-string", {"flagged": "yes"}, {"flagged": "yes"}),
    ("flagged-int", {"flagged": 1}, {"flagged": 1}),
    ("delta-nan", {"delta": math.nan}, {"delta": math.nan}),
    ("baseline-inf", {"baseline_score": math.inf}, {"baseline_score": math.inf}),
    ("current-bool", {"current_score": True}, {"current_score": True}),
]


@pytest.mark.parametrize(
    ("overrides", "payload_overrides"),
    [(o, p) for _, o, p in _REPORT_RULES],
    ids=[i for i, _, _ in _REPORT_RULES],
)
def test_the_report_refuses_what_its_reader_refuses_with_the_same_words(
    overrides: dict[str, Any], payload_overrides: dict[str, Any]
) -> None:
    """Identical messages are the observable form of "one definition": a second
    copy of a rule could agree on *whether* to refuse and still drift in *why*."""
    with pytest.raises(ValueError) as read_error:  # noqa: PT011 - compared below
        DeltaReport.from_json(_payload(**payload_overrides))
    with pytest.raises(ValueError) as write_error:  # noqa: PT011 - compared below
        _report(**overrides)
    assert str(write_error.value) == str(read_error.value)


@pytest.mark.parametrize(
    ("overrides", "payload_overrides"),
    [(o, p) for _, o, p in _ROW_RULES],
    ids=[i for i, _, _ in _ROW_RULES],
)
def test_the_row_refuses_what_its_reader_refuses_with_the_same_words(
    overrides: dict[str, Any], payload_overrides: dict[str, Any]
) -> None:
    with pytest.raises(ValueError) as read_error:  # noqa: PT011 - compared below
        DeltaReport.from_json(_payload(rows=[_row_payload(**payload_overrides)]))
    with pytest.raises(ValueError) as write_error:  # noqa: PT011 - compared below
        _row(**overrides)
    assert str(write_error.value) == str(read_error.value)


def test_a_valid_report_still_round_trips() -> None:
    report = _report()
    assert DeltaReport.from_json(report.to_json()) == report


# ----------------------------------------------------------------------
# The two places the reader was looser than the producer
# ----------------------------------------------------------------------


def _stored(run_id: str, scores: dict[str, float]) -> StoredRun:
    return StoredRun(
        run_id=run_id,
        started_at="2026-01-01T00:00:00Z",
        suite="s",
        dataset_version="v1",
        judge_model=None,
        judge_kappa=None,
        mean_score=sum(scores.values()) / len(scores),
        n_rows=len(scores),
        git_sha=None,
        rows={k: (v, "r") for k, v in scores.items()},
    )


def test_a_negative_threshold_is_refused_by_diff_runs_and_the_reader_in_the_same_words() -> None:
    """`diff_runs` has refused it since #42; the reader read it back (#266)."""
    current = _stored("c" * 8, {"a": 0.5})
    with pytest.raises(ValueError) as produce_error:  # noqa: PT011 - compared below
        diff_runs(current, current, threshold_drop=-0.1)
    with pytest.raises(ValueError) as read_error:  # noqa: PT011 - compared below
        DeltaReport.from_json(_payload(threshold_drop=-0.1))
    assert str(read_error.value) == str(produce_error.value)
    assert "inverts" in str(read_error.value)


def test_zero_is_still_a_legal_threshold() -> None:
    """The boundary: `>= 0`, and `--threshold-drop 0` means "any drop flags"."""
    assert DeltaReport.from_json(_payload(threshold_drop=0)).threshold_drop == 0.0


def test_diff_runs_emits_every_status_and_only_those_in_the_shared_set() -> None:
    """The constant is a claim about `diff_runs`; this run makes all five."""
    baseline = _stored("b" * 8, {"imp": 0.5, "reg": 0.9, "same": 0.7, "gone": 0.4})
    current = _stored("c" * 8, {"imp": 0.8, "reg": 0.1, "same": 0.7, "fresh": 0.6})
    report = diff_runs(current, baseline, threshold_drop=0.1)
    assert {r.status for r in report.rows} == set(DELTA_ROW_STATUSES)


@pytest.mark.parametrize("delta", [-1.0, -0.2, -0.05, -1e-12, 0.0, 1e-12, 0.3])
@pytest.mark.parametrize("threshold_drop", [0.0, 0.1, 0.5])
def test_status_for_only_produces_members_of_the_shared_set(
    delta: float, threshold_drop: float
) -> None:
    status, _ = _status_for(delta, threshold_drop)
    assert status in DELTA_ROW_STATUSES


# ----------------------------------------------------------------------
# A hand-built report: shape, ownership and storage
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ("ab", "rows must be a tuple of RowDelta; got str"),
        ([{"example_id": "a"}], "rows[0] must be a RowDelta; got dict"),
    ],
    ids=["str", "dict-element"],
)
def test_a_wrong_rows_shape_is_refused(rows: Any, message: str) -> None:
    with pytest.raises(TypeError) as excinfo:
        _report(rows=rows)
    assert str(excinfo.value) == message


def test_rows_are_owned_once_validated() -> None:
    """Validated, so kept (D-019): a caller's list would otherwise let a later
    append reach the frozen report and its `regressed_ids`."""
    rows = [_row()]
    report = _report(rows=rows)
    rows.append(_row(example_id="z"))
    assert type(report.rows) is tuple
    assert report.regressed_ids == ["a"]


def test_numeric_strings_are_stored_as_the_float_the_reader_would_produce() -> None:
    """Checked *and stored*: the reader coerces a numeric string with `float()`,
    and both renderers format these with `.3f` / `render_configured`, so a
    stored `"0.5"` was a raw ValueError at render time."""
    from eval_harness.comment import render_delta_markdown
    from eval_harness.runner import render_delta_ascii

    report = _report(
        threshold_drop="0.05",
        rows=(_row(baseline_score="0.9", current_score="0.5", delta="-0.4"),),
    )
    assert report.threshold_drop == 0.05
    row = report.rows[0]
    assert (row.baseline_score, row.current_score, row.delta) == (0.9, 0.5, -0.4)
    assert report == DeltaReport.from_json(_payload(threshold_drop="0.05"))
    render_delta_markdown(report)
    render_delta_ascii(report)


def test_the_issue_table_renders_nothing_it_cannot_read_back() -> None:
    """The issue's six rows, end to end: each is refused at construction, so
    there is no report left to render or to write."""
    for build in (
        lambda: _report(threshold_drop=math.nan),
        lambda: _report(suite=None),
        lambda: _report(summary={"n_flagged": 2.5}),
        lambda: _report(summary={"mean_delta": math.inf}),
        lambda: _report(rows=(_row(flagged="yes"),)),
        lambda: _report(rows=(_row(delta=math.nan),)),
    ):
        with pytest.raises(ValueError):  # noqa: PT011 - messages pinned above
            build()


# ----------------------------------------------------------------------
# The population: a rule added to a reader must reach its constructor
# ----------------------------------------------------------------------


def _function(name: str, cls: str) -> ast.FunctionDef:
    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))
    scope = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls)
    return next(n for n in ast.walk(scope) if isinstance(n, ast.FunctionDef) and n.name == name)


def _rule_calls(fn: ast.FunctionDef) -> set[str]:
    # `_finite_or_none` predates the `_check*` naming (#89) and is the row
    # scores' rule, so it is counted with them.
    return {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and (node.func.id.startswith(("_check_", "_checked_")) or node.func.id == "_finite_or_none")
    }


@pytest.mark.parametrize("cls", ["DeltaReport", "RowDelta"])
def test_the_delta_writer_enforces_every_rule_the_reader_states(cls: str) -> None:
    reader = _rule_calls(_function("from_json", cls))
    writer = _rule_calls(_function("__post_init__", cls))
    assert reader, "the reader calls no shared rule — the walk is looking at the wrong function"
    assert reader == writer, (
        f"{cls} reader-only rules: {sorted(reader - writer)}; "
        f"writer-only: {sorted(writer - reader)}"
    )


@pytest.mark.parametrize(("cls", "expected"), [("DeltaReport", 3), ("RowDelta", 1)])
def test_the_readers_remaining_inline_rules_are_json_shape_only(cls: str, expected: int) -> None:
    """A new *value* rule written inline in a reader would escape the arm above.
    What remains is about JSON shape, which a typed constructor expresses as its
    `TypeError` shape checks instead."""
    messages = sorted(
        ast.unparse(node.exc)
        for node in ast.walk(_function("from_json", cls))
        if isinstance(node, ast.Raise) and node.exc is not None
    )
    assert len(messages) == expected, messages
    assert all(any(m in s for m in ("JSON object", "JSON array")) for s in messages), messages


def test_diff_runs_checks_its_threshold_through_the_same_definition() -> None:
    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "diff_runs")
    assert "_checked_threshold_drop" in _rule_calls(fn)
