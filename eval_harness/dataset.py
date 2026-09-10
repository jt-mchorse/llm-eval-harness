"""Golden-dataset JSONL format.

Each line in a dataset file is a single JSON object representing one example.
The dataset itself carries a version string (`dataset_version`) on every line so
that downstream tooling — PR-comment eval diffs, regression runners — can
reference exact data slices.

On-disk shape (one example, pretty-printed for documentation only — real files
are one compact JSON object per line):

    {
      "id": "qa_001",
      "input": "What is the capital of France?",
      "expected_outputs": [
        {"kind": "exact",    "value": "Paris"},
        {"kind": "semantic", "value": "The capital of France is Paris."}
      ],
      "tags": ["geography", "factuality"],
      "dataset_version": "factuality-v0.1",
      "provenance": {"source": "public_domain_trivia", "added_on": "2026-05-11"}
    }

Required fields: `id` (str, unique across the file), `input` (str),
`expected_outputs` (non-empty list), `dataset_version` (str), `provenance` (dict).
Optional: `tags` (list[str], defaults to []).

Every value on a record must be *representable in canonical JSONL*: numbers
must be finite (no `NaN`/`Infinity`, which `json.dumps` emits as bare tokens
that are not JSON) and strings must be encodable as UTF-8 (no lone surrogates).
The rule applies at any depth, including inside the free-form `provenance`
object. See `_find_unrepresentable` (#213).

Acceptable `expected_outputs[i].kind` values are listed in
`ExpectedOutput.VALID_KINDS`. New kinds may be added in a minor version of the
harness; readers must reject unknown kinds with a clear error rather than
silently accepting them, because eval semantics depend on the kind.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from eval_harness.io_utils import (
    NON_FINITE,
    NON_STRING_KEY,
    UNENCODABLE,
    atomic_write_text,
    find_unrepresentable,
)


class DatasetLoadError(ValueError):
    """Raised when a JSONL dataset line fails to parse or validate.

    Carries the 1-indexed `line_no` of the offending line and a human-readable
    `reason`. Used by the loader so users get a precise pointer to the bad line
    (not a 3-line traceback into json.JSONDecodeError).
    """

    def __init__(self, line_no: int, reason: str) -> None:
        self.line_no = line_no
        self.reason = reason
        super().__init__(f"line {line_no}: {reason}")


@dataclass(frozen=True)
class ExpectedOutput:
    """One acceptable answer for an example.

    `kind` controls how an evaluator compares the model's response to `value`:
      - "exact"    — substring/casefold-insensitive equality
      - "semantic" — judged by an LLM (or embedding similarity) against `value`
      - "regex"    — `value` is a Python regex pattern; match anywhere in output
    """

    kind: str
    value: str

    VALID_KINDS: ClassVar[frozenset[str]] = frozenset({"exact", "semantic", "regex"})

    def __post_init__(self) -> None:
        # `not isinstance(self.kind, str)` must lead: `VALID_KINDS` is a
        # frozenset, so testing membership of an unhashable `kind` (a JSON
        # array/object, e.g. `{"kind": []}`) raises a raw `TypeError` from the
        # `in` itself — which escapes `_validate_record`'s `except ValueError`
        # and aborts `validate_dataset`'s collecting pass. Reject non-str kinds
        # up front so the clean `ValueError` fires and is wrapped into a
        # `DatasetLoadError` like every other bad kind (a hashable wrong kind
        # such as `123` was already handled; this closes the unhashable gap).
        if not isinstance(self.kind, str) or self.kind not in self.VALID_KINDS:
            raise ValueError(
                f"invalid expected_output kind {self.kind!r}; "
                f"valid kinds: {sorted(self.VALID_KINDS)}"
            )
        if not isinstance(self.value, str):
            raise ValueError(f"expected_output.value must be str, got {type(self.value).__name__}")

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value}


@dataclass(frozen=True)
class Example:
    """One row in a golden dataset."""

    id: str
    input: str
    expected_outputs: tuple[ExpectedOutput, ...]
    dataset_version: str
    provenance: dict[str, Any]
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        # `tags` is emitted only when non-empty so round-trip files don't gain
        # a trailing `"tags": []` they didn't write.
        out: dict[str, Any] = {
            "id": self.id,
            "input": self.input,
            "expected_outputs": [e.to_dict() for e in self.expected_outputs],
            "dataset_version": self.dataset_version,
            "provenance": dict(self.provenance),
        }
        if self.tags:
            out["tags"] = list(self.tags)
        return out


@dataclass
class Dataset:
    """A versioned collection of `Example`s loaded from a JSONL file.

    `version` is the value of `dataset_version` carried by every line in the
    file. The loader enforces that every line shares the same version, so a
    file with mixed versions is rejected — datasets are atomic units.
    """

    version: str
    examples: list[Example] = field(default_factory=list)
    source_path: Path | None = None

    def __len__(self) -> int:
        return len(self.examples)

    def __iter__(self) -> Iterator[Example]:
        return iter(self.examples)

    def dump_jsonl(self, path: str | Path) -> None:
        """Write the dataset back to disk in canonical JSONL form.

        Canonical form: one example per line, JSON keys sorted, no trailing
        whitespace, single trailing newline. Together with `load_jsonl` this
        guarantees load → dump → re-load is byte-stable for any well-formed
        input, which is what makes round-trip identity testable.

        That guarantee is enforced on *both* sides of the seam, and until #234
        only one of them: `_validate_record` rejects the classes of value this
        writer cannot faithfully emit on the way in (#213), and this method
        applies the identical rule on the way out, through the same
        `_find_unrepresentable`.

        The write half was the half that mattered and the one nobody had.
        `_validate_record` runs on the *load* path, so it says nothing about a
        `Dataset` assembled in Python — `Example` is exported, has no
        `__post_init__`, and building goldens programmatically is the ordinary
        use of this package. Measured on `main`: a `provenance` of
        `{"cost_usd": inf}` was written as a bare `Infinity` token and
        `load_jsonl` of the file just written raised `DatasetLoadError`; a
        `{1: "one"}` key was written `{"1": "one"}` and reloaded with the key
        silently changed to a string.

        Rejection happens before any bytes are written — every record is walked
        first, so a bad example leaves the destination exactly as it was rather
        than truncating it to the good prefix. Raises `ValueError` naming the
        example's index, its `id` and the JSON path, with the loader's own
        reason text.

        Since #235 the *schema* is enforced here too, through the same
        `_FIELD_RULES` and `_DatasetInvariants` the loader uses, so this method
        cannot write a file `load_jsonl` refuses. The checks run in the loader's
        own order — per-field shape, then representability, then the
        cross-record invariants — so the two sides also agree on *which*
        problem they name when a record has more than one.

        The field checks run against the `Example`'s own attributes, not
        against `to_dict()`'s output, and that is load-bearing rather than
        incidental. `to_dict()` does `dict(self.provenance)` and
        `list(self.tags)`, so `tags="urgent"` becomes a perfectly well-formed
        `["u","r","g","e","n","t"]` — six tags, round-tripping cleanly, with
        nothing left in the record for a rule to object to. Measured on `main`
        alongside `provenance=[]` silently becoming `{}` and a `Dataset.version`
        that disagreed with its rows reloading as the *other* version.

        `Dataset.version` disagreeing with the rows is rejected rather than
        silently overwritten (D-022): the loader's own message for the
        neighbouring case says "split mixed-version data into separate files",
        and overwriting every row with `self.version` would be a lossy write
        that no reader could detect.

        `tests/test_dataset_representability.py` runs the representability
        property over a variant table, and
        `tests/test_dataset_dump_write_path.py` does the same for the schema.
        """
        path = Path(path)
        if not self.examples:
            # `"\n".join([]) + "\n"` is a single blank line, which
            # `load_jsonl` rejects as "blank line; dataset must have one JSON
            # object per line". Refusing here names the real problem.
            raise ValueError("dataset has no examples; nothing to write")

        invariants = _DatasetInvariants()
        records: list[dict[str, Any]] = []
        for i, ex in enumerate(self.examples):
            # `ascii(ex.id)` and not `{ex.id!r}`: the id is itself a candidate
            # for the surrogate failure being reported, and interpolating it
            # verbatim would make *this* message unprintable — the same trap
            # `io_utils._safe_path_segment` exists for, one layer up.
            where = f"examples[{i}] (id={ascii(ex.id)})"

            reason = _find_field_violation(
                {
                    "id": ex.id,
                    "input": ex.input,
                    "dataset_version": ex.dataset_version,
                    "provenance": ex.provenance,
                    "expected_outputs": ex.expected_outputs,
                    "tags": ex.tags,
                },
                ("id", "input", "dataset_version", "provenance", "expected_outputs", "tags"),
            )
            if reason is not None:
                raise ValueError(f"{where}: {reason}")

            # The one rule that is deliberately writer-only: the two sides have
            # genuinely different domains here. The loader sees JSON objects and
            # builds `ExpectedOutput`s from them (so `__post_init__` validates
            # `kind`/`value`); this side already holds instances, and the thing
            # it can be handed that the loader cannot is a non-`ExpectedOutput`
            # item — which would otherwise reach `to_dict()` as a raw
            # `AttributeError` instead of this package's `ValueError`.
            for j, eo in enumerate(ex.expected_outputs):
                if not isinstance(eo, ExpectedOutput):
                    raise ValueError(
                        f"{where}: expected_outputs[{j}] must be an ExpectedOutput, "
                        f"got {type(eo).__name__}"
                    )

            record = ex.to_dict()
            unrepresentable = _find_unrepresentable(record)
            if unrepresentable is not None:
                json_path, reason = unrepresentable
                raise ValueError(f"{where}: field {json_path!r} {reason}")

            reason = invariants.violation_for(ex.id, ex.dataset_version)
            if reason is not None:
                raise ValueError(f"{where}: {reason}")

            records.append(record)

        # D-022. `Dataset.version` is documented as "the value of
        # `dataset_version` carried by every line in the file"; nothing checked
        # it on the way out, so `Dataset(version="v1", examples=[... "v2"])`
        # wrote a file that reloaded as `v2`.
        if self.version != invariants.version:
            raise ValueError(
                f"Dataset.version {self.version!r} does not match the "
                f"dataset_version {invariants.version!r} carried by its examples; "
                "Dataset.version is the version every row must carry (D-022)"
            )
        # Compact separators (no spaces) plus sorted keys give us a stable,
        # diff-friendly canonical form. `ensure_ascii=False` keeps non-ASCII
        # inputs human-readable on disk.
        lines = (
            json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            for record in records
        )
        atomic_write_text(path, "\n".join(lines) + "\n")


# --- loader -----------------------------------------------------------------

_REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "input",
    "expected_outputs",
    "dataset_version",
    "provenance",
)


# --- schema, shared by both sides of the seam (#235) -------------------------
#
# `_validate_record` ran on the load path only, so a `Dataset` assembled in
# Python wrote files `load_jsonl` refuses. #234 closed the *representability*
# half of that gap and its docstring scoped this half out explicitly. Measured
# on `main`, building a `Dataset` in Python, dumping, and reloading with this
# package's own loader:
#
#     id=123 / id=""                  wrote a file the loader refuses
#     input=123                       wrote a file the loader refuses
#     dataset_version=123 / ""        wrote a file the loader refuses
#     expected_outputs=()             wrote a file the loader refuses
#     tags=(1,)                       wrote a file the loader refuses
#     two examples sharing an id      wrote a file the loader refuses
#     mixed dataset_version           wrote a file the loader refuses
#     zero examples                   wrote a file the loader refuses
#     provenance=[]                   ROUND-TRIPPED, silently coerced to {}
#     tags="urgent"                   ROUND-TRIPPED, silently exploded to
#                                     ["u","r","g","e","n","t"] -- six tags
#     Dataset.version != row version  ROUND-TRIPPED, reloaded as the OTHER one
#
# The last three are the sharp ones and none was in #235's list. A refusal is
# loud; a silent coercion is not, and `Example.to_dict()` performs both of them
# (`dict(self.provenance)`, `list(self.tags)`) on the way to a record that is
# then perfectly well-formed. That is why the write-side check below runs
# against the `Example`'s own attributes and NOT against `to_dict()`'s output:
# by the time `tags="urgent"` reaches the record it is already a valid list of
# six strings, and no rule stated over the record can see what it was.
#
# One definition, called from both sides -- the neighbour #234 measured is a
# copy in the writer, which passes every behavioural test.


def _is_str(v: Any) -> bool:
    return isinstance(v, str)


def _is_non_empty_str(v: Any) -> bool:
    return isinstance(v, str) and bool(v)


def _is_mapping(v: Any) -> bool:
    # `Mapping`, not `dict`: a JSON object is always a `dict`, so this is
    # identical on the load path, and it is the honest spelling of the rule for
    # a caller who hands `Example` a `MappingProxyType` or a `Counter`.
    return isinstance(v, Mapping)


def _is_sequence_not_str(v: Any) -> bool:
    # `str` and `bytes` ARE sequences, and that is the whole hazard on the write
    # path: `list("urgent")` is a perfectly good list of strings. A JSON array
    # is a `list`, so excluding them changes nothing on the load path.
    return isinstance(v, Sequence) and not isinstance(v, (str, bytes, bytearray))


def _is_non_empty_sequence(v: Any) -> bool:
    return _is_sequence_not_str(v) and len(v) > 0


def _is_str_sequence(v: Any) -> bool:
    return _is_sequence_not_str(v) and all(isinstance(t, str) for t in v)


# (field name, predicate, the loader's exact reason text). The reasons are
# byte-identical to what `_validate_record` raised before this was extracted --
# six test files and the CLI's operator-facing output quote them.
_FIELD_RULES: tuple[tuple[str, Any, str], ...] = (
    ("id", _is_non_empty_str, "field 'id' must be a non-empty string"),
    ("input", _is_str, "field 'input' must be a string"),
    (
        "dataset_version",
        _is_non_empty_str,
        "field 'dataset_version' must be a non-empty string",
    ),
    ("provenance", _is_mapping, "field 'provenance' must be an object"),
    (
        "expected_outputs",
        _is_non_empty_sequence,
        "field 'expected_outputs' must be a non-empty list",
    ),
    ("tags", _is_str_sequence, "field 'tags' must be a list of strings"),
)

_FIELD_RULES_BY_NAME = {name: (pred, reason) for name, pred, reason in _FIELD_RULES}


def _find_field_violation(values: Mapping[str, Any], fields: Sequence[str]) -> str | None:
    """First broken per-field rule among *fields*, in the order given, or None.

    The order is a parameter because `_validate_record` interleaves its checks
    with building the `Example` -- `tags` is checked after the
    `expected_outputs` item loop, so a record with a bad tag AND a bad item
    reports the item. Passing the order preserves that exactly rather than
    quietly re-ranking the diagnosis while extracting the rule.
    """
    for name in fields:
        predicate, reason = _FIELD_RULES_BY_NAME[name]
        if not predicate(values[name]):
            return reason
    return None


class _DatasetInvariants:
    """The cross-record rules `load_jsonl` enforces, drivable one row at a time.

    Unique ids and a single `dataset_version` are properties of the *file*, not
    of a record, so they cannot live in `_find_field_violation`. They are shared
    as a small accumulator rather than as a function over the whole list
    because `load_jsonl` enforces them streaming, per line: collecting first
    would change *when* it fails on a large file, and which line number a
    later shape error reports.

    `dump_jsonl` drives the same accumulator over `self.examples` before writing
    a byte, so the writer refuses exactly what the reader would.
    """

    def __init__(self) -> None:
        self._seen_ids: set[str] = set()
        self.version: str | None = None

    def violation_for(self, row_id: str, row_version: str) -> str | None:
        if row_id in self._seen_ids:
            return f"duplicate id {row_id!r}; ids must be unique within a file"
        self._seen_ids.add(row_id)
        if self.version is None:
            self.version = row_version
        elif row_version != self.version:
            return (
                f"dataset_version {row_version!r} does not match file version "
                f"{self.version!r}; split mixed-version data into separate files"
            )
        return None


# --- representability (#213) ------------------------------------------------
#
# `load_jsonl` is this format's definition of "well-formed", and `dump_jsonl` is
# its canonical writer. The two disagreed on two classes of value, so
# `dump_jsonl`'s round-trip guarantee did not hold for them and
# `eval-harness validate` reported `findings=0` on both:
#
#   provenance: {"cost_usd": Infinity}
#       `json.loads` parses the bare `NaN` / `Infinity` / `-Infinity` tokens
#       natively, and `json.dumps` re-emits them. The resulting line is not
#       JSON. Measured on the emitted bytes: `JSON.parse` raises
#       `SyntaxError: Unexpected token 'I'`; `jq` 1.7.1 parses it *silently*,
#       turning `Infinity` into 1.7976931348623157e+308 and `NaN` into `null`
#       with no error and no exit code. The loud consumer is survivable; the
#       quiet one hands a pipeline a plausible wrong number.
#
#   input: "a\ud800b"
#       A lone surrogate is legal JSON escape syntax and Python decodes it, but
#       it is not encodable as UTF-8, so `dump_jsonl` died with
#       `UnicodeEncodeError` *after* the file had already validated clean.
#       Reproduced in `id`, `input` and `expected_outputs[].value` alike -- it
#       is a property of any string on the record, not of one field. RFC 8259
#       section 8.2 names unpaired surrogates as non-interoperable; they reach
#       traffic samples from broken UTF-16 handling upstream.
#
# Rejecting at load is the correct side of the seam. `dump_jsonl` could write
# with `errors="surrogatepass"`, but that puts invalid UTF-8 on disk, which is
# strictly worse than refusing the input; and there is no faithful JSON
# spelling of `NaN` to write at all.
#
# The finiteness half is not a new policy -- it is the contract `runner.py`
# already enforces on every numeric field it loads (#42, #185, #204), whose
# comment states this exact rationale ("egresses as an invalid bare `NaN`
# token ... which strict JSON parsers (the dashboard, `jq`, browser
# `JSON.parse`) reject"). `calibration.py` gets it for free because
# `human_score` is range-checked and `0.0 <= nan <= 1.0` is False. Of the sites
# this rule applies to, `dataset.py`'s free-form `provenance` was the one
# spelling that disagreed, and the only one behind a canonical writer.


def _find_unrepresentable(record: dict[str, Any]) -> tuple[str, str] | None:
    """Return ``(json_path, reason)`` for the first value the canonical writer
    cannot faithfully emit, or ``None`` when the whole record is representable.

    The *walk* lives in `io_utils.find_unrepresentable` (#217) so this seam and
    `calibration._row_from_dict` cannot answer differently for the same record;
    the *reasons* below are this seam's own, because they name what `dump_jsonl`
    specifically does with the value. Same split as `find_unencodable` (#215),
    one level up: shared detection, local consequence.
    """
    found = find_unrepresentable(record)
    if found is None:
        return None
    path, kind, detail = found
    if kind == UNENCODABLE:
        return path, (
            f"is not encodable as UTF-8 ({detail}); "
            "a lone surrogate is legal JSON escape syntax but has no UTF-8 "
            "encoding, so `dump_jsonl` raises UnicodeEncodeError on a file "
            "that otherwise validates clean"
        )
    if kind == NON_FINITE:
        return path, (
            f"is {detail}; dataset values must be finite. `dump_jsonl` emits a "
            "bare `NaN`/`Infinity` token, which is not JSON: `JSON.parse` "
            "rejects the line outright and `jq` silently coerces it to "
            "`null`/1.8e308"
        )
    if kind == NON_STRING_KEY:
        # The only kind that can carry an empty path: it is reported at the
        # dict that *holds* the key, and that dict is the record itself when
        # the bad key is top-level. Neither shipped caller can produce it —
        # `to_dict` writes literal `str` keys and `json.loads` only makes them
        # — but `field ''` is not a sentence, and a sixth site is exactly the
        # kind of caller that would arrive later and print it.
        return path or "(record root)", (
            f"has the non-string object key {detail}; `dump_jsonl` writes "
            "`json.dumps`, which coerces an int/float/bool/None key to a "
            'string — `{1: \'one\'}` is written `{"1": "one"}` and reloads '
            'as the string `"1"`, silently — and raises a bare TypeError '
            "for any other key type"
        )
    # Every kind `find_unrepresentable` can return must be spelled out here.
    # A fallthrough `return` would hand a *new* axis whichever message happens
    # to sit last in this function, which is how a guard ends up naming a harm
    # it did not find; the loud version is a bug report instead of a wrong
    # sentence in an operator's terminal.
    raise AssertionError(f"unhandled representability kind {kind!r} at {path!r}")


def _validate_record(raw: Any, line_no: int) -> Example:
    """Validate one parsed JSON object and return an `Example`.

    Each failure raises `DatasetLoadError(line_no, reason)` with a precise
    reason. We don't pull in jsonschema — the format is small enough that
    hand-rolled checks keep the package dependency-free and the error
    messages tailored.

    Beyond the per-field shape checks, the record is walked once for values the
    canonical writer cannot faithfully emit — non-finite numbers and strings
    with no UTF-8 encoding, at any depth including inside `provenance` (#213).
    See `_find_unrepresentable`.
    """
    if not isinstance(raw, dict):
        raise DatasetLoadError(
            line_no, f"top-level value must be JSON object, got {type(raw).__name__}"
        )

    missing = [f for f in _REQUIRED_FIELDS if f not in raw]
    if missing:
        raise DatasetLoadError(line_no, f"missing required field(s): {missing}")

    # Per-field type checks, from `_FIELD_RULES` so `dump_jsonl` enforces the
    # identical contract on the way out (#235). Order preserved exactly: `tags`
    # is still checked after the `expected_outputs` item loop below, so a record
    # with both a bad tag and a bad item still reports the item.
    tags_raw = raw.get("tags", [])
    values = {**raw, "tags": tags_raw}
    reason = _find_field_violation(
        values, ("id", "input", "dataset_version", "provenance", "expected_outputs")
    )
    if reason is not None:
        raise DatasetLoadError(line_no, reason)

    eo_raw = raw["expected_outputs"]

    expected_outputs: list[ExpectedOutput] = []
    for i, item in enumerate(eo_raw):
        if not isinstance(item, dict):
            raise DatasetLoadError(line_no, f"expected_outputs[{i}] must be an object")
        if "kind" not in item or "value" not in item:
            raise DatasetLoadError(line_no, f"expected_outputs[{i}] missing 'kind' or 'value'")
        try:
            expected_outputs.append(ExpectedOutput(kind=item["kind"], value=item["value"]))
        except ValueError as e:
            raise DatasetLoadError(line_no, f"expected_outputs[{i}]: {e}") from None

    reason = _find_field_violation(values, ("tags",))
    if reason is not None:
        raise DatasetLoadError(line_no, reason)

    # Reject any unknown top-level fields so typos don't silently no-op.
    allowed = set(_REQUIRED_FIELDS) | {"tags"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise DatasetLoadError(line_no, f"unknown top-level field(s): {unknown}")

    # Last, because shape errors are the more fundamental diagnosis and should
    # win the message when a record has both. This is the one choke point
    # `load_jsonl` and `validate_dataset` both route through, so the strict
    # loader and the collecting validator stay in lockstep by construction
    # rather than by two mirrored edits (#213).
    unrepresentable = _find_unrepresentable(raw)
    if unrepresentable is not None:
        path, reason = unrepresentable
        raise DatasetLoadError(line_no, f"field {path!r} {reason}")

    return Example(
        id=raw["id"],
        input=raw["input"],
        expected_outputs=tuple(expected_outputs),
        dataset_version=raw["dataset_version"],
        provenance=dict(raw["provenance"]),
        tags=tuple(tags_raw),
    )


def load_jsonl(path: str | Path) -> Dataset:
    """Load a JSONL golden dataset.

    Returns a `Dataset` whose `version` is the (single) dataset_version found
    on every line. Raises `DatasetLoadError(line_no, reason)` on the first
    malformed line — by design we fail fast rather than collecting errors, so
    that fixing the file is an iterative process the user can drive.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    invariants = _DatasetInvariants()
    examples: list[Example] = []

    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            stripped = raw_line.strip()
            if not stripped:
                # Blank lines aren't part of the format. Be strict about it —
                # silent skips hide accidental empty rows from broken pipelines.
                raise DatasetLoadError(
                    line_no, "blank line; dataset must have one JSON object per line"
                )
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise DatasetLoadError(line_no, f"invalid JSON: {e.msg}") from None

            ex = _validate_record(parsed, line_no)

            # Unique ids + a single dataset_version, from the accumulator
            # `dump_jsonl` also drives (#235), so the writer refuses exactly
            # what this loop would.
            reason = invariants.violation_for(ex.id, ex.dataset_version)
            if reason is not None:
                raise DatasetLoadError(line_no, reason)

            examples.append(ex)

    if not examples:
        raise DatasetLoadError(0, f"dataset file {path} contains no examples")

    version = invariants.version
    assert version is not None  # narrows for type checkers; populated above by the first valid line
    return Dataset(version=version, examples=examples, source_path=path)


def iter_jsonl(path: str | Path) -> Iterable[Example]:
    """Lazy iterator variant for very large dataset files.

    Identical validation to `load_jsonl` but yields examples one at a time
    without holding the full list in memory. Mostly useful for the regression
    runner (#3); the test suite uses `load_jsonl`.
    """
    ds = load_jsonl(path)  # placeholder eager impl; replace when issue #3 needs it
    yield from ds.examples


def filter_examples_by_tags(
    examples: Iterable[Example], tags: Iterable[str] | None
) -> list[Example]:
    """Return examples whose tag set intersects `tags` (set-union match).

    - `tags=None` or empty → no filter (return every example).
    - Otherwise an example is kept iff `set(example.tags) & set(tags)` is non-empty.

    The match is *any-of*, not *all-of*: this is the right default for an
    operator who wants to score "the geometry cluster or the history cluster
    in one shot". Strict-intersection (`--require-all-tags`) is a future
    extension if anyone asks; it's deliberately out-of-scope for issue #15.
    """
    materialized = list(examples)
    if not tags:
        return materialized
    wanted = set(tags)
    return [ex for ex in materialized if wanted & set(ex.tags)]


def collect_tag_inventory(examples: Iterable[Example]) -> list[str]:
    """Return the sorted, de-duplicated tag inventory for an example list.

    Used to produce a helpful stderr message when `--tags` matches zero rows.
    """
    inv: set[str] = set()
    for ex in examples:
        inv.update(ex.tags)
    return sorted(inv)


# --- validator (#56) --------------------------------------------------------


@dataclass(frozen=True)
class ValidationFinding:
    """One row-level issue surfaced by ``validate_dataset``.

    Mirrors the ``DatasetLoadError`` shape — ``line_no`` is 1-indexed and
    points at the offending line, ``reason`` is the same human-readable
    string the loader produces. ``code`` distinguishes shapes the JSON
    consumer can route on without parsing prose.
    """

    line_no: int
    reason: str
    code: str

    def to_dict(self) -> dict[str, Any]:
        return {"line_no": self.line_no, "reason": self.reason, "code": self.code}


@dataclass(frozen=True)
class ValidationReport:
    """Result of walking a dataset in collecting mode.

    ``ok`` is true iff zero findings AND the file contained at least one
    valid example (an empty file is a finding shape, not a healthy state).

    ``dataset_version`` is the first ``dataset_version`` observed on a
    valid line, or ``None`` if no valid lines were parsed. ``tag_counts``
    is computed over the valid examples only — invalid rows can't
    contribute tag-presence signal without conflating shape errors with
    coverage gaps.
    """

    path: str
    n_rows: int
    n_valid: int
    findings: tuple[ValidationFinding, ...]
    dataset_version: str | None
    tag_counts: tuple[tuple[str, int], ...]

    @property
    def ok(self) -> bool:
        return not self.findings and self.n_valid > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "ok": self.ok,
            "n_rows": self.n_rows,
            "n_valid": self.n_valid,
            "dataset_version": self.dataset_version,
            "tag_counts": [{"tag": t, "count": c} for t, c in self.tag_counts],
            "findings": [f.to_dict() for f in self.findings],
        }


def validate_dataset(path: str | Path) -> ValidationReport:
    """Walk a JSONL golden dataset in *collecting* mode.

    Unlike ``load_jsonl``, which raises on the first ``DatasetLoadError``,
    this surfaces every malformed row in one pass so the operator can
    fix all of them before the next ``eval-harness run`` invocation
    (which would otherwise spend judge tokens up to the first bad row).

    Detected finding shapes:

    - ``parse``         — JSON decode failure or blank line.
    - ``schema``        — record-level validation failure (missing fields,
                          bad types, unknown ``expected_outputs.kind``,
                          unknown top-level fields, and values that are not
                          representable in canonical JSONL — non-finite numbers
                          or non-UTF-8-encodable strings at any depth, #213).
                          Mirrors ``load_jsonl``'s ``_validate_record`` checks;
                          both call it, so the two cannot drift apart.
    - ``duplicate_id``  — a row's ``id`` collides with a prior row's.
    - ``version_drift`` — a row's ``dataset_version`` doesn't match the
                          first valid row's. (Datasets are atomic units;
                          mixed-version files belong in separate files.)
    - ``empty``         — file contains zero valid examples; the loader
                          treats this as a hard error and so does the
                          validator (one finding with ``line_no=0``).

    A ``FileNotFoundError`` (missing path) propagates so the CLI can
    surface it as exit 2 alongside other I/O errors.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    findings: list[ValidationFinding] = []
    seen_ids: dict[str, int] = {}
    version: str | None = None
    n_rows = 0
    n_valid = 0
    valid_examples: list[Example] = []

    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            n_rows += 1
            stripped = raw_line.strip()
            if not stripped:
                findings.append(
                    ValidationFinding(
                        line_no=line_no,
                        reason="blank line; dataset must have one JSON object per line",
                        code="parse",
                    )
                )
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as e:
                findings.append(
                    ValidationFinding(
                        line_no=line_no, reason=f"invalid JSON: {e.msg}", code="parse"
                    )
                )
                continue
            try:
                ex = _validate_record(parsed, line_no)
            except DatasetLoadError as e:
                findings.append(ValidationFinding(line_no=line_no, reason=e.reason, code="schema"))
                continue

            if ex.id in seen_ids:
                findings.append(
                    ValidationFinding(
                        line_no=line_no,
                        reason=(
                            f"duplicate id {ex.id!r}; first seen at line "
                            f"{seen_ids[ex.id]}; ids must be unique within a file"
                        ),
                        code="duplicate_id",
                    )
                )
                # Don't add the duplicate to valid_examples — it shadows
                # the original and would skew the tag histogram.
                continue

            if version is None:
                version = ex.dataset_version
            elif ex.dataset_version != version:
                findings.append(
                    ValidationFinding(
                        line_no=line_no,
                        reason=(
                            f"dataset_version {ex.dataset_version!r} does not match "
                            f"file version {version!r}"
                        ),
                        code="version_drift",
                    )
                )
                # Version-drifted rows are dropped from `valid_examples`
                # so the tag histogram reflects the file's nominal version.
                continue

            # Reserve the id only once a row actually becomes valid. A rejected
            # row (schema or version-drift) must not claim its id, or a later
            # valid row reusing it would get a spurious `duplicate_id` finding
            # pointing at a row that isn't in the valid set. This mirrors the
            # schema-rejection path above, which `continue`s before this line.
            seen_ids[ex.id] = line_no
            valid_examples.append(ex)
            n_valid += 1

    if n_valid == 0 and not findings:
        # File was empty (no lines at all). Surface as a single finding so
        # `ok` is False without an extra `empty=True` flag on the report.
        findings.append(
            ValidationFinding(
                line_no=0, reason=f"dataset file {path} contains no examples", code="empty"
            )
        )

    tag_counter: Counter[str] = Counter()
    for ex in valid_examples:
        tag_counter.update(ex.tags)
    # Sort by descending count, then alphabetically — deterministic for
    # JSON snapshots and useful for the operator (most-common tag first).
    tag_counts = tuple(sorted(tag_counter.items(), key=lambda kv: (-kv[1], kv[0])))

    return ValidationReport(
        path=str(path),
        n_rows=n_rows,
        n_valid=n_valid,
        findings=tuple(findings),
        dataset_version=version,
        tag_counts=tag_counts,
    )
