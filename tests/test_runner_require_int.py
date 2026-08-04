"""Lock tests for #190: `_require_int` closes the two gaps a bare
`int(_require_number(...))` left at the run/delta JSON loaders.

`_require_number` (#160/#184) guarantees the value is a type `int()` *accepts*.
Past that point `int()` still had two failure modes the callers relied on being
impossible:

1. **Infinity raises `OverflowError`.** Not a `ValueError` subclass, so it walked
   through `cli`'s `except ValueError` translation and out as a raw traceback at
   exit 1, breaking the documented exit-2 contract. And `json.loads("1e400")` is
   `inf` — a spec-valid JSON number literal, no bare `Infinity` token needed.
   Cross-repo sibling of llm-cost-optimizer#166.
2. **A non-integral float truncates.** `n_rows: 2.7` next to two rows became `2`,
   matched `len(rows)` and loaded clean — the coercion in front of the mismatch
   guard erasing the corruption signal that guard exists to catch.

The CLI tests drive the two real subcommands end-to-end so the exit code and the
absence of a traceback are asserted on the contract surface, not just the helper.
The unchanged-behaviour tests are what keep the fix from being a silent
tightening: an integral float, a numeric string and a bad numeric string all
have to behave exactly as they did before.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from eval_harness import runner
from eval_harness.cli import main

# `1e400` overflows an IEEE-754 double, so `json.loads` yields `inf` for it.
# Spelled as a literal in the payload text (not `float("inf")`) because that is
# the point: this arrives through ordinary, strictly-valid JSON.
INF_LITERAL = "1e400"

_COUNT_FIELDS = (
    "n_flagged",
    "n_regressed",
    "n_improved",
    "n_new",
    "n_removed",
    "n_unchanged",
)


def _run_json(n_rows: str, n_row_objects: int = 1) -> str:
    """A RunResult payload with `n_rows` spliced in as raw JSON text."""
    rows = [{"example_id": f"ex{i}", "score": 0.9, "reasoning": "ok"} for i in range(n_row_objects)]
    return (
        '{"run_id": "a", "started_at": "2026-01-01T00:00:00Z", "suite": "s", '
        f'"mean_score": 0.9, "n_rows": {n_rows}, "rows": {json.dumps(rows)}}}'
    )


def _write_pair(tmp_path: Path, current_text: str) -> tuple[Path, Path]:
    cur = tmp_path / "cur.json"
    cur.write_text(current_text, encoding="utf-8")
    base = tmp_path / "base.json"
    base.write_text(_run_json("1"), encoding="utf-8")
    return cur, base


def _delta_json(summary: dict[str, object]) -> str:
    return json.dumps(
        {
            "current_run_id": "cur12345",
            "baseline_run_id": "base1234",
            "suite": "s",
            "threshold_drop": 0.05,
            "summary": summary,
            "rows": [],
        }
    )


# --- gap 1: infinity escaped as OverflowError -------------------------------


def test_infinite_n_rows_exits_two_not_a_traceback(tmp_path: Path, capsys) -> None:
    cur, base = _write_pair(tmp_path, _run_json(INF_LITERAL))
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "n_rows must be a finite whole number" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("field", _COUNT_FIELDS)
def test_infinite_summary_count_exits_two_not_a_traceback(
    tmp_path: Path, capsys, field: str
) -> None:
    summary_text = _delta_json({f: 0 for f in _COUNT_FIELDS}).replace(
        f'"{field}": 0', f'"{field}": {INF_LITERAL}'
    )
    delta = tmp_path / "d.json"
    delta.write_text(summary_text, encoding="utf-8")
    rc = main(["comment", "--repo", "o/n", "--pr", "1", "--delta-json", str(delta), "--dry-run"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert field in err
    assert "Traceback" not in err


def test_overflow_error_is_not_a_value_error() -> None:
    """Why the guard is needed at all, pinned so the rationale can't rot.

    If a future Python made `int(inf)` raise a `ValueError`, the two guards
    above would be belt-and-braces rather than load-bearing — and this test
    would say so instead of leaving the next reader to re-derive it.
    """
    with pytest.raises(OverflowError) as exc:
        int(float("inf"))
    assert not isinstance(exc.value, ValueError)
    assert json.loads(INF_LITERAL) == float("inf")


# --- gap 2: a non-integral float truncated into agreement -------------------


def test_non_integral_n_rows_is_rejected_not_truncated(tmp_path: Path, capsys) -> None:
    # 2.7 next to two rows: `int(2.7)` == 2 == len(rows), so pre-fix this loaded
    # clean and the mismatch guard never fired on a payload that is corrupt by
    # its own definition.
    cur, base = _write_pair(tmp_path, _run_json("2.7", n_row_objects=2))
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "n_rows must be a whole number" in err
    assert "Traceback" not in err


def test_non_integral_summary_count_is_rejected_not_truncated(tmp_path: Path, capsys) -> None:
    delta = tmp_path / "d.json"
    delta.write_text(
        _delta_json({**{f: 0 for f in _COUNT_FIELDS}, "n_flagged": 2.7}), encoding="utf-8"
    )
    rc = main(["comment", "--repo", "o/n", "--pr", "1", "--delta-json", str(delta), "--dry-run"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "n_flagged" in err
    assert "Traceback" not in err


# --- unchanged behaviour: the fix must not tighten anything else ------------


@pytest.mark.parametrize("n_rows_text", ["1", "1.0", '"1"'])
def test_accepted_whole_number_spellings_still_load(
    tmp_path: Path, capsys, n_rows_text: str
) -> None:
    # An int, an integral float (what a JSON round-trip of an int can produce)
    # and a numeric string all worked before and must keep working.
    cur, base = _write_pair(tmp_path, _run_json(n_rows_text))
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 0
    assert "Traceback" not in capsys.readouterr().err


def test_bad_numeric_string_keeps_its_original_message(tmp_path: Path, capsys) -> None:
    # `"abc"` is a str, so `_require_number` passes it and `int()` raises its own
    # ValueError. That path was already exit-2 and its message is asserted
    # elsewhere; `_require_int` must not intercept it.
    cur, base = _write_pair(tmp_path, _run_json('"abc"'))
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "invalid literal for int()" in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    ("value", "expected"),
    [(3, 3), (3.0, 3), ("3", 3), (-2, -2), (0, 0), (True, None), (None, None), ([1], None)],
)
def test_require_int_unit_contract(value: object, expected: int | None) -> None:
    if expected is None:
        # bool / None / container are all rejected by the `_require_number`
        # choke-point `_require_int` defers to, with its shared message.
        with pytest.raises(ValueError, match="f must be a number"):
            runner._require_int(value, "f")
    else:
        assert runner._require_int(value, "f") == expected


def test_require_int_rejects_nan() -> None:
    # NaN already raised a ValueError from `int()`, so this was never a contract
    # break — but the message named neither the field nor the reason. Pin the
    # improved one so it can't regress to the bare interpreter text.
    with pytest.raises(ValueError, match="f must be a finite whole number"):
        runner._require_int(float("nan"), "f")


# --- lock: no caller may reintroduce the bare coercion ----------------------


def test_no_bare_int_of_require_number_remains() -> None:
    """The next whole-number field must not repeat this quietly.

    Asserting "the two known sites use `_require_int`" would go stale the moment
    a third field is added, which is exactly how this landed — `n_rows` and the
    summary counts each grew their own bare coercion. So scan for the *shape*
    instead: any `int(...)` wrapped directly around a `_require_number(...)`
    call, anywhere in the module.
    """
    source = Path(runner.__file__).read_text(encoding="utf-8")
    # Strip docstrings/comments' prose mentions of the pattern — only real code
    # should trip this. Comment lines start with optional whitespace then `#`.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("#", "*"))
    )
    offenders = re.findall(r"int\(\s*_require_number\(", code)
    assert offenders == [], (
        "a bare `int(_require_number(...))` reintroduces #190: `int()` raises "
        "OverflowError (not a ValueError) on an infinite value and silently "
        "truncates a non-integral one. Use `_require_int` instead."
    )
