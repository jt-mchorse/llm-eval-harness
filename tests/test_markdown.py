"""Unit tests for the shared GFM table-cell escaper (`eval_harness.markdown`).

`md_table_cell` is the one home for the escaping the per-emitter tests
(`test_comment.py`, `test_calibration.py`) exercise end-to-end. These pin the
helper's contract directly so a future edit that weakens it fails here loudly,
independent of any emitter.
"""

from __future__ import annotations

import re

from eval_harness.markdown import md_table_cell


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
