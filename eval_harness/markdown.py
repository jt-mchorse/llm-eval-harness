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
    """
    return _NEWLINE_RUN.sub(" ", value.replace("|", "\\|"))
