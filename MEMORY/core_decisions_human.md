# Core Decisions

Strategic decisions for this repo, with reasoning. Append-only — superseded decisions are marked, not removed.

## D-001 — Scope locked to portfolio handoff §2 (2026-05-10)
**Decision:** Scope of this repo is fixed by the portfolio handoff document, section 2.

**Why:** The handoff spec was deliberated; ad-hoc scope expansion within a session is the failure mode this prevents.

**Alternatives considered:** None — this is a baseline.

**Reversibility:** Expensive. Scope changes require a deliberate revisit and a new decision entry.

**Related issues:** —

## D-002 — `expected_outputs` is a list of typed objects (2026-05-11)
**Decision:** Each acceptable answer in a golden dataset is `{kind, value}` rather than a plain string. `kind` is one of `exact | semantic | regex`.

**Why:** The judge wrapper (#2) needs to know how to compare each expected output — exact-match for short factual answers, embedding/LLM judgment for semantic equivalence, regex for span-based assertions. Encoding the comparator with the data avoids a separate "how to compare this row" config that drifts from the data, and means the format is forward-compatible with new `kind`s without a schema revision.

**Alternatives considered:**
- `list[str]` (plain strings) — rejected: would force one global comparator per dataset, or a sidecar config keyed by id. Both are worse.
- Single `expected: str` field — rejected: real factual QA routinely has multiple acceptable answers ("Paris" / "Paris, France"), and short-answer eval needs them.

**Reversibility:** Cheap. The dataset format is opaque to consumers other than the loader; we can migrate `v0.1 → v0.2` if needed.

**Related issues:** #1, #2

## D-003 — `dataset_version` is opaque metadata (2026-05-11)
**Decision:** `dataset_version` is a free-form string owned by the dataset author. The loader treats it as opaque and only enforces that it's identical across every line in a file.

**Why:** Different datasets have different versioning conventions (semver, date-stamped, domain-stamped). Forcing one convention buys nothing — the harness only needs the version to be (a) stable per file and (b) a join key for PR-comment eval diffs. Both work with any non-empty string.

**Alternatives considered:**
- Require semver in the loader — rejected: authors already use whatever convention fits their data; this would just force them to invent fake versions.
- Allow mixed versions in a single file — rejected: makes the PR-comment join key ambiguous and hides bad data merges.

**Reversibility:** Cheap. Stricter validation can be layered on later without changing the on-disk format.

**Related issues:** #1, #6

## D-004 — Judge backend is a single-method `Backend` Protocol (2026-05-15)
**Decision:** `eval_harness.judge.Backend` is a Protocol with one method, `complete(system: str, user: str) -> str`. `Judge` takes any conforming backend. The production binding is `AnthropicBackend`; tests use a deterministic dict-lookup stub.

**Why:** The judge wrapper has to be testable without an API key, otherwise CI gates on a paid resource (the failure mode that makes test suites brittle). A single-method Protocol is the smallest possible seam — implementations don't inherit, they just expose `complete`. Adding a new provider is one new class with one method, no framework plumbing.

**Alternatives considered:**
- Hard-coded Anthropic client inside `Judge` — rejected: tests would need the SDK installed and an API key set even for unit-level work.
- Abstract base class — rejected: adds unnecessary inheritance ceremony for what's structurally a one-method seam.
- Dependency-injection container — rejected: gross overkill for one optional dependency.

**Reversibility:** Cheap. Protocol shape can grow methods in a backward-compatible way (defaults on the base or `hasattr` checks at the call site).

**Related issues:** #2, #3

## D-005 — Calibration metrics: Cohen's κ on binarized + Pearson r on continuous; only κ gates CI (2026-05-15)
**Decision:** The calibration step computes two metrics: Cohen's κ on scores binarized at threshold 0.5 and Pearson r on continuous scores. Both go in the calibration report. Only κ ≥ 0.6 gates CI.

**Why:** A judge that's "almost always right" on the binary call (correct/incorrect) but systematically scores 0.7 where humans say 0.9 has high κ but low r — the binary call agrees, but the magnitudes drift. Reporting both lets the operator see *which* dimension regressed when calibration moves. κ is the gate because the regression runner downstream consumes binary pass/fail signals; r is informational for now (and useful when the runner gains a continuous-comparison mode).

**Alternatives considered:**
- κ only — rejected: hides systematic over/under-scoring biases.
- r only — rejected: too lenient (high r with always-too-high scores still passes).
- MSE/MAE — rejected: less interpretable than κ for a `yes this is faithful / no it isn't` decision.
- Accuracy at threshold — rejected: equivalent to κ when classes are balanced, *worse* than κ when they aren't (chance-correction matters).

**Reversibility:** Cheap. Adding a third metric is a one-line change in `CalibrationResult`.

**Related issues:** #2

## D-006 — Calibration set is self-labeled with explicit honest disclosure (2026-05-15)
**Decision:** `fixtures/calibration.jsonl` is a 50-row set self-labeled by jt-mchorse on 2026-05-15, with the limitations spelled out in `docs/calibration_format.md` and on every row's `provenance`. The set is intentionally distributed across the score axis (clear-positive, partial credit, clear-negative, refusal, off-topic, subtle errors, edge cases) so that a judge that only handles clear cases doesn't pass calibration.

**Why:** A multi-rater calibration set is the right long-term answer, but blocking the judge wrapper on it would mean blocking every downstream eval on a multi-month calibration project. The pragmatic move is to ship a smaller self-labeled set with the limitations explicitly disclosed, and let the κ ≥ 0.6 threshold (which is calibrated against this single-labeler set) be the working baseline. When a multi-rater set lands, it supersedes this one via a new D-NNN with a fresh κ baseline.

**Alternatives considered:**
- Require multi-rater calibration before shipping the judge — rejected: blocks the rest of the portfolio for months.
- Ship the judge without a calibration set — rejected: the judge then has no measurable agreement-with-humans claim, which is the whole point of the calibration step.
- Generate the set with an LLM — rejected: makes the calibration self-referential (a judge measured against a judge isn't measured against humans at all).

**Reversibility:** Cheap. The set is small enough to relabel from scratch in ~30 minutes; supersede via a new D-NNN when better data arrives.

**Related issues:** #2
