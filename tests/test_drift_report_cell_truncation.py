"""The HTML report's example cell caps *text*, not markup (#240).

`render_html` rendered the "most distant candidate inputs" cell as
`html.escape(r.text)[:200]`, spending a 200-character budget on the escaped
markup instead of on the text. Every `&`, `<`, `>`, `"` and `'` costs 4-5
characters of that budget, so the cell showed less text than the cap promises by
an amount set by the input's punctuation density -- and the cut carried no
marker, so a sentence stopped mid-word read as a whole input.

Measured on `bba39c2` through `compute_drift` + `render_html`, `VISIBLE` being
`len(html.unescape(cell))`::

    input                                     source  markup  VISIBLE
    ----------------------------------------  ------  ------  -------
    code-review prompt `a['k'] && b["v"] < c`    193     200      162
    English prose with apostrophes               412     200      170
    XHTML-authoring prompt `<div>`, `&amp;`      348     200      147
    plain ASCII (the control)                    400     200      200

The first row is the one that makes this a bug rather than a rounding
preference: 193 characters is *under* the cap, so the cap should not touch that
input at all, and 31 characters went missing anyway. A code-review prompt is one
of the likeliest shapes in an LLM eval golden set.

The second harm is structural. A cut index measured in markup can land between
the `&` and the `;` of a reference the escape just produced: `"x" * 197 + "&"`
rendered a literal `&am`, and `"x" * 197 + "'"` a literal `&#x`. For some
offsets HTML5's legacy named-reference set resolves the fragment anyway
(`&amp` -> `&`, `&lt` -> `<`), so the corruption was offset-dependent -- worse
than uniformly broken, because it does not reproduce from a rounded repro.

Both plausible wrong fixes were built and run against this file:

    html.escape(r.text[:200])            right unit, still SILENT ->
                                         red on the marker arms only
    html.escape(r.text)[:200] + "…" marked, still WRONG UNIT ->
                                         red on the density table and on
                                         `renders_in_full`

so neither the unit arms nor the marker arms are redundant.
"""

from __future__ import annotations

import html
import re

import pytest

from eval_harness.drift import (
    _CELL_TEXT_CAP,
    _TRUNCATION_MARKER,
    _truncate_text,
    compute_drift,
    render_html,
)

# A filler word the hash embedder can tokenise, so a row is never dropped as
# uncomparable (D-017) and never ranked out of the representative list for
# having no tokens at all.
_NEAR_GOLDEN = "kitchen chemistry heat transfer note"
_GOLDEN = [f"{_NEAR_GOLDEN} {i}" for i in range(8)]


def _render_cell(text: str) -> str:
    """Return the rendered `<td>` markup for *text* as the one distant candidate.

    Goes through the real `compute_drift` + `render_html`, not through
    `_truncate_text` alone: the defect was an *ordering* at the call site, and a
    test of the helper in isolation is green against the unfixed renderer.
    """
    report = compute_drift(
        golden_inputs=_GOLDEN,
        candidate_inputs=[text, *(f"{_NEAR_GOLDEN} {i}" for i in range(7))],
        n_representative_examples=8,
    )
    doc = render_html(report)
    body = re.search(r"Most distant candidate inputs.*?<tbody>(.*?)</tbody>", doc, re.S)
    assert body is not None, "representative-examples table missing from the report"
    rows = re.findall(r"<tr><td>[0-9.]+</td><td>(.*?)</td></tr>", body.group(1), re.S)
    hits = [c for c in rows if _NEAR_GOLDEN not in html.unescape(c)]
    assert len(hits) == 1, f"expected exactly one distant row, got {len(hits)}: {rows!r}"
    return hits[0]


def _visible(cell: str) -> str:
    return html.unescape(cell)


# --- the density table ------------------------------------------------------
#
# Every row is longer than the cap, so every row must render exactly
# `_CELL_TEXT_CAP` characters of text plus the marker. `escaped_len` is what the
# unfixed code spent the budget on, and the rows are chosen so that number
# differs between rows -- a table whose rows all had the same escape expansion
# would agree with the unfixed answer and prove nothing.
_DENSITY_CASES = [
    pytest.param("plain ASCII", "Describe braising technique " + "a" * 400, id="ascii-control"),
    pytest.param(
        "apostrophes",
        "Explain the chef's technique, the baker's ratio, the sommelier's pairing. " * 8,
        id="apostrophes",
    ),
    pytest.param(
        "ampersands",
        "Compare salt & pepper & heat & time & fat & acid in braising. " * 8,
        id="ampersands",
    ),
    pytest.param(
        "angle brackets",
        'Rewrite as XHTML: <div class="card"><p>Hello &amp; welcome</p></div> now. ' * 6,
        id="angle-brackets-and-quotes",
    ),
    pytest.param(
        "code review",
        "Review this snippet: if (a['k'] && b[\"v\"] < c) { return d->e; } else { x = y & z; } "
        * 4,
        id="code-review-prompt",
    ),
]


@pytest.mark.parametrize(("label", "text"), _DENSITY_CASES)
def test_visible_text_is_capped_in_characters_not_in_markup(label: str, text: str) -> None:
    assert len(text) > _CELL_TEXT_CAP, f"{label}: fixture must exceed the cap to test it"
    cell = _render_cell(text)
    visible = _visible(cell)
    assert visible == text[:_CELL_TEXT_CAP] + _TRUNCATION_MARKER, (
        f"{label}: the cell must show the first {_CELL_TEXT_CAP} characters of the "
        f"input plus the marker; showed {len(visible)} characters"
    )


def test_the_density_table_rows_disagree_about_the_markup_length() -> None:
    """Anti-vacuous: the rows must actually exercise different escape expansions.

    Without this the table could be five ASCII strings, which the unfixed
    `html.escape(text)[:200]` renders correctly, and every assertion above would
    pass against the bug.
    """
    expansions = {
        label: len(html.escape(text[:_CELL_TEXT_CAP])) - _CELL_TEXT_CAP
        for label, text in (c.values for c in _DENSITY_CASES)
    }
    assert expansions["plain ASCII"] == 0, "the control must not expand"
    for label in ("apostrophes", "ampersands", "angle brackets", "code review"):
        assert expansions[label] > 0, f"{label} must expand under html.escape"
    assert len(set(expansions.values())) >= 4, (
        f"rows must span at least 4 distinct expansions to separate the two units; got {expansions}"
    )


# --- the arm the unfixed code fails hardest ---------------------------------


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            "Review this snippet and explain the bug: if (a['k'] && b[\"v\"] < c) "
            "{ return d->e; } else { x = y & z; } Then say whether && versus & is why.",
            id="193-char-code-review-prompt",
        ),
        pytest.param("'" * 30 + " braising technique notes", id="apostrophe-heavy-short"),
        pytest.param("<&>\"'" * 20 + " braising technique notes", id="all-five-escapables"),
    ],
)
def test_an_input_at_or_under_the_cap_renders_in_full(text: str) -> None:
    """No marker, nothing dropped -- the cap must not touch an under-cap input.

    This is the arm that fails on `main`: the 193-character code-review prompt
    rendered 162 characters. It is also the arm a unit-only fix passes and a
    marker-only fix fails, which is why both are kept.
    """
    assert len(text) <= _CELL_TEXT_CAP, "fixture must be at or under the cap"
    cell = _render_cell(text)
    visible = _visible(cell)
    assert visible == text, (
        f"an input of {len(text)} characters is under the {_CELL_TEXT_CAP}-character "
        f"cap and must render whole; {len(visible)} characters rendered"
    )
    assert _TRUNCATION_MARKER not in visible, "nothing was cut, so nothing may be marked"


def test_the_boundary_is_exact_on_both_sides() -> None:
    """`len == cap` renders whole; `len == cap + 1` is cut and marked.

    An off-by-one here is the shape a `<` / `<=` slip takes, and both plausible
    wrong fixes get this right -- it is the arm that keeps a *third* neighbour,
    one that marks every cell unconditionally, out.
    """
    at = "braise " + "a" * (_CELL_TEXT_CAP - 7)
    assert len(at) == _CELL_TEXT_CAP
    assert _visible(_render_cell(at)) == at
    over = at + "b"
    assert _visible(_render_cell(over)) == at + _TRUNCATION_MARKER


# --- the structural arm -----------------------------------------------------

#: An `&` that does not open a complete character reference. HTML5 resolves some
#: of these from its legacy named set and renders others literally, so the rule
#: is "no partial reference at all" rather than a list of the bad ones.
_INCOMPLETE_REFERENCE = re.compile(r"&(?![a-zA-Z][a-zA-Z0-9]*;|#[0-9]+;|#[xX][0-9a-fA-F]+;)")


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("x" * (_CELL_TEXT_CAP - 3) + "&" + "y" * 300, id="cut-inside-amp"),
        pytest.param("x" * (_CELL_TEXT_CAP - 3) + "'" + "y" * 300, id="cut-inside-x27"),
        pytest.param("x" * (_CELL_TEXT_CAP - 3) + "<" + "y" * 300, id="cut-inside-lt"),
        pytest.param("x" * (_CELL_TEXT_CAP - 3) + '"' + "y" * 300, id="cut-inside-quot"),
        *[
            pytest.param("braising " + "x" * off + "&'\"<>" + "y" * 400, id=f"sweep-offset-{off}")
            # Sweep the offsets at which an escape lands on the old cut index, so
            # the arm is discovered rather than hand-aimed at one entity.
            for off in range(_CELL_TEXT_CAP - 12, _CELL_TEXT_CAP + 1)
        ],
    ],
)
def test_no_cell_contains_a_split_character_reference(text: str) -> None:
    cell = _render_cell(text)
    bad = _INCOMPLETE_REFERENCE.search(cell)
    assert bad is None, (
        f"cell contains a partial character reference at offset {bad.start() if bad else -1}: "
        f"{cell[max(0, (bad.start() if bad else 0) - 10) :][:24]!r}"
    )


def test_the_split_reference_probe_can_fail() -> None:
    """Anti-vacuous for the regex: it must reject what it was written to reject."""
    for fragment in ("&am", "&#x", "&lt", "&quot", "&#3", "&"):
        assert _INCOMPLETE_REFERENCE.search(f"abc{fragment}") is not None, fragment
    for fragment in ("&amp;", "&lt;", "&gt;", "&quot;", "&#x27;", "&#39;"):
        assert _INCOMPLETE_REFERENCE.search(f"abc{fragment}") is None, fragment


# --- the call-site lock -----------------------------------------------------


def _escape_then_slice_sites() -> list[str]:
    """Every `escaper(...)[...]` expression in the package, found over the AST.

    Over the AST and not over the source text, for two independent reasons, both
    of which bit a first draft of this lock:

    1. A line-regex matches the prose. `_truncate_text`'s own docstring contains
       the string ``html.escape(text)[:limit]`` because explaining the defect
       requires naming it, and a grep cannot tell an explanation from an
       instance.
    2. The real site lives *inside an f-string* --
       ``f"<td>{html.escape(r.text)[:200]}</td></tr>"`` -- and a token-based
       filter that skips `STRING` tokens to solve (1) would then miss it on
       Python 3.11, where an f-string is one `STRING` token rather than the
       `FSTRING_START`/`NAME`/`OP` sequence 3.12 produces. CI runs 3.11 and
       3.12; this repo's venv runs 3.14. The AST is the one view of the file
       that is the same on all three.
    """
    import ast
    import pathlib

    import eval_harness

    def is_escaper(node: ast.expr) -> str | None:
        if isinstance(node, ast.Attribute) and node.attr == "escape":
            return "html.escape"
        if isinstance(node, ast.Name) and node.id.startswith("md_"):
            return node.id
        return None

    sites: list[str] = []
    for path in sorted(pathlib.Path(eval_harness.__file__).parent.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript):
                continue
            inner = node.value
            if not isinstance(inner, ast.Call):
                continue
            name = is_escaper(inner.func)
            if name is not None:
                sites.append(f"{path.name}:{node.lineno}: {ast.unparse(node)}")
    return sites


def test_no_call_site_slices_an_escaped_string() -> None:
    """The defect was an ordering at one call site, so pin the ordering there.

    A behavioural suite cannot tell `html.escape(_truncate_text(t))` from a
    future edit that reintroduces a slice on the escaped result for some *other*
    field, and `_truncate_text` having no test of where it is called is what lets
    the next edit orphan it silently. Discovered over the package rather than
    asserted about one line, so a second escape-then-slice site anywhere in
    `eval_harness` is a failure too.
    """
    assert _escape_then_slice_sites() == [], (
        "escape-then-slice spends a character budget on markup instead of on text "
        "(#240); slice the source first, then escape:\n" + "\n".join(_escape_then_slice_sites())
    )


def test_the_escape_then_slice_lock_can_fail() -> None:
    """Anti-vacuous: the AST matcher must find the shape it was written for.

    A lock that returns `[]` because its matcher is wrong is green forever. The
    probe rebuilds the defect's exact expression -- including the f-string
    nesting that made the token-based draft of this lock blind on 3.11 -- and
    asserts it is found.
    """
    import ast

    defect = 'def r():\n    return f"<td>{html.escape(r.text)[:200]}</td></tr>"\n'
    found = [
        ast.unparse(n)
        for n in ast.walk(ast.parse(defect))
        if isinstance(n, ast.Subscript)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Attribute)
        and n.value.func.attr == "escape"
    ]
    assert found == ["html.escape(r.text)[:200]"], found
    # And the prose form the first draft false-matched is NOT a site.
    prose = 'def r():\n    """See html.escape(text)[:limit] for why."""\n    return 1\n'
    assert [n for n in ast.walk(ast.parse(prose)) if isinstance(n, ast.Subscript)] == []


def test_the_one_rendered_text_cell_goes_through_the_helper() -> None:
    """The positive half: deleting the call must not leave this file green."""
    import inspect

    from eval_harness import drift

    src = inspect.getsource(drift.render_html)
    assert "_truncate_text(r.text)" in src, (
        "render_html must cap the example cell through `_truncate_text` so the cap "
        "is applied to text; a bare `r.text` restores the uncapped cell and a "
        "`[:...]` on the escaped result restores #240"
    )


# --- the helper's own contract ----------------------------------------------


def test_truncate_text_returns_text_not_markup() -> None:
    """It must not escape: escaping is the caller's next step, exactly once.

    A helper that escaped too would double-escape at the call site, turning a
    `&` into `&amp;amp;` -- the mirror-image corruption.
    """
    assert _truncate_text("a & b < c", _CELL_TEXT_CAP) == "a & b < c"


def test_truncate_text_rejects_a_negative_limit() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _truncate_text("abc", -1)


def test_truncate_text_cap_is_the_unit_the_prose_claims() -> None:
    """`_CELL_TEXT_CAP` is named in characters of text; pin that it is used so.

    The module's representability prose and
    `tests/test_drift_unencodable_inputs.py`'s `surrogate-past-200-char-truncation`
    row both state the cap in characters of text. Before #240 the code disagreed
    with both and nothing noticed, because every fixture on that path was ASCII.
    """
    text = "&" * (_CELL_TEXT_CAP + 50)
    assert len(_truncate_text(text)) == _CELL_TEXT_CAP + len(_TRUNCATION_MARKER)
    assert len(html.escape(text)[:_CELL_TEXT_CAP]) == _CELL_TEXT_CAP
    # The two units disagree by 5x on this input -- that gap is the bug's size.
    assert len(html.unescape(html.escape(text)[:_CELL_TEXT_CAP])) == _CELL_TEXT_CAP // 5
