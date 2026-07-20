"""GitHub-flavored-markdown table-cell escaping — one home for a recurring bug.

Every emitter in this package that renders a free-form string into a GFM table
cell has to defend the table's two structural delimiters:

- the **column** delimiter `|` — an unescaped pipe injects an extra column and
  misaligns every following row (fixed inline in `comment.py` #130 and
  `calibration.py` #134);
- the **row** delimiter `\n` (and `\r`) — a literal newline splits the cell
  across two physical lines and corrupts the table exactly as badly, but the
  #130/#134 fixes escaped only the pipe (#142).

Backticks do NOT protect either delimiter: GFM tokenizes rows on physical
newlines and splits cells on `|` *before* it parses inline-code spans, so a cell
wrapped in `` ` `` is no safer than a bare one. The escape has to happen on the
raw value.

Both fixes were written inline at three call sites, which is precisely why the
class kept recurring — a fourth emitter copies the pipe line and forgets the
newline. `md_table_cell` is the single place every GFM-table emitter routes its
free-form cells through, so the guard can't drift out of sync again.
"""

from __future__ import annotations

import re

# One or more CR/LF (in any order or run length) collapses to a single space so
# the cell stays on exactly one physical line. A run rather than char-by-char so
# a `\r\n` pair — or a blob of blank lines — doesn't expand into a wall of
# spaces.
_NEWLINE_RUN = re.compile(r"[\r\n]+")


def md_table_cell(value: str) -> str:
    """Escape *value* so it occupies exactly one GFM table cell.

    Escapes the column delimiter (`|` -> `\\|`, which GitHub renders as a literal
    pipe, inside a code span in a table too) and collapses every `\\r`/`\\n` run
    to a single space so the row delimiter can't split the cell across physical
    lines. Valid single-line content with no pipes is returned unchanged.

    The pipe escape runs first; it only ever inserts a backslash before an
    existing `|`, so it can neither create nor consume a newline and the two
    passes don't interact.

    NOTE: this defends only the two *structural* table delimiters. A cell that a
    caller then WRAPS in an inline-code span (`` `{cell}` ``) has a third hazard —
    a backtick in the value closes the span early — which this function does not
    handle. Use `md_code_cell` for code-span cells.
    """
    return _NEWLINE_RUN.sub(" ", value.replace("|", "\\|"))


def md_code_cell(value: str) -> str:
    """Render *value* as an inline-code span occupying exactly one GFM table cell.

    Some emitters wrap a free-form id in `` ` `` for legibility
    (`` `{example_id}` ``). That adds a hazard `md_table_cell` doesn't cover: a
    backtick IN the value closes the span early, so `` `a`b`c` `` tokenizes as
    two code spans with `b` leaking out as prose — the same corruption class as
    the pipe/newline delimiters, one level up. Backticks can't be backslash-
    escaped inside a code span (the backslash renders literally), so neutralize
    them to a straight quote — the identifier stays legible and the span stays a
    single span. The pipe/newline escaping still applies (a table cell is still a
    table cell), then the whole value is wrapped so callers don't re-add the
    backticks and drift back into the raw-backtick-interpolation bug.
    """
    return f"`{md_table_cell(value.replace('`', chr(39)))}`"


def md_code_span(value: str) -> str:
    """Render *value* as an inline-code span OUTSIDE a GFM table.

    Some emitters wrap a free-form string in `` ` `` in a heading, a list item, or
    a prose line — `` # Eval delta · `{suite}` ``, `` - judge model: `{model}` `` —
    not a table cell. Those share `md_code_cell`'s backtick hazard (a backtick in
    the value closes the span early and leaks the tail as prose), so neutralize
    backticks to a straight quote, and collapse every `\\r`/`\\n` run to a single
    space so the span can't spill onto a second physical line and break the
    surrounding block.

    Unlike `md_code_cell` the pipe is NOT escaped: outside a table `|` is an
    ordinary character, and a `\\|` would render a literal backslash *inside* the
    code span. That is the one difference from `md_code_cell` and the reason this
    is a separate function rather than a reuse.
    """
    return f"`{_NEWLINE_RUN.sub(' ', value.replace('`', chr(39)))}`"
