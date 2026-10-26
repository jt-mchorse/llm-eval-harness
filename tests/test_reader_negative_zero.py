"""A stored score of negative zero reads back as zero, with no sign (#412).

#405 (#404) normalised `-0.0` where a judge score is *written*. A file written
before that fix still carries the sign, and the readers kept it. Measured on
`main` (4be0351), a baseline `--out` row stored as `-0.0` printed

    diff-json  | unchanged | `a` | -0.000 | 0.000 | +0.000 |  |

where `diff` over the same runs in SQLite (`REAL` drops the sign) printed
`0.000`. A delta JSON carrying `-0.0` printed `-0.000` in all three score cells
and in `mean Δ` on the sticky-comment path, and its `threshold_drop: -0.0`
printed ``threshold drop: `-0.000` ``. A calibration row with
`human_score: -0.0` printed `-0.00` in the per-row table. `-0.0 == 0.0`, so the
sign is checked with `math.copysign`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from eval_harness.calibration import CalibrationRow, load_calibration
from eval_harness.cli import main
from eval_harness.runner import DeltaReport, RowDelta, load_run_result_from_json


def _positive(x: float) -> bool:
    return math.copysign(1.0, x) == 1.0


def _run_json(path: Path, run_id: str, scores: dict[str, float], mean: float) -> Path:
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "started_at": "2026-10-20T00:00:00Z",
                "suite": "s",
                "mean_score": mean,
                "n_rows": len(scores),
                "rows": [{"example_id": k, "score": v, "reasoning": ""} for k, v in scores.items()],
            }
        ),
        encoding="utf-8",
    )
    return path


# ----------------------------------------------------------------------
# run JSON (`load_run_result_from_json`)
# ----------------------------------------------------------------------


def test_a_run_json_row_score_and_mean_of_negative_zero_read_back_unsigned(
    tmp_path: Path,
) -> None:
    run = load_run_result_from_json(_run_json(tmp_path / "r.json", "r1", {"a": -0.0}, -0.0))
    assert _positive(run.rows["a"][0])
    assert _positive(run.mean_score)


def test_a_run_json_reader_leaves_other_scores_alone(tmp_path: Path) -> None:
    # Control: only the sign of zero moves.
    run = load_run_result_from_json(
        _run_json(tmp_path / "r.json", "r1", {"a": 0.0, "b": 0.25, "c": 1.0}, 0.4166)
    )
    assert run.rows["a"][0] == 0.0
    assert _positive(run.rows["a"][0])
    assert run.rows["b"][0] == 0.25
    assert run.rows["c"][0] == 1.0
    assert run.mean_score == 0.4166


@pytest.mark.parametrize("fmt", ["markdown", "ascii", "json"])
def test_diff_json_on_an_old_negative_zero_baseline_prints_no_sign(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fmt: str
) -> None:
    base = _run_json(tmp_path / "base.json", "base1", {"a": -0.0}, -0.0)
    cur = _run_json(tmp_path / "cur.json", "cur1", {"a": 0.0}, 0.0)
    assert main(["diff-json", "--baseline", str(base), "--current", str(cur), "--format", fmt]) == 0
    assert "-0.0" not in capsys.readouterr().out
    # And the other way round, where `0.0 - (-0.0)` is not the only arithmetic.
    assert main(["diff-json", "--baseline", str(cur), "--current", str(base), "--format", fmt]) == 0
    assert "-0.0" not in capsys.readouterr().out


def _stub(scores: list[str]) -> type:
    it = iter(scores)

    class _Judge:
        def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
            self.model = model or "fake-judge"

        def complete(self, system: str, user: str) -> str:
            return f"SCORE: {next(it)}\nREASONING: stub\n"

    return _Judge


@pytest.mark.parametrize("fmt", ["markdown", "ascii", "json"])
def test_diff_and_diff_json_agree_on_an_old_style_negative_zero_out_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fmt: str
) -> None:
    # Two real runs into one SQLite db, then the baseline `--out` file is made
    # to look like one written before #405: its zero row carries the sign. The
    # db cannot (`REAL` drops it), so `diff` is the reference.
    dataset = tmp_path / "d.jsonl"
    dataset.write_text(
        "".join(
            json.dumps(
                {
                    "id": i,
                    "input": f"question {i}?",
                    "expected_outputs": [{"kind": "exact", "value": "a"}],
                    "provenance": {"source": "t"},
                    "dataset_version": "v1",
                }
            )
            + "\n"
            for i in ("q1", "q2")
        ),
        encoding="utf-8",
    )
    db = tmp_path / "runs.db"
    outs = {}
    for name, scores in (("base", ["0.5", "0"]), ("cur", ["0.5", "0"])):
        out = tmp_path / f"{name}.json"
        argv = ["run", "--suite", "s", "--dataset", str(dataset), "--db", str(db)]
        with patch("eval_harness.cli.AnthropicBackend", _stub(scores)):
            assert main([*argv, "--out", str(out)]) in (0, 1)
        outs[name] = out
    payload: dict[str, Any] = json.loads(outs["base"].read_text(encoding="utf-8"))
    for row in payload["rows"]:
        if row["score"] == 0.0:
            row["score"] = -0.0
    outs["base"].write_text(json.dumps(payload), encoding="utf-8")
    assert '"score": -0.0' in outs["base"].read_text(encoding="utf-8")
    capsys.readouterr()
    base_id = payload["run_id"]
    cur_id = json.loads(outs["cur"].read_text(encoding="utf-8"))["run_id"]

    main(["diff", "--db", str(db), "--current", cur_id, "--baseline", base_id, "--format", fmt])
    from_db = capsys.readouterr().out
    main(
        ["diff-json", "--current", str(outs["cur"]), "--baseline", str(outs["base"])]
        + ["--format", fmt]
    )
    from_json = capsys.readouterr().out
    # `diff --format ascii` ends with one more newline than `diff-json`.
    assert from_db.rstrip("\n") == from_json.rstrip("\n")
    assert "-0.0" not in from_json


def test_a_negative_zero_threshold_drop_flag_prints_no_sign(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _run_json(tmp_path / "base.json", "base1", {"a": 0.5}, 0.5)
    cur = _run_json(tmp_path / "cur.json", "cur1", {"a": 0.5}, 0.5)
    argv = ["diff-json", "--baseline", str(base), "--current", str(cur), "--format", "ascii"]
    assert main([*argv, "--threshold-drop", "-0"]) == 0
    assert "threshold_drop=0.000" in capsys.readouterr().out


# ----------------------------------------------------------------------
# delta JSON (`DeltaReport.from_json`, the sticky-comment path)
# ----------------------------------------------------------------------


def _delta(**overrides: Any) -> dict[str, Any]:
    row = {
        "example_id": "a",
        "baseline_score": -0.0,
        "current_score": -0.0,
        "delta": -0.0,
        "status": "unchanged",
        "flagged": False,
    }
    payload: dict[str, Any] = {
        "current_run_id": "cur1",
        "baseline_run_id": "base1",
        "suite": "s",
        "threshold_drop": 0.1,
        "rows": [row],
        "summary": {
            "mean_delta": -0.0,
            "mean_score_baseline": -0.0,
            "mean_score_current": -0.0,
            "n_flagged": 0,
            "n_regressed": 0,
            "n_improved": 0,
            "n_new": 0,
            "n_removed": 0,
            "n_unchanged": 1,
        },
    }
    payload.update(overrides)
    return payload


def test_a_delta_json_reads_its_negative_zero_scores_back_unsigned() -> None:
    report = DeltaReport.from_json(_delta(threshold_drop=-0.0))
    row = report.rows[0]
    assert row.baseline_score is not None
    assert _positive(row.baseline_score)
    assert row.current_score is not None
    assert _positive(row.current_score)
    assert row.delta is not None
    assert _positive(row.delta)
    for key in ("mean_delta", "mean_score_baseline", "mean_score_current"):
        assert _positive(report.summary[key]), key
    assert _positive(report.threshold_drop)


def test_a_hand_built_delta_report_is_held_to_the_same_rule() -> None:
    # `from_json` builds through `__post_init__`; a caller building one directly
    # gets the same normalisation.
    row = RowDelta("a", -0.0, -0.0, -0.0, "unchanged", False)
    assert row.baseline_score is not None
    assert _positive(row.baseline_score)
    assert row.delta is not None
    assert _positive(row.delta)
    report = DeltaReport("c", "b", "s", -0.0, (row,), {"mean_delta": -0.0, "n_unchanged": 1})
    assert _positive(report.summary["mean_delta"])
    assert _positive(report.threshold_drop)


def test_the_comment_renders_an_old_negative_zero_delta_json_without_a_sign(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps(_delta(threshold_drop=-0.0)), encoding="utf-8")
    argv = ["comment", "--repo", "o/r", "--pr", "1", "--delta-json", str(delta), "--dry-run"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "| unchanged | `a` | 0.000 | 0.000 | +0.000 |" in out
    assert "mean Δ **+0.000**" in out
    assert "threshold drop: `0.000`" in out
    assert "-0.0" not in out


def test_a_delta_json_reader_leaves_other_values_alone() -> None:
    # Control: `None` cells, non-zero scores and counts are untouched.
    payload = _delta()
    payload["rows"][0].update(baseline_score=0.25, current_score=None, delta=None, status="removed")
    payload["summary"].update(mean_delta=-0.125, mean_score_baseline=0.5, n_unchanged=0)
    payload["summary"]["n_removed"] = 1
    report = DeltaReport.from_json(payload)
    row = report.rows[0]
    assert (row.baseline_score, row.current_score, row.delta) == (0.25, None, None)
    assert report.summary["mean_delta"] == -0.125
    assert report.summary["mean_score_baseline"] == 0.5
    assert report.summary["n_removed"] == 1


def test_a_bool_mean_delta_is_still_refused_not_normalised() -> None:
    # Control: `False == 0.0`, so a normalisation run before the check would
    # turn a JSON `false` into a valid `0.0`. The check still sees the bool.
    payload = _delta()
    payload["summary"]["mean_delta"] = False
    with pytest.raises(ValueError, match="mean_delta"):
        DeltaReport.from_json(payload)


# ----------------------------------------------------------------------
# calibration (`human_score`)
# ----------------------------------------------------------------------


def _cal_line(row_id: str, human: float, prompt: str = "p") -> str:
    return (
        json.dumps(
            {
                "id": row_id,
                "prompt": prompt,
                "response": "a",
                "rubric": "faithful?",
                "human_score": human,
                "provenance": {"src": "t"},
            }
        )
        + "\n"
    )


def test_a_calibration_row_with_negative_zero_human_score_loads_unsigned(tmp_path: Path) -> None:
    cal = tmp_path / "cal.jsonl"
    cal.write_text(_cal_line("r0", -0.0) + _cal_line("r1", 0.75), encoding="utf-8")
    rows = load_calibration(cal)
    assert _positive(rows[0].human_score)
    # Control: a non-zero score is unchanged.
    assert rows[1].human_score == 0.75


def test_a_hand_built_calibration_row_is_normalised_too() -> None:
    row = CalibrationRow("r0", "p", "a", "faithful?", -0.0, {})
    assert _positive(row.human_score)


def test_the_calibrate_row_table_prints_no_negative_zero_human_score(tmp_path: Path) -> None:
    class _Stub:
        model = "stub-judge"

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def complete(self, system: str, user: str) -> str:
            return f"SCORE: {user.split('JUDGE=')[1].split()[0]}\nREASONING: stub\n"

    cells = [(1.0, "1"), (1.0, "0.9"), (-0.0, "0"), (0.0, "0.1")]
    cal = tmp_path / "cal.jsonl"
    cal.write_text(
        "".join(_cal_line(f"r{i:03d}", h, f"q{i} JUDGE={j}") for i, (h, j) in enumerate(cells)),
        encoding="utf-8",
    )
    report = tmp_path / "report.md"
    with patch("eval_harness.cli.AnthropicBackend", _Stub):
        main(["calibrate", "--calibration", str(cal), "--report", str(report)])
    text = report.read_text(encoding="utf-8")
    assert "| `r002` | 0.00 | 0.00 | 0.00 |" in text
    assert "-0.0" not in text
