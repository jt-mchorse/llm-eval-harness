"""The run record's writer enforces every rule its reader states (#264, D-032).

`load_run_result_from_json` accumulated its rules one issue at a time (#83,
#116, #150, #185, #186, #190). The write side had none of them: `RunResult` had
no `__post_init__`, and `run_suite` copied `RunSpec.judge_kappa` into both
stores unchecked. Measured at `2c946ce`:

    RunSpec(judge_kappa=nan)   JSON: bare NaN  -> reader: ValueError   SQLite: NULL
    RunSpec(judge_kappa=True)  JSON: true      -> reader: ValueError   SQLite: 1.0
    RunSpec(judge_kappa=1.5)   JSON: 1.5       -> reader: accepted     SQLite: 1.5

The first two are one run with two stores giving two answers. The third is a κ
outside the `[-1, 1]` it is defined on, accepted by both paths, while the
calibration report refuses it (#204).
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from typing import Any

import pytest

from eval_harness.judge import JudgeScore
from eval_harness.runner import (
    RowScore,
    RunResult,
    RunSpec,
    load_run_result_from_json,
    render_run_json,
    run_suite,
)
from eval_harness.runs import connect, read_run

_RUNNER = Path(__file__).resolve().parent.parent / "eval_harness" / "runner.py"


class _Judge:
    def score(self, prompt: str, response: str, rubric: str | None = None) -> JudgeScore:
        return JudgeScore(score=0.5, reasoning="r", raw="")


class _Answers:
    def answer(self, ex: Any) -> str:
        return "x"


def _dataset(tmp_path: Path) -> Path:
    path = tmp_path / "ds.jsonl"
    rows = [
        {
            "id": f"ex{i}",
            "input": "q",
            "expected_outputs": [{"kind": "exact", "value": "x"}],
            "dataset_version": "v1",
            "provenance": {},
        }
        for i in range(2)
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _spec(tmp_path: Path, judge_kappa: Any) -> RunSpec:
    return RunSpec(
        suite="s",
        dataset_path=_dataset(tmp_path),
        judge=_Judge(),
        answer_source=_Answers(),
        judge_kappa=judge_kappa,
    )


# ----------------------------------------------------------------------
# The issue's table, through the real pipeline
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kappa", "fragment"),
    [
        (float("nan"), "non-finite judge_kappa"),
        (float("inf"), "non-finite judge_kappa"),
        (True, "judge_kappa must be a number; got bool"),
        (1.5, r"judge_kappa must be in \[-1, 1\]"),
        (-1.0000001, r"judge_kappa must be in \[-1, 1\]"),
        ([0.7], "judge_kappa must be a number; got list"),
    ],
    ids=["nan", "inf", "bool", "above-range", "below-range", "list"],
)
def test_a_bad_kappa_is_refused_before_any_row_is_scored(
    tmp_path: Path, kappa: Any, fragment: str
) -> None:
    """At `RunSpec` construction, so nothing reaches either store — before
    #264 the NaN row wrote a `NULL` to SQLite and an unreadable JSON."""
    with pytest.raises(ValueError, match=fragment):
        _spec(tmp_path, kappa)
    assert not (tmp_path / "runs.db").exists()


@pytest.mark.parametrize("kappa", [None, -1.0, 0.0, 0.72, 1.0], ids=str)
def test_every_legal_kappa_reads_back_the_same_from_both_stores(
    tmp_path: Path, kappa: float | None
) -> None:
    """The positive control, end to end: `run_suite` -> `render_run_json` ->
    `load_run_result_from_json`, and `run_suite` -> SQLite -> `read_run`, agree
    with each other and with what was configured."""
    db = tmp_path / "runs.db"
    result = run_suite(_spec(tmp_path, kappa), db_path=db, run_id="r1")
    out = tmp_path / "run.json"
    out.write_text(render_run_json(result), encoding="utf-8")
    from_json = load_run_result_from_json(out)
    with connect(db) as conn:
        from_db = read_run(conn, "r1")
    assert from_json.judge_kappa == from_db.judge_kappa == kappa
    assert from_json.rows == from_db.rows


# ----------------------------------------------------------------------
# A hand-built RunResult: every rule the reader states
# ----------------------------------------------------------------------


def _result(**overrides: Any) -> RunResult:
    kwargs: dict[str, Any] = {
        "run_id": "r1",
        "started_at": "2026-01-01T00:00:00Z",
        "suite": "s",
        "dataset_version": "v1",
        "judge_model": None,
        "judge_kappa": 0.7,
        "mean_score": 0.5,
        "n_rows": 2,
        "git_sha": None,
        "rows": (RowScore("a", 0.4, "x"), RowScore("b", 0.6, "y")),
    }
    kwargs.update(overrides)
    return RunResult(**kwargs)


def _payload(**overrides: Any) -> dict[str, Any]:
    payload = _result().to_json()
    payload.update(overrides)
    return payload


# (id, constructor overrides, the same corruption as a payload override)
_RULES: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    ("run-id-empty", {"run_id": ""}, {"run_id": ""}),
    ("run-id-none", {"run_id": None}, {"run_id": None}),
    ("mean-nan", {"mean_score": math.nan}, {"mean_score": math.nan}),
    ("mean-bool", {"mean_score": True}, {"mean_score": True}),
    ("kappa-nan", {"judge_kappa": math.nan}, {"judge_kappa": math.nan}),
    ("kappa-range", {"judge_kappa": 1.5}, {"judge_kappa": 1.5}),
    ("n-rows-mismatch", {"n_rows": 3}, {"n_rows": 3}),
    ("n-rows-fraction", {"n_rows": 2.5}, {"n_rows": 2.5}),
    (
        "duplicate-id",
        {"rows": (RowScore("a", 0.4, "x"), RowScore("a", 0.6, "y"))},
        {
            "rows": [
                {"example_id": "a", "score": 0.4, "reasoning": "x"},
                {"example_id": "a", "score": 0.6, "reasoning": "y"},
            ]
        },
    ),
    (
        "empty-id",
        {"rows": (RowScore("", 0.4, "x"), RowScore("b", 0.6, "y"))},
        {
            "rows": [
                {"example_id": "", "score": 0.4, "reasoning": "x"},
                {"example_id": "b", "score": 0.6, "reasoning": "y"},
            ]
        },
    ),
    (
        "row-score-nan",
        {"rows": (RowScore("a", math.nan, "x"), RowScore("b", 0.6, "y"))},
        {
            "rows": [
                {"example_id": "a", "score": math.nan, "reasoning": "x"},
                {"example_id": "b", "score": 0.6, "reasoning": "y"},
            ]
        },
    ),
]


@pytest.mark.parametrize(
    ("overrides", "payload_overrides"),
    [(o, p) for _, o, p in _RULES],
    ids=[i for i, _, _ in _RULES],
)
def test_the_writer_refuses_what_the_reader_refuses_with_the_same_words(
    tmp_path: Path, overrides: dict[str, Any], payload_overrides: dict[str, Any]
) -> None:
    """Identical messages are the observable form of "one definition": a second
    copy of a rule could agree on *whether* to refuse and still drift in *why*."""
    path = tmp_path / "run.json"
    path.write_text(json.dumps(_payload(**payload_overrides)), encoding="utf-8")
    with pytest.raises(ValueError) as read_error:  # noqa: PT011 - compared below
        load_run_result_from_json(path)
    with pytest.raises(ValueError) as write_error:  # noqa: PT011 - compared below
        _result(**overrides)
    assert str(write_error.value) == str(read_error.value)


def test_a_valid_record_still_round_trips(tmp_path: Path) -> None:
    result = _result()
    path = tmp_path / "run.json"
    path.write_text(render_run_json(result), encoding="utf-8")
    stored = load_run_result_from_json(path)
    assert stored.rows == {r.example_id: (r.score, r.reasoning) for r in result.rows}
    assert (stored.n_rows, stored.mean_score, stored.judge_kappa) == (2, 0.5, 0.7)


@pytest.mark.parametrize(
    ("rows", "fragment"),
    [
        ("ab", "rows must be a tuple of RowScore; got str"),
        ([{"example_id": "a"}], "rows[0] must be a RowScore; got dict"),
    ],
    ids=["str", "dict-element"],
)
def test_a_wrong_rows_shape_is_refused_before_the_loop(rows: Any, fragment: str) -> None:
    with pytest.raises(TypeError) as excinfo:
        _result(rows=rows, n_rows=len(rows))
    assert str(excinfo.value) == fragment


def test_rows_are_owned_once_validated() -> None:
    """Validated, so kept (the D-019 pair): a caller's list would otherwise
    let the duplicate-id check above become a snapshot."""
    rows = [RowScore("a", 0.4, "x"), RowScore("b", 0.6, "y")]
    result = _result(rows=rows)
    rows.append(RowScore("a", 0.9, "dup"))
    assert type(result.rows) is tuple
    assert [r.example_id for r in result.rows] == ["a", "b"]


# ----------------------------------------------------------------------
# The population: a rule added to the reader must reach the writer
# ----------------------------------------------------------------------


def _function(name: str, cls: str | None = None) -> ast.FunctionDef:
    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))
    scope: ast.AST = tree
    if cls is not None:
        scope = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls)
    return next(n for n in ast.walk(scope) if isinstance(n, ast.FunctionDef) and n.name == name)


def _rule_calls(fn: ast.FunctionDef) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id.startswith(("_check_", "_checked_"))
    }


def test_the_writer_enforces_every_rule_the_reader_states() -> None:
    reader = _rule_calls(_function("load_run_result_from_json"))
    writer = _rule_calls(_function("__post_init__", "RunResult"))
    assert reader, "the reader calls no shared rule — the walk is looking at the wrong function"
    assert reader == writer, (
        f"reader-only rules: {sorted(reader - writer)}; writer-only: {sorted(writer - reader)}"
    )


def test_the_readers_remaining_inline_rules_are_json_shape_only() -> None:
    """A new *value* rule written inline in the reader would escape the arm
    above. The four that remain are about JSON shape or presence, which a typed
    constructor expresses as the `TypeError` shape checks instead."""
    reader = _function("load_run_result_from_json")
    messages = sorted(
        ast.unparse(node.exc)
        for node in ast.walk(reader)
        if isinstance(node, ast.Raise) and node.exc is not None
    )
    assert len(messages) == 4, messages
    assert all(
        any(marker in m for marker in ("JSON object", "JSON array", "required field"))
        for m in messages
    ), messages


def test_run_spec_checks_kappa_through_the_same_definition() -> None:
    assert _rule_calls(_function("__post_init__", "RunSpec")) == {"_checked_judge_kappa"}
