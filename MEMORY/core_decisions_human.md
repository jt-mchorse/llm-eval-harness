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
