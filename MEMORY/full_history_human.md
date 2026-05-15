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

## 2026-05-15 — Issue #2: LLM-as-judge wrapper + calibration
**Duration:** ~80 min · **Branch:** `session/2026-05-15-1325-issue-02`

- Shipped `eval_harness/judge.py`: `Judge` class wrapping a single-method `Backend` Protocol (D-004), production binding `AnthropicBackend`, deterministic stub for tests. Strict `SCORE: ...\nREASONING: ...` parser with score-clamping.
- Shipped `eval_harness/calibration.py`: hand-rolled Cohen's κ + Pearson r (no scipy), tested against textbook examples; `calibrate(judge, rows)` runs every row through the judge and computes both metrics; `render_report()` formats the markdown with PASS/FAIL tag.
- Shipped 50-row `fixtures/calibration.jsonl` distributed across the score axis (clear-positive, partial credit, clear-negative, refusals, off-topic, subtle errors, edge cases). Honest single-labeler disclosure (D-006).
- Shipped `eval-harness judge calibrate` CLI: writes `docs/calibration_report.md`, exits non-zero if Cohen's κ < threshold (default 0.6).
- Wired up real CI: `ruff check` + `ruff format --check` + `pytest --cov` matrix on py3.11/3.12, replacing the stub `echo` jobs.
- Backfilled README "What this is" / "Calibration" / "Quickstart" sections; rewrote `docs/architecture.md` with the three-layer diagram and the calibration-flow diagram.
- Closed issue #1 with verification (PR #8 had merged the work yesterday but the issue stayed open because the PR body lacked `Closes #1`).

**Why this work, this session:** Every downstream eval (#3 regression runner, #5 pytest plugin, #6 PR-comment Action) depends on the judge layer; without calibration the judge is just a wrapper with no agreement-with-humans claim. Locking the four decisions (D-004 backend protocol, D-005 metric pair, D-006 self-labeled disclosure) prevents re-litigating in #3.

**Open questions / blockers:** Calibration κ measurement requires the operator to run `eval-harness judge calibrate` against a real Anthropic API once. The infrastructure is shipped; the report number itself is honestly marked pending in the README.

**Next session:** Issue #3 (regression runner with per-model diffing) — both `Dataset` and `Judge` are now shipped, so #3 is unblocked.
