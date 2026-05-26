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

Acceptable `expected_outputs[i].kind` values are listed in
`ExpectedOutput.VALID_KINDS`. New kinds may be added in a minor version of the
harness; readers must reject unknown kinds with a clear error rather than
silently accepting them, because eval semantics depend on the kind.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from eval_harness.io_utils import atomic_write_text


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
        if self.kind not in self.VALID_KINDS:
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
        """
        path = Path(path)
        # Compact separators (no spaces) plus sorted keys give us a stable,
        # diff-friendly canonical form. `ensure_ascii=False` keeps non-ASCII
        # inputs human-readable on disk.
        lines = (
            json.dumps(ex.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            for ex in self.examples
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


def _validate_record(raw: Any, line_no: int) -> Example:
    """Validate one parsed JSON object and return an `Example`.

    Each failure raises `DatasetLoadError(line_no, reason)` with a precise
    reason. We don't pull in jsonschema — the format is small enough that
    hand-rolled checks keep the package dependency-free and the error
    messages tailored.
    """
    if not isinstance(raw, dict):
        raise DatasetLoadError(
            line_no, f"top-level value must be JSON object, got {type(raw).__name__}"
        )

    missing = [f for f in _REQUIRED_FIELDS if f not in raw]
    if missing:
        raise DatasetLoadError(line_no, f"missing required field(s): {missing}")

    # Per-field type checks.
    if not isinstance(raw["id"], str) or not raw["id"]:
        raise DatasetLoadError(line_no, "field 'id' must be a non-empty string")
    if not isinstance(raw["input"], str):
        raise DatasetLoadError(line_no, "field 'input' must be a string")
    if not isinstance(raw["dataset_version"], str) or not raw["dataset_version"]:
        raise DatasetLoadError(line_no, "field 'dataset_version' must be a non-empty string")
    if not isinstance(raw["provenance"], dict):
        raise DatasetLoadError(line_no, "field 'provenance' must be an object")

    eo_raw = raw["expected_outputs"]
    if not isinstance(eo_raw, list) or not eo_raw:
        raise DatasetLoadError(line_no, "field 'expected_outputs' must be a non-empty list")

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

    tags_raw = raw.get("tags", [])
    if not isinstance(tags_raw, list) or not all(isinstance(t, str) for t in tags_raw):
        raise DatasetLoadError(line_no, "field 'tags' must be a list of strings")

    # Reject any unknown top-level fields so typos don't silently no-op.
    allowed = set(_REQUIRED_FIELDS) | {"tags"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise DatasetLoadError(line_no, f"unknown top-level field(s): {unknown}")

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

    seen_ids: set[str] = set()
    examples: list[Example] = []
    version: str | None = None

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

            if ex.id in seen_ids:
                raise DatasetLoadError(
                    line_no, f"duplicate id {ex.id!r}; ids must be unique within a file"
                )
            seen_ids.add(ex.id)

            if version is None:
                version = ex.dataset_version
            elif ex.dataset_version != version:
                raise DatasetLoadError(
                    line_no,
                    f"dataset_version {ex.dataset_version!r} does not match file version {version!r}; "
                    "split mixed-version data into separate files",
                )

            examples.append(ex)

    if not examples:
        raise DatasetLoadError(0, f"dataset file {path} contains no examples")

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
