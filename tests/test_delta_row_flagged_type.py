"""`RowDelta.flagged` must be a real bool at the parse boundary (#230).

`flagged` was the last field on the row shape read with a bare
`payload.get(...)` and no type check — the row-level sibling of the `suite`
gap #228 closed one level up on `DeltaReport.from_json`.

It is different in kind from its neighbours there, and that is what made it
easy to leave: a non-string `example_id` or `status` *crashes* a renderer, so
it announces itself at exit 1. `flagged` is only ever read by truthiness
(`":warning:" if r.flagged else ""`, `"FLAG" if r.flagged else "    "`,
`[... if r.flagged]`), so a non-bool is read successfully as the wrong answer
at exit 0.

Both directions are reachable, and only one is in the issue title:

  truthy non-bool  -> invents a flag  ("false", "0", 1, [0], {"x": 1})
  falsy  non-bool  -> suppresses one  (0, "", [], {}, and a present null)

The tests below fix the *whole accepted set*, not a list of rejected examples,
so a future widening has to come here to be widened.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval_harness.comment import render_delta_markdown
from eval_harness.runner import DeltaReport, RowDelta, render_delta_ascii

# --------------------------------------------------------------------------
# The accepted set, stated once and used by every test below.
# --------------------------------------------------------------------------

# Exactly what `DeltaReport.to_json` can emit for this field, plus the
# missing-key case the docstring promises to keep reading for older payloads.
ACCEPTED: tuple[tuple[str, object, bool], ...] = (
    ("true", True, True),
    ("false", False, False),
)

# Everything else. Each row records which *direction* the pre-fix read went, so
# the reject list doubles as the harm table.
REJECTED_TRUTHY: tuple[tuple[str, object], ...] = (
    ('string "false"', "false"),  # the issue's reproducer: every JSON string is truthy
    ('string "0"', "0"),
    ('string "no"', "no"),
    ("int 1", 1),
    ("int -1", -1),
    ("float 1.0", 1.0),
    ("non-empty list", [0]),
    ("non-empty object", {"x": 1}),
)
REJECTED_FALSY: tuple[tuple[str, object], ...] = (
    ("int 0", 0),
    ("float 0.0", 0.0),
    ("empty string", ""),
    ("empty list", []),
    ("empty object", {}),
    ("explicit null", None),
)
REJECTED = REJECTED_TRUTHY + REJECTED_FALSY


def _row(**over: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "example_id": "qa_001",
        "baseline_score": 0.9,
        "current_score": 0.9,
        "delta": 0.0,
        "status": "unchanged",
    }
    payload.update(over)
    return payload


# --------------------------------------------------------------------------
# Accepted
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "value", "expected"), ACCEPTED, ids=[c[0] for c in ACCEPTED])
def test_json_booleans_are_accepted_and_kept_as_bool(
    label: str, value: object, expected: bool
) -> None:
    row = RowDelta.from_json(_row(flagged=value))
    # `is`, not `==`: a coercing fix that returned a truthy non-bool would
    # satisfy `== True` and still leave a non-bool in a field annotated `bool`.
    assert row.flagged is expected


def test_missing_key_still_defaults_to_false() -> None:
    """The docstring promises older payloads that omit the key keep reading."""
    payload = _row()
    assert "flagged" not in payload
    assert RowDelta.from_json(payload).flagged is False


# --------------------------------------------------------------------------
# Rejected — and rejected as the ValueError the comment path contracts for
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "value"), REJECTED, ids=[c[0] for c in REJECTED])
def test_non_bool_flagged_is_rejected(label: str, value: object) -> None:
    with pytest.raises(ValueError, match="flagged must be a boolean") as exc:
        RowDelta.from_json(_row(flagged=value))
    msg = str(exc.value)
    # `cli._run_comment` catches ValueError -> exit 2. A KeyError/TypeError/
    # AttributeError here would escape as a raw traceback at exit 1 instead.
    assert "flagged" in msg
    # The message has to name the row, because a delta artifact has many.
    assert "qa_001" in msg


def test_rejection_names_the_offending_value() -> None:
    """`repr`, so `"false"` (the string) is distinguishable from `false`."""
    with pytest.raises(ValueError, match="flagged must be a boolean") as exc:
        RowDelta.from_json(_row(flagged="false"))
    assert "'false'" in str(exc.value)


# --------------------------------------------------------------------------
# The two plausible wrong fixes, each of which passes a naive test
# --------------------------------------------------------------------------


def test_the_coercion_neighbour_is_not_what_shipped() -> None:
    """`bool(payload.get("flagged", False))` fixes nothing and looks like a fix.

    It is the first thing you reach for, it makes the field's *type* correct,
    and it launders the issue's own reproducer into a flag, because
    `bool("false")` is `True`. A test that only asserted `isinstance(row.flagged,
    bool)` would pass against it.

    The separating input is any *truthy* non-bool: the coercion accepts it and
    returns `True`; the guard that shipped refuses it.
    """
    assert bool("false") is True, "sanity: this is why the coercion is wrong"
    for _label, value in REJECTED_TRUTHY:
        with pytest.raises(ValueError, match="flagged must be a boolean"):
            RowDelta.from_json(_row(flagged=value))


def test_the_int_neighbour_is_not_what_shipped() -> None:
    """`isinstance(v, int)` reads as correct and accepts a raw JSON `1`/`0`.

    It reads as correct precisely *because* `isinstance(True, int)` is `True` in
    Python — so the check passes for every legitimate value, and a test built
    only from `true`/`false`/`"false"` cannot tell the two apart.

    `to_json` emits a Python `bool` for this field and json.dump writes it as
    `true`/`false`, so a bare `1` never comes from the writer. The separating
    inputs are `1` and `0`.
    """
    assert isinstance(True, int), "sanity: this is why the int check reads as correct"
    for value in (1, 0):
        with pytest.raises(ValueError, match="flagged must be a boolean"):
            RowDelta.from_json(_row(flagged=value))


def test_the_string_only_neighbour_is_not_what_shipped() -> None:
    """Rejecting only `str` closes the issue's title and leaves the rest open.

    The issue names a string, so a guard reading `if isinstance(v, str): raise`
    passes every test derived from the issue text. It leaves `1`, `[0]`,
    `{"x": 1}` inventing flags and `0`, `[]`, `null` suppressing them.
    """
    for _label, value in REJECTED:
        if isinstance(value, str):
            continue
        with pytest.raises(ValueError, match="flagged must be a boolean"):
            RowDelta.from_json(_row(flagged=value))


# --------------------------------------------------------------------------
# Write/read parity: the writer can never emit what its own reader refuses
# --------------------------------------------------------------------------


def test_every_flagged_value_to_json_can_emit_reads_back() -> None:
    report = DeltaReport(
        current_run_id="cur",
        baseline_run_id="base",
        suite="faithfulness",
        threshold_drop=0.1,
        rows=(
            RowDelta("qa_001", 0.9, 0.5, -0.4, "regressed", True),
            RowDelta("qa_002", 0.9, 0.9, 0.0, "unchanged", False),
        ),
    )
    # Through a real JSON round trip, not just the dict — `json.dumps` is where
    # a Python bool becomes the `true`/`false` token the reader will see.
    reread = DeltaReport.from_json(json.loads(json.dumps(report.to_json())))
    assert [r.flagged for r in reread.rows] == [True, False]
    assert all(isinstance(r.flagged, bool) for r in reread.rows)


# --------------------------------------------------------------------------
# The harm, at the surface a reviewer actually reads
# --------------------------------------------------------------------------


def _one_row_report(flagged: object) -> dict[str, object]:
    return {
        "current_run_id": "cur",
        "baseline_run_id": "base",
        "suite": "faithfulness",
        "threshold_drop": 0.1,
        "summary": {
            "mean_delta": 0.0,
            "n_flagged": 0,
            "n_regressed": 0,
            "n_improved": 0,
            "n_new": 0,
            "n_removed": 0,
            "n_unchanged": 1,
        },
        "rows": [_row(flagged=flagged)],
    }


def test_a_string_flagged_no_longer_contradicts_the_summary_it_ships_with() -> None:
    """The two halves of one PR comment disagreed, and the unvalidated half won.

    Pre-fix this payload rendered a `:warning:` on an `unchanged` row under a
    summary line reading `flagged **0** · regressed 0 · unchanged 1`, at exit 0.
    The summary counts are validated (`_require_int`, #116/#190); the per-row
    flag was not.
    """
    with pytest.raises(ValueError, match="flagged must be a boolean"):
        DeltaReport.from_json(_one_row_report("false"))

    # And the guard is not vacuous — the same payload with a real `false` still
    # renders, and renders *without* the warning, in both renderers.
    ok = DeltaReport.from_json(_one_row_report(False))
    md = render_delta_markdown(ok)
    assert ":warning:" not in md
    assert "flagged **0**" in md
    assert "FLAG" not in render_delta_ascii(ok)
    assert ok.regressed_ids == []


def test_regressed_ids_no_longer_gains_a_phantom_id() -> None:
    """`regressed_ids` is public and is what `examples/` prints."""
    with pytest.raises(ValueError, match="flagged must be a boolean"):
        DeltaReport.from_json(_one_row_report([0]))
    assert DeltaReport.from_json(_one_row_report(True)).regressed_ids == ["qa_001"]


def test_cli_comment_path_exits_2_not_1(tmp_path: Path) -> None:
    """End to end: a clean exit-2 line, not a traceback and not a wrong comment.

    This is the arm that would catch the guard raising the wrong exception
    class — `_run_comment` translates ValueError/KeyError to exit 2 and lets
    anything else escape as a raw traceback at exit 1.
    """
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps(_one_row_report("false")), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval_harness.cli",
            "comment",
            "--delta-json",
            str(delta),
            "--dry-run",
            "--repo",
            "x/y",
            "--pr",
            "1",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert proc.returncode == 2, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "flagged" in (proc.stderr + proc.stdout)
    # The wrong-output failure mode, stated as an assertion: whatever else
    # happens, the row must not have been rendered with a flag.
    assert ":warning:" not in proc.stdout
    assert "Traceback" not in proc.stderr
