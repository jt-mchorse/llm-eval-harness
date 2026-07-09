"""Atomicity contract for `eval_harness.io_utils.atomic_write_text` (issue #50).

PR #49 closed the four `--out` write sites in `eval_harness/cli.py` against
the `Path.write_text` partial-write harm class by routing them through a
file-private `_atomic_write_text` helper. PR #49's memory called out three
remaining non-atomic `.write_text` sites in the package, deferred:

- `eval_harness/drift.py:679` — HTML drift report
- `eval_harness/dataset.py:145` — JSONL golden dataset
- `eval_harness/cli.py:279` — `calibrate --report` HTML

This PR promotes the helper to a package-level public symbol
(`eval_harness.io_utils.atomic_write_text`) and routes every remaining
non-atomic write site through it. The portfolio standard from the
2026-05-26 atomic-write arc is package-level helpers (see
`rag_kit/io_utils.atomic_write_text` in `rag-production-kit#44/#45`); a
file-private helper in `cli.py` was the outlier.

What this file pins:

1. **Helper unit contract** (6 tests): happy path, parent-dir creation,
   overwrite, the three load-bearing invariants — destination unchanged
   when `os.replace` raises during overwrite, no leftover `.tmp` siblings
   after failure, destination absent when `os.replace` raises during
   new-file create.
2. **Per-call-site integration** (3 tests): each *new* call site
   (drift `--output`, dataset `dump_jsonl`, calibrate `--report`) routes
   through the public helper. Pattern mirrors `test_cli_atomic_out.py`
   for the existing four CLI sites.
3. **Cross-cutting invariants** (2 tests): the dataset's documented
   round-trip byte-stability survives the atomic-helper integration;
   and the helper's `encoding` parameter is honored for non-ASCII text.

Note: the existing `tests/test_cli_atomic_out.py` keeps its 5 CLI `--out`
integration tests (run / diff / diff-json / list); its 6 unit tests on
the helper moved here so the unit suite has a single home colocated with
the helper.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness import io_utils as io_utils_mod
from eval_harness.cli import main as cli_main
from eval_harness.dataset import load_jsonl
from eval_harness.drift import cli as drift_cli
from eval_harness.io_utils import atomic_write_text

# ---------------------------------------------------------------------------
# Unit tests on the helper itself.
# Moved from tests/test_cli_atomic_out.py; same invariants, new home.
# ---------------------------------------------------------------------------


def test_atomic_write_text_happy_path(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    atomic_write_text(out, "hello\nworld\n")
    assert out.read_text(encoding="utf-8") == "hello\nworld\n"


def test_atomic_write_text_creates_parent_dirs(tmp_path: Path) -> None:
    out = tmp_path / "deep" / "nested" / "x.json"
    assert not out.parent.exists()
    atomic_write_text(out, "{}")
    assert out.read_text(encoding="utf-8") == "{}"


def test_atomic_write_text_overwrites_existing_file(tmp_path: Path) -> None:
    """Existing destination with stale content is replaced wholly — never appended."""
    out = tmp_path / "out.txt"
    out.write_text("STALE-CONTENT-MUST-NOT-SURVIVE", encoding="utf-8")
    atomic_write_text(out, "fresh")
    body = out.read_text(encoding="utf-8")
    assert body == "fresh"
    assert "STALE" not in body


def test_atomic_write_text_replace_failure_leaves_destination_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Load-bearing atomicity invariant.

    If `os.replace` raises (simulating `EXDEV` cross-device, a SIGINT
    delivered between fsync and rename, or `PermissionError`), the
    destination must not exist. The helper must never touch the
    destination directly — only via the atomic rename.
    """
    out = tmp_path / "result.json"

    def boom(*_args, **_kwargs):
        raise OSError("simulated mid-rename failure")

    monkeypatch.setattr(io_utils_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated mid-rename failure"):
        atomic_write_text(out, '{"k": "v"}')

    assert not out.exists(), "destination must remain absent when os.replace fails"


def test_atomic_write_text_replace_failure_cleans_up_tmp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No leftover `.tmp` siblings after a failed atomic write."""
    out = tmp_path / "artifacts" / "delta.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    def boom(*_args, **_kwargs):
        raise OSError("simulated mid-rename failure")

    monkeypatch.setattr(io_utils_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated mid-rename failure"):
        atomic_write_text(out, '{"k": "v"}')

    siblings = list(out.parent.iterdir())
    assert siblings == [], f"expected no temp leftovers in {out.parent}, got {siblings}"


def test_atomic_write_text_destination_unchanged_when_overwriting_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When overwriting an existing file, a failed `os.replace` must leave the
    pre-existing destination contents intact — not zero-length, not partial,
    not the new content. The property `Path.write_text` could never offer.
    """
    out = tmp_path / "existing.json"
    out.write_text('{"keep": true}', encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("simulated")

    monkeypatch.setattr(io_utils_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated"):
        atomic_write_text(out, '{"overwrite": true}')

    assert out.read_text(encoding="utf-8") == '{"keep": true}'


# ---------------------------------------------------------------------------
# Integration: each new call site routes through atomic_write_text.
# Pattern: monkeypatch io_utils.os.replace to raise, exercise the surface,
# assert the destination is untouched.
# ---------------------------------------------------------------------------


# Minimal fixture for drift and dataset paths.

GOLDEN_JSONL = (
    '{"id": "qa_001", "input": "What is 1+1?", "expected_outputs":'
    ' [{"kind": "exact", "value": "2"}], "tags": [], "dataset_version":'
    ' "smoke-v1", "provenance": {"source": "synthetic"}}\n'
)
CANDIDATE_JSONL = (
    '{"id": "qa_001", "input": "What is 1+1?", "expected_outputs":'
    ' [{"kind": "exact", "value": "2"}], "tags": [], "dataset_version":'
    ' "smoke-v1", "provenance": {"source": "synthetic"}}\n'
)


def test_drift_output_routes_through_atomic_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`drift --output` (drift.cli) must route through the atomic helper.

    The drift HTML report is the workflow-artifact surface for the eval
    diff and the local-dev quick-look. A half-written HTML aborts in the
    browser parser or, worse, lands as a workflow artifact for download.
    """
    # drift._load_inputs_jsonl accepts bare strings; compute_drift needs
    # several rows to exercise the kmeans cluster axis without degenerating.
    golden = tmp_path / "golden.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    golden_rows = "\n".join(json.dumps(f"golden input {i}") for i in range(12)) + "\n"
    candidate_rows = "\n".join(json.dumps(f"candidate input {i}") for i in range(12)) + "\n"
    golden.write_text(golden_rows, encoding="utf-8")
    candidate.write_text(candidate_rows, encoding="utf-8")
    out = tmp_path / "drift_report.html"

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(io_utils_mod.os, "replace", boom)
    rc = drift_cli(
        [
            "--golden",
            str(golden),
            "--candidate",
            str(candidate),
            "--output",
            str(out),
            "--cluster-k",
            "2",
        ]
    )

    # #104 write-seam sibling: an unwritable --output is an I/O error → clean
    # exit 2, not a raw OSError traceback at exit 1. atomic_write_text still
    # guarantees the destination is untouched on a failed rename.
    assert rc == 2
    assert not out.exists(), "drift --output must not write destination when replace fails"


def test_dataset_dump_jsonl_routes_through_atomic_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Dataset.dump_jsonl` must route through the atomic helper.

    A half-written JSONL dataset is the worst shape: downstream readers
    iterate row-by-row and either silently truncate or raise
    `json.JSONDecodeError` partway through. With overwrite atomicity,
    the pre-existing file remains intact on failure.
    """
    src = tmp_path / "in.jsonl"
    src.write_text(GOLDEN_JSONL, encoding="utf-8")
    ds = load_jsonl(src)

    out = tmp_path / "out.jsonl"
    out.write_text("PRE-EXISTING\n", encoding="utf-8")  # for the overwrite invariant

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(io_utils_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated rename failure"):
        ds.dump_jsonl(out)

    assert out.read_text(encoding="utf-8") == "PRE-EXISTING\n", (
        "dump_jsonl must leave existing file intact on rename failure"
    )


def test_calibrate_report_routes_through_atomic_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`eval-harness calibrate --report` must route through the atomic helper.

    Sibling to the four `--out` sites PR #49 already hardened; was
    overlooked because `--report` is a different argument name.
    """
    # Synthesize a tiny calibration set; one row is enough for the
    # report-write path to be exercised end-to-end. Schema per
    # eval_harness.calibration._row_from_dict.
    calibration = tmp_path / "cal.jsonl"
    calibration.write_text(
        json.dumps(
            {
                "id": "c1",
                "prompt": "Is 1+1=2?",
                "response": "Yes.",
                "rubric": "be brief",
                "human_score": 1.0,
                "provenance": {"source": "synthetic"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "calibration_report.md"

    class _DeterministicBackend:
        def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
            self.model = model or "fake"
            self.max_tokens = max_tokens

        def complete(self, system: str, user: str) -> str:
            return "SCORE: 1.0\nREASONING: matches human\n"

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    # Patch BEFORE running so the failure surfaces at the write step.
    monkeypatch.setattr(io_utils_mod.os, "replace", boom)
    monkeypatch.setattr("eval_harness.cli.AnthropicBackend", _DeterministicBackend)

    rc = cli_main(
        [
            "calibrate",
            "--calibration",
            str(calibration),
            "--report",
            str(out),
            "--threshold-kappa",
            "0.0",  # avoid κ-gate exit before write
        ]
    )

    # #104 write-seam sibling: an unwritable --report is an I/O error → clean
    # exit 2, not a raw OSError traceback at exit 1. Atomicity invariant holds.
    assert rc == 2
    assert not out.exists(), "calibrate --report must not write destination when replace fails"


# ---------------------------------------------------------------------------
# Cross-cutting invariants.
# ---------------------------------------------------------------------------


def test_dataset_round_trip_byte_stable_through_atomic_helper(tmp_path: Path) -> None:
    """The dataset.py docstring claims load → dump → reload is byte-stable.

    Pin that the atomic-helper integration didn't regress this invariant —
    canonical-form JSONL written by `dump_jsonl` must be byte-stable across
    a dump → load → dump roundtrip.
    """
    # Use a non-empty `tags` so the to_dict shape is fully populated; if
    # `dump_jsonl` happens to drop optional empty fields, we want to test
    # the round-trip identity, not the canonical-form-with-empties shape.
    src = tmp_path / "src.jsonl"
    src.write_text(
        json.dumps(
            {
                "dataset_version": "v1",
                "expected_outputs": [{"kind": "exact", "value": "2"}],
                "id": "qa_001",
                "input": "What is 1+1?",
                "provenance": {"source": "synthetic"},
                "tags": ["math"],
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    ds = load_jsonl(src)

    first_dump = tmp_path / "first.jsonl"
    second_dump = tmp_path / "second.jsonl"
    ds.dump_jsonl(first_dump)
    load_jsonl(first_dump).dump_jsonl(second_dump)
    # dump → load → dump must be byte-stable — this is what the docstring
    # promises and what the canonical form makes guarantee-able.
    assert first_dump.read_bytes() == second_dump.read_bytes()


def test_atomic_write_text_honors_encoding_parameter(tmp_path: Path) -> None:
    """Public API exposes `encoding`; non-utf-8 callers must be able to opt in."""
    out = tmp_path / "latin.txt"
    # Payload uses only characters expressible in latin-1 — the test is
    # whether the helper threads `encoding` through to NamedTemporaryFile,
    # not whether the codec accepts every Unicode char.
    payload = "café naïveté"
    atomic_write_text(out, payload, encoding="latin-1")
    # Read back with the matching encoding to confirm the bytes were written
    # using `latin-1`, not silently downgraded to utf-8.
    assert out.read_text(encoding="latin-1") == payload
    # And the on-disk bytes are exactly the latin-1 encoding of the payload,
    # which is different from the utf-8 encoding for these characters.
    assert out.read_bytes() == payload.encode("latin-1")
    assert out.read_bytes() != payload.encode("utf-8")
