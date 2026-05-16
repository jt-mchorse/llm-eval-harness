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

## D-007 — AnswerSource is a separate Protocol from judge Backend (2026-05-15)
**Decision:** The regression runner introduces an `AnswerSource` Protocol with one method, `answer(example) -> str`, distinct from the existing `Backend` Protocol used by the judge. The default `DatasetEchoSource` echoes the example's first `expected_outputs.value` so the runner can be exercised hermetically; real model-under-test sources land when a consumer needs one.

**Why:** The model under test and the judge model are conceptually different roles, and conflating them would either lock callers into "score model X with model X's own judge" (which defeats the point of LLM-as-judge) or require role-flag hacks on `Backend`. Two narrow protocols are cleaner than one wide one.

**Alternatives considered:**
- Merge `AnswerSource` into `Backend` with a `role` argument — rejected: makes the contract muddier and harder to substitute in tests.
- Single backend that serves both roles — rejected: same reason.

**Reversibility:** Cheap. Both protocols have one method each.

**Related issues:** #3

## D-008 — Run history persisted in SQLite, two tables, foreign key enforced (2026-05-15)
**Decision:** Run history is stored in a single SQLite file (default `~/.eval-harness/runs.db`, override via `--db`) with two tables: `runs` for aggregate metadata, `rows` for per-example scores, joined on `run_id`. `init_db(path)` is idempotent (`CREATE TABLE IF NOT EXISTS`); the `PRAGMA foreign_keys = ON` is set on every connection so the `rows.run_id` FK is actually enforced.

**Why:** Diffs are conceptually a join, and SQLite is the smallest-possible substrate that makes joins fast without adding a dependency. JSON-lines history would force per-diff scans; Postgres or Mongo would force a service. The PRAGMA is documented as load-bearing because SQLite silently drops orphan rows without it.

**Alternatives considered:**
- JSON-lines history (no indexes) — rejected: every diff becomes an O(N runs × N rows) scan.
- Postgres/Mongo — rejected: forces a service for a library that's supposed to run locally and in CI.
- No persistence, only in-memory diffs against a passed-in baseline — rejected: callers would need to manage history themselves, recreating this layer in each consumer.

**Reversibility:** Cheap. Two `CREATE TABLE` statements; export/import is a `.dump` away.

**Related issues:** #3, #4 (drift detection consumes this), #6 (GitHub Action persists CI runs here)

## D-009 — Sticky PR comment identified by hidden HTML marker, not author/title (2026-05-16)
**Decision:** The eval-harness PR-comment workflow uses a hidden `<!-- eval-harness:sticky-comment -->` HTML marker embedded in the comment body to find its prior comment when upserting. Matching is "marker substring appears in body"; first-match wins. The bot does *not* identify its prior comments by author name or by title parsing.

**Why:** Marker-based identity survives bot renames, token rotations, the same action running from multiple repos under different bot identities, and even a human editing the comment first. Title or author matching breaks under any of those. The downside — someone could spoof the marker in their own comment — is accepted: spoofing is a deliberate prank, not a security failure, and the worst case is "the bot edits the wrong comment", which is reversible.

**Alternatives considered:**
- Match on comment author username — rejected: changes when the token rotates; fails across orgs.
- Match on title/heading prefix — rejected: titles can be edited; markdown rendering varies.
- Locked-thread metadata — rejected: GitHub doesn't expose per-comment metadata to non-Marketplace apps.

**Reversibility:** Cheap. The marker is a single constant in `eval_harness/comment.py`.

**Related issues:** #6

## D-010 — `diff-json` operates on RunResult JSON files, not SQLite (2026-05-16)
**Decision:** A new CLI subcommand `eval-harness diff-json --current X.json --baseline Y.json` diffs two JSON files (the format `eval-harness run --out` writes) and emits a `DeltaReport` in JSON, ascii, or markdown. It does not read or write SQLite.

**Why:** CI action runners are ephemeral. The existing `eval-harness diff` requires both runs to live in local SQLite — fine for a developer's machine, useless in an Action job. Splitting the diff is cheaper than threading "use this DB" / "use these files" through one subcommand because the two paths actually serve different use cases (dev-time history-vs-history, CI-time current-vs-committed-baseline). Both share the same `diff_runs(current, baseline)` core so semantics can't drift.

**Alternatives considered:**
- Persist runs to SQLite in the action then call `diff` — rejected: the ephemeral runner means SQLite has to be uploaded as an artifact and downloaded next run; much more plumbing than diffing two committed JSON files.
- Ship the SQLite DB as a workflow artifact — rejected: storage cost + same plumbing burden.
- Re-extract via GitHub API on each run — rejected: requires Marketplace permissions and a network hop.

**Reversibility:** Cheap. The new subcommand is ~30 lines of plumbing on top of the shared `diff_runs` core.

**Related issues:** #6, #7

## D-011 — Top-level `calibrate` subcommand with `judge calibrate` kept as hidden alias (2026-05-16)
**Decision:** The `eval-harness` CLI exposes `calibrate` as a top-level subcommand alongside `run`, `list`, and `diff` (the four-subcommand contract from issue #7). The pre-existing `judge calibrate` (nested form) stays callable and routes into the same handler. The nested form is not documented in the new README quickstart but is still mentioned in the module docstring as the legacy alias.

**Why:** Issue #7's body lists the public surface as `run / list / calibrate / diff`. The repo shipped `judge calibrate` first because the calibration loop was the only thing the `judge` parent then exposed (the assumption was the `judge` namespace would grow more peers). It didn't, and the nesting forces `eval-harness judge calibrate` instead of `eval-harness calibrate` for what's a top-level concern. Removing the nested form entirely would break any consumer script or CI snippet that already invokes it — a free correction with zero upside.

**Alternatives considered:**
- Remove `judge calibrate` entirely — rejected; pure churn for downstreams.
- Keep only `judge calibrate` and close #7 as "naming disagreement" — rejected; the issue's public-surface contract is the part that matters and the nested form is unfriendly.
- Use `argparse.add_subparsers(aliases=...)` — `argparse` aliases share `--help` text, which makes the legacy form's separate semantics harder to document; the duplicated parser is two lines of code and clearer.

**Reversibility:** Cheap. The legacy alias is two `if` clauses in `main()`; removing it after a deprecation cycle is a one-line edit. If a future minor version deprecates it, the deprecation can be a `print_to_stderr` from inside `_run_calibrate` when `args.command == "judge"`.

**Related issues:** #7

## D-012 — Pytest plugin parametrizes via `pytest_generate_tests`, not collection_modifyitems (2026-05-16)
**Decision:** `@pytest.mark.eval(...)` tests are expanded one-item-per-row using pytest's `pytest_generate_tests` hook + `metafunc.parametrize()`. The plugin does NOT synthesize new test items in `pytest_collection_modifyitems`.

**Why:** The parametrize seam is what `pytest -k`, `--collect-only`, pytest-xdist (parallel runners), and pytest's per-item caching all hook into. Synthesizing items in `modifyitems` would have given the plugin tighter control over the item's lifecycle but at the cost of breaking those integrations — `pytest -k qa_001` would no longer single out a row by id, and xdist's work-stealing wouldn't see the items at collection time. The parametrize path is also the documented extension point pytest itself recommends for "one test, many inputs."

**Alternatives considered:**
- Full ownership in `pytest_collection_modifyitems` — rejected; breaks `-k`, `--collect-only`, xdist.
- Custom `Item` subclass — rejected; same brittle integration problem as modifyitems, plus more pluggy surface.
- Helper function called from each test (no parametrize) — rejected; the issue's acceptance criterion is "each eval row becomes a test", which means one pytest item per row, not one item that internally loops.

**Reversibility:** Cheap. If a future feature needs the modifyitems path (e.g., dynamic discovery of eval files), the plugin can grow a second hook while keeping the parametrize path.

**Related issues:** #5

## D-013 — Threshold assertion lives in `pytest_pyfunc_call` hookwrapper, not autouse fixture teardown (2026-05-16)
**Decision:** The "score < threshold → fail" assertion is enforced inside a `pytest_pyfunc_call` hookwrapper (a "call-phase" hook). The earlier draft used an autouse fixture with the assertion after `yield` (teardown phase), and this was changed.

**Why:** pytest classifies test outcomes by *phase*: failures in the `call` phase are reported as `failed`; failures in `setup` or `teardown` are reported as `error`. An eval row that misses its threshold is a *test failure* — not a setup error or a teardown error — and should look like one in pytest output, in CI summaries, and in `--last-failed` reruns. The hookwrapper runs the user's test body, then runs the threshold check, then raises if the score is too low — all inside the call phase.

**Alternatives considered:**
- Autouse fixture with `pytest.fail` in teardown — rejected; pytest still reports it as an `error`, not a `failed`.
- Custom `runtest` method on a subclassed `pytest.Item` — rejected; couples the plugin to pytest's internal Item lifecycle and breaks the modifyitems alternative cleanly.
- Force users to write `assert score >= threshold` themselves — rejected; the issue says "the plugin asserts the threshold automatically", and a marker that's only inert without a hand-rolled assertion is half a feature.

**Reversibility:** Cheap. The hookwrapper is one function; switching to a different enforcement seam is a localized rewrite.

**Related issues:** #5
