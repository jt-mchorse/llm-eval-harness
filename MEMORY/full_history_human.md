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
