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
import math
import os
import tempfile
from pathlib import Path
from typing import Any

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


def _name_bytes(base: str) -> int:
    """Length of *base* in the bytes the filesystem actually sees.

    `os.fsencode`, not `base.encode("utf-8")` (#226). Both halves of the
    comment above are true and the old implementation still counted the wrong
    bytes: NAME_MAX limits the bytes handed to the kernel, which is
    `os.fsencode` — `sys.getfilesystemencoding()` with
    `sys.getfilesystemencodeerrors()`, i.e. `surrogateescape` on POSIX.

    That handler is why the distinction bites rather than being pedantry. A
    path byte that is not valid UTF-8 arrives in Python as a lone surrogate in
    `U+DC80..U+DCFF`, and strict `str.encode("utf-8")` refuses to encode it —
    so `_cap_base_for_temp` used to raise `UnicodeEncodeError` on a
    destination the OS can perfectly well name, *before* reaching the length
    question. `sys.argv` is decoded with the same handler, so
    `--out $'report\\xff.html'` is enough to produce one; so is a name read
    back off a filesystem that holds non-UTF-8 bytes.

    The consequence was not a clean refusal. On a byte-transparent filesystem
    (ext4 — the CI and Action runner) the write would have *succeeded*. On a
    UTF-8-validating one (APFS) it fails either way, but the class changes:
    `OSError: [Errno 92] Illegal byte sequence`, which is what a plain
    `Path.write_text` of that target raises and what every write seam in this
    package catches, became `UnicodeEncodeError`, a `ValueError` subclass that
    `drift.cli` does not catch at all and that `cli._write_output` reports as
    *content* that "is not encodable as UTF-8" — sending the operator to look
    at their dataset over a byte in their filename.

    `os.fsencode` never raises: it uses `surrogateescape` on POSIX and
    `surrogatepass` on Windows, so every `str` a `Path` can hold round-trips.
    For a name that is valid UTF-8 it returns exactly the old number, so the
    budget is unchanged for every name that worked before.
    """
    return len(os.fsencode(base))


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
# One definition, here rather than in any caller, because the rule now has
# four enforcement sites with different consequences to describe:
#   `dataset._validate_record`       (#213)  -- `dump_jsonl` cannot emit it
#   `drift.compute_drift`            (#215)  -- `render_html` cannot be written
#   `calibration._row_from_dict`     (#217)  -- `render_report` cannot be written,
#                                               and by then the judge tokens are spent
#   `cli._write_output`              (#217)  -- the backstop: whatever slipped past
#                                               the loaders exits 2, not 1-with-a-traceback
# Each phrases its own consequence; all share the detection so they cannot
# answer differently for the same string. `find_unencodable` is the per-string
# half; `find_unrepresentable` below is the record walk the two loader-side
# sites share.


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


#: The two shapes a record can carry that a canonical JSON writer cannot
#: faithfully emit. Named so a caller can enforce a subset: the axes have
#: different consequences and not every seam has one to name for both.
UNENCODABLE = "unencodable"
NON_FINITE = "non_finite"
_ALL_KINDS = frozenset({UNENCODABLE, NON_FINITE})


def _safe_path_segment(key: str) -> str:
    """Render a dict key for an error message without ever emitting a raw
    unencodable character.

    The offending key is itself a candidate for the surrogate failure this
    check exists to catch, so interpolating it verbatim would make the *error
    path* crash when the message is written to stderr. `ascii()` escapes it.
    """
    if find_unencodable(key) is not None:
        return ascii(key)
    return key if key.isprintable() else ascii(key)


def find_unrepresentable(
    record: Any, *, kinds: frozenset[str] = _ALL_KINDS
) -> tuple[str, str, str] | None:
    """Return ``(json_path, kind, detail)`` for the first value in *record* that
    a canonical JSON writer cannot faithfully emit, or ``None`` when the whole
    record is representable.

    ``kind`` is :data:`UNENCODABLE` or :data:`NON_FINITE`; ``detail`` is the
    fragment a caller interpolates into its own message -- ``"'\\ud800' at
    position 4"`` for the former, ``"nan"`` for the latter. **The caller phrases
    the consequence.** That is the split #215 established for a single string
    (`find_unencodable` is shared; each site says what breaks) applied one level
    up to the record walk, so the two record-level enforcement sites --
    ``dataset._validate_record`` (#213) and ``calibration._row_from_dict``
    (#217) -- cannot answer differently for the same input while still naming
    different harms.

    ``kinds`` selects which axes are enforced. It is not decoration: the
    calibration loader enforces ``UNENCODABLE`` only, because no calibration
    writer emits ``provenance``, so there is no non-finite consequence to name
    there and a rejection with no reason is how a guard drifts away from the
    harm it was written for.

    Walked with an explicit stack rather than recursion on purpose. A record
    that `json.loads` accepted can be nested to the parser's own depth limit,
    and a recursive walk would add frames on top of that and could raise
    `RecursionError` -- which is not a `ValueError`, so it would escape a
    caller's `except ValueError` and abort a collecting validation pass instead
    of becoming one finding.
    """
    stack: list[tuple[str, Any]] = [("", record)]
    while stack:
        path, node = stack.pop()
        # `bool` first: it is an `int` subclass, and `math.isfinite(True)` is
        # True anyway, but branching on it explicitly keeps the numeric arm
        # about numbers.
        if isinstance(node, bool):
            continue
        if isinstance(node, str):
            if UNENCODABLE in kinds:
                unencodable = find_unencodable(node)
                if unencodable is not None:
                    bad, pos = unencodable
                    return path, UNENCODABLE, f"{bad!r} at position {pos}"
        elif isinstance(node, float):
            if NON_FINITE in kinds and not math.isfinite(node):
                return path, NON_FINITE, repr(node)
        elif isinstance(node, dict):
            for k, v in node.items():
                seg = _safe_path_segment(k)
                child = f"{path}.{seg}" if path else seg
                # A key is a string on the record too, and is subject to the
                # same UTF-8 rule as a value. Push it under its own path so the
                # message points at the key rather than at whatever it maps to.
                stack.append((f"{child} (object key)", k))
                stack.append((child, v))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                stack.append((f"{path}[{i}]", v))
    return None


def _cap_base_for_temp(base: str) -> str:
    if _name_bytes(base) <= _MAX_TEMP_BASE_BYTES:
        return base
    out = base
    while out and _name_bytes(out) > _MAX_TEMP_BASE_BYTES:
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
