# Session History (human-readable)

Chronological log of work sessions. Most recent first below the divider.

---

## 2026-05-19 — Issue #22: snapshot lock README numeric/identifier defaults to source
**Duration:** ~35 min · **Branch:** `session/2026-05-19-1910-issue-22` · **PR:** [#23](https://github.com/jt-mchorse/llm-eval-harness/pull/23) (ready)

- Added `tests/test_readme_defaults_snapshot.py` (6 tests) closing the orthogonal axis that `test_readme_snapshot.py` doesn't cover: numeric and identifier defaults the README quotes as if derived from source (calibration row count, pip extras keys, `--threshold-drop` default, kappa gate default, drift `cluster_k`, sticky-comment marker literal).
- Source is the truth — every failure message tells the operator to update the README quote to match the new live value (never the other way around). The kappa default is parsed by regex against `cli.py` source because argparse subparser defaults don't introspect cleanly without invoking `parse_args`; the regex-matched assertion fires first so a future refactor can't silently green this test.
- Tamper-verified 3 of 6 (`DEFAULT_THRESHOLD_DROP`, README "50 rows", `drift.compute_drift(cluster_k=...)` default) — each fires with the symbol referenced in the message; revert restores green. Full suite 155/155 (was 149); ruff check + format clean.

**Why this work, this session:** Phase A repo selection ran with all `priority:high` queues empty and the `priority:med`/`priority:low` issues either already had open PRs against them or required screen capture (the demo issues). Filing #22 + working it kept the portfolio's snapshot wave (eight sister PRs landed 2026-05-18..19) honest by closing the orthogonal numeric-defaults gap in the foundation repo.

**Open questions / blockers:** None.

**Next session:** Continues with whichever repo Phase A selection picks; the loop now expects more numeric-defaults snapshot opportunities across the other repos with README↔source default claims (likely candidates: `llm-cost-optimizer`, `agent-orchestration-platform`).

## 2026-05-19 — Issue #19: README + snapshot test
**Duration:** ~45 min · **Branch:** `session/2026-05-19-issue-19`

- Rewrote `What this is` from "Three pieces shipped today" to a nine-bullet landing-order picture covering every closed issue (#1–#7, #15, #17). Each bullet keeps the prior prose's tone and cites the D-NNN that drove the choice where relevant (D-005 κ gate, D-013 pytest assertion-in-call-phase, D-014 JSD drift metric).
- Architecture mermaid updated to show all shipped surface: run history → list/diff, run JSON → diff-json/comment → Action sticky comment, drift report, pytest plugin, examples directory.
- Demo section: replaced "pending until #3 lands" (closed weeks ago) with today's two-command hermetic demo path (`examples/regression_run_and_diff.py` + `examples/drift_report.py`). Captured-asset follow-up filed as #20.
- `tests/test_readme_snapshot.py` (4 tests) locks: nine `(#N)` refs in landing order, CLI bullet against `python -m eval_harness.cli --help`, every relative file reference resolves, and the Demo section invariant ("must name a follow-up issue, must not contain 'pending until ... lands'").

**Why this work, this session:** Issue #19 filed during this session after the autonomous loop noticed llm-eval-harness was the last portfolio repo whose README still carried session-specific framing from its earliest PR. Sister to nine other snapshot-test PRs the portfolio shipped 2026-05-18..19.

**Open questions / blockers:** None.

**Next session:** Continues with whichever repo Phase A selection picks; #20 is priority:low demo capture.

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

## 2026-05-15 — Issue #3: Regression runner with per-row diffing
**Duration:** ~60 min · **Branch:** `session/2026-05-15-1923-issue-3`

- Shipped `eval_harness/runs.py` (stdlib `sqlite3`, two tables `runs` + `rows` with a foreign key, idempotent `init_db`, `connect`/`write_run`/`read_run`/`latest_run_id_for_suite` helpers) and `eval_harness/runner.py` (`RunSpec`, `AnswerSource` Protocol with a `DatasetEchoSource` default, `run_suite`, `diff_runs`, `render_delta_ascii`, `render_run_json`). Two new core decisions: D-007 separates `AnswerSource` from the judge `Backend`, D-008 commits to SQLite for persistence.
- Extended `eval_harness/cli.py` with `eval-harness run --suite <name> --dataset <path> [--baseline <id>] [--threshold-drop X]` and `eval-harness diff --current <id> --baseline <id>`. The `run` command writes the per-run JSON to stdout (or `--out`) and the ASCII delta table to stderr when a baseline is available; it exits non-zero on any row dropping more than `--threshold-drop` (default `0.1`).
- 17 new hermetic tests across `tests/test_runs.py`, `tests/test_runner.py`, and `tests/test_cli_run.py`. The CLI smoke test against `fixtures/sample_factuality_v1.jsonl` finishes well under the issue's "<10s" acceptance criterion.
- Discovered + fixed an edge case during testing: two consecutive runs can share a 1-second-resolution `started_at`, so `latest_run_id_for_suite` now takes an `exclude_run_id` kwarg the runner uses after persisting the current run.
- 68/68 hermetic tests pass; ruff lint clean.

**Why this work, this session:** Every downstream consumer (#4 drift detection, #5 pytest plugin, #6 GitHub Action) needs the run + diff primitives. Locking the SQLite schema and the threshold-flag semantics now prevents re-litigating them in those issues.

**Open questions / blockers:** Real-Anthropic-API smoke runs require operator credentials; the hermetic suite covers the runner machinery itself. A real `AnthropicAnswerSource` is deferred until a consumer needs one — the Protocol is the contract.

**Next session:** Issue #4 (drift detection) or #6 (the GitHub Action that posts deltas on every PR) — both naturally follow from the run + diff layer.

## 2026-05-16 — Issue #6: GitHub Action posts sticky eval-delta PR comments
**Duration:** ~40 min · **Branch:** `session/2026-05-16-0400-issue-6`

- Shipped `eval_harness/comment.py`: `render_delta_markdown(report)` produces a GFM table with a hidden HTML marker (`<!-- eval-harness:sticky-comment -->`); `find_sticky_comment` and `upsert_sticky_comment` paginate the GitHub Issues API to find the bot's prior comment by marker and either PATCH it in place or POST a new one (D-009). HTTP plumbing is stdlib `urllib.request` — no pip dep.
- Two new CLI subcommands: `diff-json` (diffs two `RunResult` JSON files with no SQLite — D-010, picked because action runners are ephemeral) and `comment` (renders the delta JSON and upserts the sticky). `comment --dry-run` skips the API call entirely so local testing needs no token.
- Workflow `.github/workflows/eval.yml` runs on `pull_request`: installs the package, runs `diff-json` against committed `fixtures/demo_baseline.json` + `fixtures/demo_current.json` (chosen with one row in each of the five status categories — improved, unchanged, regressed-flagged, new, removed — so the comment table exercises every rendering path), then upserts the sticky comment with `permissions: pull-requests: write`.
- 19 new tests in `tests/test_comment.py`: 8 for the markdown renderer (marker placement, suite name, empty rows, table headers, flagged-row warning emoji, new/removed row em-dashes, run-id short rendering, headline-status switching); 7 drive `find_sticky_comment` / `upsert_sticky_comment` against an in-process stdlib `http.server` that mimics the GitHub API at the routes the bot uses (the helpers accept an `api_base` override designed for exactly this — no `unittest.mock` of urllib); 3 CLI end-to-end tests render the demo fixtures into markdown / JSON / dry-run output; 1 sanity test confirms there's no module-level token cache. Suite total now 87/87 green, ruff lint+format clean.
- README: new "GitHub Action: sticky eval-delta comments on PRs" section under Quickstart documenting the two-step CLI invocation downstream repos use.
- D-009 (sticky-marker identity, not author/title) and D-010 (`diff-json` JSON-pair operation, no SQLite) recorded.

**Why this work, this session:** #6 is the last load-bearing piece of llm-eval-harness's v0.1 — every downstream eval-consuming repo (rag-production-kit's #7, agent-orchestration-platform's #7, llm-cost-optimizer) needs a way to post eval deltas on PRs. Re-implementing the sticky-comment pattern in each repo would be exactly the duplication this package exists to prevent. With #6 shipped, those consumers just `pip install eval-harness` and add the two-step `diff-json` + `comment` workflow.

**Open questions / blockers:** None. The action runs on `pull_request` events; downstream consumers paste the two-step recipe from the README. A future "auto-update baseline on main-merge" workflow would close the loop but isn't on the v0.1 critical path — filing as `priority:med`.

**Next session:** All llm-eval-harness `priority:high` issues now closed. Move to a different repo — likely `llm-cost-optimizer` or `prompt-regression-suite`.

## 2026-05-16 — Issue #7: CLI run/list/calibrate/diff + macOS CI
**Duration:** ~30 min · **Branch:** `session/2026-05-16-1545-issue-7`

- Added `RunSummary` + `list_runs(conn, limit, suite)` in `eval_harness/runs.py`. Shipped the `eval-harness list` subcommand: default fixed-width text table sized from the longest cell, `--json` for machine output, `--suite` filter, `--limit` cap. Missing DB → "# no runs (no database at ...)"; empty DB → "# no runs"; suite-filter-no-match → "# no runs for suite '...'". All zero-exit.
- Promoted `calibrate` to a top-level subcommand (D-011). The pre-existing `judge calibrate` stays as a hidden alias so existing scripts/CI snippets don't break. Shared `_add_calibrate_args(parser)` helper keeps the two surfaces in sync.
- Extended `.github/workflows/ci.yml` test matrix to `os: [ubuntu-latest, macos-latest]` alongside the existing `python: ['3.11', '3.12']` axis (4 cells). Added a CLI smoke step that runs `--help` on the four public subcommands (`run / list / calibrate / diff`) per cell so the "console_script installed" + "complete --help" acceptance criteria are verified everywhere.
- 9 hermetic tests in `tests/test_cli_list.py` covering missing DB, empty DB, table-render order (most recent first), suite filter, suite-filter-no-match message, `--limit`, `--json` parseable + order-preserving, `--json` on empty, and top-level `calibrate` arg parsing. 105/105 tests pass; ruff lint + format clean.
- README quickstart gains a `list` example with the rendered table format. CLI module docstring rewritten to reflect the four public subcommands plus the two consumer-workflow subcommands (`diff-json / comment`).

**Why this work, this session:** This repo had zero `priority:high` open issues remaining after PR #11 (the comment workflow) merged. Issue #7 is the only `priority:med` that locks the CLI's public surface — getting it on `main` means downstream repos can document `eval-harness <subcommand>` without footnotes. The macOS CI cell is the smallest concrete miss that's pure additive coverage (the existing CI was ubuntu-only).

**Open questions / blockers:** None. Click/typer migration was considered and deferred — stdlib argparse meets the issue's acceptance criteria, and a click rewrite would be churn for no incremental capability.

**Next session:** `priority:med` issues remain (#4 drift detection, #5 pytest plugin). Either is a clean follow-up; both compose on the SQLite history.

## 2026-05-16 — Issue #5: Pytest plugin: evals as tests
**Duration:** ~40 min · **Branch:** `session/2026-05-16-1553-issue-5`

- Shipped `eval_harness/pytest_plugin.py` registered via `[project.entry-points.pytest11]` in `pyproject.toml`. The plugin parametrizes any test marked `@pytest.mark.eval(suite=..., dataset=..., answer_source=..., judge_backend=..., threshold=0.6, rubric=None)` with one row per dataset entry (D-012). Each generated item has the row id as its parametrize label, so `pytest -k qa_001` singles out a specific row and `pytest --collect-only` shows the full row list before running.
- `judge_score` fixture (depends on `eval_row` + `_eval_spec`) calls `answer_source.answer(example)` then `judge.score(prompt, response, rubric)` once per row and stashes the row, response, and `JudgeScore` on the test node so failure reporting has full context. An autouse `_ensure_judge_score_runs` fixture triggers the scoring even when the user's test body doesn't reference `judge_score` directly — the marker is never inert.
- The threshold assertion runs inside a `pytest_pyfunc_call` hookwrapper (D-013), not in a fixture teardown. This keeps a threshold violation in the test's `call` phase, so pytest reports it as `failed` rather than `error`. Failure messages carry row id, expected outputs, actual response, judge score, and judge reasoning so reviewers don't have to dig through stdout.
- 6 hermetic tests in `tests/test_pytest_plugin.py` use the `pytester` fixture to run synthetic test files in subprocesses: parametrize-per-row, threshold-failure context surfacing, missing-kwarg collection error, empty-dataset rejection, default threshold = 0.6, non-eval tests unaffected. Full suite is 102/102 pass; ruff lint + format clean.
- README "Quickstart" grows a "Pytest plugin: evals as tests (#5)" subsection with the marker example.

**Why this work, this session:** Issue #5 was the next `priority:med` unblocked (and one of the four acceptance lines in the §2 spec for this repo). Shipping the plugin means downstream repos can write `@pytest.mark.eval(...)` against their own datasets without rebuilding the parametrize / judge / score-threshold dance each time.

**Open questions / blockers:** None. Live Anthropic-backed plugin tests are out of CI scope (no API key budget); the plugin's own tests use stub backends. A future issue could ship a marker shortcut for `--allow-live` runs that pull from `ANTHROPIC_API_KEY`.

**Next session:** `priority:med` issues remain (#4 drift detection on production traffic samples). Or another repo per the multi-issue loop.

## 2026-05-16 — Issue #4: Drift detection on production traffic samples
**Duration:** ~55 min · **Branch:** `session/2026-05-16-1937-issue-4`

- Shipped `eval_harness/drift.py` — three drift axes scored independently and reported in one HTML page:
  1. **Length** — char-count histogram bucketed by `_LENGTH_BUCKETS`.
  2. **Embedding cluster** — a dep-free `hash_embed` (L2-normalized SHA-1 bucket hash, matching the `HashEmbedder` reference in `rag-production-kit`); k-means with stride-init for determinism builds k=8 centroids from the golden set; each candidate input is assigned to the nearest centroid by cosine; JSD between cluster-id histograms.
  3. **Judge-score** — operator-supplied `judge_score_fn(input) -> float`. Skipped (`judge=None`) when no scorer is provided so hermetic CI runs that don't pay for a judge still render the other two axes. `_judge_stub` is a deterministic word-count stub for hermetic tests.
- Recorded D-014: drift uses Jensen-Shannon divergence (base-2, bounded in `[0, 1]`) per axis. KL is unbounded and asymmetric; KS only works for ordered scalars (doesn't generalize to cluster ids); JSD does both with one formula and one threshold per axis. Default thresholds are 0.10 across all three axes — same scale, same semantics.
- HTML report renders three inline-SVG bar charts (golden vs candidate overlay), a per-axis status table (`drift_score`, `threshold`, `ok`/`drifted`, `detail`), and a representative-examples table listing the candidate inputs whose nearest-golden-centroid cosine distance is largest — the inputs that look least like anything in the golden set. Single-file output; no external CDN; mirrors the dashboard pattern in `rag-production-kit/scripts/telemetry_dashboard.py`.
- CLI wired as `eval-harness drift --golden <jsonl> --candidate <jsonl> --output <html> [--judge-stub] [--cluster-k N]`. The standalone `python -m eval_harness.drift` entry point also works for downstream wiring. Smoke-tested end-to-end on the in-repo fixtures.
- Smoke fixtures live in `fixtures/drift/`: `golden_inputs.jsonl` (20 RAG/Postgres/eval questions), `identical.jsonl` (same as golden — drift~0 across all axes), `shifted.jsonl` (20 short non-technical questions — drift > threshold on all axes including the judge stub). Tests assert the threshold posture against the defaults so an axis going slack will fail CI.
- 24 new hermetic tests (`tests/test_drift.py`): JSD identity / disjoint / partial-overlap / length-mismatch / zero-mass; `hash_embed` determinism / L2 normalization / blank input / dim validation; `compute_drift` identical / shifted / no-judge-fn / empty-input rejection / examples-furthest-first / cluster-k capping; `render_html` 3-svg vs 2-svg shape and `axis skipped` message; CLI exit-zero + output write; input-loader JSON validation. Full suite 126/126 pass, ruff clean.
- README: new "Drift detection on production traffic samples (#4)" subsection covering the CLI, the three axes, the JSD threshold posture (D-014), and the library API (`compute_drift` / `render_drift_html`).

**Why this work, this session:** #4 was the last unfilled `priority:med` open issue in this repo, and the harness's anchor v0.1 scope includes drift detection. The JSD decision (D-014) generalizes to any future axis we add (judge-confidence histograms, prompt-shape histograms, etc.) so threshold semantics stay consistent.

**Open questions / blockers:** None. Real-LLM judge runs require `ANTHROPIC_API_KEY` + budget — `--judge-stub` is the documented hermetic path; the library API takes any callable so an operator can wire a real judge in their own script.

**Next session:** All `priority:med` issues in this repo are now closed (in flight). Loop to a different portfolio repo per the multi-issue prompt.

## 2026-05-18 — Issue #15: `eval-harness run --tags` filter
**Duration:** ~30 min · **Branch:** `session/2026-05-18-1505-issue-15` · **PR:** [#16](https://github.com/jt-mchorse/llm-eval-harness/pull/16) (ready)

- Added set-union tag filtering to `eval-harness run`. The dataset format has carried per-row `tags` since #1 (D-002), but neither the runner nor the CLI exposed a way to score only a subset by tag — operators wanting to drill into one cluster after a regression had to slice the JSONL by hand.
- Pure dataset-layer helper (`filter_examples_by_tags`, `collect_tag_inventory`) keeps the matching logic at the schema layer; the runner threads it through `RunSpec.tags` and raises `EmptyTagFilterError` with the requested tags + on-disk tag inventory so the silent-zero-rows failure mode is structurally impossible.
- CLI parser tolerates whitespace and empty tokens (`--tags ' , '` is treated as no filter, not "match nothing"), exits 2 on unknown-tag with a stderr message naming what the dataset actually offers.
- 14 new tests (137/137 total); ruff clean; README quickstart updated.

**Why this work, this session:** Every original `priority:high` issue is closed. The repo is feature-complete per its §2 spec, so the next-most-leverage move was to extend an existing surface in a way the dataset schema already supported — the tags field was unused at the query layer.

**Open questions / blockers:** None — PR ready for review.

**Next session:** Move to the next repo in the build sequence per the multi-issue loop; this repo only needs the calibration κ benchmark (operator action) and a 60-s demo recording before v0.1.

## 2026-05-18 — Issue #17: `examples/` directory with smoke-tested integration patterns
**Duration:** ~45 min · **Branch:** `session/2026-05-18-1913-issue-17`

- Added `examples/` with four self-contained Python files exercising each layer of the public API (calibration, regression run + diff, drift, pytest-marker). All four are hermetic — stub backends + `DatasetEchoSource` keep them runnable without an API key.
- New `tests/test_examples_smoke.py` (8 tests) imports each example fresh via `importlib`, captures stdout, and asserts the expected sentinels + on-disk artifacts. The pytest example is exercised through a subprocess so the outer suite and the inner parametrized items stay cleanly isolated. Full test count: 145/145.
- README gets a new `### Examples` subsection under Quickstart with a four-row table and a note that each example swaps cleanly to `AnthropicBackend()` for live runs. The stale "68 hermetic tests pass" line is replaced with `# full hermetic suite (no API key)` to avoid future bitrot.

**Why this work, this session:** The harness is feature-complete per §2 and is imported by other portfolio repos, but downstream-repo authors had only the README snippets + skimming `tests/` to learn the integration patterns. A smoke-tested examples directory is leverage — it documents the wire-up patterns, won't bitrot, and is the obvious next click after the Quickstart.

**Open questions / blockers:** None. PR opened ready for review; CI will exercise the smoke suite alongside the existing tests.

**Next session:** Move to the next repo in the build sequence (`llm-cost-optimizer`) and look for a similar leverage move.

## 2026-05-19 — Issue #24: Public-surface snapshot test
**Duration:** ~30 min · **Branch:** `session/2026-05-19-2317-issue-24` · **PR:** [#25](https://github.com/jt-mchorse/llm-eval-harness/pull/25) (ready, CI green, merging)

- Issue filed in-session: a portfolio-wide loop turn started with zero open `priority:high` or `priority:med` issues across all twelve repos and only demo-capture `priority:low` blockers; per Phase B step 5's escape, picked llm-eval-harness (first in build sequence) and filed a fresh actionable issue grounded in a real gap — coverage of `eval_harness/__init__.py` was 0%, meaning silent renames in any submodule could break the README's `from eval_harness import ...` example without any test failing.
- New `tests/test_public_surface.py` (5 axes, 10 test items) locks: (1) `__version__` is semver-ish, (2) every `__all__` entry is bound non-None, (3) `__all__` agrees bidirectionally with the AST-parsed `from eval_harness.X import` block, (4) README's quoted `Judge` / `calibrate` / `load_calibration` resolve at the top level, (5) one anchor per submodule (judge/calibration/dataset/drift/runner/runs) survives at the top level.
- Coverage trick: the `eval-harness` pytest plugin is loaded by entry points before pytest-cov instruments, so the package's top-level `__init__.py` always executed pre-instrumentation and showed 0% even with tests exercising every re-export. An `importlib.reload(eval_harness)` at the test module top forces the body to re-execute under the tracer; coverage of `__init__.py` jumps 0% → 100%.
- Also `.coverage` artifacts to `.gitignore` so a local `pytest --cov` doesn't appear as uncommitted state.

**Why this work, this session:** Same hygiene posture as the recent README snapshot tests across the portfolio (#19, #22 in this repo). Orthogonal axis — Python public surface vs. README text. A library that twelve other repos plan to import deserves a snapshot on its top-level surface; this is the cheapest way to catch a silent break.

**Open questions / blockers:** None.

**Next session:** Loop to another repo. This repo's open queue is now {#20 (demo capture)} — gated on human action.

## 2026-05-22 — Hide `judge calibrate` alias from top-level help (#27)

**Duration:** ~25 min. **Issue:** [#27](https://github.com/jt-mchorse/llm-eval-harness/issues/27). **PR:** TBD.

The CLI module docstring and README both said `judge calibrate` "remains as a hidden nested alias for backwards compat". The CLI did not actually hide it: the `judge` subparser was registered with `help="Judge-related subcommands."` and showed up in `eval-harness --help` exactly like the canonical `calibrate`. A new operator reading the help saw two ways to do the same thing, and the README's own quickstart used the legacy form.

First attempt was `help=argparse.SUPPRESS` on `add_parser("judge", ...)` — but argparse renders that as literal `==SUPPRESS==` in subparser listings, which is worse than not suppressing it. Switched to an argv rewrite at the top of `main()`: if argv starts with `["judge", "calibrate"]`, rewrite to `["calibrate", ...rest]` before constructing the parser. The `judge` subparser is then never registered, so `--help` only shows the issue #7 contract surface (`run / list / calibrate / diff / diff-json / comment / drift`), and legacy invocations still resolve via the rewrite.

Four tests pin the contract in `tests/test_cli_judge_alias.py`: top-level help omits `judge` (and includes the canonical four); `judge calibrate --help` and `calibrate --help` produce byte-identical output (proves the rewrite is faithful); `judge` alone fails at the parser; `judge unknown-subcommand` fails at the parser. The README quickstart's `eval-harness judge calibrate` is replaced with the canonical `eval-harness calibrate`, with a one-sentence note that the legacy form still works. The Benchmarks line at L321 gets the same fix.

Seventh post-v0.1 silent-drift fix today across the portfolio. The fix family is now well-established: every repo has had at least one "the README/contract claims X, the code does Y" gap, and closing them in this batch is bracing the portfolio against the rule §10 spends its longest entry on.

## 2026-05-22 — Issue #29: architecture doc reflects all nine shipped surfaces, not the judge-PR-only pre-shipping state

**Duration:** ~30 min. **Issue:** [#29](https://github.com/jt-mchorse/llm-eval-harness/issues/29). **PR:** [#30](https://github.com/jt-mchorse/llm-eval-harness/pull/30).

`docs/architecture.md` was committed alongside the judge + calibration PR (issue #2) and never reframed when issues #3 (regression runner), #4 (drift detection), #5 (pytest plugin), #6 (GitHub Action / sticky comment), #7 (CLI), #15 (`--tags` filter), and #17 (examples/) shipped over the following months. The directory diagram showed five modules (`dataset.py`, `judge.py`, `calibration.py`, `cli.py`, `__init__.py`); reality is ten (`runner.py`, `runs.py`, `drift.py`, `pytest_plugin.py`, `comment.py` are all on disk and exercised by CI). Two layer headers carried `(#2 · this PR)` framing. A "Pending downstream (open issues)" section listed five issues as future work that all closed long ago. Root README is already up to date and locked by `tests/test_readme_snapshot.py` + `tests/test_readme_defaults_snapshot.py`; only `docs/architecture.md` lagged.

Rewrote the doc with the full ten-module directory diagram (each line annotated with its origin issue) and added per-layer sections for #3 / #4 / #5 / #6 — the four downstream surfaces that had been "Pending". Added a "CLI surface" section enumerating the seven subcommands and explaining the D-007 backwards-compat alias plus #27's visibility regression guard. Added a "Cross-cutting surfaces" section covering #15 (`--tags`), #17 (examples), #24 (public surface lock), and the README hygiene patterns (#19, #22) — these aren't layers of their own but should appear somewhere in the architecture doc. Replaced "Pending downstream" with a "Where to look next" footer parallel to the embedding-model-shootout / vector-search-at-scale shape. The existing "What's deliberately not in the harness" block stayed — it was already honest steady-state framing.

Lock-against-drift: `tests/test_architecture_doc.py` is the third architecture-doc lock to land this session in a Python repo (after `embedding-model-shootout` PR #20 and `vector-search-at-scale` PR #22). Three invariants: every backtick-quoted `eval_harness/...`, `fixtures/...`, `examples/...`, `tests/...`, `docs/...`, `scripts/...`, `.github/...` token resolves on disk (placeholders containing `<...>`, `{...}`, or `*` are skipped — the `*` extension is new this strike, because the doc mentions `tests/test_cli_*.py` as a globbed file family rather than a literal); every issue in `KNOWN_SHIPPED_ISSUES = (1, 2, 3, 4, 5, 6, 7, 15, 17)` is referenced at least once (#19 README pivot, #20 demo capture, #22 README defaults, #24 public surface, #27 CLI alias are excluded — each is locked by its own dedicated snapshot/regression test); banned phrases (`this pr`, `pending downstream`, `(unfiled)`, `to-be-filed`) are absent. Three belt-and-braces hard-pin tests lock `BANNED_PHRASES`, `KNOWN_SHIPPED_ISSUES`, and `RESOLVABLE_PREFIXES` to their exact contents. Tamper-verified three ways. Full suite 176/176 (was 169; +7 new). `ruff check . && ruff format --check .` clean.

Fourteenth post-v0.1 drift fix in the portfolio pattern, fifth architecture-doc lock test in this session, third Python variant of the pattern. The portfolio now has eight repos with an architecture-doc lock test.

**Why this work, this session:** Loop iteration in a day session. Four architecture-doc fixes already landed today across other repos with the same shape; `llm-eval-harness` is the first repo in the build sequence and the natural target for the fifth strike. Issue #29 was filed mid-session as `priority:med` then closed in the same session per the session prompt's loop protocol.

**Open questions / blockers:** None — PR opened ready for review.

**Next session:** `prompt-regression-suite` is the remaining drift target in the portfolio (build sequence position 3, `docs/architecture.md` still says `## Shipped (this PR — issue #1)` + has `:::pending` mermaid nodes). Other repos either have clean docs already (rag-production-kit, agent-orchestration-platform, chunking-strategies-lab, python-async-llm-pipelines, llm-cost-optimizer) or have just landed the lock (cookbook, emb-shootout, vss, nextjs, ai-app, this one).

## 2026-05-23 — Architecture-doc active-decision-range axis + real-drift backfill (#31)

**Duration:** ~25 min. **Issue:** [#31](https://github.com/jt-mchorse/llm-eval-harness/issues/31). **PR:** [#32](https://github.com/jt-mchorse/llm-eval-harness/pull/32).

Fifth of twelve repos to land the active-decision-range upper-bound axis on its architecture-doc lock (sister to `rag-production-kit` PR #29, `llm-cost-optimizer` PR #27, `python-async-llm-pipelines` PR #24, `chunking-strategies-lab` PR #21). The axis parses `MEMORY/core_decisions_ai.md` for non-superseded `D-NNN` entries with id `>= MIN_ACTIVE_DECISION_ID` (2 — D-001 is the scope baseline) and fails loud when an active decision isn't cited anywhere in `docs/architecture.md`.

The new test caught **real drift** on first run — three omissions plus one outright mis-attribution: D-010 (`diff-json` SQLite-free posture, added to the Layer 6 paragraph), D-011 (top-level `calibrate` with `judge calibrate` as the hidden alias, added to the CLI Surface section), and D-012 (`pytest_generate_tests` vs `collection_modifyitems` for `pytest -k` / `pytest-xdist` compatibility, added to Layer 5). The CLI Surface paragraph also **incorrectly attributed** the `judge calibrate` alias to D-007 — fixed by replacing with D-011 there and adding the real D-007 reference (`AnswerSource` Protocol separation) to the Layer 2 Judge + Calibration section where it actually belongs.

Tamper-verified three axes: synthetic D-099 active block → per-D-NNN missing list fires; removing inline D-014 citation → same test fires with D-014 flagged; flipping `MIN_ACTIVE_DECISION_ID` → hard-pin fires. Pycache gotcha noted in next-session context: when changing a module-level constant, `tests/__pycache__` can serve the old compiled value across pytest runs; `rm -rf tests/__pycache__` clears it.

**Why this work, this session:** First in the multi-issue loop after Phase A merged seven open PRs. The active-decision-range axis is established as a portfolio pattern by four sister PRs and was missing in 8 of 12 repos; llm-eval-harness is §8 build-sequence #1 and starting here lets subsequent loop iterations cite it as the canonical template.

**Open questions / blockers:** none — PR ready for review.

**Next session:** Apply the same pattern to the next four repos with arch-doc tests but no D-axis (`embedding-model-shootout`, `vector-search-at-scale`, `prompt-regression-suite`, `agent-orchestration-platform`).

## 2026-05-23 — 60-second demo capture script (#20, AC3 of 3)

**Duration:** ~35 min. **Issue:** [#20](https://github.com/jt-mchorse/llm-eval-harness/issues/20). **PR:** [#33](https://github.com/jt-mchorse/llm-eval-harness/pull/33).

First issue picked under the day-session "issue genuinely actionable by Claude" rule — the portfolio reached the quiet point where every open issue is a `[demo]` GIF/MP4 capture, the v0.1 quality bar's only outstanding row across all twelve repos. Of the three acceptance criteria on each demo issue, two are operator-only (record the GIF, embed it in README) and one is scriptable — "capture script committed under `scripts/` so the demo can be re-captured deterministically." This session lands that third row for `llm-eval-harness`.

`scripts/capture_demo.py` sequences `examples/regression_run_and_diff.py` and `examples/drift_report.py` in-process under explicit `STAGE N` banners with a `--pause-seconds` knob so the screen recorder has cue points to cut on. The drift example's tempfile-path HTML is copied into a stable destination (`docs/demo-artifacts/drift_report.html`, gitignored — regenerated artifact, not source) and the printed path is rewritten in the captured stdout so the recording shows the stable destination, not a random tempdir. The browser auto-opens unless `--no-open`. For flow #3 (the sticky-comment HTML marker), which needs real PR webhook events and can't be Python-driven, the script prints a numbered cheat-sheet of `gh fork → push → re-push` commands the operator runs on a throwaway fork.

`tests/test_capture_demo_smoke.py` adds four tests under the same hermetic contract as the existing examples-smoke suite (no API key, no live network). The architecture-doc lock landed in a prior session already excluded #20 from its closed-feature-issue coverage list with the note *"capture script shipped in a separate PR and locked by `tests/test_capture_demo_smoke.py`"* — so this PR's test file is exactly the lock that prior session anticipated. The `scripts/` resolvable-prefix slot was likewise pre-reserved in `RESOLVABLE_PREFIXES`.

**Why this work, this session:** Day-session selection rules said pick the highest-priority unblocked issue in the earliest build-sequence repo; with zero `priority:high` and `priority:med` across all twelve repos, the only `priority:low` issues were the seven demo-GIF captures. `llm-eval-harness` is build-sequence #1; AC3 was the only Claude-actionable row. Doing AC3 here gives the next six demo issues across the portfolio a worked example to mirror.

**Open questions / blockers:** AC1 + AC2 require operator action (screen recorder + README embed). The PR is ready for review on AC3 standalone — issue #20 stays open until JT records the capture.

**Next session:** Continue the day-session loop on the next demo-capture issue. `nextjs-streaming-ai-patterns` #16 and `ai-app-integration-tests` #16 already reference capture scripts in their titles (so the AC3 row is already done there — those are pure AC1/AC2 operator blockers). The four remaining options with AC3 still open are `llm-cost-optimizer` #18, `prompt-regression-suite` #15, `rag-production-kit` #25, `mcp-server-cookbook` #16; build-sequence picks `llm-cost-optimizer` #18 next.

## 2026-05-24 — Issue #34: `diff` gains `--format markdown` and `--out`

**Duration:** ~20 min. **Issue:** [#34](https://github.com/jt-mchorse/llm-eval-harness/issues/34). **Branch:** `session/2026-05-24-0311-issue-34`.

`eval-harness diff` (SQLite-backed) was missing `--format markdown` and `--out`, both of which `eval-harness diff-json` (JSON-file-based) already had. The renderers (`render_delta_markdown`) and the parent-dir-creating `--out` plumbing already shipped on `diff-json` under D-010 — so this was a pure surface-parity dispatch, no new renderer and no new tradeoff. The asymmetry forced anyone with SQLite run history to detour through `run --out` + `diff-json` to get a markdown table for a PR comment, instead of just diffing the runs they already had.

New `tests/test_cli_diff_format.py` seeds two runs (`HighBackend` baseline → `LowBackend` current, every row flagged), reads back the `run_id`s from SQLite in `started_at` order — the first use of that pattern in this repo — then exercises `diff` under `ascii` / `json` / `markdown`, plus `--out` writing to a nested tmpdir, plus `--format json --out` for completeness. The markdown test pins the GFM table by row lines starting with `| ` rather than exact column count, since that's the renderer's contract, not the CLI's.

**Why this work, this session:** Opportunistic post-PR-A pick after merging the five capture-demo PRs (including this repo's #33 for issue #20). With every `priority:high`/`med` issue closed across the portfolio and only operator-blocked GIF captures remaining, a CLI parity gap surfaced cleanly from reading `eval_harness/cli.py` — narrow, well-scoped, ships in one session.

**Open questions / blockers:** none — PR ready for review.

**Next session:** Continue the night-session loop on the next portfolio repo. Build-sequence #2 is `llm-cost-optimizer`; survey its CLI surface and README for similar narrow parity gaps.

## 2026-05-24 — Issue #36: `list` gains `--out` for parity with `run` / `diff` / `diff-json`

**Duration:** ~30 min. **Issue:** [#36](https://github.com/jt-mchorse/llm-eval-harness/issues/36). **Branch:** `session/2026-05-24-1512-issue-36`.

`list` was the last subcommand without `--out`. It already accepted `--json` (boolean → JSON array on stdout), but the only sink was stdout, so CI consumers wanting a JSON artifact had to shell-redirect — which can't auto-create missing parent dirs and gives no way for a Python-driven CI step to assert the artifact exists. After #35 brought `diff` in line this morning, `run` / `diff` / `diff-json` all already had `--out PATH` with the same `Path(args.out).parent.mkdir(parents=True, exist_ok=True)` plumbing. This PR finishes the four-subcommand parity.

`_run_list` refactored to build the rendered string up front — text table, JSON array, or one of the no-runs short-circuits — and dispatch through a single new `_emit_list_output` helper that mirrors the `_run_diff` / `_run_diff_json` sink decision. The missing-DB short-circuit routes through `--out` too, so a caller asserting `runs.json` exists after the step doesn't trip on absence when the DB hasn't been created yet. New `tests/test_cli_list_out.py` adds 5 tests: both formats happy-path with stdout silent under `--out`, nested parent dir auto-create, missing-DB `[]` artifact through `--out`, and a regression guard that the no-`--out` JSON and text stdout paths still emit unchanged.

Tail tally: 193 / 193 pass, ruff clean. Pre-#36 baseline was 188 — the prior PR (#35) description overstated its own post-merge total as 193 when it was actually 188; the #37 PR description was edited after the initial open to pin the accurate number rather than echo the prior PR's number.

**Why this work, this session:** First Phase B+C target of a 180-min day session, after Phase A merged 10 ready PRs across the portfolio in ~20 minutes. With every `priority:high` and `priority:med` issue closed across all twelve repos and only operator-blocked GIF captures remaining, narrow CLI parity gaps surfaced cleanly from reading the CLI surface. `list` was the obvious one in `llm-eval-harness` — well-scoped, ships in one session, finishes the `--out` axis.

**Open questions / blockers:** none — PR ready for review.

**Next session:** Continue the day-session loop. Build-sequence #2 (`llm-cost-optimizer`) and #3 (`prompt-regression-suite`) are the natural next pick-ups. Survey their CLI surfaces for the same shape of parity gap; if nothing surfaces, drop to the per-script `--dry`-style audit pattern that landed #31 this morning.

## 2026-05-24 — Issue #38: diff_runs rejects negative threshold_drop at the library boundary
**Duration:** ~25 min · **Branch:** `session/2026-05-24-issue-38`

- `_status_for(delta, threshold_drop)` flips the sign at `runner.py:282` as `delta < -threshold_drop`. A user typing `--threshold-drop=-0.05` got a silently corrupted regression report — passing PRs reported as failing and vice versa. The CLI exposes `--threshold-drop` three times (`run`, `diff`, `diff-json`) with no argparse-level validator.
- Added a single `if threshold_drop < 0.0: raise ValueError(...)` at the top of `diff_runs`. Library-boundary guard funnels every CLI path plus programmatic use through one canonical check; comment in source documents the sign-flip failure mode.
- Seven new tests in `tests/test_runner.py` under a `#38` block: negative raises with the offending value in the message; zero accepted (boundary — "flag any drop"); existing positive 0.05 still works (regression pin); parametrized sweep over `-1e-6, -0.001, -0.5, -1.0` all raise. A `_make_two_runs_for_diff` helper was hoisted from the existing `TestDelta` to keep the new tests dependency-free.

**Why this work, this session:** Sister to today's `llm-cost-optimizer` #32 (`UncertaintyRouter` validates signal names at construction). Same value-domain validation parity family — the rest of the eval-harness surface raises at boundaries (`_load` empty-dataset, `EmptyTagFilterError`, `JudgeScore.__post_init__` score-in-range, `comment.upsert_sticky_comment` marker check); `threshold_drop` was the one user-supplied magnitude flowing through to math layer unchecked.

**Open questions / blockers:** none — PR ready for review.

**Next session:** Continue the day-session loop. Build sequence #3 (`prompt-regression-suite`) and #4 (`rag-production-kit`) are the next viable hunting grounds; both have similar Protocol-or-CLI value-domain surfaces worth scanning.

## 2026-05-24 — Issue #40: compute_drift validates threshold range at boundary
**Duration:** ~20 min · **Branch:** `session/2026-05-24-issue-40`

- `compute_drift` exposes three thresholds (`length_threshold`, `embedding_threshold`, `judge_threshold`, each defaulting `0.10`) that gate `AxisReport.status` as `drift > threshold`. JSD is bounded `[0, 1]` per D-014, so any threshold outside that range silently breaks the gate: `threshold > 1.0` makes it un-trippable; `threshold < 0.0` makes it trip on every input including identical golden/candidate sets. The harm reaches every consumer of the public surface (`eval_harness/__init__.py:40,100`) including the `drift` CLI subcommand.
- Added a single-loop validator at function entry that raises `ValueError(f"{name} must be in [0.0, 1.0]; got {value}")` for any out-of-range threshold, mirroring the error shape at `drift.py:152,183` and the recent `runner.diff_runs` guard from PR #39. Validation runs before any histogram / hash-embed / k-means work so bad config fails fast.
- Two parametrized test blocks in `tests/test_drift.py` under a `#40` comment header: one over `(axis-name, bad-value)` proving each axis raises with its own parameter name in the message; one over `(axis-name, good-value)` proving the inclusive bounds `0.0` and `1.0` are accepted alongside `0.5`. Net 24 new collected cases.

**Why this work, this session:** Direct extension of the #38/#39 pattern that landed earlier today. Same harm class (numeric threshold, single comparison gate, no boundary validation), same fix shape, slightly broader (3 parameters × 1 function vs 1 parameter × 3 entrypoints). With every `priority:high`/`priority:med` issue closed across the portfolio, this kind of contract-tightening sweep is the right autonomous-session work.

**Open questions / blockers:** none — PR ready for review.

**Next session:** Continue the day-session loop. Build sequence #2 (`llm-cost-optimizer`) and #3 (`prompt-regression-suite`) are the natural next pickups after this one merges; scan their public-surface threshold/range parameters for the same shape of gap.

## 2026-05-25 — Issue #42: extend sign-only guards on diff_runs.threshold_drop and list_runs.limit to finiteness
**Duration:** ~25 min · **Branch:** `session/2026-05-24-issue-42`

- Two existing sign-only range checks let `NaN` and `+/-Infinity` through. `runner.diff_runs.threshold_drop` (#38-shipped guard at `runner.py:304`) accepted `NaN`; `_status_for` then computed `delta < -NaN` = always false, so every row was classified as non-flagged regression → the CI regression gate that `--threshold-drop` drives silently disabled. `+Infinity` had the inverse silent-degradation shape. `runs.list_runs.limit` accepted `NaN` (propagated into the SQLite `LIMIT` bind as a cryptic `sqlite3.InterfaceError`) and floats (`0.5` silently truncated to `0` in SQLite's integer coercion → zero rows returned).
- Tightened both: `threshold_drop` now requires `math.isfinite(x)`; `limit` now requires `isinstance(x, int) and not isinstance(x, bool) and x > 0` (the explicit `bool` exclusion exists because Python's `bool` subclasses `int`). Error messages updated from "must be >= 0.0" / "must be positive" to "must be a finite number >= 0.0" / "must be a positive integer" so callers can grep the new contract. Two pre-existing tests that pinned the old message strings updated in place.
- 14 new tests: `tests/test_runner.py` parametrized over `[NaN, +Infinity, -Infinity]` for `threshold_drop`; `tests/test_runs.py` new `TestListRunsLimitValidation` class parametrized over `[0, -1, 0.5, 1.5, NaN, +Inf, -Inf, "10", True, False]` plus boundary acceptance. Test count 238 (was 224 after #40). Ruff clean.

**Why this work, this session:** Sixth Phase B+C target in the 360-min night session. Brings llm-eval-harness's existing sign-only contract checks (from #38/#39/#40) into the same finiteness contract that landed across the portfolio tonight: `ai-app-integration-tests#24`, `nextjs-streaming-ai-patterns#24`, `mcp-server-cookbook#32`, `agent-orchestration-platform#29`, `prompt-regression-suite#35`. Second PR in this repo tonight; the first was via the Phase A fixup-merge of PR #41 (#40 D-014 `compute_drift` threshold validation).

**Open questions / blockers:** none — PR ready for review.

**Next session:** Continue the loop. `llm-cost-optimizer` and `rag-production-kit` are natural next targets for a second iteration tonight — both already had a contract-tightening PR fixup-merge today but the deeper validation gap pattern (silent-clamp removal, finiteness extension) hasn't been swept through their cost dataclasses comprehensively.

## 2026-05-25 — Issue #44: `AnthropicBackend(max_tokens=...)` value-domain validation
**Duration:** ~25 min · **Branch:** `session/2026-05-25-issue-44`

- Hoisted a positive-integer validator above the lazy `import anthropic` in `AnthropicBackend.__init__`, matching the `runs.list_runs.limit` shape from #42 (`not isinstance(int) or isinstance(bool) or <= 0`). Construction now fails fast with `ValueError("max_tokens must be a positive integer; got ...")` regardless of whether the optional `judge` extra is installed.
- Closed three silent failure modes: `max_tokens=True` silently bound `1` and returned a 1-token judge response (surfaced far downstream as `JudgeParseError`); `0`/negative reached the Anthropic API as opaque 400s; `0.5`/`NaN`/`inf` slipped sign-only checks and either reached the API or behaved as `False` (NaN <= 0 is False).
- Added `tests/test_judge_max_tokens_validation.py`: 16-value reject matrix (bool/zero/negative/float/NaN/inf/None/str/list/tuple/dict), boundary acceptance for `1/2/256/512/100_000`, and a pinning test proving validator-runs-before-lazy-import (asserts `ValueError` rather than `ImportError` in an env without the extra). 23 new tests; full suite 238 → 261.

**Why this work, this session:** First Phase B+C target in today's 180-min DAY session after the Phase A pass squash-merged three ready PRs (`rag-production-kit#41`, `embedding-model-shootout#34`, `llm-cost-optimizer#39`) — all three were the same portfolio-wide positive-int contract sweep. Extending that same sweep into `judge.py` lands the first validator in the judge module and matches the construction-site pattern from `embedding-model-shootout#34` (validator above lazy import).

**Open questions / blockers:** none — PR ready for review.

**Next session:** Continue the multi-issue loop. Deferred follow-ups from `rag-production-kit#41` (`generator.max_chunks`, `embedder.dim`, `streaming.PhaseTimings.percentile`) and `embedding-model-shootout#34` (`hash_embedder.dim/ngram`, `synthesize_queries n/min/max`) are the next natural targets — both repos explicitly named them in PR bodies, both fit the same active pattern.

## 2026-05-26 — Issue #46: Bounded-float validation on calibration thresholds
**Duration:** ~20 min · **Branch:** `session/2026-05-25-1900-issue-46`

- `binarize(threshold)` and `render_report(threshold_kappa)` now use the bounded-float validator shape established by `compute_drift` in #40: reject `NaN`/`inf`/`-inf`/`bool`/non-numeric, then enforce the explicit value-domain range (`[0, 1]` for `binarize.threshold` to match `JudgeScore.score`; `[-1, 1]` for `threshold_kappa` to match Cohen's κ).
- Closes two silent-failure modes documented in #45's deferred list: `threshold=NaN` silently produced κ=0 via the degenerate `pe == 1.0` branch in `cohens_kappa`; `threshold_kappa=NaN`/`-2` silently broke or disabled the CI gate.
- 47 new parametrize tests across both sites. Full suite 261 → 285. Ruff clean.

**Why this work, this session:** Fourth Phase B+C target in today's 180-min DAY session and second PR in this repo today. PR #45 (`AnthropicBackend.max_tokens`) explicitly named these two calibration boundaries as "Out of scope (file separately if needed)" — closing them in the same session keeps the deferred-list-closure narrative consistent across the day's PRs (`rag-production-kit#43`, `embedding-model-shootout#36`, and now this one).

**Open questions / blockers:** none — PR ready for review.

**Next session:** With four explicit deferred-lists now closed in one day (`llm-eval-harness#45` for judge max_tokens, `rag-production-kit#43` for three deferred sites, `embedding-model-shootout#36` for five deferred sites, and this PR for two calibration sites), the active validation-sweep arc has no remaining named follow-ups. Next sessions can pivot to discovery passes on repos not yet touched today (`prompt-regression-suite`, `chunking-strategies-lab`, `vector-search-at-scale`, `python-async-llm-pipelines`, `agent-orchestration-platform`, `mcp-server-cookbook`, `nextjs-streaming-ai-patterns`, `ai-app-integration-tests`) or pivot away from validation entirely.

## 2026-05-26 — Issue #48: Atomic `--out` writes (the first non-validation pivot)
**Duration:** ~25 min · **Branch:** `session/2026-05-26-1510-issue-48`

- All four `--out` write sites in `eval_harness/cli.py` used `Path(args.out).write_text(...)` directly — not atomic. SIGINT/SIGTERM/disk-full/OOM between the implicit `open(..., "w")` truncate and `close()` flush leaves the destination zero-length or partial. The blast radius traces through the GitHub Action (D-006): `run --out` → `diff-json --out` → `comment` consumes whichever JSON the prior step wrote. A workflow cancellation in any of the first two steps leaves a half-written file that the next step parses, and the sticky PR comment posts garbage (or the workflow fails with a misleading `json.JSONDecodeError`).
- Added a single `_atomic_write_text(path, text)` helper to `eval_harness/cli.py`: writes to a `tempfile.NamedTemporaryFile(dir=target.parent, delete=False)` sibling, `fsync`s, then `os.replace`s. Same-directory placement is load-bearing — guarantees same filesystem so the rename can't fall back to a copy. On any exception between temp write and rename, `contextlib.suppress(FileNotFoundError)` cleans up the temp leftover.
- Routed all four `--out` call sites through it: `_run_run` (cli.py:300), `_run_diff` (336), `_run_diff_json` (354), `_emit_list_output` (448 — used by all four `list --out` paths including the missing-DB short-circuit).
- 11 new tests in `tests/test_cli_atomic_out.py`: six unit tests on the helper itself (happy path; parent-dir create; overwrite; the load-bearing `os.replace`-raises destination-absent invariant; `os.replace`-raises temp-cleanup invariant; overwrite-fails destination-unchanged invariant — the property `Path.write_text` could never offer) and five integration tests (one per `--out` subcommand proving the routing through the helper survives a monkeypatched `os.replace` failure, plus an end-to-end happy-path covering all four `--out` surfaces in sequence with valid content assertions). Full suite 327 → 338. Lint and format green.

**Why this work, this session:** First Phase B+C target in today's 180-min DAY session and the first explicit pivot away from the validation arc. Prior session memory called out `portfolio_validation_arc_is_saturated_future_sessions_should_pivot_away_from_validation`. Output-layer atomicity is the natural next harm class: the prior arc closed input-rejection at function-entry boundaries; this closes corrupt outputs to disk at a single chokepoint with a portable, stdlib-only pattern.

**Open questions / blockers:** none — PR ready for review.

**Next session:** Loop continues — multiple repos plausibly need the same atomic-write pattern wherever a CLI emits an artifact consumed by another step. `llm-cost-optimizer` (dashboard JSON), `prompt-regression-suite` (HTML diff reports), and `rag-production-kit` (cost telemetry rollup) are the natural deeper targets. Or pivot to a different harm class on a TypeScript repo — `mcp-server-cookbook` or `agent-orchestration-platform` may have analogous artifact writes.

## 2026-05-26 — Issue #50: Promote `atomic_write_text` to package-level, close remaining drift / dataset / calibrate sites
**Duration:** ~35 min · **Branch:** `session/2026-05-26-1910-issue-50`

- PR #49 landed a file-private `_atomic_write_text` in `cli.py` and called out `eval_harness/drift.py:679` as a deferred follow-up. This session promoted the helper to a public package-level symbol at `eval_harness/io_utils.py` and routed all five remaining non-atomic write sites through it: the explicit drift HTML deferred site, plus two uncovered sites — `dataset.py:145` (`Dataset.dump_jsonl` for canonical-form JSONL) and `cli.py:279` (`calibrate --report` HTML, which PR #49 missed because it's a different argument name from `--out`). The four existing `--out` sites in cli.py were refactored to import the public helper; the private `_atomic_write_text` was removed.
- Codified the portfolio-wide pattern that emerged from the 2026-05-26 atomic-write arc with D-015: atomic-write helpers live in package-level `io_utils` modules, not file-private. `rag-production-kit#44/#45` led with `rag_kit/io_utils.atomic_write_text`; `prompt-regression-suite#40` followed in `prompt_regression/io.py`; this issue promoted `llm-eval-harness` to match. Three other repos (`llm-cost-optimizer`, `mcp-server-cookbook`, `ai-app-integration-tests`) used a similar shape from the start. Only `cli.py`'s file-private placement was the outlier; that's now closed.
- Test churn: the 6 unit tests on the helper moved from `tests/test_cli_atomic_out.py` (where they imported `_atomic_write_text` from `cli`) to a new colocated home at `tests/test_io_utils_atomic_write.py` (where they import `atomic_write_text` from `io_utils`). Added 3 new integration tests for the three new call sites (drift, dataset, calibrate) plus 2 cross-cutting tests (dataset round-trip byte-stability survives the helper integration; `encoding` parameter is honored). The existing `test_cli_atomic_out.py` kept its 5 CLI `--out` integration tests, with imports updated to monkey-patch `eval_harness.io_utils.os.replace` (not `eval_harness.cli.os.replace`, which no longer exists since cli.py no longer imports `os`). Full suite went 313 → 324. Lint and format green.

**Why this work, this session:** First Phase B target of today's 180-min DAY session, after a six-PR squash-merge Phase A from the morning's atomic-write fanout. The deferred drift.py site from #49 was the most obviously named loose end; exploring it surfaced two additional non-atomic sites (`dataset.py` and `cli.py:279`) that #49 hadn't flagged. Promoting the helper to a public module made all three reachable with a single import and centralized the test-surface monkey-patch target, matching the pattern five other repos already use.

**Open questions / blockers:** none — PR ready for review.

**Next session:** Continue the multi-issue DAY loop — pick a different repo. Candidate harm classes the portfolio hasn't yet covered: (a) input-trust on external API responses (Anthropic, embeddings, etc. — what if the response is missing fields or has unexpected shape?), (b) resource leaks on error paths (file handles, sqlite connections, subprocess handles), (c) determinism guarantees in tests (pinned seeds, no clock-dependent fixtures), (d) extending the io_utils promotion to other repos that still have a file-private atomic-write helper. (d) is the lowest-friction next move since the pattern is identical and the value is portfolio-coherence.

## 2026-05-26 — Issue #52: README decision-range upper-bound lock
**Duration:** ~15 min · **Branch:** `session/2026-05-26-2319-issue-52`

- Added `test_decision_range_cites_latest_active` and `_max_active_decision_id` helper to `tests/test_readme_snapshot.py`. Sister lock to chunking-strategies-lab's same-named invariant, which caught real drift this session.
- Bumped README's architecture-section to cite `D-002…D-015` (D-015 = the io_utils package-level decision from #51).

**Why this work, this session:** Authoring this lock in chunking-strategies-lab this session caught D-011 → D-012 drift; propagating the invariant to the other 10 portfolio repos closes the same drift class portfolio-wide. llm-eval-harness was first because it had also just gained a new decision (D-015) without the README being updated — exactly the failure mode the test guards.

**Open questions / blockers:** none.

**Next session:** Continue propagating the lock to the remaining nine repos (llm-cost-optimizer next per build sequence).

## 2026-05-27 — Issue #54: CONTRIBUTING.md cadence-wording propagation
**Duration:** ~3 min · **Branch:** propagation branch · **PR:** #55

- Replaced pre-D-008 `~60-minute session cap` line with D-008 (180/360 min, multi-issue loop) and D-004 (Phase A PR auto-merge) wording, matching the bootstrap template post-portfolio-ops#3.

**Why this work, this session:** Iteration in the autonomous NIGHT session propagation arc for portfolio-ops#3.

**Open questions / blockers:** none.

**Next session:** continue portfolio propagation.

## 2026-05-27 — Issue #54: CONTRIBUTING.md cadence-wording propagation
**Duration:** ~3 min · **PR:** #55

- Replaced pre-D-008 `~60-minute session cap` line with D-008 (180/360 min, multi-issue loop) and D-004 (Phase A PR auto-merge) wording, matching the bootstrap template post-portfolio-ops#3.

**Why this work, this session:** Iteration in the autonomous NIGHT session propagation arc for portfolio-ops#3.

**Open questions / blockers:** none.

**Next session:** continue portfolio propagation.

## 2026-06-01 — Issue #56: `eval-harness validate` subcommand
**Duration:** ~60 min · **Branch:** `session/2026-06-01-1515-issue-56`

- Added `validate_dataset(path) -> ValidationReport` to `eval_harness/dataset.py`. Walks a JSONL golden in *collecting* mode (vs. `load_jsonl`'s fail-fast) so one command surfaces every malformed row instead of the operator running, fixing, re-running until clean. Five stable finding codes: `parse`, `schema`, `duplicate_id`, `version_drift`, `empty`. `ValidationReport` is a frozen dataclass with `n_rows`, `n_valid`, `dataset_version`, `tag_counts` (desc-by-count then alpha tiebreak), and a tuple of `ValidationFinding` entries. Duplicate-id and version-drift rows are excluded from the tag histogram so shadow rows don't skew coverage signal.
- Wired `eval-harness validate <path> [--json]` in `eval_harness/cli.py`. Exit codes 0/1/2 (clean / findings / I/O error) match the convention `scripts/audit_phase_a.py` set in portfolio-ops#19 — CI consumers can chain validators uniformly. Re-exported `validate_dataset`, `ValidationReport`, `ValidationFinding` from `eval_harness/__init__.py`.
- 14 tests in `tests/test_validate.py`: factuality fixture happy path (verifies tag histogram and dataset_version), accumulating-errors path (three different bad shapes interleaved with a valid row, findings reported in line-number order), duplicate-id detection with first-seen-line reference, version-drift, empty-file (single `empty` finding at line 0), missing file → `FileNotFoundError` → CLI exit 2, `to_dict` shape stability, frozen-dataclass round trip, and CLI end-to-end across clean / malformed / `--json` / missing-file paths.
- README "What this is" extended to a tenth bullet (#56) and CLI surface bullet (#7) extended to include `validate`. `docs/architecture.md` cross-cutting section gained the new surface. `tests/test_architecture_doc.py::KNOWN_SHIPPED_ISSUES` and its hard-pin assertion both updated to include 56; `tests/test_readme_snapshot.py` expected-sequence in `test_what_this_is_section_lists_nine_closed_issues_in_order` extended too (name of the test is now technically a misnomer — left as-is to preserve git blame; happy to rename in a follow-up).

**Why this work, this session:** First DAY-session iteration of 2026-06-01. All twelve portfolio repos at zero priority:high open issues at session start; per build-sequence rule and the "file an issue if none exists" fallback, `llm-eval-harness` was earliest in the sequence and the most natural gap was a pre-flight dataset linter — every other CLI surface costs API tokens to exercise.

**Open questions / blockers:** none — full pytest pass, ruff clean, live CLI smoke against `fixtures/sample_factuality_v1.jsonl` returns the expected `ok:` summary at exit 0.

**Next session:** the validator could grow a `--allow-tags '<a,b,c>'` flag that flags rows tagged with anything outside the allowlist — useful for repos that want to enforce a closed tag vocabulary. Not in scope for #56; would be a clean follow-up.

## 2026-06-01 — Issue #58: `eval-harness validate --calibration` subcommand
**Duration:** ~50 min · **Branch:** `session/2026-06-01-1914-issue-58`

- Added `validate_calibration(path) -> ValidationReport` in `eval_harness/calibration.py` mirroring `validate_dataset` (#56). Walks the calibration JSONL in *collecting* mode so one pre-flight surfaces every malformed row before `eval-harness calibrate` spends judge tokens up to the first bad one. Finding codes `parse | schema | duplicate_id | score_range | empty` — four shared with the golden-dataset validator plus the calibration-specific `score_range` (`human_score` outside `[0, 1]`). Same `ValidationReport` dataclass returned, with `dataset_version=None` and `tag_counts=()` (calibration schema has neither), so CI consumers can route both outputs through one parser.
- Wired `eval-harness validate --calibration <path>` into `eval_harness/cli.py`. Exit codes 0/1/2 unchanged; `--json` round-trip works identically; summary line shows `version=calibration` so the operator can tell the kind at a glance, and error messages say `calibration not found` instead of `dataset not found` when the flag is set.
- `CalibrationLoadError` grew an optional `.code` field (default `schema`, `score_range` for the range check). The collecting-mode walker reads `e.code` to route findings without re-parsing the reason text. Backwards-compatible — `load_calibration` callers only ever referenced `line_no` and `reason`.
- 14 new tests in `tests/test_validate.py` (appended to the existing file rather than creating a sibling — the unit of test is the shared `ValidationReport` contract, not the kind): ok path on the shipped 50-row `fixtures/calibration.jsonl`, accumulating bad rows in source order, duplicate-id with shadow-row exclusion, score_range out-of-range float, bool-as-number schema rejection (subtle isinstance(bool) check), missing required field, unknown top-level field, non-object row, empty file, missing file, ValidationReport JSON-shape parity, CLI ok/fail/exit-2 paths, `--json` round-trip, kind-aware error message.
- README bullet 11 cites #58; architecture mermaid grows a `validate --calibration` edge off the calibration node; `docs/architecture.md` invariants section gains a parallel paragraph. `tests/test_architecture_doc.py::KNOWN_SHIPPED_ISSUES` extends to `(..., 56, 58)`; `test_readme_snapshot.py` expected ordering does the same. Full suite 357/357 green; ruff check + format clean.

**Why this work, this session:** Phase A merged three clean PRs (eval-harness#57, prompt-regression-suite#48, cost-optimizer#51) and surfaced zero remaining priority:high issues across all twelve portfolio repos. The natural gap that pays for itself: calibration is the κ ≥ 0.6 CI gate (D-005), and `load_calibration` is still fail-fast on the first malformed row — exactly the operator pain `validate_dataset` (#56) was designed to eliminate for the golden datasets. Closing the symmetric loop on the calibration set was the cleanest, scoped Phase B unit for this DAY session.

**Open questions / blockers:** none — full pytest + ruff green; live CLI smoke against `fixtures/calibration.jsonl` returns the expected `ok:` summary at exit 0.

**Next session:** the validator could grow a `--strict-provenance` flag that checks for required provenance keys (e.g., `labeled_by`, `added_on`) — currently the loader accepts any dict. Not in scope for #58; would be a clean follow-up if the calibration set ever grows multi-labeler entries.

## 2026-06-17 — Issue #60: Workflow YAML-parseability lock
**Duration:** ~25 min · **Branch:** `session/2026-06-17-1909-issue-60`

Added `tests/test_workflows_yaml_parseable.py` and pulled `pyyaml>=6.0`
into `[project.optional-dependencies].dev`. The test parametrizes
`yaml.safe_load` plus a non-empty `jobs:` assertion over every `*.yml`
under `.github/workflows/` — today that's `ci.yml` and `eval.yml`, so
5 tests total (1 smoke + 2 parse + 2 jobs). It grows naturally as
workflow files are added.

**Why this work, this session:** `portfolio-ops#27` closed a 21-day
silent CI outage caused by a single unquoted colon-space in a `run:`
value. GitHub Actions silently completed the workflow with zero jobs
and `conclusion=failure`; `statusCheckRollup` stayed empty so Phase A
auto-merge couldn't tell. `portfolio-ops#30` shipped the lock for
`portfolio-ops` itself; the session memory explicitly called out the
remaining 12 repos as a propagation followup. This PR is the first
hop. `llm-eval-harness`'s workflows are safe today (they use the
`run: |` block-scalar form) — the lock makes that *cannot* drift.

**Open questions / blockers:** none — full pytest (358 → 363) + ruff
clean locally; PR #61 open and waiting for CI.

**Next session:** propagate the same lock to the other 11 portfolio
repos (one issue + one PR per repo).

## 2026-06-17 — Issue #62: timeout-minutes guard + lock test
**Duration:** ~30 min · **Branch:** `session/2026-06-17-2318-issue-62`

- Added `timeout-minutes: 15` to all three jobs in `.github/workflows/ci.yml` (lint, test matrix, memory-check) and `timeout-minutes: 10` to the eval-comment job in `.github/workflows/eval.yml`. GitHub Actions defaults to 360 min/job when `timeout-minutes` is missing — a hung job burns the full 6-hour ceiling before being killed.
- Added `tests/test_workflows_timeout_minutes.py` with 13 new tests: 1 discovery smoke + 3 parametrized (has-timeout, is-int with bool-subclass guard, in-band) × 4 jobs. Per-repo policy band `[1, 30]` with a comment naming what workload would justify bumping the max.
- Filed and worked the issue in the same session. Pre-existing backlog across the 12 portfolio repos was either operator-blocked (API keys, demo captures) or empty, so per the session-prompt fallback I filed a real-content issue and worked it.

**Why this work, this session:** Portfolio-wide survey today showed 1/17 workflows had `timeout-minutes` set. The other 16 ran unbounded. This is the canonical first hop in propagating the lock — same pattern as the YAML-parseability lock (#60 ← portfolio-ops#30/#31) that propagated this morning across the 12 repos. llm-eval-harness is first in the §8 build sequence, so the policy band gets calibrated here and per-repo overrides flow from there.

**Open questions / blockers:** none. 358 → 371 pytest passes, ruff clean. PR #63 open.

**Next session:** Propagate to the remaining 11 portfolio repos (one issue + one PR each, per-repo policy band override expected for the heavy-benchmark ones). After a few weekly cycles of the new audit-cron (portfolio-ops#34, this morning), consider adding a `missing-timeout` fingerprint to `scripts/audit_phase_a.py`.

## 2026-06-18 — Issue #64: concurrency guard + lock test
**Duration:** ~30 min · **Branch:** `session/2026-06-18-1515-issue-64`

- Added top-level `concurrency:` block to both `ci.yml` (group
  `ci-${{ github.ref }}`) and `eval.yml` (group `eval-${{ github.ref }}`,
  distinct so the two workflows don't cancel each other on the same ref).
  Both set `cancel-in-progress: true`.
- Added `tests/test_workflows_concurrency.py` — 7 new tests: 1 smoke +
  3 parametrized invariants × 2 workflows (`has_concurrency`,
  `group_is_nonempty_string`, `cancel_in_progress_is_true_bool`). Same
  PT018 split-assert pattern as the timeout-minutes lock so ruff stays
  clean while each invariant fails on its own line.

**Why this work, this session:** the audit-side fingerprint shipped in
portfolio-ops #41 (2026-06-18 night) surfaces every workflow missing a
top-level `concurrency:` group. Survey at the start of this session: only
`ai-app-integration-tests` had the lock (the template); 12 of 13 portfolio
repos with 19 workflows were unprotected. `llm-eval-harness` is the
canonical first hop for the propagation, mirroring the timeout-minutes
arc (#62 here → 11 follow-on per-repo PRs over the night session). Without
a concurrency group, a rapid push-on-push burns one full CI run per push
even when the in-flight run is immediately superseded.

**Open questions / blockers:** none. Test count 371 → 378. Full pytest
clean; ruff check + ruff format --check clean.

**Next session:** propagate the same lock pattern to the remaining 11
unprotected repos — separate issues filed through the multi-issue loop
this session and chained across day/night sessions.

## 2026-06-19 — Issue #66: validate --out for sink-parity
**Duration:** ~28 min · **Branch:** `session/2026-06-19-0318-issue-66`

- Added `--out PATH` to `eval-harness validate` so its output (human
  summary or `--json` payload) atomic-writes to disk instead of stdout.
- `_run_validate` builds the rendered string once, then routes through
  `atomic_write_text(args.out, rendered)` when `--out` is set, else
  `print(rendered, end="")`. Findings continue to print to stderr in
  human-readable mode regardless of `--out` so the operator's diagnostic
  channel survives stdout capture.
- Exit-2 (file-not-found) raises before any rendering, so `--out` leaves
  no zero-byte sentinel a CI step could mistake for "ran successfully".
- 6 new tests; README `Dataset validator` section gains a one-line
  `--out` example.

**Why this work, this session:** sibling-of-#36 propagation. After this
PR, all 5 output-producing subcommands (`run / list / diff / diff-json /
validate`) accept `--out` with identical atomic-write semantics.

**Open questions / blockers:** none. 378 → 384 pytest passes. PR #67
open and ready.

**Next session:** consider whether `drift --output` (positional-required
on a different shape) should be normalized to `--out` for symmetry —
separate consideration, behaviorally a breaking change to that CLI surface.

## 2026-06-19 — Issue #68: DeltaReport.from_json + RowDelta.from_json — drop the SimpleNamespace shim
**Duration:** ~25 min · **Branch:** `session/2026-06-19-issue-68`

- Filed issue #68 during this session's Phase A loop as a direct sibling-propagation of chunking-strategies-lab #47 (PR #48): same asymmetric `to_json` without inverse, but with a louder symptom — `cli._run_comment` carried a 30-line `SimpleNamespace` shim plus a `# type: ignore[arg-type]` silencer to make the renderer accept a duck-typed object pretending to be a `DeltaReport`. Worked immediately.
- Added `RowDelta.from_json(payload)` and `DeltaReport.from_json(payload)` classmethods, symmetric to the existing `to_json()`. Top-level `DeltaReport.from_json` defaults match exactly what the SimpleNamespace shim was applying (`current_run_id='current'`, `baseline_run_id='baseline'`, `suite='(unknown)'`, `threshold_drop=DEFAULT_THRESHOLD_DROP`) — that defaulting moves from the CLI into the dataclass classmethod so the CLI no longer needs a defensive `.get(...)` chain.
- `threshold_drop` is float-coerced (older operator-hand-written payloads may carry it as int/string). `summary` is dict-copied (not aliased) so caller mutations don't bleed into the frozen dataclass — locked by a dedicated test.
- `cli._run_comment` collapses from ~30 lines of shim construction plus the `types.SimpleNamespace` import plus the `# type: ignore[arg-type]` annotation to two lines: `report = DeltaReport.from_json(payload); body = render_delta_markdown(report)`. The renderer now gets a properly-typed instance.
- 9 new tests in `tests/test_comment.py`: row-level identity, optional-field defaults, missing-required-key raises (×2 fields), report-level populated + empty round-trips, default-fill matches prior shim, threshold_drop float coercion, summary-independent-copy invariant, and an end-to-end CLI `comment --dry-run` test verifying the markdown output is byte-identical to direct `render_delta_markdown` against a hand-built `DeltaReport`. The last test is the real safety net: it proves the swap is behavior-preserving on the production CLI path, not just on synthetic dataclass round-trips.

**Why this work, this session:** the portfolio is saturated and the chunking-strategies-lab #47 work I closed earlier this session named this exact pattern as a sibling-propagation candidate. The `# type: ignore[arg-type]` was an active piece of technical debt in production CLI code today, not just a missing API — strictly higher value than a synthetic API-completeness fill.

**Open questions / blockers:** none. 384 → 393 pytest passes. PR #69 merged.

**Next session:** the from_json propagation chain is now at two hops (chunking #47/#48 + this PR). The natural third hop is `rag-production-kit` — `PhaseTimings.to_dict()` + `Aggregate.to_dict()` shipped in earlier sessions without symmetric readers. Worth filing as a sibling issue if a future session needs substantive work in a saturated portfolio state. The `RunResult ↔ StoredRun` asymmetry in this repo's `load_run_result_from_json` is intentional (deliberate shape change for the diff path), not a from_json gap; not in scope.

## 2026-06-22 — Issue #71: judge parser — symmetric out-of-range score clamp
**Duration:** ~20 min · **Branch:** `session/2026-06-22-0310-issue-71`

- Found during Phase A code-reading: `parse_judge_output` clamped a too-high judge score (`SCORE: 1.05` → `1.0`) but the too-low side was unreachable — the SCORE regex had no optional sign, so `SCORE: -0.2` failed the SCORE-line match and raised a misleading `missing SCORE: line` error. The `max(0.0, ...)` half of the clamp was dead code for anything the regex could match.
- Fix: allow an optional leading sign in `_SCORE_RE` so a negative numeric score matches the SCORE line and reaches the existing `max(0.0, min(1.0, score))` clamp. Both ends now clamp symmetrically. A non-numeric SCORE line (`SCORE: high`) still raises `JudgeParseError` — the sign allowance doesn't loosen the match to non-numeric values.
- 4 new tests: clamp-below-zero, `-0.0` in-range, explicit `+` sign, and non-numeric-still-raises. Full suite 393 → 397, ruff clean. PR #72 open and ready.

**Why this work, this session:** the portfolio is saturated (almost every repo at zero open issues, no priority:high anywhere, only demo-capture tasks left). This was a real behavioral asymmetry plus dead code in the production judge path — strictly higher value than a synthetic API-completeness fill, found by reading `judge.py` directly during Phase A.

**Open questions / blockers:** none.

**Next session:** `AnthropicBackend.complete` makes a single API call with no retry/backoff — a transient rate-limit or 529 overloaded aborts a whole multi-row run. Worth filing as a meatier resilience issue if a future session needs substantive work here.

## 2026-06-22 — Issue #73: judge backend — retry transient API failures with capped backoff
**Duration:** ~35 min · **Branch:** `session/2026-06-22-1055-issue-73`

- Acted on the #71/#72 session's parked lead: `AnthropicBackend.complete` made a single `messages.create` call with no retry. Since `run_suite` calls the judge once per dataset row in a serial loop, a single transient `429`/`529`/connection blip aborted the entire multi-row run and discarded every row scored so far — a real, recurring failure mode that gets worse the longer the suite.
- Fix: added an import-free transient-error classifier (`is_transient_error`, keyed on duck-typed `status_code` and connection-error class names so it runs without the `anthropic` extra), a generic capped-exponential-backoff retry loop (`retry_call`, with an injectable sleep clock), and wired both into `complete`. Permanent 4xx errors re-raise immediately; only transient failures retry. Added validated retry knobs following the repo's existing positive-int / finite-number contract.
- 33 new hermetic tests (no `anthropic` install): classification, backoff sequence + capping, knob validation, and `complete()` end-to-end via a fake client built through `__new__`. Full suite 397 → 430, ruff clean. PR #74 ready.

**Why this work, this session:** the portfolio is still saturated (only 3 open issues, all binary demo-capture tasks not doable headless). This was a concrete, high-value resilience bug already documented as the next lead in the prior session's memory — strictly better than a synthetic fill.

**Open questions / blockers:** none.

**Next session:** the judge backend is now resilient, but the *answer source* model in the runner (`AnswerSource`/`run_suite`) has no equivalent retry seam — a real Anthropic-backed answer source would have the same single-call fragility. Worth filing as a sibling resilience issue if a future session needs substantive work here.

## 2026-06-22 — Issue #75: calibration/pytest-plugin — reject an empty rubric
**Duration:** ~25 min · **Branch:** `session/2026-06-22-1549-issue-rubric-collapse`

- Found via a Phase A Explore sweep over calibration/drift/comment/dataset/runs/pytest_plugin (two `x or DEFAULT` falsy-collapses, same class as the cost-optimizer #73 `or 0.0` bug). `rubric` is a **required** calibration field, but `_validate` only checked `isinstance(str)` — it accepted `""`, and `calibrate()` then ran `row.rubric or FAITHFULNESS_RUBRIC`, silently judging the row against the *default* rubric and corrupting the κ/r calibration (the trust anchor) with no diagnostic. The pytest marker had the same `or`-collapse, where rubric is documented-optional (None → default is fine) but an explicit `rubric=""` also collapsed.
- Fix (principle: an empty rubric is malformed → fail loud; only an *absent* rubric defaults): `_validate` now rejects empty/whitespace rubric (same standard as `id`); `calibrate()` passes `row.rubric` verbatim (the `or` default is dead, removed with the now-unused import); `_read_marker` keeps None → default but raises on an explicit empty/whitespace rubric.
- 5 new tests (3 parametrized empty/whitespace load-rejects, a recording-judge test that calibrate passes each row's rubric verbatim, and a marker-explicit-empty-rubric collection error). Verified they fail pre-fix. Suite 430 → 435, ruff clean. PR ready.

**Why this work, this session:** the portfolio is saturated (only `priority:low` demo-capture issues open). This was a real silent-corruption bug in the calibration trust anchor, found by dogfooding — higher value than a synthetic fill.

**Open questions / blockers:** none for this issue. Separately filed mcp-server-cookbook#54 (postgres-readonly `sqlGuard.stripComments` ignores string-literal boundaries) for JT to assess — not auto-fixed because the Explore agent couldn't demonstrate a working exploit and a security-guard change on an unverified exploit needs a human call.

**Next session:** calibration/plugin are now hardened on the rubric path. drift/comment/dataset/runs scanned clean this session.

## 2026-06-22 — Issue #77: binarize — validate score, not just threshold
**Duration:** ~25 min · **Branch:** `session/2026-06-22-1950-issue-77`

- Found via a Phase A Explore-subagent sweep over the eval-harness core (calibration/drift/judge/runner/comment/runs/dataset); llm-eval-harness picked as a priority-tier repo (build-seq pos 1) under the D-009 loop bias — the fifth dogfood fix this run. `binarize` thoroughly validates `threshold` (the #45 bounded-float guard) but left `score` unguarded, despite both sharing `JudgeScore.score`'s `[0, 1]` domain and the docstring documenting the exact NaN failure. So `binarize(NaN) → 0`, `binarize(inf) → 1`, `binarize(2.0) → 1` silently, which collapses a rater to a constant and corrupts Cohen's κ to a silent `0.0` — the same failure mode #45 closed for `threshold`.
- Fix: apply the identical bounded-float validator to `score`. Added parametrized score-rejection + in-range-acceptance tests next to the existing threshold ones; the rejection tests fail pre-fix. Suite 435 → 458, ruff clean. PR #78 ready.

**Why this work, this session:** the repo had zero open issues; a dogfood sweep of the foundational priority-tier repo surfaced a real silent-κ-corruption gap on a public, documented-contract function — completing the #40/#45 finiteness-guard arc.

**Open questions / blockers:** none.

**Next session:** `binarize` is now guarded on both arguments. A possible follow-on (deferred, not filed): pushing finiteness validation up into dataset `human_score` loading, so a malformed golden row is rejected at load rather than relying on `binarize`'s guard downstream.

## 2026-06-22 — Issue #79: runner — load_run_result_from_json silently dropped duplicate example_ids
**Duration:** ~15 min · **Branch:** `session/2026-06-22-2351-issue-79`

- Found via a Phase A dogfood Explore agent over the eval-harness core, then verified by reading + reproducing. `load_run_result_from_json` built `rows` as a dict keyed by `example_id` and read `n_rows` straight from the payload, so a duplicate `example_id` silently overwrote the earlier row, leaving `n_rows` disagreeing with `len(rows)`. `diff_runs` consumes `rows` as its source of truth, so a deduped run produced a wrong per-example delta and a wrong reported row count in the CI comment.
- This was inconsistent with the repo's own convention: `dataset.load_jsonl` already rejects duplicate ids loudly. Fix: the run-load path now raises on a duplicate `example_id` instead of silently overwriting. 2 tests (duplicate raises — fails pre-fix; clean payload round-trips with `n_rows == len(rows)`). Suite 458 → 460, ruff clean. PR #80 ready.

**Why this work, this session:** llm-eval-harness is the foundational priority-tier repo with no open issues; a dogfood sweep surfaced a silent-data-loss + state-inconsistency gap on the run-load path (which feeds the regression diff), and the fix aligns it with an explicit existing convention. Low reachability (needs an externally-produced/corrupted run JSON), filed priority:low.

**Open questions / blockers:** none.

**Next session:** the run-load path is now as strict as the dataset-load path on id uniqueness. The earlier deferred lead (pushing finiteness validation up into dataset `human_score` loading) remains open.

## 2026-06-23 — Issue #81: comment render crashed on null mean_delta
**Duration:** ~15 min · **Branch:** `session/2026-06-23-0351-issue-81`

- Fixed a crash in `render_delta_markdown`. It read `mean_delta = summary.get("mean_delta", 0.0)`, whose default only applies on a missing key. A present-but-null `mean_delta` (an undefined mean Δ serialized as JSON null, which `from_json` passes through verbatim) reached the `:+.3f` format and raised `TypeError`, aborting the entire comment render in CI.
- Coerced explicitly with `float(raw) if raw is not None else 0.0` (preserving a legitimate `0.0`). Added a null-mean_delta render test. Red pre-fix, green post-fix. Suite 460 → 461, ruff clean.

**Why this work, this session:** found by a second-pass deep read in the night session's Phase A dogfood wave (first pass on this repo was clean). Same reachability tier as the merged #79 fix — a hand-edited / externally-produced delta JSON crashes the GitHub-Action comment step.

**Open questions / blockers:** none.

**Next session:** the `int(summary.get("n_*", 0))` count fields would also raise on present-null, but counts are never null in a real summary; left out of scope.

## 2026-06-23 — Issue #83: load_run_result_from_json silently defaulted a missing mean_score to 0.0
**Duration:** ~25 min · **Branch:** `session/2026-06-23-1900-issue-83`

- A Phase A dogfood second-pass sweep of the loader path found that `load_run_result_from_json` read `mean_score` with a silent `float(payload.get("mean_score", 0.0))` default. Since `0.0` is a valid score, a payload missing the field (corrupt/truncated/incompatible) loaded indistinguishably from a genuine zero run.
- `diff_runs` computes `mean_delta = current.mean_score - baseline.mean_score`, so the corruption flowed straight into the headline regression metric — a +0.2 improvement reported as a −0.6 regression, gating CI (`--threshold-drop`) and rendering in the PR comment. Made `mean_score` required (descriptive `ValueError`), matching the #79 duplicate-id guard and the loader's other bracket-accessed required fields. Suite 461 → 462, ruff clean.

**Why this work, this session:** the only `priority:high` open issues elsewhere were operator-blocked (portfolio-ops #17) or deliberate `decision-revisit` security-guard work (mcp-server-cookbook #54/#55, skipped per D-007); a fresh dogfood find on a priority-tier repo was the highest-value autonomous work available.

**Open questions / blockers:** none.

**Next session:** the loader's remaining `.get(..., default)` reads are genuinely-optional metadata or sensibly derived (`n_rows` → `len(rows)`); not corruption-masking, left out of scope.

## 2026-06-23 — Issue #85: load_run_result_from_json accepted non-finite scores, silently disabling the regression gate
**Duration:** ~25 min · **Branch:** `session/2026-06-23-2311-issue-85`

- A Phase A dogfood code-read of the loader/diff path (immediately after the #83 required-`mean_score` fix merged) found that `load_run_result_from_json` checked presence (#83) and uniqueness (#79) of run-JSON fields but never that the numbers are *finite*. Python's `json.loads` parses the bare `NaN`/`Infinity` tokens by default, so an externally-produced or hand-edited run artifact can carry a non-finite `score`.
- Reproduced: a current run whose `q1` score is `NaN` loaded clean, then `diff_runs` classified the NaN delta as `unchanged`/not-flagged (the sign-only `_status_for` returns False for every comparison against NaN), so `n_flagged == 0` and `cli._run_diff_json` exits 0 — the CI regression gate silently passed a garbage run. Same failure mode as the #42 `threshold_drop` finiteness guard, on the data side.
- Added two fail-loud finiteness guards in the loader (per-row `score` naming the `example_id`, and top-level `mean_score`), matching the in-function duplicate-id and missing-mean_score guards. 5 new tests (NaN/+Inf/-Inf row score, NaN mean_score, end-to-end), red pre-fix / green post-fix. Suite 462 → 467, ruff clean.

**Why this work, this session:** priority-tier repo, earliest in build sequence; the only `priority:high` issues elsewhere were operator-blocked (portfolio-ops #17) or `decision-revisit` security work already deferred to JT (mcp-server-cookbook #54/#55). A fresh dogfood find continuing this repo's fail-loud loader-hardening arc (#42/#75/#77/#79/#83) was the highest-value autonomous work available.

**Open questions / blockers:** none.

**Next session:** the loader is the right choke point — `threshold_drop` finiteness is already guarded at the diff layer (#42), so no defensive NaN-delta guard was added in `diff_runs`. No reachable gap left on this path.

---
## 2026-06-24 — Issue #87: drift._clamp01 didn't reject non-finite judge scores
**Duration:** ~28 min · **Branch:** `session/2026-06-24-0320-issue-87`

- `_clamp01` (the choke point every operator-supplied `judge_score_fn` result passes through) did sign-only clamping with no finiteness check. A NaN judge score crashed `_judge_histogram` cryptically at `int(s*10)` ("cannot convert float NaN to integer"), and +Inf/-Inf silently clamped to 1.0/0.0, poisoning `mean_score` and the JSD histogram while the report rendered as if clean.
- Added a `math.isfinite` guard raising a descriptive ValueError, matching the runner #86 and calibration #45 finiteness guards. Finite out-of-range scores still clamp to [0,1].
- 6 new tests (parametrized NaN/±Inf on `_clamp01`, finite-clamp regression, NaN and +Inf end-to-end through `compute_drift`). Red via `git stash`, green after. Suite 467 → 473, ruff clean.

**Why this work, this session:** llm-eval-harness was the next priority-tier repo by the build-sequence tie-break; the loader/calibration paths were already saturated, so a parallel dogfood sweep of the less-hardened modules (drift/dataset/io_utils) surfaced this as the highest-confidence reachable bug.

**Open questions / blockers:** none.

**Next session:** with `_clamp01` guarding judge scores there's no reachable non-finite path into `jensen_shannon`; the dataset.py / io_utils.py / pytest_plugin.py modules are the next dogfood frontier if this repo is picked again.

---
## 2026-06-24 — Issue #89: non-finite values leaked into the posted PR comment
**Duration:** ~25 min · **Branch:** `session/2026-06-24-1513-issue-89`

- The `comment` command's JSON load path (`DeltaReport.from_json` / `RowDelta.from_json`) didn't validate finiteness, so a NaN/±Infinity in a delta artifact (parseable from a bare JSON token) rendered as `+nan`/`inf`/`nan` in the sticky PR comment the bot posts. The sibling run-data loader `load_run_result_from_json` was hardened against exactly this in #42; this session extended the same contract to the comment path.
- Added a `_finite_or_none` helper for the row score fields (None passes through) and non-finite rejection of `threshold_drop` + `summary["mean_delta"]` in `DeltaReport.from_json`; explicit `null` and absent mean_delta stay legal. 17 new tests, red-without-guard / green-with, full suite + ruff clean.

**Why this work, this session:** found via a Phase A dogfood sweep and reproduced end-to-end; mcp-server-cookbook was the stalest repo but its only priority:high issues are human-blocked `decision-revisit` security-guard items (D-007 fall-through), so selection landed on llm-eval-harness (priority tier, build-seq #1).

**Open questions / blockers:** none.

**Next session:** belt-and-suspenders renderer-side `:.3f` guards in `comment.py` are a low-priority follow-up (loader-side rejection already makes the renderer path unreachable from corrupt input).

---
## 2026-06-24 — Issue #91: jensen_shannon reported "no drift" (0.0) when one distribution was empty
**Duration:** ~30 min · **Branch:** `session/2026-06-24-2315-issue-91` · **PR:** #92 (ready)

- `drift.py`'s `jensen_shannon` is the exported primitive that scores every drift axis (length / embedding / judge) and gates the regression report. Its `if sp <= 0.0 or sq <= 0.0: return 0.0` guard conflated two opposite cases: two empty distributions (identical "nothing" → correctly 0.0) and *exactly one* empty distribution (the maximally-disjoint case → should be 1.0, the JSD upper bound the docstring already promised). Because a score of 0.0 reads as "no drift", an axis whose histogram collapses to all-zero on one side silently reported maximal drift as none — a false-negative bypassing the gate. Reproduced: `jensen_shannon([0,0,0],[1,2,3])` → 0.0, while the genuinely-disjoint `[1,0]`/`[0,1]` correctly returns 1.0.
- Split the guard (both empty → 0.0, exactly one empty → 1.0) and tightened the docstring. The existing `test_jsd_handles_zero_mass` had **locked in the buggy 0.0**, so I replaced it with three tests covering empty-vectors, both-sides-zero, and one-side-zero in each direction. Full suite green (492), ruff clean. Consistent with D-014 (JSD base-2 bounded [0,1]).

**Why this work, this session:** found via a Phase A dogfood Explore sweep of the numeric chokepoints and reproduced. mcp-server-cookbook was the stalest repo (~56h) but its only `priority:high` issues (#54/#55) are human-blocked `decision-revisit` security-guard items already skip-commented on 06-22/06-23 (D-007 fall-through), so selection landed on llm-eval-harness (priority tier, build-seq #1). Same dogfood→issue→PR shape as the recent finiteness sweep.

**Open questions / blockers:** none.

**Next session:** #93 — `_length_histogram` silently drops inputs ≥ 1M chars (the reachability mechanism for this bug), filed `priority:low`; make the top bucket open-ended or add an overflow bucket.

## 2026-06-24 — Issue #93: _length_histogram silently dropped inputs ≥ 1M chars
**Duration:** ~20 min · **Branch:** `session/2026-06-24-2318-issue-93` · **PR:** #94 (ready)

- `_length_histogram` bucketed by `(0, 32, …, 4096, 1_000_000)` with a strict `lower <= n < upper` check on every bucket, so an input of length ≥ 1,000,000 chars matched no bucket and was silently dropped. An all-huge candidate set then collapsed the histogram to all-zero, and the length drift axis reported "no drift" — the reachability mechanism for the `jensen_shannon` one-empty false-negative I fixed in #91 earlier this run. The `1_000_000` entry was already an ∞ sentinel (`render_html` labels the last bucket `4096-∞`); the histogram just wasn't honoring it.
- Made the final bucket open-ended (`n >= lower`, no upper bound), so every input at or above 4096 is counted there and nothing is dropped. 4 tests including an end-to-end `compute_drift` that an all-huge candidate set now registers as length-`drifted`. Red→green verified, full suite green, ruff clean.

**Why this work, this session:** second Phase B iteration of the same DAY run; #93 is the follow-up I filed during the #91 fix, completing the silent-drop story while context on `drift.py` was warm. Note this branch is based on `main` (which doesn't yet include #91's unmerged PR #92); the histogram fix is independent — once inputs are counted, neither histogram is all-zero, so the normal JSD path applies regardless of #91. #92 and #94 touch different functions and don't conflict.

**Open questions / blockers:** none.

**Next session:** the embedding/judge axes can't collapse to all-zero (every input is assigned to a cluster / scored into a bucket), so length was the only silently-droppable axis; no further histogram follow-up needed.

## 2026-06-25 — Issue #91 (landing): rebased and merged the jensen_shannon fix
**Duration:** ~20 min · **Branch:** `session/2026-06-24-2315-issue-91` (rebased) · **PR:** #92 (merged)

- NIGHT-session Phase A surfaced two ready PRs here: #94 (issue #93, the open-ended length histogram) was clean with green CI, so I merged it first; that made #92 (issue #91, the `jensen_shannon` one-empty-side fix) conflict, since both PRs had appended test blocks to the same region of `tests/test_drift.py` and both had appended MEMORY session entries.
- Picked #91 up as the Phase B work item (priority:med, in priority-tier llm-eval-harness, after D-007 fall-through skipped mcp-server-cookbook's human-blocked #54/#55 and portfolio-ops' operator-blocked #17). Rebased the branch onto current `main`: the `drift.py` fix applied cleanly (different function from #94), and the only conflicts were the two appended MEMORY entries — resolved by keeping both in chronological order (#91 @23:15 before #93 @23:18). Verified the merged tree (both fixes, both test sets, buggy test gone), full suite **496 passed**, ruff clean. Force-pushed, CI re-ran fully green, merged squash.

**Why this work, this session:** completing already-reviewed in-flight work beats inventing new work in a saturated portfolio; #92 was a real drift-gate false-negative fix blocked only by a mechanical rebase conflict its sibling merge created.

**Open questions / blockers:** none.

**Next session:** when two sibling PRs branch from the same `main` and both append to a shared test file + the MEMORY logs, merging one will create append-conflicts (not code conflicts) in the other — resolve by keeping both, chronologically.

---
## 2026-06-25 — Issue #96: validate compute_drift's cluster_k / n_representative_examples
**Duration:** ~25 min · **Branch:** `session/2026-06-25-1910-issue-96`

- Third instance of the documented drift false-negative class (after #91 jensen_shannon one-empty and #93 length-histogram open bucket). `compute_drift` validated its three thresholds at the boundary but not two other numeric params. `cluster_k <= 0` made `_kmeans` return empty centroids, so the embedding axis took the no-centroids branch and reported drift `0.0`/`ok` regardless of actual drift — a silent regression-gate bypass reachable from the CLI (`drift --cluster-k 0`). `n_representative_examples < 0` turned `examples[:n]` into a negative slice that silently returned a wrong-sized set (38 of 40 instead of the default 5).
- Added two guards in the same validation block as the existing threshold checks: `cluster_k >= 1` and `n_representative_examples >= 0`, failing loud at the choke point (matching `_clamp01`'s philosophy). 8 red-green tests; 6 fail without the fix, the two inclusive-boundary "accepts" tests pass in both versions. 496 → 504 suite green, ruff clean.

**Why this work, this session:** llm-eval-harness was the top priority-tier pick (earliest in build sequence, 6 days stale) with zero open issues; dogfooding the drift core surfaced a real, reachable instance of the exact false-negative class the module's own docstrings call out.

**Open questions / blockers:** none.

**Next session:** the CLI `--cluster-k` could grow an argparse range guard for an earlier, friendlier error, but the library-level `ValueError` already surfaces cleanly — low priority.

---
## 2026-06-25 — Issue #98: reject a present n_rows that disagrees with the row count
**Duration:** ~20 min · **Branch:** `session/2026-06-25-2316-issue-98`

- `load_run_result_from_json` already failed loud on duplicate ids, non-finite scores, and a missing/non-finite `mean_score`, but trusted the payload's `n_rows` field without checking it against the rows actually loaded. The duplicate-id guard's own comment names the hazard (`n_rows` disagreeing with `len(rows)` corrupts the per-example deltas `diff_runs` computes) yet only closed the dict-overwrite path to it — a plain payload with `n_rows: 3` and two non-duplicate rows still loaded silently inconsistent. Since `n_rows` is rendered as the run table's `n=` column and persisted to SQLite, the mismatch surfaces a count disagreeing with the `rows` dict downstream consumers iterate.
- Added a guard that rejects a *present* mismatched `n_rows`, preserving the `len(rows)` default for payloads that omit the field. Two tests (mismatch rejected, absent-field default path). 504 → 506 suite green, ruff clean.

**Why this work, this session:** mcp-server-cookbook (the only 36h-stale repo) had two `decision-revisit` security-guard issues blocked on JT, and portfolio-ops #17 is operator-blocked on a secret, so selection fell through to the priority-tier tie-break — llm-eval-harness, earliest in build sequence. Dogfooding the JSON loader surfaced the last unguarded integrity field in a function whose every other field is already validated.

**Open questions / blockers:** none.

**Next session:** the loader's integrity guards now cover every load-bearing field; future work here is more likely on the `diff_runs`/CLI side than the loader.

## 2026-06-26 — Issue #102: pearson_r now guards non-finite input
**Duration:** ~20 min · **Branch:** `session/2026-06-26-1525-issue-102`

- `binarize` guards finiteness on both arguments (#45) and `render_report` guards `threshold_kappa`, but the other public metric, `pearson_r`, had only empty/length/zero-variance guards. A non-finite element silently propagated to a `NaN` result (`den == 0` is False for NaN, so the zero-variance guard misses it), and `_interpret_pearson(NaN)` then rendered it as a confidently-wrong **"very strong"** correlation in the calibration report. Reproduced on main: `pearson_r([0.1, nan, 0.3], …) -> nan`, `_interpret_pearson(nan) -> "very strong"`.
- Added a `_require_finite_numbers` guard to `pearson_r` (both lists), mirroring `binarize`'s contract — reject non-number, `bool`, `NaN`, `±inf`; no range check, since Pearson is scale-invariant. The `calibrate()` path only shielded this incidentally (`binarize` runs first), but a public metric must hold its own contract. 8 new tests; full suite 508 → 516, ruff clean.

**Why this work, this session:** fourth issue of a multi-issue DAY run; llm-eval-harness is priority-tier with no open backlog, so per Phase A step 6 I filed a substantive issue from a code read. This is the same finiteness-guard pattern the module already applies elsewhere (#42, #45) — closing the one public metric that didn't hold it.

**Open questions / blockers:** none.

**Next session:** calibration metrics now all fail loud on degenerate/non-finite input; `_interpret_*` NaN-hardening is deliberately out of scope (no reachable NaN source remains from the metric path).

## 2026-06-26 — Issue #104: CLI read-side subcommands fail clean (::error:: + exit 2)
**Duration:** ~35 min · **Branch:** `session/2026-06-26-1925-issue-104`

- `run` and `validate` already translate their domain errors into a clean `::error::` stderr line plus a documented exit code, but the four read-side subcommands didn't: `diff` on an unknown run id leaked a `KeyError`, `diff-json`/`comment` on a missing or corrupt file leaked a `FileNotFoundError`/`ValueError`, and `list --limit 0` (or negative) leaked a `ValueError` — each as a raw traceback. That broke the CLI's `0 = clean / 1 = findings|regression / 2 = I/O or usage error` exit contract.
- Added a small `_fail(msg)` helper (prints `::error::{msg}`, returns 2) and routed `_run_list`, `_run_diff`, `_run_diff_json`, and `_run_comment` through it. `json.JSONDecodeError` is caught before `ValueError` (it's a subclass). Two success-path guards pin the unchanged exit-0 (identical runs) and exit-1 (real regression past the 0.1 threshold) behavior so the translation can't swallow a legitimate diff. Suite 516 → 525, ruff clean.

**Why this work, this session:** first issue of a DAY run after the Phase A merge pass (3 PRs merged). All 13 repos were touched in the overnight session, so no staleness floor tripped; mcp-server-cookbook's two `priority:high` issues are both `decision-revisit` security-guard items already skipped under D-007, so the rule-3 tie-break (priority-tier, earliest build sequence) landed on llm-eval-harness, which had no open backlog — I filed #104 from a code read. The prior session (#102) explicitly predicted the next gap was "more likely on the diff_runs/CLI side"; this closes it.

**Open questions / blockers:** none.

**Next session:** CLI error handling is now uniform across all subcommands; #105 (vestigial `judge`/`judge_command` dead branch in `main()`) is a low-priority cleanup left open.

## 2026-06-26 — Issue #105: Remove vestigial judge/judge_command dead branch in cli.main()
**Duration:** ~20 min · **Branch:** `session/2026-06-26-2310-issue-105`

- `cli.main()`'s dispatch began with `if args.command == "judge" and args.judge_command == "calibrate": return _run_calibrate(args)`. That branch was unreachable: no `judge` subparser is registered (`dest="command"`), so `args.command` is never `"judge"`, and the legacy `judge calibrate` form is already normalized to `calibrate` by the argv-rewrite at the top of `main()`. The branch survived only by short-circuit evaluation (`args.judge_command` is not a real namespace attribute). Removed it; dispatch now falls through to the canonical `calibrate` branch, with an explanatory comment.
- Added two dispatch-lock tests to `test_cli_judge_alias.py`: the `judge calibrate` alias actually reaches `_run_calibrate` via a monkeypatched sentinel (asserting `args.command == "calibrate"` and that no `judge_command` attribute exists), and the plain `calibrate` form shares the same branch. The existing alias tests already locked the `--help` surface and the argv-rewrite; these add the dispatch-layer proof so the dead-code removal can't silently break the alias. Suite 525 → 527, ruff clean.

**Why this work, this session:** second issue of a multi-issue DAY run (after the Phase A merge of 4 clean PRs). All repos were fresh and only `mcp-server-cookbook` had `priority:high` issues — both `decision-revisit` security-guard items already deferred under D-007, so I respected that skip and the tie-break landed on llm-eval-harness, whose sole open issue (#105) is this cleanup, filed as a followup by the prior session.

**Open questions / blockers:** none.

**Next session:** the dispatch is now a flat list of one-branch-per-command; the only remaining vestige is the harmless `return 2  # unreachable` after `parser.error(...)`, deliberately left out of scope.

## 2026-06-27 — Issue #108: Unicode-aware drift hash tokenizer
**Duration:** ~25 min · **Branch:** `session/2026-06-27-0318-issue-108`

- `_HASH_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")` (`drift.py`) matched only ASCII alphanumerics. On a module whose job is detecting drift on *production traffic samples* — inherently multilingual — any non-Latin input (CJK, Cyrillic, …) produced **zero tokens**, so `hash_embed` returned the all-zero vector, the exact sentinel reserved for *empty* input. Every semantically-distinct non-ASCII input therefore collapsed to identical "empty" content, and accented Latin text was mangled (`café` → `caf`). Reproduced on main: `hash_embed('天気は良い') == hash_embed('株価が下落')` returned `True`.
- Fixed with `re.compile(r"[^\W_]+")` — Unicode alphanumerics excluding underscore. This keeps ASCII tokenization **byte-identical** to the old regex (underscore stays a separator, so no existing ASCII test can break) and only changes non-ASCII behavior. Added 4 regression tests (accents preserved, CJK/Cyrillic non-empty, ASCII-unchanged incl. underscore-split, two distinct non-ASCII strings → distinct embeddings neither equal to the empty zero vector). Suite 527 → 531, ruff clean.

**Why this work, this session:** first issue of a multi-issue NIGHT run after merging 10 clean PRs in Phase A. All repos were fresh and the only `priority:high`/decision-revisit issues (mcp #54/#55, cost-optimizer #97) are JT-decision blockers (D-007), so I dogfooded the priority tier in build order; this was the one solid, reproducible bug surfaced (4 parallel hunters; the other 3 repos were honest declines).

**Open questions / blockers:** none.

**Next session:** drift embedding axis is now multilingual-safe; the dep-free hash embedder remains intentionally simple (no locale-aware tokenization).

## 2026-06-27 — Issue #110: `run` crashed on an invalid --threshold-drop
**Duration:** ~20 min · **Branch:** `session/2026-06-27-0428-issue-110`

- `diff_runs` validates `threshold_drop` and raises `ValueError` for negative/NaN/Inf (the #42 guard). `_run_diff` and `_run_diff_json` both catch it → `_fail` → exit 2, but `_run_run`'s `diff_runs` call was outside any try/except, so a bad `--threshold-drop` passed to `run` leaked a raw traceback (non-2 exit), breaking the CLI's documented "0 clean / 1 findings / 2 usage error" contract. The NaN case is the worst — the guard exists to stop NaN silently disabling the regression gate, but in `run` it crashed instead of erroring cleanly.
- Wrapped `_run_run`'s baseline-diff block in `except ValueError: return _fail(str(e))`, mirroring the sibling subcommands (single-source validation stays in `diff_runs`). Added 4 parametrized tests (nan/inf/-inf/-0.5) asserting exit 2 + the `::error::threshold_drop must be a finite number` line; the negative values are passed via the `=` form to dodge an argparse tokenization quirk. Suite 527 → 531, ruff clean.

**Why this work, this session:** thirteenth issue of a multi-issue NIGHT run; a high-confidence, clean CLI exit-code-contract fix surfaced by a second-pass dogfood of priority-tier llm-eval-harness.

**Open questions / blockers:** none.

**Next session:** all three diff-bearing subcommands now honor the exit-2 usage contract uniformly; validating `--threshold-drop` before the (expensive) eval runs/persists remains a possible follow-up.

## 2026-06-27 — Issue #112: `run --baseline <unknown-id>` leaked a KeyError traceback
**Duration:** ~15 min · **Branch:** `session/2026-06-27-1927-issue-112`

- `_run_run` caught only `ValueError` on the baseline-diff path, but an explicit unknown `--baseline` routes through `load_baseline` → `read_run`, which raises `KeyError("no run with id 'x'")`. The run JSON printed, then the uncaught traceback escaped — instead of the clean exit-2 usage error the sibling `diff` command honors. This is the `KeyError` half of #110 (which fixed the `ValueError` half on the same path).
- Fixed with an `except KeyError` clause mirroring `_run_diff`, translating the message via `_fail`. Added a lock test (reproduced firsthand via the fake-backend seam) that fails on the pre-fix code.

**Why this work, this session:** third issue of a multi-issue DAY run; this was the error-handling gap the Phase A dogfood flagged for priority-tier llm-eval-harness — a real exit-code-contract violation even though it wasn't a wrong-output bug.

**Open questions / blockers:** none.

**Next session:** continue the loop if time remains.

## 2026-06-28 — Issue #114: `validate_dataset` let a version-drifted row reserve its id
**Duration:** ~25 min · **Branch:** `session/2026-06-28-1533-issue-114`

- `validate_dataset` recorded each id in `seen_ids` *before* the version-drift check, so a version-drifted row — which is explicitly dropped from the valid set — still claimed its id. A later, fully-valid, correct-version row reusing that id was then reported as a spurious `duplicate_id` finding (its "first seen at line N" pointing at a discarded row) and wrongly excluded from `n_valid`, which can fail a `validate` gate on a clean dataset.
- The tell was an internal inconsistency: the schema-rejection path already `continue`s *before* the id is recorded (so it doesn't reserve an id), while the version-drift path did. Fixed by moving the `seen_ids` assignment to run only once a row becomes valid (just before `valid_examples.append`), making both rejection paths consistent. `load_jsonl` is intentionally untouched — it fails fast on the first drift and never continues, so the ordering never manifests there. Added a regression test for the id-reuse-after-drift repro; suite 536 → 537, ruff clean.

**Why this work, this session:** second substantive issue of a multi-issue DAY run (after landing the three mcp-server-cookbook rebase PRs in Phase A/B). Priority-tier llm-eval-harness had zero open issues, so this was filed from a Phase A dogfood sweep and fixed the same session — the saturated-portfolio dogfood→issue→PR pattern.

**Open questions / blockers:** none.

**Next session:** continue the loop if time remains.
