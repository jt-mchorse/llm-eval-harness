"""#228: `suite` was the one field `DeltaReport.from_json` never type-checked.

`DeltaReport.from_json` is deliberately permissive about *presence* — its
docstring says "No required fields at the top level — every field has a
documented default" — and every field it reads is nonetheless validated for
*type* at the parse boundary, because the renderers downstream are not
defensive and `cli._run_comment` calls them **outside** its exit-2 `try`.

Three top-level fields are read as strings with a bare `.get` default:
`current_run_id`, `baseline_run_id`, `suite`. The first two were guarded; the
third was not. A `"suite": null` in an externally-produced or hand-edited delta
JSON reached `md_code_span(report.suite)` in `comment.render_delta_markdown`
and raised `AttributeError: 'NoneType' object has no attribute 'replace'` —
neither a `ValueError` nor a `KeyError`, so `_run_comment` did not catch it and
the CLI exited 1 with a traceback, breaking the documented
`2 = I/O or usage error` contract.

`RowDelta.from_json`'s `status` guard already writes the mechanism down one
level lower: "a free-form string that lands in two renderers ... would raise a
raw AttributeError (`md_table_cell(...).replace`) ... at exit 1, breaking the
exit-2 contract the comment path honors". `suite` is the same shape, so the
tests here are the same shape too:

  - the *crash* consequence, through the real CLI (markdown renderer);
  - the *silent-wrong-output* consequence (the ascii renderer interpolates with
    a plain `{}` and would print a header naming the suite `None`);
  - the permissive-presence behaviour that must survive the guard;
  - a discovered-population lock so the next string field added to
    `DeltaReport` cannot join `suite` unguarded.
"""

from __future__ import annotations

import dataclasses
import json
import typing
from pathlib import Path

import pytest

from eval_harness.cli import main
from eval_harness.comment import render_delta_markdown
from eval_harness.runner import DeltaReport, render_delta_ascii

# The four JSON types a `suite` key can carry that are not a string. `True` is
# in the list on purpose: `bool` is an `int` subclass and reads as "truthy
# string-ish" to a sloppy guard, but `isinstance(True, str)` is False and the
# renderers break on it exactly like `None` does.
NON_STRING_SUITES: list[object] = [None, 3, 1.5, True, ["a"], {"a": 1}]


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "current_run_id": "cccccccccc",
        "baseline_run_id": "bbbbbbbbbb",
        "suite": "factuality",
        "threshold_drop": 0.05,
        "rows": [],
        "summary": {"mean_delta": 0.0, "n_flagged": 0},
    }
    base.update(overrides)
    return base


def _comment_dry_run(delta: Path) -> list[str]:
    return ["comment", "--repo", "o/n", "--pr", "1", "--delta-json", str(delta), "--dry-run"]


# --- the crash consequence: the markdown renderer, through the real CLI ------


@pytest.mark.parametrize("bad", NON_STRING_SUITES, ids=lambda v: type(v).__name__)
def test_comment_non_string_suite_exits_two_without_traceback(
    tmp_path: Path, capsys, bad: object
) -> None:
    """The contract is the *exit code*, not merely "does not crash".

    A fix that coerced (`md_code_span(str(report.suite))`, or `str(...)` at the
    parse boundary) would render a heading and exit 0 — no traceback, and still
    wrong. Asserting exit 2 plus a single `::error::` line is what separates the
    guard from that neighbour.
    """
    delta = tmp_path / "d.json"
    delta.write_text(json.dumps(_payload(suite=bad)), encoding="utf-8")

    rc = main(_comment_dry_run(delta))

    assert rc == 2
    captured = capsys.readouterr()
    assert "::error::" in captured.err
    assert "suite" in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    # Nothing may be posted/printed as a comment body when the artifact is bad.
    assert "# Eval delta" not in captured.out


@pytest.mark.parametrize("bad", NON_STRING_SUITES, ids=lambda v: type(v).__name__)
def test_from_json_rejects_non_string_suite_as_valueerror(bad: object) -> None:
    """`ValueError` specifically: `_run_comment` catches `ValueError`/`KeyError`
    and nothing else, so the exception *class* is the part of the contract that
    makes the exit-2 arm above fire."""
    with pytest.raises(ValueError, match="suite"):
        DeltaReport.from_json(_payload(suite=bad))


# --- the silent-wrong-output consequence: the ascii renderer ----------------


def test_ascii_header_cannot_be_handed_a_non_string_suite() -> None:
    """`render_delta_ascii` interpolates `suite` with a plain `{}`, so it does
    not raise on a non-string — it renders `(suite=None, ...)`, a header that
    states the suite is literally named `None`. That is the same harm #120 names
    for a null per-row `example_id`, one field up, and it is invisible.

    Both renderers are public (`eval_harness.__all__`), so the guard has to sit
    at the parse boundary to cover this path at all: there is no exception to
    catch here.
    """
    with pytest.raises(ValueError, match="suite"):
        DeltaReport.from_json(_payload(suite=None))


def test_ascii_header_still_carries_a_real_suite_name() -> None:
    """Anti-vacuous companion: the guard must not have made the field unusable."""
    report = DeltaReport.from_json(_payload(suite="factuality"))
    assert "suite=factuality" in render_delta_ascii(report)


def test_markdown_heading_still_carries_a_real_suite_name() -> None:
    report = DeltaReport.from_json(_payload(suite="factuality"))
    assert "# Eval delta · `factuality`" in render_delta_markdown(report)


def test_backtick_in_suite_is_still_neutralized() -> None:
    """The #180 code-span guard on this same value stays in force — the type
    check is an addition, not a replacement."""
    report = DeltaReport.from_json(_payload(suite="a`b"))
    heading = render_delta_markdown(report).splitlines()[2]
    assert heading.count("`") == 2


# --- the permissive-presence behaviour the guard must not break -------------


def test_missing_suite_still_defaults() -> None:
    """`from_json` documents "no required fields at the top level". Turning the
    type check into a *presence* check (`payload["suite"]` / raising on a
    missing key) is the other plausible wrong fix; this pins it out."""
    payload = _payload()
    del payload["suite"]
    assert DeltaReport.from_json(payload).suite == "(unknown)"


def test_missing_suite_renders_end_to_end(tmp_path: Path, capsys) -> None:
    payload = _payload()
    del payload["suite"]
    delta = tmp_path / "d.json"
    delta.write_text(json.dumps(payload), encoding="utf-8")

    rc = main(_comment_dry_run(delta))

    assert rc == 0
    assert "# Eval delta · `(unknown)`" in capsys.readouterr().out


def test_empty_string_suite_is_accepted() -> None:
    """Unlike `example_id` (which is guarded as *non-empty* because it names a
    row), `suite` has no emptiness contract — an empty suite name renders as an
    empty code span, which is ugly but not corrupt. Pinning this keeps a future
    tightening from arriving as an accident."""
    assert DeltaReport.from_json(_payload(suite="")).suite == ""


# --- the population lock ----------------------------------------------------


def _string_fields_of_delta_report() -> list[str]:
    """Discover, rather than hand-list, the `str`-annotated fields on
    `DeltaReport`.

    Hand-listing is how `suite` was missed in the first place: the guard added
    for the run ids enumerated two of the three string fields and read as a
    survey. A discovered population makes the next field added to the dataclass
    join this test automatically instead of waiting for someone to notice.
    """
    hints = typing.get_type_hints(DeltaReport)
    return [f.name for f in dataclasses.fields(DeltaReport) if hints.get(f.name) is str]


def test_population_discovery_is_not_vacuous() -> None:
    """A discovery helper that silently matches nothing turns the lock below
    into a no-op that passes against the unfixed code. Floor it, and name the
    field this issue is about so a refactor that renames it fails loudly."""
    found = _string_fields_of_delta_report()
    assert len(found) >= 3, f"expected at least 3 str-typed DeltaReport fields, found {found}"
    assert "suite" in found
    assert "current_run_id" in found
    assert "baseline_run_id" in found


@pytest.mark.parametrize("field", _string_fields_of_delta_report())
def test_every_string_field_rejects_a_present_null(field: str) -> None:
    """Every `str`-typed top-level field must refuse a present-but-null value at
    the parse boundary. The two run ids already did; `suite` is why this test
    exists; anything added later is covered on arrival."""
    with pytest.raises(ValueError, match=field):
        DeltaReport.from_json(_payload(**{field: None}))


@pytest.mark.parametrize("field", _string_fields_of_delta_report())
def test_every_string_field_survives_the_round_trip(field: str) -> None:
    """Mirror assertion: the guards reject non-strings *and only* non-strings.
    A guard that rejected everything would pass the test above."""
    value = f"{field}-value"
    rebuilt = DeltaReport.from_json(_payload(**{field: value}))
    assert getattr(rebuilt, field) == value
