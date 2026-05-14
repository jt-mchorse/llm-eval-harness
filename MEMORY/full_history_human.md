# Session History (human-readable)

Chronological log of work sessions. Most recent first below the divider.

---

## 2026-05-11 — Issue #1: Golden dataset JSONL format

**Duration:** ~55 min · **Branch:** `session/2026-05-11-issue-01` · **PR:** [#8](https://github.com/jt-mchorse/llm-eval-harness/pull/8) (draft)

- Stood up the `eval_harness` package skeleton with PEP 621 / hatchling and a deliberately dependency-free dataset layer so it can be imported in CI sandboxes and downstream repos without dragging in API SDKs.
- Shipped `load_jsonl` + `Dataset.dump_jsonl` + `DatasetLoadError(line_no, reason)` plus a hand-rolled validator (no jsonschema dep). Canonical dump form (sorted keys, compact separators) gives byte-equal round trip on well-formed input.
- Documented the format in `docs/dataset-format.md`, shipped a 10-line factual-QA fixture with full provenance, and 15 pytest cases covering happy path, round-trip identity, and every malformed-line case the loader promises to catch.

**Why this work, this session:** Issue #1 is the foundational contract every other eval surface (#2 judge wrapper, #3 regression runner, #6 PR-comment Action) depends on, and it was the lowest unassigned `priority:high` in the repo at the start of the eval-spine build sequence.

**Open questions / blockers:** None — PR is draft pending JT review.

**Next session:** Start on #2 (LLM-as-judge wrapper) — natural consumer of `expected_outputs[i].kind == "semantic"`.
