"""Lock tests for #421: a key repeated inside one JSON object is a malformed row.

Bare `json.loads` resolves a repeated key last-one-wins, and `loads_json` -- the
one JSON reader every loader goes through -- passed no `object_pairs_hook`. A
calibration row with ``"human_score"`` written twice loaded the SECOND label (so
kappa moved with it), a dataset row with ``"id"`` written twice loaded the
second id, and `validate` / `validate --calibration` reported both files clean.

The duplicate is now refused as a `JSONDecodeError`, so it reaches every
reader's existing bad-JSON arm: a ``parse`` finding in the collecting
validators, the loader's own error in the strict loaders, exit 2 in the CLI.
The controls pin what must still decode: the same key at different nesting
levels, the same key in sibling objects, and every committed fixture.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.calibration import CalibrationLoadError, load_calibration
from eval_harness.cli import main
from eval_harness.dataset import DatasetLoadError, load_jsonl
from eval_harness.drift import _load_inputs_jsonl
from eval_harness.io_utils import loads_json
from eval_harness.runner import load_run_result_from_json

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"


def _dataset_row_with_dup_id() -> str:
    """The first sample row with a second ``id`` appended (the hunt's repro)."""
    row = (FIXTURES / "sample_factuality_v1.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert row.endswith("}")
    return row[:-1] + ',"id":"qa_999","input":"What is 2+2?"}'


def _calibration_row_with_dup_score() -> str:
    """The first calibration row (human_score 1.0) with ``"human_score": 0.0`` appended."""
    row = (FIXTURES / "calibration.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert row.startswith('{"human_score": 1.0,')
    assert row.endswith("}")
    return row[:-1] + ', "human_score": 0.0}'


def test_precondition_bare_json_loads_keeps_the_last_value() -> None:
    assert json.loads(_calibration_row_with_dup_score())["human_score"] == 0.0


# --- loads_json -------------------------------------------------------------


def test_loads_json_refuses_a_repeated_key_naming_it() -> None:
    with pytest.raises(json.JSONDecodeError, match="duplicate key 'a'"):
        loads_json('{"a": 1, "b": 2, "a": 3}')


def test_loads_json_refuses_a_repeated_key_in_a_nested_object() -> None:
    with pytest.raises(json.JSONDecodeError, match="duplicate key 'source'"):
        loads_json('{"provenance": {"source": "x", "source": "y"}}')


def test_loads_json_refuses_a_repeated_key_inside_a_list() -> None:
    with pytest.raises(json.JSONDecodeError, match="duplicate key 'k'"):
        loads_json('[{"k": 1}, {"k": 2, "k": 3}]')


def test_control_same_key_at_different_levels_still_decodes() -> None:
    assert loads_json('{"a": {"a": {"a": 1}}, "b": [{"a": 2}]}') == {
        "a": {"a": {"a": 1}},
        "b": [{"a": 2}],
    }


def test_control_same_key_in_sibling_objects_still_decodes() -> None:
    assert loads_json('[{"k": 1}, {"k": 2}]') == [{"k": 1}, {"k": 2}]


def test_control_every_committed_json_document_still_decodes() -> None:
    files = subprocess.run(
        ["git", "ls-files", "*.json", "*.jsonl"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    checked = 0
    for name in files:
        text = (ROOT / name).read_text(encoding="utf-8")
        docs = [text] if name.endswith(".json") else [ln for ln in text.splitlines() if ln.strip()]
        for doc in docs:
            try:
                expected = json.loads(doc)
            except ValueError:
                continue  # malformed on purpose (fixtures/broken.jsonl)
            assert loads_json(doc) == expected, name
            checked += 1
    assert checked > 50  # the fixtures were actually walked


# --- validate: a parse finding, and the walk goes on --------------------------


@pytest.mark.parametrize(
    ("calibration", "key"), [(False, "id"), (True, "human_score")], ids=["dataset", "calibration"]
)
def test_validate_reports_a_parse_finding(
    tmp_path: Path, capsys, calibration: bool, key: str
) -> None:
    p = tmp_path / "rows.jsonl"
    row = _calibration_row_with_dup_score() if calibration else _dataset_row_with_dup_id()
    p.write_text(row + "\n{not json\n", encoding="utf-8")
    argv = ["validate", str(p)]
    if calibration:
        argv.insert(1, "--calibration")
    rc = main(argv)
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert rc == 1
    assert f"line 1 [parse]: invalid JSON: duplicate key '{key}'" in out
    assert "line 2 [parse]" in out


# --- the strict loaders -------------------------------------------------------


def test_load_jsonl_refuses_a_repeated_key(tmp_path: Path) -> None:
    p = tmp_path / "rows.jsonl"
    p.write_text(_dataset_row_with_dup_id() + "\n", encoding="utf-8")
    with pytest.raises(DatasetLoadError, match="duplicate key 'id'"):
        load_jsonl(p)


def test_load_calibration_refuses_a_repeated_key(tmp_path: Path) -> None:
    p = tmp_path / "cal.jsonl"
    p.write_text(_calibration_row_with_dup_score() + "\n", encoding="utf-8")
    with pytest.raises(CalibrationLoadError, match="duplicate key 'human_score'"):
        load_calibration(p)


def test_drift_reader_refuses_a_repeated_key(tmp_path: Path) -> None:
    p = tmp_path / "inputs.jsonl"
    p.write_text('{"input": "a", "input": "b"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate key 'input'"):
        _load_inputs_jsonl(p)


def test_run_json_reader_refuses_a_repeated_key(tmp_path: Path) -> None:
    text = (FIXTURES / "demo_current.json").read_text(encoding="utf-8")
    assert text.rstrip().endswith("}")
    run = tmp_path / "run.json"
    run.write_text(text.rstrip()[:-1] + ', "judge_kappa": 0.1}', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError, match="duplicate key 'judge_kappa'"):
        load_run_result_from_json(run)


# --- the CLI: exit 2, the bad-input code ---------------------------------------


def test_drift_exits_two_on_a_repeated_key(tmp_path: Path, capsys) -> None:
    golden = tmp_path / "golden.jsonl"
    golden.write_text('{"input": "a", "input": "b"}\n', encoding="utf-8")
    out = tmp_path / "x.html"
    rc = main(
        [
            "drift",
            "--golden",
            str(golden),
            "--candidate",
            str(FIXTURES / "drift" / "shifted.jsonl"),
            "--output",
            str(out),
        ]
    )
    assert rc == 2
    assert "duplicate key 'input'" in capsys.readouterr().err
    assert not out.exists()


class _JudgeMustNotRun:
    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake-judge"

    def complete(self, system: str, user: str) -> str:
        raise AssertionError("judge called for a dataset with a repeated key")


def test_run_exits_two_before_judging(tmp_path: Path, capsys) -> None:
    dataset = tmp_path / "rows.jsonl"
    dataset.write_text(_dataset_row_with_dup_id() + "\n", encoding="utf-8")
    db = tmp_path / "runs.db"
    with patch("eval_harness.cli.AnthropicBackend", _JudgeMustNotRun):
        rc = main(["run", "--suite", "s", "--dataset", str(dataset), "--db", str(db), "--no-diff"])
    assert rc == 2
    assert "invalid JSON: duplicate key 'id'" in capsys.readouterr().err
    assert not db.exists()
