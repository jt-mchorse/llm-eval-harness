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
import secrets
import stat
from pathlib import Path
from typing import Any

# Cap the target basename's contribution to the temp filename. The temp name is
# `.<base>.<random>.tmp`; the affixes add ~13-20 bytes, so prepending a full
# basename that is itself near NAME_MAX (255 on ext4/APFS) overflows the limit
# and the write fails with `OSError: [Errno 63] File name too long` — even though
# a plain `Path.write_text` of that same target succeeds (sibling of
# rag-production-kit#128 and mcp-server-cookbook#96). The base in the temp name
# is cosmetic (`ls`-ability); uniqueness comes from the random component (and
# `O_EXCL` in `_open_temp`), so truncating it is safe. Budget is in BYTES (NAME_MAX is a byte
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
# five enforcement sites with different consequences to describe:
#   `dataset._validate_record`       (#213)  -- `dump_jsonl` cannot emit it
#   `drift.compute_drift`            (#215)  -- `render_html` cannot be written
#   `calibration._row_from_dict`     (#217)  -- `render_report` cannot be written,
#                                               and by then the judge tokens are spent
#   `cli._write_output`              (#217)  -- the backstop: whatever slipped past
#                                               the loaders exits 2, not 1-with-a-traceback
#   `Dataset.dump_jsonl`             (#234)  -- the writer itself, for a record
#                                               that reached it without a loader
# Each phrases its own consequence; all share the detection so they cannot
# answer differently for the same string. `find_unencodable` is the per-string
# half; `find_unrepresentable` below is the record walk the loader sites and
# the writer share.
#
# The fifth arrived late for a reason worth leaving here. For four sites this
# list read as a survey of where the rule is enforced, and every member of it
# was an *ingress* -- two loaders, a drift compute seam, a CLI backstop. The
# question none of them asks is whether the rule's own writer can be reached
# without passing one, and `Dataset.dump_jsonl` could: `Example` is exported,
# has no `__post_init__`, and a `Dataset` assembled in Python never sees
# `load_jsonl`. So the canonical writer emitted `{"cost_usd":Infinity}` --
# a file its own loader rejects on the very next read (#234).


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


#: The shapes a record can carry that a canonical JSON writer cannot faithfully
#: emit. Named so a caller can enforce a subset: the axes have different
#: consequences and not every seam has one to name for all of them.
UNENCODABLE = "unencodable"
NON_FINITE = "non_finite"
NON_STRING_KEY = "non_string_key"
UNSERIALIZABLE_TYPE = "unserializable_type"
#: A container reachable from itself. `json.dumps` raises
#: ``ValueError: Circular reference detected`` on one, so unlike the four kinds
#: above it does not *silently* corrupt a round trip, and the failure is already
#: a `ValueError`. It is a finding anyway, because the walk meant to describe a
#: record **could not terminate on it** (#259): iterative with no ancestor
#: tracking, a cycle grew both the stack and the path string without bound until
#: the process was OOM-killed. The docstring's own argument is why that matters --
#: a `RecursionError` is unacceptable because it "would escape a caller's
#: `except ValueError`", and a hang escapes it too, and forever. Reported here so
#: the enforcement sites name the field path, as they do for every other kind.
CIRCULAR_REFERENCE = "circular_reference"
_ALL_KINDS = frozenset(
    {UNENCODABLE, NON_FINITE, NON_STRING_KEY, UNSERIALIZABLE_TYPE, CIRCULAR_REFERENCE}
)

#: The Python types `json.dumps` emits *faithfully* -- one JSON value out, the
#: same Python value back from `json.loads`. A `Counter`, an `OrderedDict`, an
#: `IntEnum`, a `str` subclass and a `list` subclass all round-trip **equal**
#: through this writer (measured, #238), so all five must pass.
#:
#: Four of them pass because the arms *above* the type check are spelled with
#: `isinstance` and consume them first -- a `Counter` is handled by the `dict`
#: arm, a `str` subclass by the `str` arm. Only an `int` subclass reaches the
#: type check, `int` having no arm of its own. So the faithful set is enforced
#: by two mechanisms that have to agree, and `type(v) in` here is red on
#: exactly one of the five (measured: `IntEnum`) while `type(v) ==` in the arms
#: above would be red on the other four. Both halves are pinned in
#: `tests/test_dataset_dump_value_types.py`; neither is obvious from reading
#: this line alone, which is why the count is written down.
#:
#: `tuple` is deliberately absent. It is the one type that serializes without
#: erroring and still is not faithful -- `("a","b")` is written as a JSON array
#: and reloads as a `list`, so the record survives and the *value* does not.
#: That is the silent half of this axis, and the reason the axis is a type
#: check rather than a `try: json.dumps(...) except TypeError` (which is green
#: on exactly the tuple rows).
_FAITHFUL_JSON_TYPES: tuple[type, ...] = (str, int, float, bool, dict, list)


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

    ``kind`` is :data:`UNENCODABLE`, :data:`NON_FINITE`,
    :data:`NON_STRING_KEY` or :data:`UNSERIALIZABLE_TYPE`; ``detail`` is the
    fragment a caller interpolates into its own message --
    ``"'\\ud800' at position 4"``, ``"nan"``, ``"1 (int)"``, ``"tuple"``.
    **The caller phrases the consequence.** That is the split #215
    established for a single string (`find_unencodable` is shared; each site
    says what breaks) applied one level up to the record walk, so the
    record-level enforcement sites -- ``dataset._validate_record`` (#213),
    ``calibration._row_from_dict`` (#217) and ``Dataset.dump_jsonl`` (#234) --
    cannot answer differently for the same input while still naming different
    harms.

    :data:`NON_STRING_KEY` arrived with the write-side site (#234) and is the
    reason it had to. The two loader sites are fed `json.loads` output, whose
    object keys are always `str`; a `Dataset` built in Python is not, so
    ``dump_jsonl`` is the first caller that can hand this walk a non-string
    key. It is a representability finding on its own terms, not merely a crash
    to avoid: `json.dumps` *coerces* an `int`/`float`/`bool`/`None` key to a
    string (``{1: "one"}`` is written ``{"1": "one"}``, and reloads as the
    string ``"1"``), and raises a raw `TypeError` for any other key type. The
    first is the sharper half -- silent, and it breaks the round-trip identity
    ``dump_jsonl`` exists to guarantee.

    :data:`UNSERIALIZABLE_TYPE` is the *value*-side twin of
    :data:`NON_STRING_KEY`, and arrived for the same reason one axis later
    (#238). This walk type-checked a record's keys and only three *axes* of its
    values, so every other value type fell straight through it. The two harms
    are the pair the non-string-key paragraph above already names, on the other
    side of the colon: a `tuple` is *coerced* -- written as a JSON array,
    reloaded as a `list`, no error, and the round-trip identity ``dump_jsonl``
    exists to guarantee quietly broken -- while a `set`, `bytes`, `date`,
    `Decimal`, `mappingproxy` or plain object raises a bare `TypeError` naming
    no example, no id and no field path. `provenance` is documented free-form
    (``dict[str, Any]``), so it is the one field where an arbitrary Python
    object is the *ordinary* input, and `Example.expected_outputs` and
    `Example.tags` are both declared as tuples, which makes a tuple-valued
    `provenance` entry this package's own house idiom rather than an exotic.

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
    # `(path, node, on_path_at_entry)`. **Ancestors, not a global visited set**
    # (#259): two keys pointing at one dict is a legal DAG, and a `visited` set
    # reports the second reference as circular -- built and run, and it flags the
    # DAG control. Only a container reachable *from itself* is a cycle.
    #
    # Tracked with one mutable set plus an exit marker rather than a fresh
    # `frozenset` per node, which is what `rag-production-kit`'s `_json_safe`
    # does. That version is O(depth) per node and so quadratic in depth, and this
    # walk has no depth cap where that one truncates at `_MAX_DEPTH`. A walk whose
    # cost depends quadratically on a caller's nesting is the same class of
    # host-dependent boundary the iterative rewrite existed to remove. Measured
    # on a linear chain, marker vs frozenset: 5000 levels 0.005s vs 0.088s;
    # 20000 levels 0.059s vs 1.573s. Four times the depth costs 12x here and 18x
    # there -- the quadratic showing up, not a constant factor.
    on_path: set[int] = set()
    # `False` = descend into this node; `True` = leaving it, drop it from the
    # path. LIFO, so the exit marker is pushed *before* the children and popped
    # after all of them.
    stack: list[tuple[str, Any, bool]] = [("", record, False)]
    while stack:
        path, node, leaving = stack.pop()
        if leaving:
            on_path.discard(id(node))
            continue
        if isinstance(node, (dict, list, tuple)):
            if id(node) in on_path:
                if CIRCULAR_REFERENCE in kinds:
                    return path, CIRCULAR_REFERENCE, type(node).__name__
                # Axis not enforced by this caller, so do not descend. Unlike the
                # other not-enforced arms, skipping loses no coverage: nothing
                # below a back-reference is absent from the path already, and
                # descending is the non-termination this arm exists to stop.
                continue
            on_path.add(id(node))
            stack.append((path, node, True))
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
                if not isinstance(k, str):
                    # Reported where it is found, not pushed as a node: there
                    # is no path segment to push it under until the key has
                    # been rendered, and rendering it is the step that used to
                    # crash. `_safe_path_segment` calls `find_unencodable`,
                    # which calls `k.encode` -- so an `int` key raised
                    # `AttributeError` out of the line below, escaping every
                    # caller's `except ValueError` exactly the way the
                    # `RecursionError` this walk is iterative to avoid would
                    # (#231). `ascii()` and not `repr()` because a key can be a
                    # *container* of strings, and a tuple holding a lone
                    # surrogate would put it back into the message this
                    # function exists to keep clean.
                    if NON_STRING_KEY in kinds:
                        return path, NON_STRING_KEY, f"{ascii(k)} ({type(k).__name__})"
                    # Axis not enforced here, but the *value* still is: descend
                    # under a rendered key so a caller enforcing only
                    # UNENCODABLE keeps finding surrogates below a non-string
                    # key instead of losing that subtree.
                    seg = _safe_path_segment(ascii(k))
                    stack.append((f"{path}.{seg}" if path else seg, v, False))
                    continue
                seg = _safe_path_segment(k)
                child = f"{path}.{seg}" if path else seg
                # A key is a string on the record too, and is subject to the
                # same UTF-8 rule as a value. Push it under its own path so the
                # message points at the key rather than at whatever it maps to.
                stack.append((f"{child} (object key)", k, False))
                stack.append((child, v, False))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                stack.append((f"{path}[{i}]", v, False))
        elif node is not None and not isinstance(node, _FAITHFUL_JSON_TYPES):
            # The value-side twin of the non-string-key arm above, and it
            # carries the same pair of harms that arm's own comment names for
            # keys: `json.dumps` either *coerces* the value (a `tuple` becomes
            # a JSON array and reloads as a `list`) or raises a bare
            # `TypeError` (`set`, `bytes`, `date`, `Decimal`, `mappingproxy`,
            # any plain object) -- which escapes every caller's
            # `except ValueError` exactly as the `AttributeError` on an int key
            # did (#231) and as a non-`ExpectedOutput` item reaching
            # `to_dict()` did (#235). Keys got both halves closed; values had
            # neither (#238).
            #
            # The membership test is written over the whole faithful set even
            # though the arms above already consumed `bool`/`str`/`float`/
            # `dict`/`list`, so the rule reads in one place and survives a
            # reordering of the chain. `int` and `None` are what actually
            # reach here and pass.
            #
            # `type(node).__name__` and never the value: a `tuple` can hold a
            # lone surrogate, which is the exact string `_safe_path_segment`
            # and the `ascii(k)` above exist to keep out of these messages.
            if UNSERIALIZABLE_TYPE in kinds:
                return path, UNSERIALIZABLE_TYPE, type(node).__name__
            # Axis not enforced by this caller, but the items still are, on the
            # same reasoning as the non-string-key arm: a caller asking only
            # for UNENCODABLE should keep finding a surrogate inside a tuple
            # rather than losing that subtree. Only `tuple` -- a `set` has no
            # stable index to name in a path, so there is no honest `[i]` to
            # report and descending would make the message order-dependent.
            if isinstance(node, tuple):
                for i, v in enumerate(node):
                    stack.append((f"{path}[{i}]", v, False))
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
        fd, tmp_path = _open_temp(target)
        # `os.fdopen` closes `fd` itself if building the text wrapper fails
        # (e.g. an unknown encoding), so no separate close is needed here.
        with os.fdopen(fd, "w", encoding=encoding) as tmp:
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        _copy_existing_mode(target, tmp_path)
        os.replace(tmp_path, target)
        tmp_path = None
    finally:
        if tmp_path is not None:
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()


# File mode (#274, portfolio-ops#81). This helper used to create its temp file
# with `tempfile.NamedTemporaryFile`, which always creates 0600 -- it is built
# for private scratch files -- and `os.replace` carries the temp's mode onto the
# target. So every new artifact was owner-only regardless of the umask, and
# overwriting an existing 0644 file demoted it to 0600, where the
# `Path.write_text` this helper replaced did neither. The temp is now created
# with `0o666` so the KERNEL applies the umask (reading the umask in Python
# needs `os.umask(0)`, which briefly changes it for every thread), and an
# existing target's mode is copied onto the temp before the rename.
_TEMP_ATTEMPTS = 100


def _open_temp(target: Path) -> tuple[int, Path]:
    """Create `.<base>.<random>.tmp` beside *target*; return `(fd, path)`.

    `O_EXCL` makes the create fail rather than reuse a name that already
    exists, which is the guarantee `NamedTemporaryFile` gave; the random part
    is 8 characters, the same length it used, so the NAME_MAX budget above is
    unchanged.
    """
    prefix = f".{_cap_base_for_temp(target.name)}."
    for _ in range(_TEMP_ATTEMPTS):
        candidate = target.parent / f"{prefix}{secrets.token_hex(4)}.tmp"
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            continue
        return fd, candidate
    raise FileExistsError(f"could not create a unique temp file beside {target}")


def _copy_existing_mode(target: Path, tmp_path: Path) -> None:
    """Give *tmp_path* the permission bits *target* has now, if it exists.

    `Path.write_text` truncates in place, so an existing file keeps its mode;
    the rename replaces the inode, so the mode has to be carried over. A
    missing target is the new-file case and keeps the umask-derived mode.
    """
    try:
        mode = stat.S_IMODE(os.stat(target).st_mode)
    except FileNotFoundError:
        return
    os.chmod(tmp_path, mode)


def copy_json_value(value: Any) -> Any:
    """Copy a JSON value deeply over *containers*, leaving everything else alone.

    The copy a frozen record needs for a free-form JSON field, and the one
    `dict(...)` is not (#254).

    `dataset.Example.provenance` and `calibration.CalibrationRow.provenance`
    are both documented free-form JSON objects held by `frozen=True`
    dataclasses. `frozen` prevents *rebinding* an attribute; it says nothing
    about the object the attribute points at. So a `dict(...)` at the boundary
    stops a caller swapping the whole mapping and lets them edit anything
    nested inside it — measured through `load_jsonl` → `to_dict` →
    `dump_jsonl`, where a nested edit to `to_dict()`'s return reached the
    frozen `Example` and then the file on disk, with no `FrozenInstanceError`
    anywhere, because nothing was ever rebound.

    **Deep over containers rather than `copy.deepcopy`**, on purpose. The
    contract on these fields is JSON, and every non-container JSON value —
    `str`, `int`, `float`, `bool`, `None` — is already immutable, so copying
    them buys nothing. `deepcopy` would additionally recurse into whatever a
    direct constructor happened to store there, which changes the failure mode
    for out-of-contract input (a `deepcopy` of an open file handle raises, at a
    boundary whose job is to copy metadata) without making any in-contract case
    safer.

    **Not `dict(...)` at a new site**, which is the trap this function exists
    to avoid: the defect here *is* a shallow copy, so a fix that re-spells one
    somewhere else would pass any test that only checks "was it copied at all".
    `embedding-model-shootout#133` recorded the general form on
    `portfolio-ops#71` — a shallow copy is only complete when the element type
    is proved immutable, and `dict[str, Any]` proves nothing about its values.

    **`dict` and `list` only, and that is a decision rather than an oversight.**
    The recursion covers exactly the two mutable containers
    `Dataset.dump_jsonl`'s faithfulness table *accepts*. Everything else it
    lists is rejected at the write seam with its own type named —
    ``tuple``/``namedtuple``, ``set``, ``frozenset``, ``bytes``,
    ``bytearray``, ``mappingproxy``, ``Decimal``, ``date``. Copying those would
    be actively wrong on two counts. A `namedtuple` rebuilt through
    ``tuple(...)`` loses its class, so the guard that must name ``_Point``
    reports ``tuple`` instead — measured, one red arm. And `bytearray`/`set`
    are mutable but unreachable as *harm*, because no artifact can carry them:
    `find_unrepresentable` refuses the record on the way in and `dump_jsonl`
    refuses it on the way out, so an aliased one has no writer to corrupt.

    A `dict` or `list` **subclass** is normalised to its base type. `Counter`,
    `OrderedDict` and a `list` subclass are all on the accept table, and all
    three compare equal to their base and serialize to identical JSON, so
    nothing a caller can observe through this package changes. Rebuilding via
    ``type(value)(...)`` instead would preserve the class for those three and
    raise for any subclass with a different ``__init__`` signature — a
    strictly worse trade at a boundary whose contract is JSON.

    **Iterative, with an `id()`-keyed memo, and D-027 shipped it recursive
    (#259).** A cyclic `provenance` never terminated and a deeply nested one
    exhausted the stack -- inside `__post_init__`, before any validation ran, so
    `Example(provenance=<cyclic>)` raised `RecursionError` straight out of its own
    constructor. :func:`find_unrepresentable` in this very module is iterative
    **on purpose** and its docstring gives the reason: a `RecursionError` "is not
    a `ValueError`, so it would escape a caller's `except ValueError` and abort a
    collecting validation pass instead of becoming one finding." D-027 put a
    recursive copy *upstream* of that walk. The reason was already written down;
    the copy just did not inherit it.

    `rag-production-kit`'s D-022 ported this function and its own SSE totality
    suite went 8 red on exactly this, which is how the sibling was found.

    **A cycle is preserved, not refused here**, and that is the half that needed
    deciding rather than copying. `rag` preserves *and emits*, because its wire
    seam is lenient by D-017 ("stream alive, don't raise"). This package refuses
    -- so the question was only *where*, and the answer is not "in the copier":
    a copier that refused would be a second enforcement site with its own
    message, and this module spent #213/#217/#234/#238 collapsing exactly that
    kind of duplication into one walk. The copy is isomorphic to its input and
    :data:`CIRCULAR_REFERENCE` refuses it at the seam, naming the field path.

    That ordering is load-bearing in one direction: **making this function
    iterative on its own is not shippable.** Before #259 the `RecursionError`
    here was *masking* a worse failure one call later -- `find_unrepresentable`
    is iterative and had no ancestor tracking, so a cycle that survived the copy
    grew its stack and its path string without bound. Fixing the copy alone turns
    a `RecursionError` into a hang. An arm states that so a future partial revert
    reads as a regression rather than a simplification.

    The memo does two jobs. It terminates on a cycle, and it **preserves the
    input's sharing structure** -- two keys pointing at one dict still point at
    one dict afterwards, a fresh one. The recursive version expanded that into
    independent copies, which is both less faithful and exponential on a
    DAG-shaped `provenance`.
    """
    if not isinstance(value, (dict, list)):
        return value
    root: Any = {} if isinstance(value, dict) else []
    memo: dict[int, Any] = {id(value): root}
    # Every source container stays referenced while the walk runs, so CPython
    # cannot recycle an `id` out from under `memo`.
    keep: list[Any] = [value]
    stack: list[tuple[Any, Any]] = [(value, root)]
    while stack:
        src, dst = stack.pop()
        items = src.items() if isinstance(src, dict) else enumerate(src)
        for key, child in items:
            if isinstance(child, (dict, list)):
                copied = memo.get(id(child))
                if copied is None:
                    copied = {} if isinstance(child, dict) else []
                    memo[id(child)] = copied
                    keep.append(child)
                    stack.append((child, copied))
            else:
                copied = child
            if isinstance(dst, dict):
                dst[key] = copied
            else:
                dst.append(copied)
    return root
