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

## D-014 — Drift axes use Jensen-Shannon divergence (base-2, bounded in [0, 1]) (2026-05-16)
**Decision:** Each drift axis in `eval_harness.drift` (length, embedding-cluster, judge) scores the difference between the golden distribution and the candidate distribution with Jensen-Shannon divergence in base-2. JSD is symmetric in its arguments and bounded in `[0, 1]`. The same threshold scale (0.0 = identical, 1.0 = maximally different) is used per axis, with axis-specific defaults the caller can override.

**Why:** Three reasons stack. (1) **Bounded** — KL divergence has no upper bound, so picking a threshold means picking a number that has no natural meaning; "0.42 drift" only signifies something if the operator already knows the scale of that axis. JSD's 0..1 range gives every axis the same scale and the same threshold semantics. (2) **Symmetric** — KL is direction-dependent (`KL(golden||candidate)` is not the same as `KL(candidate||golden)`), and that asymmetry is a frequent source of bugs when someone swaps argument order. JSD removes the question entirely. (3) **Works on every axis we need** — KS only operates on ordered scalars, which is fine for length but doesn't generalize to the cluster-id axis (cluster ids are categorical, not ordered). JSD operates on any discrete distribution, so the same formula scores all three axes.

**Alternatives considered:**
- KL divergence (either direction) — rejected; unbounded and asymmetric, both ergonomic failures.
- Kolmogorov-Smirnov statistic — rejected; doesn't generalize to categorical (cluster id) data.
- Total variation distance — viable; bounded and symmetric, but the 0..1 range interprets differently and it's less common in ML drift literature, so we'd lose recognizability.
- Wasserstein / Earth Mover's distance — rejected; the natural implementation needs an extra dep (`scipy`) and the math doesn't generalize to categorical clusters without a ground metric we'd have to invent.

**Reversibility:** Cheap. The metric is one function (`jensen_shannon`) called from three call sites; swapping to a different metric is a localized rewrite.

**Related issues:** #4

## D-015 — Atomic-write helpers live in package-level `io_utils`, not file-private (2026-05-26)
**Decision:** Atomic-write helpers in this repo (and the wider portfolio) live in a package-level `io_utils` module — for `llm-eval-harness` that is `eval_harness/io_utils.py` exposing `atomic_write_text(path, text, encoding="utf-8")`. File-private helpers like the `_atomic_write_text` PR #49 originally placed in `cli.py` are an anti-pattern: they prevent other modules in the same package from reaching the helper, and they fragment the test surface so each importing module has to monkey-patch a different `<mod>.os.replace`.

**Why:** The 2026-05-26 atomic-write arc landed similar helpers across six repos. `rag-production-kit#44/#45` led with a package-level `rag_kit/io_utils.atomic_write_text` and three call sites; `prompt-regression-suite#40` followed in `prompt_regression/io.py`; `mcp-server-cookbook#37` used a separate `atomic_write.ts` module. Only `llm-eval-harness#49` kept the helper file-private, on the theory that "only cli.py needs it." That theory broke immediately: this issue (#50) found three additional call sites in `drift.py`, `dataset.py`, and a fifth in `cli.py` itself that the private placement either obscured or couldn't reach. Promoting the helper centralizes the test surface (one `io_utils.os` to monkeypatch) and gives every module in the package a path to atomicity guarantees without re-implementing the pattern.

**Alternatives considered:**
- Keep the helper file-private in `cli.py` — rejected; the call sites in `drift.py` and `dataset.py` would have to either duplicate the helper or import a private symbol across module boundaries (anti-pattern flagged by every linter).
- Split into one helper per call-site file — rejected; the pattern is identical across all five sites, so duplication has no upside and several downsides (each copy can drift, each needs its own test suite).
- Ship a separate distribution package — rejected; gross over-engineering for ~25 lines that has exactly one consumer.

**Reversibility:** Cheap. The helper is two dozen lines and a stable API; if a future evolution wants per-module variants, the public symbol can call into private ones.

**Related issues:** #48, #50

## D-016 — Non-strict mypy gate as the baseline strictness bar (2026-07-07)
**Decision:** Adopt a non-strict `mypy` gate for `eval_harness` as the baseline strictness bar, wired into CI (`ci.yml` lint job) and locked by a test (`tests/test_mypy_clean.py`). Config lives in `pyproject.toml` `[tool.mypy]`: no blanket `ignore_missing_imports`, a per-module override for the optional `anthropic` SDK only, and `warn_unused_ignores` + `warn_redundant_casts` on.

**Why:** #146 shipped a `py.typed` marker so `eval_harness`'s annotations are visible to downstream type-checkers (notably `rag-production-kit`, which mirrors `eval_harness.runner.RunResult`), but nothing machine-checked them in this repo — they could silently drift from the code. A gate keeps them honest. Non-strict (rather than full strict mode) is the right starting bar: the 7 pre-existing errors were mostly annotation-shape and one latent `AttributeError`, none needing strict-mode machinery; forcing `disallow_untyped_defs` now would generate churn without correctness value. Declining the blanket `ignore_missing_imports` keeps a mistyped import surfacing; the per-module override scoped to `anthropic.*` handles the one genuinely-optional dependency and, being config rather than an inline ignore, stays clean whether or not the `judge` extra is installed (verified both ways).

**Alternatives considered:**
- Full strict mode now — rejected; churn without correctness value at this stage. Tightening is a follow-up.
- Blanket `ignore_missing_imports = true` — rejected; it would silently swallow a typo'd import. Only `anthropic` needs the escape hatch, so a per-module override is more precise.
- No gate (leave annotations unchecked) — rejected; that's exactly the silent-drift failure the py.typed marker's value depends on avoiding.
- pyright instead of mypy — rejected; mypy is already the portfolio's Python convention and installs cleanly into the existing `dev` extra.

**Reversibility:** Cheap. The strictness bar is a few config lines; tighten or swap the checker in a follow-up (a mypy-strict or pyright migration would be its own decision).

**Related issues:** #146, #148

---

## D-017 — The all-zero `hash_embed` vector means *uncomparable*, not *maximally distant*

**Date:** 2026-08-24

**Decision.** An input with no alphanumeric tokens embeds to the all-zero
vector, and every cosine-derived quantity for it is **undefined**, not zero.
The remedy splits by side: a *golden* set with nothing embeddable is rejected
outright; *candidate* inputs that are uncomparable are counted in a new
`DriftReport.n_uncomparable` field and excluded from the cluster histograms and
from `representative_examples`. The length and judge axes still see them.

**Why.** `_cosine` of the zero vector with any centroid is exactly `0.0`, and
nothing in the module distinguished that from a genuine cosine of `0.0`. So a
content-free input scored a distance of `1.000` — the ceiling of the range in
practice — and outranked every input with real content. Because
`representative_examples` is *truncated*, that did not merely rank wrongly, it
evicted: with a golden set of 6 billing + 6 shipping utterances and a candidate
set of 4 real inputs plus 6 token-less ones, all five example slots went to
punctuation and none of the four real inputs surfaced. The same tie also made
`_assign` (which starts at `best_sim = -2.0` and takes the first centroid that
beats it) pile every token-less input into cluster 0, moving the published
embedding JSD from `0.1909` to `0.3122` — a 0.12 shift caused by six inputs
carrying no information at all.

The split by side is the substance of the decision, and it comes from the two
sides having different economics. A golden set is *authored* — small, reviewed,
and fixable — so the strictest possible response is affordable there, and it is
warranted: measured before this change, `compute_drift(['!!!', '???'], ...)` was
accepted and reported `embedding drift_score=0.000, status="ok"`. Every centroid
is the zero vector, every candidate lands in cluster 0, and the two histograms
come out identical, which is this module's encoding of "no drift". That is a
maximal false negative produced by a baseline that can measure nothing — the
same class as #91 (one-empty JSD) and #93 (the length-histogram open bucket),
reached through the embedder instead. A candidate set, by contrast, is a
*sampled production traffic slice*: large, unreviewed, and full of whatever real
users typed. Aborting a 10,000-line drift run because one row is an emoji would
be the wrong trade, so those are counted and set aside.

Counting rather than silently dropping matters on its own terms. "4,120 of
10,000 candidate inputs had no comparable content" is itself a drift finding,
and often a more actionable one than the JSD it was corrupting. It is rendered
in the HTML report and named in the embedding axis's `detail` string, not merely
left available on the dataclass.

**Alternatives considered.**
- *Exclude silently, report no count* — rejected; loses the junk-traffic signal
  entirely, which is arguably the more useful finding.
- *Reject uncomparable candidate inputs at ingest, the way the empty golden set
  and out-of-range thresholds are rejected* — rejected; a single emoji in a
  10k-line traffic sample would abort the run.
- *Keep them and give them a dedicated histogram bucket* — rejected; it changes
  the length of `cluster_counts` and the meaning of a cluster id for every
  consumer, to encode a category that is not a cluster.
- *Leave it, and document the skew as accepted* — rejected; the eviction of real
  examples is not a rounding error, it is total at the default `n=5`.
- *Change `hash_embed` itself (character n-gram backoff, so an emoji run embeds
  to something)* — rejected **for this issue**; it would move every
  already-published number on every axis, and it answers a different question
  than "what does the zero vector mean". A legitimate separate decision.

**Reversibility:** Cheap. One dataclass field, one guard, and two filters.

**Related issues:** #210, #208

## D-018 — an unrepresentable input is rejected on both drift sides (2026-08-26)

**Decision.** `compute_drift` rejects a golden *or* candidate input that has no
UTF-8 encoding — in practice a lone surrogate — rather than excluding it from
the report the way D-017 excludes token-less inputs on the candidate side.

**Why.** D-017's asymmetry is deliberate and still right for what it covers: a
golden set is authored, small and fixable, so one with nothing embeddable is a
broken baseline and fails loud, while a candidate set is a sampled traffic slice
and a single emoji must not abort a 10k-line run. But that argument is about
*embeddability*. A token-less input is perfectly representable — it can be
written to the report, it just has no angle to any centroid. A lone surrogate
cannot be written down at all: `render_html` produces a string that
`atomic_write_text` cannot encode, so there is no version of "keep going" that
still produces the artifact the command exists to produce.

Excluding the row instead would silently deflate `n_candidate` and both
histograms with no diagnostic — the same false-negative class this repo has
already fixed twice, in #91 (one-empty JSD) and #93 (the length-histogram open
bucket). And it is the same call #213 made one seam over, for the same reason:
there is no faithful spelling of the value to write, so the input is refused
rather than repaired.

**Alternatives considered.** (1) Extend D-017's split and drop unencodable
candidate rows — rejected for the deflation above. (2) Sanitise on write with
`errors="surrogatepass"` or a replacement character — the first puts invalid
UTF-8 on disk, which is strictly worse than refusing; the second silently
alters the operator's data in the one place the operator is meant to eyeball
it. (3) Catch `UnicodeEncodeError` at the write seam and return exit 2 — this
turns the crash into a clean failure but still spends the whole run to discover
a problem visible in the input, and does nothing for the library road the README
documents.

**Reversibility.** Cheap. One check at one choke point, and the "before"
behaviour is a documented, measured variant table in
`tests/test_drift_unencodable_inputs.py`.

## D-019 — A no-arg eval body is supported, not illegal (2026-09-01)
**Decision:** `pytest_generate_tests` parametrizes `eval_row` for **every**
eval-marked test, widening the item's fixture closure first when the body does
not already pull the name in — rather than failing collection for bodies that
omit it.

**Why:** The marker's contract, written in three places, is "one item per
dataset row… regardless of body signature". The old guard —
`if "eval_row" in metafunc.fixturenames` — honoured that only for bodies that
named the row. #223 reported it as a no-arg-body problem, but the real predicate
was never "the body is empty", it was "`eval_row` never reached the closure":
`def test_demo()`, `def test_demo(tmp_path)` and `def test_demo(**kwargs)` all
collect **one** unparametrized item and then die in setup with
`fixture 'eval_row' not found`, because the autouse `_ensure_judge_score_runs`
resolves `judge_score`, which declares `eval_row`, and nothing ever *defines*
an `eval_row` fixture — it exists only as a parametrized value.
`def test_demo(judge_score)` escapes only incidentally, because that
declaration is what drags the name into the closure.

The issue leaned toward failing at collection, on the grounds that always
parametrizing "needs care". That was worth measuring rather than assuming:
appending the name to `metafunc.fixturenames` before `metafunc.parametrize`
turns all six shapes into two passing items on **pytest 8.4.2 and 9.0.3** — the
two ends of the `pytest>=8.0` dev floor — and pytest passes only the funcargs a
body's signature names, so a body that ignores the row is unaffected at call
time. Given that it works, supporting the shape beats outlawing it: failing
collection would make the marker's own "regardless of body signature" claim
permanently false and force boilerplate on a user who wants a row-scoped eval
plus a `tmp_path` and nothing else.

**Alternatives considered:**
- *Fail at collection with a message naming `eval_row`* — rejected: cheap and
  honest, but it narrows a documented contract to avoid a two-line change that
  measurement showed is available.
- *Define a real `eval_row` fixture* — rejected: a no-arg body would then run
  **once**, not once per row, which is the inert-marker failure D-013's autouse
  fixture exists to prevent.
- *Document that bodies must name `eval_row`* — rejected: same narrowing,
  without even a collection-time error to enforce it.

**Reversibility:** Cheap. Two lines in `pytest_generate_tests`, and the
before/after behaviour of all six shapes is a measured variant table in
`tests/test_pytest_plugin_body_signatures.py`.

## D-020 — Remote judge failures share exit 2; the message, not the code, tells them apart (2026-09-07)
**Decision:** The two judge-seam rows #218 left open — the remote rejecting the
request (a non-transient 400/404, a bad `--model`) and a transient failure that
outlasted `retry_call`'s attempt budget (429/5xx/connection) — both exit **2**,
and the difference an operator acts on is carried in the `::error::` message
rather than in a distinct exit code.

**Why:** Exit 1 on `run` and `calibrate` is not a spare code. It already means
"a row dropped past `--threshold-drop`" and "Cohen's κ below threshold", so a
429 storm that outlasted the retry budget was being reported to CI as a
*quality regression* — the one reading that sends an operator to look at their
prompts instead of at the API status page. Exit 1 is the only genuinely wrong
answer here.

They share exit 2 because `_fail`'s own documented contract is "I/O **or**
usage error", and these two are precisely its two halves: a rejected request is
the usage half, an exhausted budget against a remote that is down is the I/O
half. The one thing a shared code would lose is whether to fix the invocation
or simply run it again later — and that rides in the message, which is exactly
where this repo already carries every other exit-2 distinction. A missing file
and a malformed file are both 2 with different messages.

Because that argument makes the message load-bearing, it is pinned rather than
trusted: `test_the_two_halves_are_distinguishable_in_the_message` asserts the
two lines are not equal, that "re-running may succeed" appears on exactly the
retryable one, and that the retry line names the budget it actually spent.

**Mechanism.** `is_backend_failure`, a third duck-typed, import-free sibling of
`is_transient_error` and `is_auth_error`. It asks a different *kind* of
question — provenance ("did this come back over the wire?") rather than
severity — and that is what let the fix avoid the `except Exception` the issue
ruled out. The retag lives inside `AnthropicBackend.complete`, a frame a
caller's own `Backend` never enters, and a bug in our own content-block loop
inside that same `try` carries no status code and no SDK class name, so both
keep their traceback.

**Alternatives considered:**
- A distinct exit 3 for retry-exhausted transients, so CI could auto-retry —
  rejected because nothing in this repo or its GitHub Action branches on a
  fourth code today, and every consumer reading "non-zero, non-one" as
  "something is wrong" would need updating for a capability no caller has asked
  for. This is the alternative to revisit, and the evidence that should reopen
  it is a consumer that actually wants to auto-retry on an outage.
- Leaving both on exit 1 (the status quo) — rejected: it is the one reading
  that is actively false.
- `except Exception` at the CLI seam — rejected: it would swallow a genuine bug
  in a caller's own `Backend` into a clean usage-error line and delete the stack
  trace that is the only way they could fix it. Strictly worse than the
  traceback it replaces.
- Splitting the pair — 400 on exit 2, retry-exhausted 5xx on exit 1 — rejected:
  it divides them along the one axis that is not about severity, and leaves half
  the problem exactly where it was.

**Reversibility:** Cheap. The contract is pinned by one grid test and two doc
tables, all edited in the same PR.

**Related issues:** #220, #218, #194

---

## D-021 — `dump_jsonl` enforces the loader's representability rule, on the write path, through the same walk
**Date:** 2026-09-08

**Decision.** `Dataset.dump_jsonl` walks every record through the loader's own
`_find_unrepresentable` before writing any bytes, raising `ValueError` naming
the example index, its `id` and the JSON path. A non-`str` object key becomes a
representability finding of its own (`NON_STRING_KEY`) rather than an
`AttributeError` out of the walk.

**Why.** #213 closed one side of this seam and the writer's docstring claimed
the whole of it: "That guarantee is enforced, not merely asserted:
`_validate_record` rejects the two classes of value this writer cannot
faithfully emit." `_validate_record` runs on the **load** path. `Example` is
exported, is a frozen dataclass with no `__post_init__`, and assembling a
`Dataset` in Python — the ordinary use of a reusable eval framework — never
meets the loader. Measured on `main`, with no loader involved: a `provenance` of
`{"cost_usd": inf}` was written as a bare `Infinity` token, and `load_jsonl` of
the file *just written* raised `DatasetLoadError`; a `{1: "one"}` key was
written `{"1": "one"}` silently and reloaded with the key changed from `int` to
`str`. The canonical writer emitted files its own reader refuses.

The comment that reads as covering this does not. `dataset.py` says "Rejecting
at load is the correct side of the seam. `dump_jsonl` could write with
`errors="surrogatepass"`, but that puts invalid UTF-8 on disk." That reason is
*true*, and it answers **how** the writer should handle a bad value — not
**whether it is reachable with one**.

The non-string-key axis was required rather than optional. Routing the writer
through the shared walk is exactly what first hands that walk a Python-built
dict, and it answered with `AttributeError: 'int' object has no attribute
'encode'` (#231) — escaping every caller's `except ValueError` precisely as the
`RecursionError` the walk is iterative to avoid would. It is also a finding on
its own terms: `json.dumps` *coerces* an `int`/`float`/`bool`/`None` key to a
string and raises a bare `TypeError` for any other key type.

**Scope boundary, stated rather than assumed.** This is the representability
rule, not full schema validation on the write path. `Example(id=123)` still
writes an `id` that `load_jsonl` refuses; that is a strictly larger change with
a different shape, and `test_the_scope_boundary_is_representability_not_schema`
pins the boundary so the next reader does not conclude the write path is fully
guarded.

**Alternatives considered.**
- Writing with `errors="surrogatepass"` — rejected: it puts invalid UTF-8 on
  disk, which is strictly worse than refusing the record, and there is no
  faithful JSON spelling of `NaN` to write at all.
- Validating in `Example.__post_init__` — rejected: it moves the failure to
  construction, cannot see a `provenance` dict mutated after construction (the
  dataclass is frozen, the dict it holds is not), and would not cover a
  `Dataset` whose `examples` list is assigned directly.
- A second copy of the rules local to the writer — rejected, and this is the
  neighbour that taught the most: it passes every behavioural assertion in the
  new module. Only the two structural tests catch it.
- Full schema validation on the write path — deferred, filed separately.

**Reversibility:** Cheap. One call site, one kind constant, and the boundary is
pinned by tests rather than by prose.

**Related issues:** #234, #231, #213

## D-022 — `dump_jsonl` rejects a `Dataset` whose `version` disagrees with its rows
**Date:** 2026-09-09 · **Issue:** #235 · **Reversibility:** cheap

`Dataset.version` is documented as "the value of `dataset_version` carried by
every line in the file". Nothing checked that on the way out, so
`Dataset(version="v1", examples=[Example(dataset_version="v2")])` wrote a file
that reloaded as `v2` — the field that names the version quietly lost the
argument to the field on the row.

Two repairs were available. Overwriting every row with `self.version` makes the
write succeed, and that is exactly what is wrong with it: it is a lossy write no
reader can detect. The row said `v2`, the file says `v1`, and nothing on disk
records that a value was changed. Rejecting matches what the loader already says
for the neighbouring mixed-version case — "split mixed-version data into separate
files" — and leaves the caller to state which version they meant.

Scope is the write path only. `load_jsonl` is unchanged: it already derives the
file version from the rows and rejects rows that disagree with each other.

---

## D-023 — Report out-of-support candidate mass; document the invariance that causes it
**Date:** 2026-09-15 · **Reversibility:** cheap

**Decision.** `DriftReport` gains `n_length_off_support: int` and
`n_judge_off_support: int | None` — candidate inputs sitting in a histogram
bucket the golden set never occupies. The two histogram axes' `detail` strings
and the HTML report surface them, all three only when non-zero, so an ordinary
report is byte-unchanged. No axis score changes and no existing number moves.

**The property.** Jensen-Shannon divergence over a histogram is invariant to how
the candidate distribution redistributes mass among buckets where `P_i == 0`.
The per-bucket term reduces to exactly `Q_i / 2` — a function of the mass, not
of which zero-`P` bucket holds it. So an input can move several buckets further
from the golden distribution without moving the axis by a single bit.

This was verified rather than asserted. All 28 redistributions of the demo
corpus's 6 out-of-support inputs produce the identical `0.5689626904850149`, and
the exact contribution identity — off-support buckets sum to half the
out-of-support fraction — was checked against a from-definition decomposition
over 400 random histogram pairs. On the demo corpus that means 6 of 8 candidate
inputs are off support on *both* histogram axes, so `0.375` of the `0.5690`
length score, about 66%, is frozen.

**This is not a defect and is not being fixed.** A categorical divergence over
unordered buckets has no notion of "further outside the support" — a bucket
carries no order. That is the price of D-014's bounded, symmetric choice, and
the alternatives it rejected (KL: unbounded and asymmetric; KS: ordered scalars
only) are still rejected for the same reasons. The invariance is documented and
reported, not removed.

**Why a count is the right companion.** This is the second instance of a shape
D-017 already decided. `n_uncomparable` reports the inputs the *embedding* axis
structurally cannot see, with the argument written into its own comment: such a
count "is itself a drift finding, and often a more actionable one than the JSD
on the axis it was corrupting." Issue #243 called this "a design question, not
an obvious yes" — that was overcautious. The repo had already answered the
general question; this applies it to a second blind spot in the same report.

**What the count does not do.** It is invariant to exactly the same
redistribution the JSD is, so it does *not* distinguish "just outside the
support" from "far outside it" — and nothing here does. It answers how much of
the score is frozen, which is a different and cheaper question. What it does
discriminate is two *reports*: against a golden histogram of `(4,4,0,0,0)`, the
candidates `(0,8,0,0,0)` and `(2,2,0,0,4)` both score `0.311278124459`, with 0%
and 80% of that identical number frozen respectively. That pair was found by
exhaustive search, not constructed.

**Alternatives considered:**
- Change the divergence to something order-aware — rejected; D-014's reasons
  hold, and reporting a blind spot is not the same as removing it.
- A fraction rather than a count — rejected; `n_candidate` is on the report so
  the fraction is derivable, and a count matches `n_uncomparable` and
  `bucket_counts`.
- Put the field on `AxisReport` so all three axes carry it — rejected; it would
  force a meaningless value on the embedding axis, whose structure is cluster
  assignment rather than a histogram over a fixed domain.
- Documentation only — rejected; a documented property with no field and no test
  is a claim, and the operator reading an HTML report never sees the docstring.

**Two named fields, not one tuple.** Every other tuple field on `DriftReport`
reads `(golden, candidate)`. A tuple whose slots were *axes* would invite
exactly the wrong-unit misreading; two plain fields cannot be misindexed. And
`None` rather than `0` on the judge slot, because `0` would claim a clean result
for an axis that never ran.

**Related issues:** #243, #241, #210

---

## D-024 — the embedding axis carries the off-support count too
**Date:** 2026-09-21 · **Amends:** D-023 · **Reversibility:** cheap

**Decision.** `DriftReport` gains `n_embedding_off_support`, the third member of
the family D-023 introduced. D-023 deliberately left the embedding axis out; the
reason it gave is a true premise with a false conclusion, and this corrects it.

**Why.** D-023 wrote that the embedding axis has no counterpart for "outside the
support" because "every comparable candidate is assigned to some golden
centroid". Every candidate is indeed assigned to *some* centroid. But the
support is the set of buckets the **golden histogram occupies**, not the set of
centroids that exist, and `_kmeans` *retains* a centroid whose cluster went
empty rather than dropping it:

```python
for ci in range(k):
    if counts[ci] == 0:
        new_centroids[ci] = list(centroids[ci])   # retained, not dropped
        continue
```

So a cluster carrying no golden mass is reachable, `_assign` will route a
candidate to it, and the embedding score is the same `jensen_shannon` over a
histogram with the same `q_i / 2` invariance. The claim was about the wrong
population.

**Measured, not argued.** 70 of 20,000 random corpora put candidate mass in such
a cluster; 1,531 of 20,000 had a golden-empty cluster at all. Reproduced at a
second seed with different vocabularies through the public `compute_drift`. On
one case — golden `(3, 0, 0, 1)`, candidate `(1, 2, 0, 0)` — all three
redistributions of the off-support mass among the two empty clusters give the
identical `0.5176503615477757`, and a from-definition decomposition puts 64.4%
of that score in the frozen regime.

**The one thing this axis does not share with its siblings: the denominator.**
The embedding axis excludes uncomparable inputs (D-017), so the count's base is
the *clustered* candidate count, not `n_candidate`. That is numerical, not
presentational — the frozen contribution is half the off-support fraction *of
the histogram the JSD normalizes*. On a measured report with one uncomparable
candidate the true frozen contribution is `(1/2)/2 = 0.25` of a `0.4733` score,
where an `n_candidate` base would claim `0.1667`.

**Alternatives considered:**
- Leave it as D-023 shipped — rejected; the exclusion rests on a premise this
  session falsified by measurement, and a documented false reason is worse than
  no documentation.
- Base the count on `n_candidate` for uniformity — rejected, and measured wrong:
  it understates the frozen fraction whenever any candidate is uncomparable.
  Uniformity of unit is not uniformity of meaning.
- Drop empty centroids in `_kmeans` so D-023's original claim becomes true —
  rejected; it would move every published embedding number including the
  README's pinned `# stdout:` example, and it repairs the documentation by
  changing the measurement.

**What this does not change.** D-014's divergence stands, and `_kmeans`'
empty-centroid retention is untouched. This reports a blind spot; it does not
remove one — exactly how D-023 framed itself.

**It also falsifies one of D-023's rejected alternatives.** "Put the field on
`AxisReport` so all three axes carry it — rejected; it would force a meaningless
value on the embedding axis." The value is not meaningless there. That
alternative stays rejected on its other ground (the shape of hanging a count off
`AxisReport`), but its stated reason was wrong.

**Related issues:** #246, #243, #210, #207
