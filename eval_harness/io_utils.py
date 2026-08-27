"""Atomic on-disk write helpers.

The eval harness writes several artifact kinds that downstream steps consume:
- `run` / `diff` / `diff-json` / `list --out` write JSON/markdown that the
  GitHub Action's `comment` step (D-009) reads via the sticky-comment workflow.
- `calibrate --report` writes the calibration HTML report consumed by JT.
- `drift --output` writes the drift HTML report read in browser or uploaded
  as a workflow artifact.
- `Dataset.dump_jsonl` writes JSONL golden files consumed by every other
  subcommand and by the pytest plugin.

`Path.write_text` (and `open(path, "w").write(...)`) are not atomic: SIGINT /
SIGTERM / disk-full / OOM between the implicit `open(..., "w")` truncate and
`close()` flush leaves the destination zero-length or partially written. The
downstream consumer then either crashes with a misleading `json.JSONDecodeError`
or, worst case for D-006's sticky-comment workflow, posts garbage to the PR.

`atomic_write_text` writes to a sibling temp file in the same directory,
`fsync`s, then `os.replace`s. Same-directory placement is load-bearing:
guarantees same filesystem so the POSIX rename cannot fall back to a copy.

This module is the package-level home for the helper. PR #49 originally placed
it private to `cli.py`; promotion here matches the `rag_kit/io_utils.py`
pattern established in `rag-production-kit#44/#45` and is the portfolio
standard going forward.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

# Cap the target basename's contribution to the temp filename. The temp name is
# `.<base>.<random>.tmp`; the affixes add ~13-20 bytes, so prepending a full
# basename that is itself near NAME_MAX (255 on ext4/APFS) overflows the limit
# and the write fails with `OSError: [Errno 63] File name too long` — even though
# a plain `Path.write_text` of that same target succeeds (sibling of
# rag-production-kit#128 and mcp-server-cookbook#96). The base in the temp name
# is cosmetic (`ls`-ability); uniqueness comes from `NamedTemporaryFile`'s random
# component, so truncating it is safe. Budget is in BYTES (NAME_MAX is a byte
# limit) and we trim on a char boundary so multibyte names are never split
# mid-codepoint.
_MAX_TEMP_BASE_BYTES = 200


# --- representability (#213, #215) ------------------------------------------
#
# Every writer listed in this module's docstring encodes to UTF-8, so a string
# with no UTF-8 encoding is unwritable by all of them. In practice that means a
# *lone* surrogate: `"\ud800"` is legal JSON escape syntax, `json.loads` decodes
# it happily, and it then dies at the write with `UnicodeEncodeError`, long after
# whatever validated the input reported clean. RFC 8259 section 8.2 names
# unpaired surrogates as non-interoperable; they reach production traffic
# samples from broken UTF-16 handling upstream.
#
# A *valid* surrogate pair is not this. `json.loads('"\ud83c\udf89"')` combines
# the two escapes into a single U+1F389 codepoint, which encodes fine — so the
# rule is "does `.encode("utf-8")` succeed", never "does the source contain an
# escape above U+FFFF".
#
# One definition, here rather than in either caller, because the rule now has
# two enforcement sites with different consequences to describe:
#   `dataset._find_unrepresentable` (#213)  -- `dump_jsonl` cannot emit it
#   `drift.compute_drift`           (#215)  -- `render_html` cannot be written
# Each phrases its own consequence; both share the detection so they cannot
# answer differently for the same string.


def find_unencodable(text: str) -> tuple[str, int] | None:
    """Return ``(offending_text, position)`` for the first run of characters in
    *text* that has no UTF-8 encoding, or ``None`` when the whole string is
    encodable.

    ``position`` is a character index into *text*, not a byte offset -- there is
    no byte offset to report, precisely because the string cannot be encoded.
    """
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as e:
        return text[e.start : e.end], e.start
    return None


def _cap_base_for_temp(base: str) -> str:
    if len(base.encode("utf-8")) <= _MAX_TEMP_BASE_BYTES:
        return base
    out = base
    while out and len(out.encode("utf-8")) > _MAX_TEMP_BASE_BYTES:
        out = out[:-1]
    return out


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Write *text* to *path* atomically.

    On success the destination contains exactly *text*. On any failure path
    (signal, disk-full, OOM during flush), the destination is either unchanged
    (overwrite case) or absent (new-file case) — never partial.

    Parent directories are created with `mkdir(parents=True, exist_ok=True)`
    so callers don't have to gate on `.parent.mkdir(...)` themselves; this is
    the shape every existing caller used before promotion.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=target.parent,
            prefix=f".{_cap_base_for_temp(target.name)}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, target)
        tmp_path = None
    finally:
        if tmp_path is not None:
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()
