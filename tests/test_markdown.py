"""Unit tests for the shared GFM table-cell escaper (`eval_harness.markdown`).

`md_table_cell` is the one home for the escaping the per-emitter tests
(`test_comment.py`, `test_calibration.py`) exercise end-to-end. These pin the
helper's contract directly so a future edit that weakens it fails here loudly,
independent of any emitter.
"""

from __future__ import annotations

import re

from eval_harness.markdown import md_code_cell, md_code_span, md_table_cell


def test_escapes_pipe_as_literal():
    # `|` -> `\|` so GitHub renders a literal pipe instead of a column delimiter.
    assert md_table_cell("lang=py|framework=x") == "lang=py\\|framework=x"


def test_collapses_newline_run_to_single_space():
    # A literal newline is a GFM row delimiter; collapse any CR/LF run to one
    # space so the cell can't split across physical lines. #142.
    assert md_table_cell("a\nb") == "a b"
    assert md_table_cell("a\r\nb") == "a b"
    assert md_table_cell("a\rb") == "a b"
    # A run collapses to a single space, not one space per newline.
    assert md_table_cell("a\n\n\nb") == "a b"


def test_defends_both_delimiters_at_once():
    # The exact reachable payload: a newline followed by an injected pipe.
    assert md_table_cell("qa\n| INJ") == "qa \\| INJ"


def test_output_carries_no_structural_delimiter():
    # Post-escape, the cell contributes zero unescaped pipes and zero newlines —
    # the two properties every table emitter relies on.
    out = md_table_cell("x|y\nz|w")
    assert "\n" not in out
    assert "\r" not in out
    assert len(re.findall(r"(?<!\\)\|", out)) == 0


def test_valid_single_line_content_unchanged():
    # No pipes, no newlines -> returned verbatim. The helper must not mangle the
    # overwhelmingly common case.
    assert md_table_cell("qa-001_v2") == "qa-001_v2"
    assert md_table_cell("") == ""


def test_md_code_cell_neutralizes_backtick_so_span_stays_single():
    # #180: a value WRAPPED in an inline-code span has a third hazard beyond the
    # pipe/newline delimiters — a backtick closes the span early, splitting
    # `` `a`b`c` `` into two code spans with `b` leaking out as prose. The wrapped
    # result must contain exactly two backticks (the span's own delimiters).
    out = md_code_cell("suite/case`rm -rf`x")
    assert out.count("`") == 2
    assert out.startswith("`")
    assert out.endswith("`")
    assert "rm -rf" in out  # legible, just not as its own leaked prose


def test_md_code_cell_still_defends_pipe_and_newline():
    # A code cell is still a table cell: the pipe/newline escaping applies inside
    # the wrap. Interior pipes are `\|`-escaped (GFM's table extension unescapes
    # them to a literal `|` before the code span is parsed) and CR/LF runs
    # collapse to a single space.
    assert md_code_cell("a|b") == "`a\\|b`"
    assert md_code_cell("a\r\nb") == "`a b`"


def test_md_code_cell_valid_id_just_wrapped():
    # The common case: a clean id is simply wrapped, no mangling.
    assert md_code_cell("qa-001_v2") == "`qa-001_v2`"


def test_md_code_span_neutralizes_backtick_so_span_stays_single():
    # #182: the non-table code-span sibling of #180 — a heading/list-item span
    # (`` # Eval delta · `{suite}` ``) has the same backtick hazard. The wrapped
    # result must carry exactly the two span-delimiter backticks.
    out = md_code_span("claude`rm -rf`x")
    assert out.count("`") == 2
    assert out.startswith("`")
    assert out.endswith("`")
    assert "rm -rf" in out


def test_md_code_span_collapses_newline_but_leaves_pipe_literal():
    # Newlines still collapse (a span spilling onto a new physical line breaks the
    # surrounding heading/list). But unlike `md_code_cell`, the pipe is NOT escaped:
    # outside a table `|` is ordinary and a `\|` would render a literal backslash.
    assert md_code_span("a\r\nb") == "`a b`"
    assert md_code_span("a|b") == "`a|b`"


def test_md_code_span_valid_value_just_wrapped():
    assert md_code_span("claude-opus-4-6") == "`claude-opus-4-6`"
