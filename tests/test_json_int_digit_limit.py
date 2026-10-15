"""Lock tests for #365: a JSON integer over the digit limit is bad input, not a crash.

On 3.11+ `json.loads` refuses an integer literal longer than
`sys.get_int_max_str_digits()` (4300 by default on 3.11/3.12, which CI runs)
with a plain `ValueError` -- not a `JSONDecodeError`. `loads_json` translated
only the `RecursionError` half of that set (#333), so `validate` and
`validate --calibration` exited 1 (the "findings" code) and `run` exited 1 (the
"a row regressed" code) with a traceback, and a GitHub API body escaped
`_do_request`'s not-JSON arm.

The literal is built from the live limit, so the suite exercises whatever limit
the interpreter running it has; the precondition test fails loudly if that
limit is off and nothing below would be exercised.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness import comment
from eval_harness.calibration import CalibrationLoadError, load_calibration
from eval_harness.cli import main
from eval_harness.dataset import DatasetLoadError, load_jsonl
from eval_harness.io_utils import loads_json
from eval_harness.runner import load_run_result_from_json

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"

LIMIT = sys.get_int_max_str_digits()
BIG = "1" + "0" * LIMIT  # LIMIT + 1 digits


def _dataset_row(extra: str) -> str:
    """The first sample row, with `"n": <extra>` added to its provenance."""
    row = (FIXTURES / "sample_factuality_v1.jsonl").read_text(encoding="utf-8").splitlines()[0]
    marker = '"provenance":{'
    assert marker in row
    return row.replace(marker, marker + '"n":' + extra + ",", 1)


def _calibration_row(human_score: str) -> str:
    obj = json.loads((FIXTURES / "calibration.jsonl").read_text(encoding="utf-8").splitlines()[0])
    obj["human_score"] = 0.5
    text = json.dumps(obj)
    assert '"human_score": 0.5' in text
    return text.replace('"human_score": 0.5', '"human_score": ' + human_score, 1)


def test_precondition_json_loads_refuses_the_literal_with_a_bare_value_error() -> None:
    assert LIMIT > 0, "int/str digit limit is disabled; nothing in this file is exercised"
    with pytest.raises(ValueError, match="integer string conversion") as info:
        json.loads(BIG)
    assert not isinstance(info.value, json.JSONDecodeError)


def test_loads_json_raises_a_decode_error_naming_the_limit() -> None:
    with pytest.raises(json.JSONDecodeError, match=f"longer than the {LIMIT}-digit limit"):
        loads_json('{"n": ' + BIG + "}")


def test_loads_json_still_decodes_an_int_at_the_limit() -> None:
    at_limit = "9" * LIMIT
    assert loads_json(at_limit) == int(at_limit)


# --- the collecting validators: a parse finding, and the walk goes on ---------


@pytest.mark.parametrize("calibration", [False, True], ids=["dataset", "calibration"])
def test_validate_reports_a_parse_finding_and_keeps_going(
    tmp_path: Path, capsys, calibration: bool
) -> None:
    p = tmp_path / "rows.jsonl"
    row = _calibration_row(BIG) if calibration else _dataset_row(BIG)
    p.write_text(row + "\n{not json\n", encoding="utf-8")
    argv = ["validate", str(p)]
    if calibration:
        argv.insert(1, "--calibration")
    rc = main(argv)
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert rc == 1  # findings, reported -- not an escaped exception
    assert f"line 1 [parse]: invalid JSON: integer literal longer than the {LIMIT}" in out
    assert "line 2 [parse]" in out


# --- run: exit 2 before the judge is ever asked ------------------------------


class _JudgeMustNotRun:
    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake-judge"

    def complete(self, system: str, user: str) -> str:
        raise AssertionError("judge called for a dataset that does not decode")


def test_run_exits_two_before_judging(tmp_path: Path, capsys) -> None:
    dataset = tmp_path / "rows.jsonl"
    dataset.write_text(_dataset_row(BIG) + "\n", encoding="utf-8")
    db = tmp_path / "runs.db"
    with patch("eval_harness.cli.AnthropicBackend", _JudgeMustNotRun):
        rc = main(["run", "--suite", "s", "--dataset", str(dataset), "--db", str(db), "--no-diff"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert f"invalid JSON: integer literal longer than the {LIMIT}" in err
    assert not db.exists()


# --- the readers that already exited 2 now say which input was bad -----------


def test_diff_json_names_the_run_json(tmp_path: Path, capsys) -> None:
    text = (FIXTURES / "demo_current.json").read_text(encoding="utf-8")
    assert '"judge_kappa": 0.71' in text
    cur = tmp_path / "cur.json"
    cur.write_text(text.replace('"judge_kappa": 0.71', '"judge_kappa": ' + BIG), encoding="utf-8")
    rc = main(
        ["diff-json", "--current", str(cur), "--baseline", str(FIXTURES / "demo_baseline.json")]
    )
    assert rc == 2
    assert "::error::invalid run JSON: integer literal longer than" in capsys.readouterr().err


def test_comment_names_the_delta_json(tmp_path: Path, capsys) -> None:
    delta = tmp_path / "delta.json"
    delta.write_text('{"n": ' + BIG + "}", encoding="utf-8")
    rc = main(["comment", "--repo", "a/b", "--pr", "1", "--delta-json", str(delta), "--dry-run"])
    assert rc == 2
    assert "::error::invalid delta JSON: integer literal longer than" in capsys.readouterr().err


def test_drift_exits_two_on_a_golden_row(tmp_path: Path, capsys) -> None:
    golden = tmp_path / "golden.jsonl"
    golden.write_text('{"input": "hi", "n": ' + BIG + "}\n", encoding="utf-8")
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
    assert "integer literal longer than" in capsys.readouterr().err
    assert not out.exists()


# --- the strict loaders and the GitHub response reader ------------------------


def test_strict_loaders_raise_their_own_errors(tmp_path: Path) -> None:
    rows = tmp_path / "rows.jsonl"
    rows.write_text(_dataset_row(BIG) + "\n", encoding="utf-8")
    with pytest.raises(DatasetLoadError, match="integer literal longer than"):
        load_jsonl(rows)
    cal = tmp_path / "cal.jsonl"
    cal.write_text(_calibration_row(BIG) + "\n", encoding="utf-8")
    with pytest.raises(CalibrationLoadError, match="integer literal longer than"):
        load_calibration(cal)
    run = tmp_path / "run.json"
    run.write_text('{"mean_score": ' + BIG + "}", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_run_result_from_json(run)


class _Resp(io.BytesIO):
    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def test_a_github_body_over_the_limit_is_the_not_json_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = ('[{"id": ' + BIG + ', "body": "x"}]').encode("ascii")
    monkeypatch.setattr(comment.request, "urlopen", lambda req, timeout: _Resp(body))
    with pytest.raises(RuntimeError, match="returned a body that is not JSON"):
        comment._do_request("GET", "https://api.github.com/x", "tok")
