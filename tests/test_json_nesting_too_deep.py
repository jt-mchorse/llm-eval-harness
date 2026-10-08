"""Lock tests for #333: JSON nested too deep to decode is bad input, not a crash.

`json.loads` raises `RecursionError` on deep enough nesting -- about 100,000
levels of ``[`` on 3.11/3.12, which CI and `eval.yml` run. Every reader caught
`JSONDecodeError` only, so that input escaped as a traceback at exit 1: the code
`diff-json` uses for "a row regressed" and `validate` for "findings".
`eval.yml` only fails on ``rc > 1``, so a corrupt run JSON took the regression
path (sibling of rag-production-kit#299).

The fix routes every reader through `io_utils.loads_json`, which re-raises the
`RecursionError` as a `JSONDecodeError`. The last test pins that no module in
the package calls `json.loads` directly, so the next reader can't miss it.
"""

from __future__ import annotations

import ast
import io
import json
from pathlib import Path

import pytest

from eval_harness import comment
from eval_harness.calibration import CalibrationLoadError, load_calibration
from eval_harness.cli import main
from eval_harness.dataset import DatasetLoadError, load_jsonl
from eval_harness.io_utils import loads_json
from eval_harness.runner import load_run_result_from_json

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"

# 1,000,000 levels: enough on every interpreter measured (3.11 and 3.12 fail
# at 100,000; 3.14 parses 100,000 and fails at 1,000,000). The precondition
# test below proves it on whichever interpreter runs the suite, so a host
# where this nesting decodes fails loudly instead of letting every arm pass
# against code that was never exercised.
DEPTH = 1_000_000
DEEP = "[" * DEPTH + "]" * DEPTH


def test_precondition_the_input_really_overflows_json_loads() -> None:
    with pytest.raises(RecursionError):
        json.loads(DEEP)


def test_loads_json_raises_a_decode_error_naming_the_cause() -> None:
    with pytest.raises(json.JSONDecodeError, match="nesting too deep to decode"):
        loads_json(DEEP)


def test_loads_json_is_json_loads_on_ordinary_input() -> None:
    doc = '{"a": [1, 2.5, null, true, "x"], "b": {"c": NaN}}'
    got = loads_json(doc)
    want = json.loads(doc)
    assert got["a"] == want["a"]
    assert got["b"]["c"] != got["b"]["c"]  # NaN round-trips as json.loads gives it


def test_loads_json_keeps_the_ordinary_decode_error() -> None:
    with pytest.raises(json.JSONDecodeError, match="Expecting property name"):
        loads_json("{not json")


# --- the CLI: exit 2 / a parse finding, never a traceback at exit 1 ----------


@pytest.fixture
def deep_file(tmp_path: Path) -> Path:
    p = tmp_path / "deep.json"
    p.write_text(DEEP, encoding="utf-8")
    return p


def test_diff_json_exits_two_on_a_deep_current(deep_file: Path, tmp_path: Path, capsys) -> None:
    rc = main(
        [
            "diff-json",
            "--current",
            str(deep_file),
            "--baseline",
            str(FIXTURES / "demo_baseline.json"),
            "--format",
            "json",
            "--out",
            str(tmp_path / "d.json"),
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::invalid run JSON" in err
    assert "nesting too deep" in err
    assert not (tmp_path / "d.json").exists()


def test_diff_json_exits_two_on_a_deep_value_inside_a_valid_run(tmp_path: Path, capsys) -> None:
    payload = json.loads((FIXTURES / "demo_current.json").read_text(encoding="utf-8"))
    text = json.dumps(payload)
    # The same nesting as an extra key of an otherwise valid run JSON.
    cur = tmp_path / "cur.json"
    cur.write_text(text[:-1] + ', "extra": ' + DEEP + "}", encoding="utf-8")
    rc = main(
        ["diff-json", "--current", str(cur), "--baseline", str(FIXTURES / "demo_baseline.json")]
    )
    assert rc == 2
    assert "::error::invalid run JSON" in capsys.readouterr().err


def test_comment_exits_two_on_a_deep_delta(deep_file: Path, capsys) -> None:
    rc = main(
        ["comment", "--repo", "a/b", "--pr", "1", "--delta-json", str(deep_file), "--dry-run"]
    )
    assert rc == 2
    assert "::error::invalid delta JSON" in capsys.readouterr().err


@pytest.mark.parametrize("calibration", [False, True], ids=["dataset", "calibration"])
def test_validate_reports_a_parse_finding_and_keeps_going(
    tmp_path: Path, capsys, calibration: bool
) -> None:
    p = tmp_path / "rows.jsonl"
    p.write_text(DEEP + "\n{not json\n", encoding="utf-8")
    argv = ["validate", str(p)]
    if calibration:
        argv.insert(1, "--calibration")
    rc = main(argv)
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert rc == 1  # findings, reported -- not an escaped exception
    assert "line 1 [parse]: invalid JSON: nesting too deep to decode" in out
    # The collecting pass reached the row after the deep one.
    assert "line 2 [parse]" in out


def test_drift_exits_two_on_a_deep_golden_row(tmp_path: Path, capsys) -> None:
    golden = tmp_path / "golden.jsonl"
    golden.write_text(DEEP + "\n", encoding="utf-8")
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
    assert "nesting too deep" in capsys.readouterr().err
    assert not out.exists()


# --- the strict loaders and the GitHub response reader ------------------------


def test_strict_loaders_raise_their_own_errors(tmp_path: Path, deep_file: Path) -> None:
    rows = tmp_path / "rows.jsonl"
    rows.write_text(DEEP + "\n", encoding="utf-8")
    with pytest.raises(DatasetLoadError, match="nesting too deep"):
        load_jsonl(rows)
    with pytest.raises(CalibrationLoadError, match="nesting too deep"):
        load_calibration(rows)
    with pytest.raises(json.JSONDecodeError):
        load_run_result_from_json(deep_file)


class _Resp(io.BytesIO):
    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def test_a_deep_github_response_is_the_not_json_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        comment.request, "urlopen", lambda req, timeout: _Resp(DEEP.encode("ascii"))
    )
    with pytest.raises(RuntimeError, match="returned a body that is not JSON"):
        comment._do_request("GET", "https://api.github.com/x", "tok")


# --- the seam: one reader, so the next site cannot miss it --------------------


def test_no_module_calls_json_loads_directly() -> None:
    offenders = []
    for path in sorted((ROOT / "eval_harness").glob("*.py")):
        if path.name == "io_utils.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"loads", "load"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "json"
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], f"use io_utils.loads_json instead: {offenders}"


def test_the_seam_test_sees_a_direct_call() -> None:
    tree = ast.parse("import json\njson.loads(x)\n")
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "loads"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "json"
    ]
    assert len(calls) == 1
