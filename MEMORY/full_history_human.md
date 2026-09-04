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

**Duration:** ~18 min · **Branch:** `session/2026-05-11-issue-01` · **PR:** [#8](https://github.com/jt-mchorse/llm-eval-harness/pull/8) (draft)

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
**Duration:** ~18 min · **Branch:** `session/2026-05-16-1937-issue-4`

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

## 2026-06-28 — Issue #116: null `run_id` / null summary count crashed the delta renderers with a raw TypeError
**Duration:** ~35 min · **Branch:** `session/2026-06-28-1914-issue-116`

- A delta or run JSON artifact carrying a JSON `null` where a string/int is assumed crashed the `diff-json` / `comment` CLI paths with an uncaught `TypeError` and exit 1, violating the documented `2 = I/O or usage error` exit contract (those handlers catch `ValueError`/`KeyError`/`OSError`/`JSONDecodeError`, but not `TypeError`). Same defect class as the finiteness guards (#42/#86/#89) and the present-null `mean_delta` coercion (#81/#100).
- Three concrete paths, all reproduced firsthand: (1) null `run_id` in a RunResult JSON → `render_delta_ascii` `run_id[:8]`; (2) null `current_run_id`/`baseline_run_id` in a delta JSON → `render_delta_markdown` `run_id[:8]` (the `.get` default only fires on a *missing* key, not a present null); (3) null summary count → `render_delta_markdown` `int(None)`, while `render_delta_ascii` silently rendered the literal string `None`. The `mean_delta` field on the adjacent line was already null-guarded — the count siblings were left bare.
- Fixed loader-side for run ids (`load_run_result_from_json` + `DeltaReport.from_json` reject a present-null/non-string id → `ValueError` → exit 2) and renderer-side for counts (both renderers coerce a present-null count to `0`, matching the `mean_delta` handling and bringing the two renderers to parity). 11 lock tests added to the #104 exit-code-contract file; suite 537 → 548, ruff check + format clean.

**Why this work, this session:** first substantive issue of a multi-issue DAY run. Phase A found no mergeable PRs (only protected demo-capture drafts) and a clean audit; priority-tier llm-eval-harness (first in build sequence) had zero open issues, so a Phase A dogfood sweep surfaced this latent bug family — the saturated-portfolio dogfood→issue→PR pattern. Left llm-cost-optimizer #97 (batch-idempotency decision-revisit) untouched: it is explicitly filed for JT confirmation.

**Open questions / blockers:** none.

**Next session:** continue the loop — rotate to another repo to avoid same-repo append-only MEMORY conflicts.

## 2026-06-29 — Issue #118: README validate examples showed stale rows=8
**Duration:** ~9 min · **Branch:** `session/2026-06-29-0355-readme-validate-rowcounts`

- The README's two `validate` examples claimed `rows=8 valid=8`, but the shipped CLI prints `rows=10` for the factuality fixture (10 lines) and `rows=50` for calibration (50 lines). The calibration `8` was doubly wrong — the README says "50 rows" three other places. Real counts are test-locked.
- README-only fix aligning both example outputs to the verified CLI output.

**Why this work, this session:** eighth issue of the night run, from the parallel doc-contract subagent sweep.

**Open questions / blockers:** none.

**Next session:** README validate examples match the shipped CLI output and the test-locked fixture sizes.

## 2026-06-29 — Issue #120: null/non-string `example_id` escaped the exit-2 contract on `diff-json` and `comment`
**Duration:** ~28 min · **Branch:** `session/2026-06-29-1912-issue-120`

- `example_id` is the load-bearing per-row join key, but the two JSON loaders read it by bare bracket access with no type check — the one remaining gap in a field family where `run_id`, `mean_score`, `n_rows`, and per-row `score` are all already guarded against present-but-invalid values. A `null` (or non-string) `example_id` in a corrupt/hand-edited artifact broke the CLI exit contract two ways, both reproduced firsthand.
- (1) `diff-json`: the `null` id became a `None` dict key, then `diff_runs`' `sorted(set(current.rows) | set(baseline.rows))` raised a raw `TypeError` (`'<' not supported between str and NoneType`), exit 1 — bypassing the documented exit-2 fail-clean contract (the catch blocks honor `ValueError`/`KeyError`/`FileNotFoundError`/`JSONDecodeError`, not `TypeError`). (2) `comment`: the `null` id flowed into `render_delta_markdown` and posted the literal string `None` as the row id into the PR comment, exit 0 — silently wrong. Same defect class as the #110/#116 null-`run_id` exit-2 fixes.
- Fixed loader-side in both `load_run_result_from_json` and `RowDelta.from_json`: reject a non-string/empty `example_id` with a `ValueError`, mirroring the existing `run_id` guard; `_run_diff_json` and `_run_comment` already translate it to a clean `::error::` line + exit 2. 4 lock tests added to the #104 exit-code-contract file (diff-json × ascii/markdown/json + comment dry-run), confirmed failing on pre-fix code via `git stash` before passing. Suite 548 → 552, ruff check + format clean.

**Why this work, this session:** first substantive issue of a multi-issue DAY run. Phase A found a clean merge queue (zero ready PRs across all 13 repos) and a clean audit (only the known operator-blocked `portfolio-ops` `trending-daily` stale-schedule finding). Priority-tier `llm-eval-harness` (first in build sequence) had zero open issues, so a dogfood hunter subagent surfaced this latent bug — the saturated-portfolio dogfood→issue→PR pattern. A parallel hunter on `rag-production-kit` found no genuine in-scope bug (that repo is unusually hardened), so the loop rotates elsewhere next.

**Open questions / blockers:** none.

**Next session:** continue the loop on another repo (avoid same-repo append-only MEMORY conflicts); the deferred `drift`-subcommand uncaught-traceback gap is filed separately as priority:med.

## 2026-06-29 — Issue #122: `drift` was the last subcommand outside the exit-2 fail-clean contract
**Duration:** ~30 min · **Branch:** `session/2026-06-29-2309-issue-122`

- `drift.cli` (`drift.py:715`) delegated straight to `_load_inputs_jsonl` / `compute_drift` with no exception translation — unlike `_run_diff_json` / `_run_comment` / `_run_validate`, which all catch their data-layer exceptions and fail clean. Reproduced all three paths firsthand on `main` first (acceptance criterion #1): a missing `--golden`/`--candidate` path leaked a raw `FileNotFoundError` (exit 1); an empty input / zero valid rows leaked a raw `ValueError: …no inputs loaded`; malformed JSON leaked a raw `ValueError` (already wrapped from `json.JSONDecodeError` by `_load_inputs_jsonl` — the issue had speculated a raw `JSONDecodeError`, corrected in the plan and test comments).
- Fixed by wrapping the input-loading block in `drift.cli` in a `try/except` translating `FileNotFoundError` / `OSError` / `ValueError` to a clean `::error::` line + exit 2, mirroring `_run_diff_json`'s catch shape. The guard lives in `drift.cli` (not `cli._run_drift`) so the contract holds on both the `eval-harness drift` path and the direct `python -m eval_harness.drift` entrypoint.
- **Scoping catch:** a first draft also wrapped `atomic_write_text(args.output, …)`, which broke the pre-existing `test_drift_output_routes_through_atomic_helper` — that test deliberately asserts an output-write `OSError` *propagates* (the atomic-write artifact guard: an aborted rename must leave no half-written report). The full suite caught it before push; `atomic_write_text` was moved outside the `try` so the artifact guard is preserved. 7 lock tests added (missing/empty/bad-JSON × golden+candidate + a valid-inputs exit-0 guard), all 6 error-path tests confirmed failing on pre-fix code. Suite 552 → 559, ruff clean.

**Why this work, this session:** first substantive issue of a multi-issue DAY run (Phase A merged 3 clean PRs across llm-eval-harness/llm-cost-optimizer/chunking, and the audit was clean bar the known operator-blocked portfolio-ops finding). #122 was the deferred follow-up filed during the earlier session that produced #120 — completing the exit-2 contract across every user-facing subcommand.

**Open questions / blockers:** none.

**Next session:** continue the loop on another repo to avoid same-repo append-only MEMORY conflicts; the portfolio is saturated (zero `priority:high` issues anywhere), so expect a dogfood→issue→PR pattern.

## 2026-06-30 — Issue #124: `comment` leaked a RuntimeError (exit 1) on missing GITHUB_TOKEN
**Duration:** ~20 min · **Branch:** `session/2026-06-30-0317-issue-124`

- `_run_comment` (`cli.py`) called `upsert_sticky_comment` **outside** its delta-load `try/except`. With no `GITHUB_TOKEN`/`GH_TOKEN`, `comment._resolve_token` raises `RuntimeError`, which escaped `main` as a raw exit-1 traceback — breaking the CLI's documented `0 = clean / 1 = findings / 2 = I/O or usage error` contract (the same one the read-side exit-2 sweeps #104/#110/#116/#122 uphold). A missing token is a pure usage/config error (forgetting `permissions: pull-requests: write` in Actions).
- Fixed by wrapping the `upsert` call in `try/except RuntimeError` → `_fail` (clean `::error::` line + exit 2). This also brings the GitHub-API HTTP-error `RuntimeError` from `_do_request` under the same contract. Scoped to `RuntimeError` only — the marker `ValueError` is always satisfied by `render_delta_markdown`, so a genuine internal bug there should still surface. The token path is network-free, so it's deterministically testable.
- Lock test: missing-token `comment` (non-dry-run) → exit 2 with `::error:: … token missing` and no traceback; companion asserts `--dry-run` still returns 0. Confirmed failing pre-fix via `git stash`. Suite 559 → 561, ruff clean.

**Why this work, this session:** second issue of a NIGHT multi-issue run; a dogfood hunter surfaced this exit-2-contract gap in priority-tier `llm-eval-harness`, reproduced firsthand before acting. Distinct from #123 (drift subcommand).

**Open questions / blockers:** none — ready for review.

**Next session:** continue the loop.

## 2026-06-30 — Issue #126: `calibrate` leaked a raw traceback (exit 1) on a missing/malformed calibration file
**Duration:** ~20 min · **Branch:** `session/2026-06-30-1511-issue-126`

- `_run_calibrate` (`cli.py:293`) called `load_calibration(args.calibration)` with no error translation — the one subcommand left out of the exit-code-contract sweep (#104 → #110/#116/#122/#124). A missing file (`FileNotFoundError`) or a malformed row (`CalibrationLoadError`, a `ValueError` subclass) escaped `cli.main` as a raw exit-1 traceback, breaking the documented `0 = clean / 1 = findings / 2 = I/O or usage error` contract that `validate` (missing-file → 2) and `run` already honor. Reproduced both firsthand before acting.
- Fixed by wrapping **only** the `load_calibration` call in `try/except` (mirroring how `_run_validate` wraps `validator(args.dataset)`): `FileNotFoundError`/`OSError` → `_fail("calibration not found: …")`, `ValueError` → `_fail(str(e))` — both exit 2. The load fires *before* the judge backend is constructed, so the fix is hermetic (no API key, no `judge` extra). calibrate's exit **1** stays reserved for the legitimate "Cohen's κ < threshold" findings outcome, so load/usage failures map to **2**.
- Three tests: missing-file → exit 2 and malformed-row → exit 2 (both confirmed failing pre-fix via `git stash`, inverse safety net), plus an over-rejection/scoping guard proving the load-only catch does not swallow a *downstream* `ValueError` (which would mask a real bug as a usage error). Suite 561 → 564, `ruff check` + `ruff format --check` clean.

**Why this work, this session:** first issue of a DAY multi-issue run. Portfolio is deeply saturated (zero `priority:high` issues; Phase A merged the four ready bug-fix PRs that closed the pre-filed backlog), so dogfood→issue→PR: read `cli.py` end-to-end and found `calibrate` was the last subcommand outside the exit-2 contract. Priority-tier `llm-eval-harness` chosen via D-009 tie-break (nextjs was the 18h-stale tier repo but its only issue #16 is operator-blocked binary-recording, so D-007 fall-through).

**Open questions / blockers:** none — ready for review. Filed #128 (low) for the adjacent empty-but-valid-file seam, deliberately out of this PR's scope.

**Next session:** continue the loop on another repo to avoid same-repo append-only MEMORY conflicts.

## 2026-06-30 — Issue #128: calibrate leaked a raw traceback on an empty-but-valid calibration file
**Duration:** ~15 min · **Branch:** `session/2026-06-30-1937-issue-128`

- Follow-up to #126 (landed via #127, merged in this run's Phase A). #126 brought the `calibrate` **load** seam into the exit-code contract (missing/malformed → 2). An empty-but-valid (0-row) file is downstream of that: `load_calibration` returns `[]` cleanly, so the catch doesn't fire. Then `calibrate(judge, [])` raised `ValueError` (exit 1 traceback), or in a minimal install `AnthropicBackend(...)` raised `ImportError` first — both broke the `2 = usage error` contract.
- Fixed with a zero-row check (`if not rows: return _fail(...)`) placed right after `load_calibration` returns and before the backend is constructed, so it reports exit 2 + a clean `::error::no rows to calibrate against in <path>` line, hermetically. Note: only a truly empty (0-byte) file reaches `[]` — `load_calibration` raises on blank/whitespace lines — so I dropped a blank-lines test whose message assertion would have been wrong. +2 hermetic tests (empty file → exit 2, `::error::` naming the path, no traceback; a guard that the backend is never constructed on the empty path), both failing pre-fix. Suite 564 → 566, ruff clean.

**Why this work, this session:** third issue of a DAY multi-issue run (after nextjs #70 and rag #108). Picked as the earliest priority-tier repo's lowest unblocked issue once its #126 upstream merged this run; `llm-cost-optimizer` #97 had fallen through earlier as a `decision-revisit` one-way blocker.

**Open questions / blockers:** none — ready for review.

**Next session:** continue the loop. The read-side `since()` swallow noted in rag #108 and chunking #93 (BOM/utf-8-sig) remain candidates.

## 2026-07-01 — Issue #130: a `|` in example_id broke the GFM sticky-comment table
**Duration:** ~25 min · **Branch:** `session/2026-07-01-0325-issue-130`

- `_row_to_md` wrapped `example_id` in backticks "so multi-word IDs don't break the column" — but backticks don't protect a literal `|`: GFM splits table cells on unescaped pipes *before* parsing inline code, so a piped id (`lang=py|framework=fastapi`) injected an extra column and corrupted the whole posted PR-comment table (confirmed: row had 8 unescaped pipes vs the header's 7). Fixed by escaping `|` → `\|`, which GitHub renders as a literal pipe inside a code span in a table. `render_delta_ascii` is unaffected (2-space separators) and must not escape — locked by a sibling test so a future `|`-delimited ascii refactor inherits the escaping need.
- +2 tests (`tests/test_comment.py`): markdown row keeps the header's unescaped-pipe count (fails pre-fix 8≠7); ascii renderer is pipe-free and renders a piped id verbatim. Suite 502 → 504, ruff + format clean.

**Why this work, this session:** portfolio is saturated — all remaining open issues are one-way `decision-revisit`s or non-headless `[demo]` captures. Ran a parallel dogfood bug-hunt across priority-tier repos (3 agents + 2 self-hunts); all came back NO_BUG_FOUND except this borderline finding, which empirical repro confirmed as a real output-corruption defect worth shipping (llm-eval-harness is priority-tier).

**Open questions / blockers:** none — ready for review.

**Next session:** continue the loop. The deferred backtick-in-id case remains a low-severity follow-up if it proves reachable.

## 2026-07-01 — Issue #132: trailing-dot judge scores (`SCORE: 1.`) raised a misleading "missing SCORE:" error
**Duration:** ~25 min · **Branch:** `session/2026-07-01-2310-issue-132`

- `parse_judge_output`'s `_SCORE_RE` numeric group (`[+-]?[0-9]*\.?[0-9]+`) required a digit *after* the optional decimal point, so a trailing-dot integer like `SCORE: 1.` or `SCORE: 0.` failed the SCORE-line match entirely and surfaced as `JudgeParseError: missing SCORE: line` — the exact misleading class #71 fixed for out-of-range negatives. Since `float("1.") == 1.0` this is a plausible judge output, and the error aborts a whole multi-row `run_suite`/`calibrate`. Reproduced firsthand: `1.` failed while `1`, `.5`, `1.5`, `-0.2`, `+0.4` all parsed — a leading-dot/no-dot vs trailing-dot asymmetry.
- Fixed by widening the group to `[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)` (no-dot, leading-dot, trailing-dot) so the value reaches the existing symmetric clamp. Verified against 16 cases before editing: the widening still rejects `.`, sign-only `-`, `1.2.3`, and sci-notation `1e0` via the `\s*$` anchor. +5 tests (trailing-dot int→1.0, trailing-dot zero→0.0, negative trailing-dot→clamped 0.0, and a parametrized guard that malformed forms still raise). Suite 575 → 580, ruff + format clean.

**Why this work, this session:** first issue of a DAY multi-issue run; `llm-eval-harness` was the stalest priority-tier repo (~19h) and earliest in the build sequence among stale tier repos, with zero open issues → dogfood hunt. Read the full core surface (drift/calibration/runner/runs/judge/dataset/comment/io_utils/cli/pytest_plugin); the repo is exceptionally hardened and this was the single reproducible gap found.

**Open questions / blockers:** none — ready for review.

**Next session:** continue the loop. Scientific-notation scores remain a documented out-of-scope non-issue.

## 2026-07-02 — Issue #134: escape pipes in the calibration report table (~20 min)

**What got done.** `calibration.render_report` builds the per-row markdown table for the calibration report, interpolating each row's `id` and the judge's free-form `reasoning` into a GitHub-flavored table cell. Neither was escaping `|`, so a pipe in either field split the cell into extra columns and corrupted the table's alignment when GitHub rendered it — the same bug we already fixed in the PR-comment renderer (#130), just never applied here. Escaped `|` → `\|` in both fields and added a lock test that asserts the data row's unescaped-pipe count matches the header's (and that the literal pipes survive). Verified it fails before the fix and passes after; full suite (581 tests) green, ruff clean.

**Why prioritized.** The whole open-issue backlog is either JT-decision one-way blockers (llm-cost #97, vector-search #71) or operator-blocked demo captures (nextjs #16, etc.), and nextjs — the stale priority-tier repo — only had the operator-blocked demo. Fell through to llm-eval-harness (priority tier, zero open issues) and dogfooded the core surface; this pipe-escaping gap in the calibration report was the one reproducible defect found, and it mirrors an established in-repo fix.

**Open questions / blockers.** None for this issue. This closes the last GFM-table emitter that lacked pipe escaping (drift HTML uses `html.escape`; comment.py fixed in #130).

## 2026-07-02 — Issue #136: characterization test for drift.percentile (~15 min)

**What got done.** `drift.percentile` (a NIST type-7 linear-interp percentile) is public — exported in `drift.__all__` — and drives the length-drift report's `median` and `p95`, but had zero direct tests. Added 8 characterization tests to `tests/test_drift.py`, one per branch of the contract: empty→0.0, single element, q=0/q=1 on unsorted input, even-n median interpolation (`[1,2,3,4]`@0.5→2.5), the integral-index `lo==hi` branch (`[10,20,30,40,50]`@0.5→30.0), fractional interpolation (`[0,10]`@0.25→2.5, `[1..100]`@0.95→95.05), and q-out-of-range ValueError. Every expected value was verified firsthand against the real function first. No production code change; full suite green (584 passed), ruff clean.

**Why prioritized.** Second issue of the day run. Two parallel dogfood bug-hunts on the priority-tier zero-open-issue repos (rag-production-kit and llm-eval-harness) both came up empty after deep probing (kappa fuzz 200k, JS divergence 100k, percentile vs a NIST reference over 50k cases) — the portfolio is bug-saturated. Per the "stop after two empty hunts" rule I pivoted from bug-hunting to locking an untested public function the hunt had surfaced. Still issue-driven: filed #136, closed it same session.

**Open questions / blockers.** None. A property/fuzz test against a reference impl was deferred as a possible separate low-priority follow-up; the enumerated cases already cover every branch.

## 2026-07-03 — Issue #138: unhashable `expected_outputs.kind` leaked a raw TypeError instead of a clean DatasetLoadError
**Duration:** ~25 min · **Branch:** `session/2026-07-03-0317-issue-138`

- `ExpectedOutput.__post_init__` (`eval_harness/dataset.py:75`) validated `kind` with `self.kind not in VALID_KINDS`. `VALID_KINDS` is a `frozenset`, so an **unhashable** `kind` (a JSON array/object, e.g. `{"kind": []}`) raised a raw `TypeError` from the membership test — *before* the intended `ValueError`. `_validate_record`'s wrapping `except ValueError` didn't catch it, so `load_jsonl` leaked the traceback and `validate_dataset`'s collecting pass aborted entirely — exactly the failure collecting-mode exists to prevent. A hashable wrong kind (`123`) was already handled cleanly; only unhashable JSON types hit the gap.
- **Fix:** lead the guard with `not isinstance(self.kind, str)` so the existing `invalid expected_output kind` `ValueError` fires and is wrapped into `DatasetLoadError` like every other bad kind. +4 regression tests (load_jsonl on list/dict kind → `DatasetLoadError`; the `ExpectedOutput` unit check → `ValueError`; `validate_dataset` surfaces exactly one `schema` finding while surrounding rows still validate). Reproduced firsthand before and after; suite 584 → 588, ruff + format clean.

**Why this work, this session:** second issue of a NIGHT run, portfolio saturated. Ran two parallel dogfood hunts on the priority-tier zero-open-issue repos not yet hunted this cycle — `chunking-strategies-lab` came up clean after 2000+ fuzz cases per strategy; `llm-eval-harness` surfaced this. Verified the agent's finding firsthand before fixing (per the saturation guidance).

**Open questions / blockers:** none — ready for review.

**Next session:** continue the loop. Remaining portfolio work is JT-blocked decision-revisits (llm-cost #97, vector-search #71) and operator-verification demos.

## 2026-07-03 — Issue #140: symbol-resolution doc-lock (propagates portfolio-ops #55) (~20 min)

**What got done.** `tests/test_architecture_doc.py` locked path tokens, issue/decision coverage, and banned phrases — but never checked that the symbols the doc *names* actually exist. That's the exact drift class portfolio-ops #55 catalogued across the portfolio (a doc naming a nonexistent `BatchAPIBackend` / `compute_frontier` passes CI). Added `test_doc_symbol_refs_resolve` for the two citation styles this doc uses: `<submodule>.<symbol>` attribute refs (e.g. `io_utils.atomic_write_text`) resolved via `importlib` + `hasattr`, and multi-word CamelCase public types (`RunResult`, `AnthropicBackend`, `ValidationReport`, `AnswerSource`) checked against the `eval_harness` public surface. Filename tokens (`cli.py`, `runs.sqlite`) and bare snake_case field names (`human_score`, `dataset_version`) are excluded so there are no false positives. The skip-extension set is hard-pinned. Inverse-verified by injecting drifted symbols of both styles into a doc copy — both flagged. Suite 588 → 590, ruff clean.

**Why this work, this session:** third worked issue of the DAY run. After shipping chunking-strategies-lab #102, the loop fell through two genuinely-saturated repos (python-async-llm-pipelines and ai-app-integration-tests — thorough two-hunter dogfood sweeps, no shippable bug; ai-app's one finding was `headersToObject` dropping multi-`Set-Cookie`, but that header is redacted before write so it's moot). A full portfolio open-issue sweep showed the only actionable, non-blocked, non-decision-revisit work was portfolio-ops #55/#56. Rather than only file meta-issues, executed #55's own remediation — filed the per-repo follow-up (#140) in a priority-tier repo and shipped the lock as the propagation template.

**Open questions / blockers:** none — ready for review. This doc adapts the lock to the bare-symbol + `submodule.symbol` styles here (not emb_shootout's fully-qualified `pkg.mod.sym`), so the propagation is per-repo, not copy-paste.

**Next session:** continue #55 propagation to the remaining repos (rag-production-kit, llm-cost-optimizer, chunking-strategies-lab, nextjs [TS: exported-name check], etc.), one small PR each. Remaining non-propagation work stays JT-blocked (decision-revisits llm-cost #97 / vector-search #71; operator secret config portfolio-ops #17).

## 2026-07-05 — Issue #142: GFM table emitters don't escape newlines in free-form id cells
**Duration:** ~35 min · **Branch:** `session/2026-07-05-1912-issue-142` · **PR:** #143

- Both markdown-table emitters (`comment._row_to_md`, `calibration.render_report`) escaped the GFM column delimiter `|` (per #130/#134) in free-form id cells but left the row delimiter `\r`/`\n` intact. A literal newline in `row.id` or `example_id` splits the row across two physical lines and corrupts the table exactly as an unescaped pipe corrupts columns. Both cells are reachable — `load_calibration` and `load_jsonl` accept any non-empty string id — and both were reproduced firsthand before the fix.
- The `|`-only escape was duplicated inline at three call sites, which is precisely why this class keeps recurring (a new emitter copies the pipe line and forgets the newline). Fixed by centralizing in a new internal `eval_harness/markdown.py` `md_table_cell()` that escapes `|` and collapses any CR/LF run to a single space, and routing all three sites through it. Added 7 tests (5 helper unit + 1 newline-lock per emitter). 590 → 597 passing, ruff clean.

**Why this work, this session:** portfolio is deeply saturated — Phase A merged three ready collision/parity-lens PRs and found nothing else auto-mergeable; the audit was clean; and rag-production-kit + nextjs dogfood hunts both came up empty. The one productive vein was the recurring GFM-table escaping class, which a targeted hunt surfaced (same class as #130/#134/#79) with two firsthand-reproduced findings.

**Open questions / blockers:** none — ready for review.

**Next session:** correctness surface is saturated; remaining open items are JT-gated decision-revisits (lco #97 draft #124 / D-013, vsas #71) and display-blocked demo captures. The productive lens remains collision/parity/GFM and re-examining hunter-dismissed "design choice" leads against objective invariants.

## 2026-07-06 — Drift example stdout was stale (issue #144, ~30 min)

A Phase-A dogfood doc-drift hunt (run-the-shipped-example lens) caught the README's Drift-detection example quoting stale stdout numbers: `length=0.4012 / embedding=0.2783 / judge=0.3094`. Running the exact documented `eval-harness drift ... --judge-stub` command against the committed fixtures on a fresh clone deterministically prints `length=0.729 / embedding=0.156 / judge=0.896` — the 4-decimal example predated the JSD/D-014 rework and nothing pinned it, so it drifted silently. Same class as the earlier #118/#119 stale-example fixes.

Fixed the README line to the real output (no fabricated numbers — copied from the shipped command) and added a 7th pairing to `test_readme_defaults_snapshot.py` that recomputes drift on the committed fixtures with the judge stub and asserts the README line, closing the lock gap. Full suite green, ruff clean. PR #145, ready.

**Why prioritized:** the static issue queue is still exhausted (all open issues are JT-gated decision-revisits or headless demo captures), so work came from a fresh-lens hunt; this was the only reproducible finding across three parallel hunts (encoding-unicode and numeric-boundary both came up empty, reconfirming saturation on those axes).

## 2026-07-06 — Issue #146: ship a PEP 561 `py.typed` marker for `eval_harness`
**Duration:** ~15 min · **Branch:** `session/2026-07-06-2321-issue-146` · **PR:** #147

- `eval_harness` is the flagship "imported by every repo" package (11 of 12 modules typed) with a real committed downstream consumer — `rag-production-kit` pins a git dep on `eval-harness` and its `evals/run_eval.py` mirrors `eval_harness.runner.RunResult`. But it shipped no PEP 561 `py.typed` marker, so downstream mypy/pyright saw `import eval_harness` as untyped. Added the marker, the `Typing :: Typed` classifier, and a two-axis regression test; verified firsthand the wheel ships the marker. 600 passing, ruff clean.

**Why this work, this session:** second issue of the DAY loop and the higher-value of the two `py.typed` fixes — this is the one repo whose gap concretely bites an in-portfolio consumer today. Correctness surface is saturated (five empty fresh-lens hunts this run), so the productive vein was an objective packaging-correctness sweep.

**Open questions / blockers:** none — ready for review.

**Next session:** the `py.typed` lens is now closed for the two repos that matter (lco, leh — the only two Python packages imported as libraries by siblings). Do NOT PR the marker for ems/vsas/prs/chunking — cosmetic there, not consumer-biting, would be sibling-churn.

## 2026-07-07 — Issue #148: Non-strict mypy gate for eval_harness
**Duration:** ~18 min · **Branch:** `session/2026-07-07-0308-issue-148`

- Added a non-strict `mypy` gate (`[tool.mypy]` in `pyproject.toml`, `mypy` in the `dev` extra, a step in the `ci.yml` lint job, and `tests/test_mypy_clean.py` locking it) so the annotations shipped via the #146 `py.typed` marker can't silently drift from the code.
- Triaged all 7 pre-existing errors with real fixes: renamed a k-means loop variable in `drift.py` reused for both a centroid vector and a cluster index; annotated the optional `judge_score` as `JudgeScore | None` and guarded `row.id` against a `None` row (removing a latent `AttributeError`) in `pytest_plugin.py`; `# type: ignore`'d the genuinely-dynamic `_eval_failure_extra` monkey-patch; and dropped a now-redundant import ignore in `judge.py`.
- Config declines a blanket `ignore_missing_imports` (so typo'd imports still surface) and scopes a per-module override to the optional `anthropic` SDK — verified clean both with and without it installed. Full suite: 601 passed.

**Why this work, this session:** Objective, pre-filed follow-up (#148) from the #146 py.typed work; the gate is the machine-checked half of the "annotations are honest" contract.

**Open questions / blockers:** none.

**Next session:** `llm-cost-optimizer#129` is the sibling gate — its 5 mypy errors are all the redis `ResponseT` sync/async union in `semantic_cache.py`.

## 2026-07-07 — Issue #150: Non-object JSON payloads break the CLI exit-2 contract
**Duration:** ~30 min · **Branch:** `session/2026-07-07-1514-issue-150`

- `load_run_result_from_json` and `DeltaReport.from_json`/`RowDelta.from_json` did `json.loads()` then `payload.get(...)`/`r["example_id"]` with no `isinstance(dict)` guard, so a valid-JSON-but-not-an-object input (bare list/number/string/null, or a non-object row) leaked a raw `AttributeError`/`TypeError` and exited **1** — the code reserved for findings/regression — instead of the documented exit **2** for malformed input. Reproduced firsthand via `diff-json` and `comment`.
- Added four `isinstance(payload, dict)` → `ValueError` guards (top-level + per-row in both loaders), mirroring `dataset._validate_record`; the CLI's existing `except ValueError → _fail` translates them to a clean `::error::` + exit 2.
- Parametrized regression test locks exit-2 for both subcommands on top-level and per-row non-object inputs. Full suite 601 passed; ruff clean.

**Why this work, this session:** Same isinstance-after-`json.loads` loader-parity vein as prs#108/chunking#110; the field-by-field guards (#120/#122/#124/#138) left the object-shape gap open. Found by a parallel dogfood hunt, verified firsthand.

**Open questions / blockers:** none.

**Next session:** judge/calibration/drift/dataset audited and saturated — this object-shape guard closes the last open loader-parity gap in the CLI read path.

## 2026-07-08 — Issue #152: pytest plugin threshold assertion tripped PluggyTeardownRaisedWarning
**Duration:** ~40 min · **Branch:** `session/2026-07-08-1517-issue-152`

- The plugin raised its threshold `AssertionError` **after `yield`** in an old-style `@pytest.hookimpl(hookwrapper=True)` hook (`pytest_pyfunc_call`) — i.e. in the wrapper's teardown. Modern pluggy (1.6, bundled with pytest 8/9) reports that as a `PluggyTeardownRaisedWarning` on every failing eval, and under `-W error` / `filterwarnings = error` (a common CI setting) it re-surfaced the failure **as** that warning class, burying the structured row/score/reasoning block the plugin exists to deliver. The outcome stayed `failed`, but the diagnostic delivery and failure attribution were broken — contradicting the module docstring's promise.
- Fixed by migrating the hook to the new-style `@pytest.hookimpl(wrapper=True)` form (supported since pluggy 1.2 / pytest 7.2; repo pins `pytest>=8.0`): `result = yield` re-raises body failures directly, and the threshold `raise` propagates as a normal call-phase failure — no teardown raise, no warning, clean `AssertionError` on all warning configs. Verified firsthand: default `1 failed, 1 warning` → `1 failed`; `-W error` failure-attribution flipped from the pluggy warning back to a clean `AssertionError`.
- Two regression tests added (fail pre-fix, pass on fix): `warnings=0` on a default run, and no `pluggy.PluggyTeardownRaisedWarning` crash under `-W error` with the structured block intact. Full suite 611 → 613, ruff/format/mypy clean.

**Why this work, this session:** leh was the stalest priority-tier repo (23h) and its static issue queue is empty; a 5-lens parallel dogfood hunt (calibration, drift, runner-diffing, comment-delta all empty) surfaced this in the pytest-plugin-lifecycle lens. Every finding verified firsthand on clean main before filing.

**Open questions / blockers:** none — ready for review.

**Next session:** the "old-style hookwrapper teardown-raise" lens is swept on leh — `pytest_pyfunc_call` was the only hook raising after `yield`; `pytest_runtest_makereport`/`logreport` don't raise. Test-authoring gotcha: the plugin docstring now literally contains `PluggyTeardownRaisedWarning`, which pytest renders in the failing inner test's traceback — assert on the warning *count* (`warnings=0`) or the dotted `pluggy.` crash prefix, not a bare substring scan of stdout.

---

## 2026-07-09 — Issue #154: pytest-plugin eval threshold unvalidated (nan/-inf bypasses the gate)
**Duration:** ~25 min · **Branch:** `session/2026-07-09-0359-issue-154` · **PR:** #155

- `@pytest.mark.eval(..., threshold=...)` was coerced with `float(...)` but never range-checked. A non-finite (nan/±inf) or out-of-[0,1] threshold reached the gate `score.score < threshold` unguarded; a nan/-inf threshold makes that comparison always False, so the assertion never fires and a broken judge scoring 0.0 passes green. 1.5 makes every eval impossible to pass.
- Fix: `if not 0.0 <= threshold <= 1.0: raise ValueError(...)` in `_read_marker` at collection time — one bounds check catches nan/±inf/out-of-range. Mirrors the sibling threshold guards (calibration.py, judge.py). Parametrized regression test over nan/-inf/inf/1.5/-0.1. Full suite + mypy gate + ruff green.
- Reproduced firsthand on clean main. Found by a parallel dogfood agent (threshold-boundary lens); I reset its working-tree changes and reimplemented cleanly.

**Why this work, this session:** llm-eval-harness is priority-tier with a globally-exhausted static queue. The finiteness/range threshold-guard sweep had reached every loader path but not the operator-written `@pytest.mark.eval` decorator kwarg — the one remaining entry point.

**Open questions / blockers:** none.

**Next session:** threshold-guard sweep is now complete in leh incl. the pytest marker; check operator-written *decorator kwargs* (not just loaders) for the same guard class in other repos.

## 2026-07-09 — Issue #156: run/delta loaders raise raw TypeError on nested container fields
**Duration:** ~25 min · **Branch:** `session/2026-07-09-1549-issue-156` · **PR:** #157

- #150 rejected a non-object top-level payload and non-object per-row in the run/delta JSON loaders, but left the nested `rows`/`summary` *fields* unguarded: a present-but-wrong-container value (`{"rows": 5}`, `{"summary": 5}`) reached `dict(...)` / `for r in ...` and raised a raw `TypeError` (exit 1), bypassing the documented exit-2 clean-failure contract.
- Guarded the nested `rows`/`summary` fields with a clean `ValueError` in both `DeltaReport.from_json` and `load_run_result_from_json` (and fixed the `dict(None)` crash on an explicit-null summary). 11 regression tests, all failing pre-fix. Full suite + ruff + mypy gate green.

**Why this work, this session:** found via the sibling-branch-incomplete-fix meta-lens (a prior fix that closed one case leaving a sibling exposed) — the third hit of this run via that lens (after aop#99 and nextjs#80); reproduced firsthand via the shipped CLI before fixing.

**Open questions / blockers:** none — ready for review.

**Next session:** the nested-container sibling of #150 is now closed on both loaders. The isinstance-after-json.loads container-parity vein is fully swept in leh.

## 2026-07-09 (PM) — Issue #158: CLI write-seam exit-code contract (the #104 sibling)
**Duration:** ~35 min · **Branch:** `session/2026-07-09-1927-issue-writeseam` · **PR:** #159

**What got done.** The eval-harness CLI documents a `0 = clean / 1 = findings / 2 = I/O or usage error` exit contract. #104 translated read/load I/O errors to a clean `::error::` line + exit 2 for every subcommand — but the write seam was left bare. All six cli.py write sites (`calibrate --report`, `run/diff/diff-json/list/validate --out`) called `atomic_write_text` directly, plus a seventh in `drift.cli`, so an unwritable destination (a directory, read-only path, unwritable parent) escaped as a raw `OSError` traceback at exit 1, breaking the contract. In `drift.cli` the write had been *explicitly* left outside the exit-2 try on the rationale that the OSError "must propagate to preserve the atomic-write artifact guard" — but that no-half-written-report guarantee is internal to `atomic_write_text` (temp + `os.replace` + cleanup) and holds regardless of whether the caller catches. Added a `_write_output` helper translating `OSError` → exit 2 and routed all six cli.py sites through it (plus `_emit_list_output`'s four branches); wrapped the drift write in the same translation. Migrated the five existing atomicity tests from `pytest.raises(OSError)` (which pinned the propagation *mechanism*) to `assert rc == 2` + destination-absent (both invariants hold), and added a hermetic `validate --out <dir>` test locking exit 2 + `::error::` line + no traceback. Full suite 630 pass, ruff clean.

**Why prioritized.** Found via the exit-code-contract lens — the same class as this run's ems#87, applied to a priority-tier repo. Reproduced firsthand on `validate`, `list`, and `drift` before filing.

**Open questions / blockers.** None — ready for review.

**Next session:** leh CLI exit-code contract is now complete on both axes (#104 read, #158 write) across all 7 write subcommands. Don't re-sweep this class in leh.

## 2026-07-10 — Issue #160: numeric-coercion exit-2 parity in the loaders (~30 min, night)

**What got done.** The run/delta JSON loaders coerced numeric fields with a bare `float()`/`int()`. A container- or null-typed value (which `json.loads` produces natively) raised a raw `TypeError`, which the CLI catch blocks (`KeyError`/`ValueError`/`OSError`/`JSONDecodeError`) don't translate — so it escaped as a traceback at exit 1, violating the documented exit-2 contract. #150/#156 guarded the container *shape* and #116 translated null ids/counts, but the scalar numeric coercions were left unguarded. Same field, same workflow: `score="abc"` already exited 2 via `ValueError`, but `score=[1,2]` exited 1 via an uncaught `TypeError`. Verified all six sites firsthand.

Added a `_require_number(value, field)` isinstance guard (mirroring the #150/#156 container guards) that rejects a non-numeric container/null with a clean `ValueError` before coercion; numbers and numeric strings pass through unchanged (a bad numeric string still raises the original `ValueError`, already exit-2, so no message regression). Applied it at all six sites (`_finite_or_none`, `threshold_drop`, `mean_delta` on the comment path; `score`, `n_rows`, `mean_score` on the diff-json path). CLI-level tests lock exit-2/no-traceback for a container/null numeric field on both subcommands; all fail pre-fix. Full suite + ruff + mypy (D-016) green.

**Why prioritized.** Static priority:high queue globally exhausted; found via the sibling-incomplete-fix meta-lens. The leh exit-2 data-layer contract is now complete across container shape (#150/#156), null scalars (#116), and numeric coercion (#160).

**Open questions / blockers.** None — PR ready for review.

## 2026-07-10 — Issue #162: exit-2 parity for malformed summary count fields (~25 min, night)

**What got done.** `comment.render_delta_markdown`'s `_count` helper rendered the summary count fields (`n_flagged`, `n_regressed`, `n_improved`, `n_new`, `n_removed`, `n_unchanged`) via a bare `int(v)`. #116 guarded only the present-null case; a present-but-non-numeric count — a JSON array/object (`int([1,2])` → `TypeError`) or a non-numeric string (`int("abc")` → `ValueError`) — still crashed the renderer, which runs *outside* `_run_comment`'s exit-2 `try`, so it escaped as a raw traceback at exit 1 (read as "regression found" in CI). This is the count sibling of the #160/#161 numeric-coercion fix, which hardened the loaders' scalar numerics but never the summary count fields the renderer reads.

Added a count-field validation loop to `DeltaReport.from_json` (after the `mean_delta` guard, the established parse boundary): each present-non-null count is checked via `int(_require_number(v, key))` — `_require_number` rejects containers, `int(...)` rejects non-numeric strings, both as a clean `ValueError` → exit 2. Missing/null counts still fall through to the renderer's null→0 coercion. 23 CLI-level test cases (6 count keys × 3 bad values → exit 2/no-traceback, plus 5 good values → exit 0); all fail pre-fix. Full suite (624) + ruff green. Verified the repro firsthand before and after.

**Why prioritized.** Static priority:high queue globally exhausted; found via the sibling-incomplete-fix meta-lens on the just-merged #161. The leh exit-2 contract is now complete across container shape (#150/#156), null scalars (#116), loader numeric coercion (#160/#161), and now the comment renderer's count fields (#162).

**Open questions / blockers.** None — PR ready for review.

## 2026-07-10 — Issue #164: escape pipe/newline in the status delta-row cell (~20 min, night)

**What got done.** `comment._row_to_md` interpolated the delta row's `status` field **raw** into the GFM table (`| {r.status} | ...`), while the adjacent `example_id` cell — and `row.id` + `js.reasoning` in `calibration.py` — all route through `md_table_cell`. `status` was the one free-form cell left unescaped after the #130/#134/#142 sweep that introduced `md_table_cell` and wired every other cell through it. A `status` carrying a literal `|` injected an extra column (7 cells against the 6-column header); a newline split the row across two physical lines — corrupting the posted sticky PR comment at exit 0. The field is reachable via the shipped `comment --delta-json` entry point (the delta JSON round-trips through `RowDelta.from_json` and, per the module docstring, is CI-generated or hand-editable — the same trust model as `example_id`).

A second seam: `RowDelta.from_json` read `status=payload["status"]` with a bare bracket access and no type guard, while its sibling required field `example_id` is validated to a non-empty string. A non-string status would reach `md_table_cell(...).replace` (AttributeError) or the ascii renderer's `f"{r.status:9}"` (TypeError) as a raw exit-1 traceback, breaking the comment path's exit-2 contract (#124).

Fix: route the status cell through `md_table_cell` in `_row_to_md`, and add an `isinstance(status, str)` guard in `RowDelta.from_json` mirroring the `example_id` guard (clean ValueError → exit 2). Three regression tests (pipe-in-status renders one column, newline-in-status stays one line, from_json rejects dict/list/int/None status); all fail pre-fix. Full suite green; ruff check + format clean. Reproduced firsthand before and after, with the escaped `example_id` cell as the control.

**Why prioritized.** Static priority:high queue globally exhausted; found via the sibling-incomplete-fix meta-lens (the recurring GFM-table pipe/newline-escaping class). This completes `md_table_cell` routing for every free-form GFM cell in the leh comment/calibration renderers.

**Open questions / blockers.** None — PR ready for review.
## 2026-07-11 — Issue #166: reject present-but-non-numeric judge score in drift._clamp01 (~18 min, night)

**What got done.** `drift._clamp01` is the choke point every operator-supplied `judge_score_fn` result passes through in `compute_drift` (a public seam), and its docstring promises to fail loud "matching calibration.binarize (#45)". But it guarded only the numeric-but-non-finite case: a present-but-non-numeric return (str/None/list off the BYO judge seam, or None on an abstain) hit the bare `math.isfinite(x)` and raised a raw `TypeError` instead of the clean `ValueError` the contract promises. `binarize` — cited by name — rejects both non-numeric and non-finite (and bool); `_clamp01` honored only half.

Broadened the guard to reject a non-real-number (and bool) the same as a non-finite one, keeping the exact `"judge score must be finite"` message so the existing NaN/Inf tests still match. Seven tests (str/None/list/dict/bool at `_clamp01`; non-numeric via `compute_drift`). Full suite + ruff green. Reproduced firsthand before/after.

**Why prioritized.** Static priority:high queue globally exhausted; found via a broad llm-eval-harness sweep + the sibling-incomplete-fix meta-lens (the docstring cites binarize as the model; binarize guards both, `_clamp01` guarded only non-finite). Scope note: no CLI exit-code path (the drift CLI only uses `_judge_stub`), so this is a documented-contract-parity gap at the `compute_drift` Python-API layer, not a silent-wrong-result.

**Open questions / blockers.** None — PR #167 ready for review.

## 2026-07-12 — Issue #168: run's missing/malformed --dataset exits 2, not a traceback (~15 min, night)

**What got done.** The `run` subcommand (`_run_run`, `eval_harness/cli.py`) wrapped `run_suite(...)` in a `try` that caught **only** `EmptyTagFilterError`. A missing/unreadable/malformed `--dataset` (read downstream via `runner._load → dataset.load_jsonl`, which raises `FileNotFoundError` / `DatasetLoadError`) escaped as a **raw traceback at exit 1**, breaking the CLI's `0 = clean / 1 = findings|regression / 2 = I/O or usage error` contract. `run` was the one input seam the #104/#110/#116/#122/#124 exit-code sweep skipped — and `_fail`'s own docstring *claims* `run` honors the contract.

Pre-load the dataset (`list(load_jsonl(args.dataset))`) and translate `FileNotFoundError` → `_fail("dataset not found: ...")`, `OSError` → `_fail("failed to read dataset ...")`, `DatasetLoadError` → `_fail(str(e))` **before** constructing the judge backend, mirroring `_run_calibrate`'s load-before-backend ordering. 2 tests. Full suite 675, ruff + mypy (D-016) clean. Reproduced both cases firsthand (missing → exit 2 `dataset not found`; malformed → exit 2 `line 1: invalid JSON`).

**CI caught a real subtlety.** My first attempt put the catch *after* `AnthropicBackend(model=...)`. But `AnthropicBackend.__init__` **imports `anthropic` at construction** (judge.py:163, not lazy), so in CI's minimal install (no `judge` extra) it raised `ModuleNotFoundError`/`ImportError` **before** the dataset catch → exit 1; the suite passed locally only because my `.venv` has `anthropic`. Fixed by validating the dataset **before** building the backend (exactly what `_run_calibrate` does); the two tests now `monkeypatch.setitem(sys.modules, "anthropic", None)` to lock hermeticity in any environment. Lesson: `run`-path tests must simulate the minimal install.

**Why prioritized.** Found via a cross-repo exit-code/missing-file hunt (the lens that yielded vsas #85/#87 this run). The other 4 repos (rag/chunking/ems/lco) came back EMPTY on this lens — their bench scripts are self-contained generators with no operator-file input, or no in-repo exit-2 contract to diverge from. Verified firsthand. Not JT-gated.

**Open questions / blockers.** None — PR #169 ready.

## 2026-07-13 (Night) — Issues #171 + #170: architecture-tree + README surface-count completeness
**Duration:** ~25 min · **Branch:** `session/2026-07-13-0525-issue-171` · **PR:** #172 (closes both)

- **#171 (new):** `docs/architecture.md`'s directory tree listed 11 of `eval_harness/`'s 12 modules — `markdown.py` (the cross-cutting GFM escaper `md_table_cell`, #130/#134/#142, sibling of the listed `io_utils.py`) was absent. Uncaught because the fenced tree's bare `foo.py` entries are neither backtick paths nor dotted symbols and nothing asserted completeness. Added it to the tree + a code-tied lock (every `eval_harness/*.py` basename must appear in the doc, inverse-verified). Left the "nine pieces of code" prose — it counts the 9 *feature* modules; `markdown.py` is cross-cutting.
- **#170 (filed, priority:low):** the README "What this is" intro said "Nine closed issues map to nine pieces" while the list had grown to 11 bullets (#56/#58 uncounted). Fixed the intro to "Eleven", de-staled the readme-snapshot lock test name/docstring/message, and added an assertion tying the intro's spelled-out count to the number of top-level numbered bullets.
- Both fixed in one PR (same repo, same drift class, same investigation, one MEMORY entry to avoid append-only sibling conflicts). Verified both new locks flag the pre-fix state. Full suite 678 pass; ruff format/check clean.

**Why this work, this session:** the "arch-doc drift beyond the lock lens" — directory-tree/count-completeness variant — ported from chunking-strategies-lab #122 and nextjs-streaming-ai-patterns #83 earlier the same night; third repo in a row this lens hit.

**Open questions / blockers:** none — ready for review.

**Next session:** check the remaining JS arch-doc repos (mcp-server-cookbook, ai-app-integration-tests) and the other Python repos (rag, lco, prs, ems, vsas, aop, pyasync) for the same directory-tree completeness gap — a fenced tree or module list stale vs the shipped package.

## Session 2026-07-13 (night) — issue #173: validate/run exit 2 on non-UTF-8 dataset

`eval-harness validate` (and `validate --calibration`) and `eval-harness run` leaked a raw `UnicodeDecodeError` traceback at exit 1 on a dataset/calibration JSONL that isn't valid UTF-8, breaking the documented "0 clean / 1 findings / 2 I/O error" contract. `load_jsonl`/`validate_dataset`/`validate_calibration` decode lazily while iterating the file handle, outside the per-row `json.loads` try, so a non-UTF-8 byte raises there. `UnicodeDecodeError` subclasses `ValueError` — not `OSError`, not `DatasetLoadError` — so it escaped `_run_validate`'s and `_run_run`'s narrow catches. `_run_calibrate` was already robust because it catches bare `ValueError`.

The fix adds `except UnicodeDecodeError` → exit 2 to both gap seams (the `_run_validate` fix covers both `validate` and `validate --calibration`, which route through the same handler). Verified all three seams firsthand before and after. Three lock tests; full suite green, ruff clean.

**Why this work, this session:** Eighth hit of the night run, and the second of a *second-order cross-repo* sweep: after shipping the prompt-regression-suite #125 `UnicodeDecodeError`-at-utf8-read-seam fix, the same lens surfaced this in embedding-model-shootout (#101) and here. The decode-failure mode is a `ValueError` subclass that slips past `OSError`/`DatasetLoadError`-only catches at seams with a documented exit-code contract that decode lazily while iterating the handle. Verified firsthand before filing.

**Open questions / blockers:** none — PR #174 ready for review.

**Next session:** Phase A merge PR for #173.

## 2026-07-14 (night) — Issue #175: atomic_write_text overflows NAME_MAX on a long basename
**Duration:** ~15 min · **Branch:** `session/2026-07-14-0734-issue-175` · **PR:** #176

`atomic_write_text` built its temp file name as `.<basename>.<random>.tmp`, so a destination basename near `NAME_MAX` (255 bytes) overflowed the limit and raised `OSError` ENAMETOOLONG — even though a plain `write_text` of that same path succeeds. Reachable from every operator-controlled `--out`/`--output` path and `Dataset.dump_jsonl`. This is the identical bug already fixed in `rag-production-kit#128` and `mcp-server-cookbook#96`; leh still carried the pre-fix construction. Verified firsthand: a 250-byte basename that `write_text` accepts failed via `atomic_write_text`.

Fixed by porting the rag#128 fix — cap the basename's contribution to the temp name to a 200-byte budget (`_cap_base_for_temp`, trimming on a char boundary since NAME_MAX is a byte limit and a multibyte codepoint must never be split). One regression test; full suite green, ruff clean.

**Why this work, this session:** Fifth hit of the night run, surfaced by a cross-repo `atomic_write_text` overflow hunt. The helper is copy-pasted (identically vulnerable) across every remaining Python repo (ems, prs, chunking, vsas, lco, pyasync) — a multi-repo sweep of a real bug already deemed worth fixing twice (rag, mcp), one PR per repo.

**Open questions / blockers:** none — PR #176 ready for review.

**Next session:** Phase A merge PR for #175.

## 2026-07-15 — Issue #178: bool threshold disables the eval gate (sibling of #154)

The #154 fix added range-validation to the `@pytest.mark.eval(threshold=...)`
marker, but used a bare `float(...)` + bounds check. Because `bool` is an `int`
subclass, `float(True)==1.0` and `float(False)==0.0` land inside `[0,1]` and slip
through — `threshold=False` silently disables the gate (a broken judge scoring 0.0
passes green), `threshold=True` makes every eval impossible to pass. The guard's own
comment claimed to mirror calibration.py/judge.py, which explicitly reject `bool` —
but this seam didn't. A comment that lies about parity is a strong incomplete-fix tell.

Fixed by rejecting `bool`/non-numerics before coercing, mirroring the siblings.
Verified firsthand; full suite green.

Why prioritized: sibling-incomplete-fix meta-lens (surfaced by a hunt agent, verified
firsthand) on a priority-tier repo.

## 2026-07-16 (night) — md_code_cell: backtick-safe code-span table cells (#180)

`comment.py` and `calibration.py` wrap `md_table_cell(id)` in an inline-code span (`` `{id}` ``). `md_table_cell` escapes the pipe and collapses newlines but never neutralizes a backtick *in the value* — so a backtick in `example_id`/`row.id` (both free-form external input) closes the wrapping span early, leaking the middle out as prose into the posted PR comment / calibration report. This is the second-order cross-repo sibling of this run's own chunking-strategies-lab #135.

Fixed by adding `md_code_cell(value)` to `markdown.py` — it applies the `md_table_cell` pipe/newline escaping, neutralizes interior backticks to a straight quote, and wraps the result in a single span — then routing both emitters through it (keeping the module's "single home for GFM-cell escaping" invariant). Verified firsthand; 6 tests added. The leh sibling-hunt agent had reported leh SATURATED but missed this — it checked the threshold/judge/cli angle, not the markdown code-span-backtick one. PR #181. Lens: the backtick-in-code-span class transfers across every repo whose emitters wrap free-form strings in `` ` ``.

## 2026-07-17 — Issue #182: backtick in non-table code spans

#180 fixed backtick-breaks-the-code-span for the markdown table cells (via
`md_code_cell`), but three non-table code spans that wrap free-form strings were
left raw: the eval-delta suite heading and the run-id summary line in
`comment.py`, and the judge-model list item in `calibration.py`. A backtick in
the suite name, a run id loaded from a hand-edited delta JSON, or the `--model`
value closes the span early and leaks the rest as prose. `md_code_cell` couldn't
be reused because its pipe-escaping is table-only (a `\|` renders a literal
backslash in a heading/list). Added `md_code_span` (backtick + newline
neutralization, no pipe escape) and routed all three sites through it — output is
byte-identical for clean values, so existing snapshots stay green. A firsthand
`grep` for backtick-wrapped interpolations found the two extra sites the hunt
agent missed. Shipped as PR #183 (ready).

## 2026-07-20 (night) — issue #184: boolean scores silently fabricated 1.0/0.0

`_require_number` in the run/delta JSON loaders guarded against list/dict/null
scalars but not `bool`. Since `bool` is an `int` subclass, a JSON `true`/`false`
at any numeric field (score, mean_score, n_rows, and five more) passed the guard
and the caller's `float()`/`int()` turned it into a fabricated perfect `1.0` or a
zero `0.0` — silently flipping the regression gate at exit 0 with no diagnostic.
This was the cross-repo twin of embedding-model-shootout #108, found by running
the sibling-incomplete-fix lens on the freshest merged surface. One-line fix at
the single numeric choke-point closes all eight fields; four tests added. PR #185.

## 2026-07-21 — judge_kappa run-JSON validation (#186, PR #187)

`load_run_result_from_json` validates every numeric field at the parse boundary
(`n_rows`, `mean_score` + finiteness, per-row `score`) via `_require_number` —
except `judge_kappa`, read by a bare `payload.get()`. #185 hardened the
`_require_number` choke-point against bool, but `judge_kappa` never called it, so a
JSON `true`/`false` loaded as a Python bool (violating `float | None`), a
string/list loaded mistyped, and a NaN token loaded as `nan` then re-emitted as an
invalid bare `NaN` token in the run JSON the dashboard reads (strict parsers reject
it — the same corruption the `mean_score` finiteness guard prevents). Routed the
optional field through `_require_number` + `math.isfinite` (null stays None),
mirroring the `mean_score` and `DeltaReport.from_json` `mean_delta` guards. Five
tests. Lesson: hardening a shared validation choke-point doesn't help a field that
never routes through it — audit every numeric assignment for a bare `.get()` that
skips the choke-point. Found via the sibling-incomplete-fix lens on #185.

## 2026-07-31 — ruff 0.16.1 started formatting Markdown (#188, PR)

CI installs ruff unpinned through `pip install -e '.[dev]'`, and ruff 0.16.1 —
released since the last green run — extended `ruff format` to Python code
blocks *inside Markdown*. Nothing in this repo changed; the tool's scope did.
Six portfolio repos broke the same way on the same day: rag-production-kit,
llm-eval-harness, chunking-strategies-lab and llm-cost-optimizer went red on the
morning's merges, while prompt-regression-suite and python-async-llm-pipelines
were latent, set to go red on their next push.

The trap is version skew. Local venvs still carry 0.15.13, so `ruff format
--check` passes locally and fails in CI; reproducing it at all meant installing
0.16.1 into a throwaway venv. I only found it because my own in-flight PR went
red on lint and `main` turned out to be red too.

Reformatting the Markdown would have been the wrong fix. The lint contract here
has always been "format Python source", and prose is not Python source. The
sharpest case is chunking-strategies-lab, where the same sweep wanted to rewrite
`data/corpus/05_async_pipelines.md` — a pinned benchmark corpus document.
Editing a code block inside it changes the text the chunkers run over and shifts
every canonical metric. A lint tool must never rewrite a benchmark input.

So: `extend-exclude = ["*.md"]`, which re-states the scope the config always
meant, plus a lock test so a future pyproject cleanup can't silently re-expand
it. The test asserts on the config rather than shelling out to ruff, because the
intent needs to be un-droppable and the assertion has to hold on any ruff
version — including ones predating the Markdown feature, which is the very skew
that let this land unnoticed. Amusingly, the lock test itself tripped a *second*
0.16.1 change: UP036 now flags the `sys.version_info >= (3, 11)` tomllib import
guard at `target-version = "py311"`. Lint rules drift on minor releases too, not
just formatter scope.

Pinning a ruff range in `.[dev]` is the deeper fix, but that is a dependency
policy call across six repos rather than a bug fix, so it is flagged for JT
rather than made unilaterally.

## 2026-08-04 — Issue #190: two things `int()` does that the guard in front of it didn't cover

`_require_number` is the one numeric choke-point for the run and delta JSON
loaders, and its docstring states the contract the CLI leans on: a bad value is
rejected "with a clean `ValueError`", which `cli` turns into the documented exit
2. Two callers coerced its result with `int(...)`, and `int()` has two failure
modes that guard says nothing about.

The first breaks the contract outright. `int(float("inf"))` raises
`OverflowError`, which is not a `ValueError` subclass, so it walked through
`_run_diff_json`'s and `_run_comment`'s `except ValueError` and out as a raw
traceback at exit 1. The reachability is the part worth noting: this needs no
bare `Infinity` token, because `json.loads("1e400")` is `inf`. A spec-valid JSON
number literal gets there, so a strict producer reaches it too.

The second is quieter and, I think, more interesting. `n_rows`'s guard exists
because "a mismatch signals a corrupt or incompatible payload" — its own comment
says so. But `"n_rows": 2.7` next to two rows became `int(2.7) == 2`, matched
`len(rows)`, and loaded clean. The coercion sitting *in front of* the guard
erased the very signal the guard was written to catch. The six summary counts
truncated the same way.

This is the cross-repo twin of llm-cost-optimizer#166 from 2026-07-31, which
found both halves at `_sdk_request_total`. Same shape, different choke-point.

`_require_int` rejects a non-finite and a non-integral float with a field-named
`ValueError` and otherwise defers to what `int()` already did correctly. That
deference is the part I spent the most care on: an int, an integral float
(`3.0`, which a JSON round-trip of an int can produce), and a numeric string
(`"3"`) all still load at exit 0, and `"abc"` still raises the `ValueError`
`int()` itself raises with the message another test already asserts. A fix like
this is only safe if it is narrow, so the behaviour-preservation tests carry as
much weight as the failure ones.

The lock scans for the *shape* — any `int(...)` wrapped directly around a
`_require_number(...)` call — instead of asserting that the two known sites use
the helper. Asserting the sites would go stale the moment a third whole-number
field is added, and that is precisely how this landed: `n_rows` and the summary
counts each grew their own bare coercion, independently, months apart. I
reverted both call sites and confirmed ten of the new tests fail, the lock among
them, before shipping.

One test does nothing but pin `int(float("inf"))` raising a non-`ValueError`. If
a future Python changes that, the guards become belt-and-braces rather than
load-bearing, and I would rather a test say so than leave the next reader to
re-derive the rationale from the docstring.

Swept the rest of the repo for the same shape and it is clean: `drift._clamp01`
already rejects non-finite scores before `_judge_histogram`'s `int(s * 10)`,
`percentile`'s `q` is range-checked, and `mean_score` / `mean_delta` /
`judge_kappa` all carry finiteness guards. The renderers' bare `int(v)` sits
downstream of the loader boundary, which is where the exit-2 contract is
documented and now enforced.

Full suite 732 passed, ruff 0.16.1 and mypy clean. Shipped as PR #191.

## 2026-08-05 — a degenerate judge scored a perfect 1.0 (#192)

`parse_judge_output` clamped its parsed score with a hand-rolled
`max(0.0, min(1.0, float(...)))`. `_SCORE_RE`'s numeric group is unbounded
(`[0-9]+`), and `float()` does not raise on a long digit run — `float("9" * 309)`
is `inf`. Clamped, that is exactly `1.0`.

So a judge model stuck in a degenerate repetition loop — the exact pathology an
eval harness exists to detect — scored full marks. That 1.0 flows into
`mean_score`, into `diff_runs`' `mean_delta`, and into the CI regression gate. A
degenerate judge made the gate *greener*, which is the worst possible direction
for a silent failure. A negative run scored 0.0 the same way.

The contract was already written down, one module over. `drift._clamp01`:

> Clamping is for finite-but-out-of-range values; a *non-finite* score (NaN/±Inf)
> is corruption, not something to clamp — NaN would later crash
> `_judge_histogram` cryptically at `int(s * 10)` and ±Inf would silently clamp
> to 1.0/0.0, poisoning `mean_score` and the JSD histogram.

Three judge-score seams enforced that — `_clamp01`, `load_run_result_from_json`
(#86), `binarize` (#45) — and the fourth, the one that actually parses the
model's output, did precisely what that docstring calls out as wrong.

I nearly talked myself out of this one. `SCORE: 100` also clamps to 1.0, and
that is deliberate, so "`inf` → 1.0" looked merely consistent. The test suite
settled it: `test_clamp01_rejects_non_finite` and
`test_clamp01_still_clamps_finite_out_of_range` sit side by side, so the repo had
already drawn the line between "finite out-of-range → clamp" and "non-finite →
reject". `parse_judge_output` just never got the second half. Worth remembering
that grepping the suite for a test naming the behavior can *confirm* a bug, not
only refute one — the usual use of that check is the other direction.

The fix extracts the rules as `judge.clamp_judge_score` and makes
`drift._clamp01` delegate to it. `judge.py` imports no local modules, so it is
the safe home and there is no cycle. `parse_judge_output` converts the resulting
`ValueError` into `JudgeParseError`, which already subclasses `ValueError`, so
the CLI's exit-2 translation needs no new arm — there is a test for that too.
The two seams previously agreed by accident and diverged on the half that
mattered; they are now literally the same callable, with a test asserting it.

Everything deliberate is preserved: `1.05` → `1.0`, `-0.1` → `0.0`, `+1.5`,
the trailing-dot and leading-dot forms from #132, and — the test that proves the
guard keys off *representability* rather than length — a 308-digit score, which
is representable, still clamps to `1.0` rather than raising. 309 is where a digit
run first exceeds float's range.

Two process notes. Reverting both source files for the anti-vacuous check only
produced an `ImportError` at collection, which proves the tests depend on the
change but never actually runs the assertions; patching *only* the clamp call
back to its old form, with the helper still present, gave exactly the six
expected failures. When a revert breaks collection, the check hasn't run — narrow
it. And ruff's `PT011`/`PT017` make the obvious ways of testing a subclass
relationship both fail lint; the clean form is
`pytest.raises(BroadType, match=…) as excinfo` followed by
`assert isinstance(excinfo.value, Subclass)`.

This came from asking where else the portfolio parses a number out of
*model-produced* text, after reading the `prompt-regression-suite#131` fix that
merged this morning — it closed the same "`int` raises loudly, `float` overflows
silently" asymmetry on its slot extractor. Here there was no `try` at all, and
only the silent half is reachable because no `int()` is involved.

Full suite 746 passed; ruff clean under 0.15.13 and 0.16.1.

## Session 2026-08-06 — the one misconfiguration that didn't exit 2 (#194)

Every operator mistake `eval-harness run` can make already ends in a
clean `::error::` line and exit 2: a missing dataset, an unreadable one,
non-UTF-8 bytes, a malformed row, a `--tags` filter that matches nothing.
Every one except the mistake an operator is most likely to make.

```
$ eval-harness run --suite faithfulness --dataset fixtures/sample_factuality_v1.jsonl \
    --tags geography,history --no-diff
Traceback (most recent call last):
  ...
TypeError: "Could not resolve authentication method. ..."
exit=1
```

That is the README's own `--tags` example, copy-pasted verbatim. (It was
the one `run` example without an `ANTHROPIC_API_KEY=sk-...` prefix; the
two above it have one.) `calibrate` had the identical gap.

### Why it escaped

`anthropic.Anthropic()` resolves credentials **lazily**. Construction
succeeds with `api_key=None`. The failure appears at the first
`messages.create` — while *building request headers*, before anything is
sent — as a bare **`TypeError`**. `TypeError` isn't a `ValueError`, so it
walked past every translation in `_run_run` and out through four frames
of `run_suite` → `Judge.score` → `retry_call` → `_once` as a raw
traceback, on the very first row.

An *invalid* key is the same story one layer over: `AuthenticationError`
(401) is correctly classified non-transient, re-raises out of
`retry_call`, and also lands at exit 1 with a traceback.

There's an irony in `AnthropicBackend.__init__`. It opens with a comment
saying it validates "before the lazy `import anthropic` so misconfig
fails fast," and it does — thoroughly — for `max_tokens`, `max_attempts`,
`base_retry_delay`, and `max_retry_delay`. The one piece of configuration
that is actually absent on a fresh clone was the one that failed slow.

And this repo is *built* to run without a key: `pytest # full hermetic
suite (no API key)`, `--judge-stub`, stub backends throughout. "No key"
isn't an exotic state here. It's the default one.

### The obvious fix is wrong

Reject at construction when `ANTHROPIC_API_KEY` is unset. It's one line
and it's a trap. `anthropic>=0.116` resolves credentials from four
channels: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, a named
`ANTHROPIC_PROFILE`, and workload-identity federation. The `judge`
extra's floor is `>=0.32`, so this repo can't pin that list — a future
release can add a fifth.

An env check would tell a profile-authenticated operator that their key
is missing and refuse to run. That's a false positive that breaks a
*working* setup, which is worse than the traceback it replaces. The
general rule: when a dependency has more configuration channels than you
can enumerate, a pre-check risks false positives on valid setups while a
post-failure classifier risks none — it only ever runs on a request that
already failed. Pick the direction where the failure mode is "degrade to
the old behaviour," not "block a valid user."

### So: classify, don't predict

`is_auth_error(exc)` is a sibling of the existing `is_transient_error`,
with the same duck-typed, import-free design so it works (and is
testable) without the `judge` extra. Three handles, in decreasing
robustness: `status_code` 401/403; class name `AuthenticationError` /
`PermissionDeniedError`; and, for the no-credential case that has neither
a status code nor a dedicated class, a `TypeError` whose message names
credential resolution. `complete()` retags a classified failure as
`JudgeAuthError(ValueError)`; the CLI turns that into exit 2 at both
seams, naming `ANTHROPIC_API_KEY` and pointing at the hermetic stub path.

If a future SDK rewords that message, the sniff stops matching and
behaviour degrades to the pre-fix traceback — never to a false rejection.

### The tests are mostly about what it must *not* claim

Eighteen of the twenty-five: 400, 404, 429, 500, a connection error, a
genuine `TypeError` from our own code, a `ValueError` that quotes the
marker phrase (this module's own docstring does), a `bool` masquerading
as a status code. Over-claiming is the entire risk of a message sniff.

One test pins the marker against the **real** SDK, skipped without the
`judge` extra. It clears every `ANTHROPIC_*` variable first, and that is
load-bearing rather than hygiene: `Anthropic(api_key=None)` still
consults the environment, so the first draft made a live network call and
failed on a real 401 on a machine with a key exported.

`test_backend_complete_reraises_permanent_error_without_retry` used a
401, which this change reclassifies, so it now uses 400. Its subject is
the *no-retry* property, which 400 exercises identically, and the new
tests pin the same `calls == 1` / `sleeps == []` for 401/403. A 500 is
still transient and still exhausts the retry budget.

547 green, ruff clean, mypy clean. The anti-vacuous check reverted only
the two behavioural arms, leaving `is_auth_error` defined so collection
still works: 7 behavioural tests fail, 18 classification tests stay green.
The first attempt at that revert deleted `calibrate`'s whole `try` block,
left a bare `try:`, and produced a `SyntaxError` that broke collection in
ten files — a suite that never runs its assertions proves nothing.

### Found the same way, filed separately

Running every README command verbatim also turned up
`fixtures/broken.jsonl`: referenced twice by the validator section, never
committed, so `eval-harness validate fixtures/broken.jsonl --json` exits
2 on a fresh clone.

## 2026-08-07 — the README's validator examples ran against a file that wasn't there (#196)

The README's dataset-validator section documents two commands against
`fixtures/broken.jsonl`. That file was never committed, so on a fresh clone
both of them exited 2 with `dataset not found`. The cost wasn't just a dead
command: the section exists to show the *findings* output — the `--json`
payload shape, the stable code strings CI consumers route on — and none of
it was demonstrable. The `--out` example was worse still, documenting
"exit 2 leaves `--out` untouched" as a contrast with an exit-1 path it had
no way to show.

The fix commits a six-row fixture that carries exactly one of each
non-`empty` finding code, on a known line each, and pastes the real payload
into the README in place of the elision. `empty` can't join them — it only
fires when a file yields zero valid rows *and* no other finding — so it
stays covered by the unit tests, and the README now says so.

The more interesting part is why this survived. There is already a test
whose docstring promises that every path the README references resolves on
disk, and it has been green the whole time. Its pattern only matches paths
inside markdown-link parentheses. Every path in the README that a reader is
told to actually *type* sits inside a ```bash fence, and the lock had never
looked at a single one of them. A lock that enumerates the wrong entry
points is worse than no lock, because it makes the gap read as covered.

So the new sister test walks bash fences specifically, scoped to
`fixtures/` paths. That scoping is what keeps it quiet: output paths like
`report.json` are written *by* the command and must not pre-exist, and
`fixtures/main-baseline.json` appears only inside a YAML block explicitly
labelled as what *downstream* repos put in their own workflows — a
placeholder in someone else's tree. Restricting to bash fences excludes
both classes without needing a denylist to maintain.

One fixture-design note. The first draft used `{"kind": "contains"}` on the
row meant to trigger `version_drift`, and it reported `schema` instead: an
invalid kind is caught inside record validation, which `continue`s before
the version comparison ever runs. An earlier check masks a later one. That
took one command invocation to find and would have taken a long time to
spot by reading.

## 2026-08-12 — the entry point nobody's sweep ever listed (#198)

This repo has swept its exit-code contract six separate times (#104, #110,
#116, #122, #124, #128). Every one of those passes walked `eval_harness/`.
None of them walked `scripts/`. `scripts/capture_demo.py` has a
`main(argv) -> int` under `raise SystemExit(main())` — it is an entry point by
every structural definition the repo uses — and four of its own seams were
bare.

The `--pause-seconds` flag was `type=float` with nothing behind it, and it
failed in both directions. `inf` reached `time.sleep` and raised an
`OverflowError`, and because `_pause` is called *between* stages, it fired
only after STAGE 1 had already run: the operator gets a half-finished capture
and a traceback. The quiet half is worse. `_pause` guards `if seconds > 0`,
and `nan > 0` is `False`, so `--pause-seconds=nan` exited 0 having paused
nowhere. The pauses are the only reason this script exists — they're the cue
points the screen recorder cuts on — so that's a clean, successful-looking run
that produces an unusable recording, with no diagnostic anywhere.

The other two were writes, and it's worth noting they are genuinely two, not
one. `output_dir.mkdir(...)` catches the `--output-dir` that's a file, or
under a file parent. But a *read-only* directory already exists, so it sails
through `mkdir(exist_ok=True)` and dies at `shutil.copy2` instead — after both
hermetic examples have run. The hostile input that reaches the second seam is
precisely the one the first seam accepts.

What settled that this was an oversight rather than a deliberate "scripts
don't owe you an exit contract" call is an asymmetry inside the file itself.
`main` already hand-writes a failure path — but only for the examples it
drives: `if rc1 != 0: print("[capture] ...", file=sys.stderr); return rc1`. So
the script does have exit-code discipline. It just applied it to the one
failure source that wasn't its own. A file that guards the failures it
*imports* while leaving bare the ones it *originates* is worth a second look
anywhere in the portfolio.

Reverting the source and keeping the tests puts 9 of 10 in the red. The two
that stay green are meant to: one pins the `nan > 0 is False` mechanism (true
before and after — that's the point of it), and one asserts a valid run still
exits 0.

## 2026-08-13 — The judge parser could return a score and a reasoning from different blocks (#200)

**Duration:** ~45 min · **Issue:** #200 · **PR:** #201

`parse_judge_output` built its result from two independent searches — one for the `SCORE:` line, one for the `REASONING:` line — with nothing tying them to the same part of the response. Both patterns are line-anchored and have no notion of block context. Three ways to get a well-formed, confidently wrong score fell out of a fourteen-row variant table.

The sharpest is induced by the harness's own prompt. `SYSTEM_TEMPLATE` tells the judge to answer in exactly `SCORE: <number between 0 and 1>` / `REASONING: <one sentence>`, and restating an instruction before complying is about the most common thing a language model does. When it happens, the score skips the placeholder — it isn't numeric — and advances to the real answer, while the reasoning stays pinned to the echoed placeholder. The returned pair describes two different blocks. A prompt template that shows a literal format example is an input generator for its own parser, which is worth remembering.

The second is a direct transfer of the chunking bug shipped earlier in this same run: a `SCORE:` line inside a fenced code block won over the real one below it, so a judge quoting the rubric's worked example got scored at the example's value. The fence-span helper was ported across repos unchanged. The third: a judge explaining what 0.0 means was scored 0.0 for it, and now raises instead.

Rejecting loudly is the right direction here. #192 hardened this same function on the same principle — a wrong-but-plausible judge score is precisely the failure this harness exists to catch, so it is the one failure it must not manufacture itself.

One thing deliberately left alone: when a judge gives two scores, the first still wins. Whether a self-correcting judge's *last* score should win instead is a real design question and deserves its own issue rather than riding along in a correctness fix.

## 2026-08-14 — drift's two exported math primitives didn't enforce the domains they document (#202)

`eval_harness.drift` exports `jensen_shannon` and `percentile` in `__all__`.
Both docstrings state a value-domain precondition. Neither enforced it.

`jensen_shannon`'s docstring promises "non-negative weight vectors of equal
length". The length half raises; the non-negative half never existed. Feed it a
`NaN` and it returns `0.0` — which is this function's own encoding of *"the
distributions are identical"*. The mechanism is a chain of guards that each
individually look correct: `sum()` becomes `NaN`, `nan <= 0.0` is `False` so
both empty-side branches fall through, and `_kl`'s `if ai > 0.0 and bi > 0.0`
is `False` for every `NaN`, so the corrupt slots contribute nothing at all. The
divergence gets computed over whatever survived and lands on zero. Every drift
axis built on it reports `status="ok"`. That is the same false-negative shape
issues #91 and #93 fixed at other seams — this time reached through the value
domain rather than through an all-zero histogram.

Negative weights had two separate silent modes. `[10, -5]` sums to 5,
normalizes to `[2.0, -1.0]`, and `_kl` skips the negative slot, returning
`0.3475…` — inside `[0, 1]`, so it survives every bounds check downstream.
`[-1, -1]` sums to `-2`, trips the `sp <= 0.0` *empty* branch, and is reported
as **maximal drift** for a vector that isn't a distribution at all. That second
mode is why the new guard sits *above* the empty-side branches: a guard placed
below them would never have seen it. There's a test named for that placement.

`percentile`'s docstring was a single line: "matches the rag-kit pattern".
`rag_kit.telemetry.percentile` has rejected non-finite values since
rag-production-kit#80, and the two function bodies were otherwise identical —
so the parity claim was aspirational rather than true. The consequence is worth
stating precisely: the multiset `{1.0, 3.0, 4.0, NaN}` at `q=0.5` returned
`2.0`, `3.5`, or `nan` depending only on where the caller happened to put the
`NaN` in the list, because `sorted()` leaves it in an implementation-defined
slot.

Neither defect is reachable through `compute_drift` or `drift.cli` today. I
checked every internal feed firsthand and said so in the issue, the PR, and the
close comment: `_length_stats` passes `float(len(s))`, the three
`jensen_shannon` call sites pass non-negative integer histograms, `_clamp01`
already guards the judge seam, and the CLI reads JSONL of strings. So this is a
public-API contract gap, not a live corruption path — which is the same
argument rag-kit made when it guarded its own copy.

How it was found is worth recording. Grepping the repo for prose assertions
("never", "cannot", "mirrors", "matches", "in parity with") turned up a rich
vein, and `percentile`'s parity claim was the thread. Rather than read the two
functions and reason about them, I AST-extracted all five `percentile` copies
in the portfolio and ran one input table through all of them side by side. A
first attempt to import the real modules died on `rag_kit.db` requiring
`psycopg`; pulling the function *source* out with `ast.get_source_segment` and
exec'ing it in a stub namespace sidesteps every repo dependency, and is the
technique to reuse for any cross-repo pure-function differential. The matrix
showed the three-different-answers-for-one-multiset row immediately.

Two hunts came back empty and are recorded so they aren't repeated. A 19-case
differential between `validate_dataset` and `validate_calibration` — blank
lines, BOM, CRLF, NUL bytes, bad UTF-8, duplicate ids, `null`/list/bare-number
rows, and five malformed id shapes — found **full parity on all 19**, so that
prose assertion genuinely holds. Both validators do abort on undecodable bytes,
which looked like a live instance of the collecting-mode class fixed in
prompt-regression-suite#133, but `cli.py` already translates
`UnicodeDecodeError` to a clean exit 2 for both. Not a bug.

## 2026-08-19 — `cohens_kappa` validated length and nothing else (#204)

`eval_harness` exports three calibration metric entry points — `binarize`,
`pearson_r`, `cohens_kappa` — and two of the three validate their inputs.
`cohens_kappa` checked that the two rater lists were the same length and
non-empty, and then never looked at an element. `_require_finite_numbers`
sits one definition below it in the same file doing exactly that job for
`pearson_r`, and its docstring spells out the argument in words that are true
of κ verbatim: an unguarded non-finite value "renders it as a confidently-wrong
'very strong' correlation."

For κ the rendering is worse, because `_interpret_kappa` is a ladder of `<`
comparisons and every comparison against `NaN` is `False`. A `NaN` rating falls
all the way through to the final branch and comes out labelled **"almost
perfect"**. Rendered firsthand, the report reads:

```
- result: **FAIL**

| metric | value | interpretation |
|--------|-------|----------------|
| Cohen's κ (binarized at 0.5) | nan | almost perfect |
```

That is `docs/calibration_report.md`, the file D-005 gates CI on. A report
that says FAIL and "almost perfect" in the same table is worse than one that
refuses to render.

The docstring's "on a binary scale" turned out to be load-bearing rather than
decorative: `pe = a_pos*b_pos + (1-a_pos)*(1-b_pos)` is a chance-agreement
*probability* only when every element is in `{0, 1}`. Rather than hand-pick
variants, I brute-forced the element domain `{-1,0,1,2,3}` at n=2 and n=3 and
found 8088 input pairs whose κ is `NaN` or outside `[-1, 1]`. The extreme is
`cohens_kappa([3,3,0], [1,0,1]) == -9007199254740991.0`, but the dangerous set
is the quiet one — `[0,2,0,2]` vs `[0,1,0,1]` returns `0.0` and `[0.5,0.5]` vs
`[0,1]` returns `-1.0`. Both sit comfortably inside κ's real range and read as
ordinary calibration results. Nothing downstream could notice.

A second, sharper half fell out of the same reading. `render_report` computes
`result.cohens_kappa >= threshold_kappa` and has a five-line guard rejecting a
non-finite or out-of-range `threshold_kappa`, justified in its docstring by
"finite values outside that range cannot ever match ... so the gate is silently
broken." Every word of that is equally true of the *left* operand, which was
unvalidated — and since `CalibrationResult` is a public export, that is the
path the `NaN` report above was produced through. The general lens: when a
guard exists to protect a comparison, check whether it covers both sides.

One judgment call is worth flagging because it narrows working behaviour.
`cohens_kappa([True, False], [1, 0])` returned a correct `1.0` and now raises.
I took that anyway so the module holds one opinion about `True` instead of
three — `binarize` and `_require_finite_numbers` already reject it, and
`calibrate` feeds all three from the same rows. The error message names the fix
and the test is called `test_bool_is_rejected_even_though_it_returned_the_right_answer`,
so if JT disagrees the change is one line and obvious.

Neither gap is reachable from inside the repo today: `calibrate` feeds
`cohens_kappa` guarded `binarize` output. That is the same standing as the two
guards merged in #203, and the same reason applies — the names are in
`eval_harness.__all__`, other portfolio repos import this one as a library, and
`docs/architecture.md` names the math as the reusable part.

27 tests, every assertion anchored to a value measured on the pre-fix tree
rather than to an exception type. Reverting only the four behavioural lines —
keeping the new symbols so collection still works — turns 22 of them red.

## 2026-08-20 — the diff baseline followed insertion order (#206)

All four `ORDER BY` sites in `eval_harness/runs.py` sorted on `started_at`
alone. `utc_now_iso()` has one-second resolution, so the tie is not a corner
case — it is what consecutive runs normally produce. Measured: one distinct
value across 2000 back-to-back calls, and six consecutive real `run_suite()`
calls all landing on a single second. Among tied rows SQLite's order is
implementation-defined, and it tracked insertion order.

What led me there was `load_baseline`'s own docstring. It already names the
hazard — it cites the "1-second-resolution `started_at`" as the reason
`exclude_run_id` exists. That guard closes the half where the *current* run is
the collider. Two *prior* runs sharing a timestamp still tied. A stated reason
is a test case, and the question to ask is which half of it is actually covered.

The consequence is the artifact CI posts on a PR. Two prior runs at one second
scoring 0.90 and 0.30, against a current run of 0.60:

    good written first -> baseline 0.30, mean_delta +0.30, nothing flagged
    bad  written first -> baseline 0.90, mean_delta -0.30, every row flagged

A clean pass or a regression, same three runs, decided by write order.

`list_runs` was the sharper half. `--limit` did not merely reorder the output,
it changed which runs appeared: over all six insertion permutations of three
tied runs, `limit=2` returned three different *sets*. A run silently vanished
from the operator's history. Reordering output is cosmetic; dropping a row is
not — so the test asserts on membership at the limit boundary, not just order.

The tiebreak is `run_id`, the primary key: unique, total, and *content* rather
than a position. A `rowid` tiebreak would make the result independent of the
query plan but not of the insertion order, which is the actual defect — the
same distinction that came out of agent-orchestration-platform#120 earlier in
this run. The repo already does this job properly one module over: `dataset.py`
sorts its tag inventory on `(-count, name)`.

I left `utc_now_iso()` alone, and measured why. Sub-second and whole-second
stamps do not lexicographically interleave — `"...T07:17:08.123456Z" <
"...T07:17:08Z"` is `True`, because `.` sorts before `Z` — so switching the
format would make a newer run sort *before* an older one already on disk. That
needs its own issue and a migration story, and it is not a prerequisite for a
total order.

One honest limitation, stated in the docstring rather than left for the reader
to infer: a `run_id` tiebreak makes the order a pure function of the stored
data. It does not recover which tied run truly ran last, since `run_id` is a
random UUID. Determinism is the property being fixed.

**Why this work, this session:** the static `priority:high` queue was globally
empty again, so the issue came out of a firsthand probe of the read/write and
ordering seams in this repo.

**Open questions / blockers:** none. `#177` (calibration doc table) still needs
the maintainer's intended per-group breakdown.

**Next session:** sub-second `started_at` with a migration story is the natural
follow-up, but it is a stored-format change and wants JT's call on the
compatibility question.

---

## 2026-08-21 — drift reports that changed their mind when you reordered the file (#208)

`compute_drift` is the function that decides whether production traffic has
moved far enough from the golden set to fail CI. It turned out not to be a
function of the corpora at all — it was a function of the corpora *and the order
the lines happened to be in*.

The tell was in a docstring. `_kmeans` said "stride-init for determinism," and
that claim is true only if the input order is fixed. It isn't: the drift CLI
reads its corpora from JSONL files, and shuffling lines in a JSONL file is a
semantically null edit. So I shuffled one. Forty times, against one fixed
candidate set: ten different embedding scores from 0.0088 to 0.1414, a sixteen-
fold spread, and both verdicts — seventeen shuffles said `ok`, twenty-three said
`drifted`, for byte-identical corpora.

What made this more than a one-line fix is that three separate things in that
function read the input order. The stride init picked its seeds by position.
The assignment loop settled a cosine tie by taking whichever centroid it met
first. And the centroid update accumulated with `+=` — float addition isn't
associative, so summing the same numbers in a different order gives a different
answer in the last bits. That third one is the reason "just sort the seeds"
would have looked like a fix and not been one: a last-bit wobble in a centroid
carries into the next assignment round, and can push an input across a cluster
boundary, which is a whole-bucket change in the histogram the divergence is
computed over. So rather than tiebreak three sites, the fix canonicalizes the
processing order once at the top of the function and maps the assignments back
to the caller's indexing on the way out. That map-back got its own test, because
`compute_drift` throws the assignments away and would never have caught a
regression in it.

There was a second, sharper defect alongside it. The "representative examples" —
the inputs that look least like anything in the golden set — were sorted on
distance alone and then truncated to five. Sorting is stable, so tied inputs
were ranked by where they sat in the file, and the truncation turned that into a
difference in *membership*: six tied candidates contesting five slots produced
six different five-element sets over sixty shuffles. This is the same shape as
the run-history bug fixed last session one module over, and the lesson repeats:
at a truncation boundary, an untiebroken sort doesn't reorder the output, it
changes what's in it.

Ties here aren't a corner case. `hash_embed` sums per-token vectors, so it's a
bag of tokens: duplicate inputs embed identically, and duplicates are the normal
condition of a production traffic sample. The argument for reachability comes
straight out of the embedder's own algebra.

One published number moved. The README quotes the drift example's output, and
the repo's doc-lock test went red on `embedding=0.156`. The deterministic result
on the same committed fixtures is `0.147`. Nothing was regenerated to make the
build pass — the lock caught a real number changing, which is exactly what it's
for, and its failure message says so itself: source is the truth.

I left one thing alone deliberately, and filed it as #210. A text with no
alphanumeric tokens — an empty string, punctuation, an emoji — embeds to the
zero vector, and the zero vector's cosine with every centroid is exactly zero.
So it scores a distance of 1.000: maximal novelty. A genuinely novel request
measured 0.647. Put five emoji and one real novel request in a candidate set and
the real one is surfaced zero times out of forty; the punctuation takes every
slot. That's the same class as two other fixes this month — a value standing in
for "not measurable" that happens to sit at an end of the scale doesn't abstain,
it ranks — but the remedy here is a genuine design choice between excluding
these inputs, rejecting them, or reporting them as their own category, and there
is a knock-on question about them all piling into cluster zero and skewing the
histogram. That deserves a deliberate call, not a drive-by.

Cluster seeding quality is also untouched, and worth naming: a stride over a
sorted list is still weak k-means initialization, and when `k` is more than half
of `n` the stride collapses to 1 and it's simply the first `k` vectors.
Determinism was the defect. Better seeding is a different argument that would
move already-published numbers on its own merits.

---

## 2026-08-24 — Issue #210: a token-less input is uncomparable, not maximally distant (D-017)

**What got done.** `hash_embed` returns the all-zero vector for any input with
no alphanumeric tokens — an empty string, punctuation, an emoji run, whitespace
— and `_cosine` of the zero vector with any centroid is exactly `0.0`. Nothing
in `drift.py` distinguished that from a *genuine* cosine of `0.0`, so a
content-free input scored a distance of `1.000`, the ceiling of the range, and
outranked every input with real content. Because `representative_examples` is
sorted and then *truncated*, that did not merely rank wrongly, it evicted:

```
golden = 6 billing + 6 shipping utterances, cluster_k=4
candidates = 4 real + 6 token-less, n_representative_examples=5
  -> ['', ' \n\t ', '!!!', '---', '???']     0 of the 4 real inputs surfaced
```

The same tie corrupted the histogram the embedding JSD is computed over.
`_assign` starts at `best_sim = -2.0` and every centroid ties at `0.0`, so the
first one always wins and every token-less input piles into cluster 0:

```
4 real candidates              emb JSD 0.1909   histogram (1, 3, 0, 0)
the same 4 + 6 token-less      emb JSD 0.3122   histogram (7, 3, 0, 0)
```

Six inputs carrying no information moved a published drift score by 0.12. One
`'!!!'` row on the *golden* side did the mirror thing — it seeded k-means from
the origin, moving the golden histogram to `(6, 5, 0, 2)` and the score from
0.1909 to 0.1432.

**The finding that wasn't in the issue.** A golden set in which *nothing* is
embeddable was accepted and reported `embedding drift_score=0.000, status="ok"`.
Every centroid is the zero vector, every candidate assigns to cluster 0, and the
two histograms come out identical — which is this module's encoding of "no
drift". A maximal false negative on the regression gate, produced by a baseline
that can measure nothing. That is the third instance of the class already fixed
in #91 (one-empty JSD) and #93 (the length-histogram open bucket), reached this
time through the embedder.

**The decision (D-017).** The remedy splits by side, because the two sides have
different economics. A golden set is *authored* — small, reviewed, fixable — so
one with nothing embeddable now raises. A candidate set is a *sampled production
traffic slice*, so a single emoji must not abort a 10,000-line drift run: those
inputs are counted in a new `DriftReport.n_uncomparable` field and excluded from
the cluster histograms and the example list. That split is what let the issue's
two competing remedies both be right, on the side each was right for. The length
and judge axes deliberately still see these inputs — a char count is truthful
and a judge can legitimately score them — and a test asserts it rather than
assuming it, because dropping them from every axis would trade one wrong number
for three.

Counting rather than silently dropping is the point of the field: "6 of 10
candidate inputs have no embeddable content" is itself a drift finding, and it
is rendered in the HTML report and named in the embedding axis's `detail`
string, not just left on the dataclass.

**Two things worth carrying forward.** First, `sum(cluster_counts) ==
ClusterStats.n` is now an invariant with a test — `n` is the *clustered* count,
not the input count, so `n_golden - n` is exactly the uncomparable count.
Excluding inputs without moving `n` would have made the two disagree silently,
which is the shape of defect this change exists to fix. Second, the tie-break
fixture added by #207 was built out of the very inputs this issue removes
(`["", "!!!", "...", "???", "———", "🎉🎉🎉"]` tie precisely *because* they all
embed to the zero vector). It has been rebuilt from the six permutations of one
three-token bag, which is the reachability argument `compute_drift`'s own
tie-break comment makes. A fixture that exercises a property via a degenerate
input stops exercising it the moment the degenerate input is fixed.

**Why this was prioritized.** Filed but not worked by the 2026-08-21 run, in the
priority-tier repo that sits first in the §8 build sequence, with a concrete
acceptance-criteria list and a measured reproduction already attached.

**Open questions.** Whether `hash_embed` itself should get a character n-gram
backoff so an emoji run embeds to *something* rather than to nothing. Deferred
deliberately: it would move every already-published number on every axis, and it
answers a different question than what the zero vector *means*.

**Tests.** 38 new (`tests/test_drift_uncomparable_inputs.py`), of which 14 fail
against a narrowed revert of the four behavioural hunks. Suite 872 → 910 green,
ruff clean, mypy clean.

## 2026-08-25 — `dataset.py` no longer accepts records it cannot write back (#213)

**What got done.** `Dataset.dump_jsonl`'s docstring promised that `load → dump →
re-load` is byte-stable "for any well-formed input, which is what makes round-trip
identity testable." That was prose, and the repo had never actually tested it over
a table — only over two hand-built happy rows. Running a 19-row variant table
through it broke the claim twice. A non-finite number anywhere on a record (most
plausibly inside the free-form `provenance` object) came back out as a bare
`NaN`/`Infinity` token, which is not JSON; and a lone surrogate — legal JSON escape
syntax that Python decodes — loaded clean and then killed the writer with
`UnicodeEncodeError`. Both files passed `eval-harness validate` with `findings=0`.
One iterative record walk in `_validate_record`, the single choke point `load_jsonl`
and `validate_dataset` both route through, closes both.

**Why this was prioritized.** No `priority:high` issue existed anywhere in the
portfolio, so the target was found firsthand in the priority-tier repo that sits
first in the §8 build sequence. `dataset.py` owns the repo's primary artifact — the
golden-dataset format every other subcommand, the pytest plugin, and downstream
repos read.

**The detail that makes it a real finding.** It is not enough that the emitted line
is invalid JSON; what matters is what consumers *do* with it. Browser `JSON.parse`
rejects it outright, which is survivable. `jq` 1.7.1 parses it **silently**, turning
`Infinity` into `1.7976931348623157e+308` and `NaN` into `null`, with no error and
no exit code — so a pipeline step that shells out to `jq` gets a plausible wrong
number instead of a failure.

**Not a new policy.** `runner.py` already enforces this exact finiteness contract on
every numeric field it loads (#42, #185, #204), and its comment states the rationale
verbatim. `calibration.py` gets it for free, because `human_score` is range-checked
and `0.0 <= nan <= 1.0` is False. Of the sites the rule applies to, `dataset.py`'s
`provenance` was the one that disagreed — and the only one behind a canonical writer.

**Open questions.** None for this issue. `calibration.py`'s `provenance` is
unguarded too, but that module has no canonical writer, so the egress this fix is
about does not exist there.

**Tests.** 35 new (`tests/test_dataset_representability.py`) — a 15-row ACCEPT table
and an 8-row REJECT table. Disabling the guard turns every REJECT row red and leaves
every ACCEPT row green; the ACCEPT half is the anti-vacuous control, since a check
written too broadly would turn the REJECT rows green while quietly breaking real
datasets. Suite 865 → 900 green, ruff clean, mypy clean.

## 2026-08-26 — the same byte either killed the run or vanished (#215)

**What got done.** `#213`, shipped hours earlier, taught the *dataset* seam that
a string with no UTF-8 encoding is not well-formed, because `dump_jsonl` cannot
emit it. `drift` reads through a different loader and writes through a different
writer, and got neither half. `compute_drift` now rejects an unencodable input
on both sides, and the detection lives once in `io_utils.find_unencodable`,
shared with the dataset check.

**The lens was the previous fix's own rationale.** `#213` argued for itself by
naming where the bad input comes from — "they reach traffic samples from broken
UTF-16 handling upstream". Drift detection *is* the traffic-sample consumer. It
was the one place the rule was argued for and not applied. When a fix justifies
itself by naming a producer, go read that producer.

**Four outcomes for one byte, decided by position rather than by badness.**
`render_html` puts raw input text in exactly one place — `html.escape(r.text)`
truncated to 200 characters, over `representative_examples`. So a lone surrogate
crashed the run only if the JSD ranking picked its row *and* it sat below
character 200. On a highly-distant candidate row it died at exit 1 with a raw
traceback. On a near-duplicate of a golden row it was ranked out of the top-N and
the report was written with that row simply absent. At character 240 the `[:200]`
slice dropped it. In the golden set it was never rendered at all. When a crash
depends on a ranking or a truncation, the absence of a crash proves nothing.

**The exit code is what makes it a contract bug.** `UnicodeEncodeError`
subclasses `ValueError`, not `OSError`, so the write seam's `except OSError`
could never have caught it, and it escaped at exit **1** — which in this CLI
means *findings*. A gate treating 1 as "drift detected, alert the team" and 2 as
"infrastructure error, retry" was told there was drift when no report existed.

**Choosing the choke point meant counting the roads.** The obvious fix was the
loader, but the README ships a library snippet — `compute_drift(...)` then
`write_text(render_drift_html(report))` — that has no loader. `compute_drift` is
the one function both roads pass through, it was already this module's
input-contract choke point, and putting the check there landed it inside
`drift.cli`'s existing `except ValueError`, so exit 2 came for free with no new
catch.

**Why this needed a decision (D-018).** D-017 deliberately lets token-less
candidate rows through — one emoji must not abort a 10k-line traffic slice — and
it would have been easy to extend that here. It doesn't transfer: D-017 is about
*embeddability*, and a token-less row can still be written to the report. This
one cannot be written down at all. Dropping it instead would deflate
`n_candidate` and both histograms with no diagnostic, the same false-negative
class as #91 and #93.

**A plan correction.** The plan said "README impact: none expected". Wrong — the
paragraph immediately above the new rule ends "a candidate sample is production
traffic, so one emoji there is counted, not fatal (D-017)", which now reads as a
blanket promise. A new exception to a documented leniency has to land next to the
leniency.

**Measured and deliberately not filed.** `load_calibration` admits surrogates,
but every CLI writer it feeds uses `json.dumps` at the default
`ensure_ascii=True`, which escapes them back to ASCII. `dump_jsonl` is the only
writer in the package using `ensure_ascii=False`, and #213 already guards it. The
`runs.py` SQLite `INSERT` does raise on a surrogate, but its only text source is
judge output from the API rather than an operator-supplied file, so reachability
needs its own measurement — noted, not filed as padding.

**Tests.** 55 new. Neutering the drift guard turns 25 red with no control row
affected; neutering the shared helper turns 42 red across *both* this file and
`test_dataset_representability.py` — that second number is the one that proves
the definition is really single. Suite 945 → 1000 green, ruff and mypy clean.

## 2026-08-27 — #217: a calibration row that cannot be written down

`#213` taught the golden-dataset loader to reject a record the canonical writer
cannot emit; `#215` taught `drift.compute_drift` the same. The grid for "who
else" was sitting in `io_utils`' own module docstring, which enumerates four
writer families. Two had the guard. The calibration loader and the CLI write
seam did not.

The sharp part is not the crash, it is the pre-flight. `validate_calibration`
exists, in its own words, so an operator "can fix every issue before
`eval-harness calibrate` spends judge tokens". On a three-row file that is pure
ASCII on disk — the surrogate is the six-character escape `\ud800` — it reported
`ok: rows=3 valid=3 findings=0`. Then the whole set was judged, and the report
write died with a raw `UnicodeEncodeError` at exit 1. Exit 1 on `calibrate` is
the "Cohen's κ below threshold" outcome, so the crash and the legitimate finding
were the same signal, and the money was already spent. `calibrate` now exits 2 at
the load seam, before the backend is even constructed.

The write seam was the other half. `_write_output` was added precisely so no
`--out` site calls `atomic_write_text` bare. `atomic_write_text` raises exactly
two things and it caught one: `UnicodeEncodeError` is a `ValueError`, not an
`OSError`. `_run_validate` already carries the matching arm on the *read* side,
with a comment spelling out the same reasoning. Reachable with no judge and no
API key at all, through the run-JSON artifact the Action uploads and downloads.

The record walk moved to `io_utils.find_unrepresentable`, so the two record-level
sites share one detector while each still phrases its own consequence. Its
`kinds` parameter is load-bearing rather than decorative: `dataset` enforces the
non-finite axis because `dump_jsonl` re-emits the record, and calibration does
not, because nothing writes a calibration record back out. A rejection with no
consequence to name is how a guard drifts away from the harm it was written for,
so the absence is pinned by its own test instead of left to a comment.

And a lesson that cost real time: writing *about* a lone surrogate is how you
ship one. A bare escape inside a non-raw docstring is not six characters after
compilation, it is a real unpaired surrogate. Where it lands decides how it
fails — `compile()` refuses a docstring outright, but compiles an assignment, a
`return` literal, a dict value or an f-string piece and silently carries the
surrogate into the module. The bytes on disk catch neither half; the file is
valid UTF-8 either way. So the new lock walks the compiled constants of every
package module and every test module, and the package now satisfies in its own
source the rule it enforces on its inputs.


## 2026-08-27 (correction) - #217: I pinned an interpreter property as if it were a code property

The PR said "1099 passed". That was true on Python 3.14, which is what my local
venv runs, and CI runs 3.11 and 3.12. Four of seven jobs went red.

The cause was worth the trip. `test_the_docstring_half_is_caught` asserted that
`compile()` refuses a docstring containing a lone surrogate. That is not a
property of the code being tested; it is a property of the interpreter. On 3.14,
`compile()` raises for module, function and class docstrings. On 3.11 and 3.12 it
raises for nothing at all - every literal position compiles cleanly and silently
carries a real unpaired surrogate into the module.

Which means the "loud half / silent half" matrix in the PR body was measured on
one interpreter and stated unconditionally, and on the versions CI actually runs
there is no loud half. Both of the slips that motivated writing the lock in the
first place would have shipped straight through CI rather than crashing at
import. The lock is worth more than the PR claimed, not less.

The fix is to assert the outcome rather than the road: a surrogate-bearing
literal is caught, and which arm catches it - the compile refusal or the constant
walk - is an interpreter detail. Whenever a test names a mechanism, the question
is whether the mechanism or the result is the contract.

Two things I should have done. My own notes carry a rule about host-environment
assertions, and interpreter version belongs on that list next to clock, CPU and
filesystem. And I had merged a PR this same morning whose design comment says, in
so many words, that a guarantee cannot be conditional on which Python is running
it - then wrote a test that was. Checking the CI matrix before probing language
behaviour would have cost thirty seconds.

I also nearly mis-blamed my own diff: my local 3.11 fails a different test file,
and stashing and re-running on `main` showed it fails there too - a stale pytest
in that interpreter, nothing to do with the change.

## 2026-08-28 - issue #218: the judge seam translated exactly one of its exceptions

The issue reported that `JudgeParseError` escapes `calibrate` as a raw traceback at
exit 1 - the code that means "Cohen's kappa below threshold" - so a judge that
answered in the wrong format was reported to CI as a calibration failure. It also
asked for the answer as a grid rather than a list: which judge-layer exceptions can
reach each subcommand's top frame, and which of those each subcommand translates.

Building that grid before planning is what made the fix bigger than the issue.
`run` has the identical gap, and the parse error is not the only escapee. Only two
subcommands ever construct a judge, and across nine failure modes exactly one -
`JudgeAuthError`, which got an explicit arm in #194 - was translated. Everything
else, including an `ImportError` from an install without the optional `judge`
extra, exited 1 with a stack trace. On these two paths that is not merely untidy:
exit 1 already means "a row regressed" or "the judge is no longer calibrated", so
an operational failure was being answered as a quality result.

Two comments in the repo had already reasoned about the exception they then let
escape. One calls the minimal-install `ImportError` a break of the exit-code
contract and handles it only on the path where the backend is never built. The
other validates the dataset first precisely so that `ImportError` cannot mask a
dataset error - it ordered the code around the exception and never translated it.
That pattern, where a fix's own wording points at the site it missed, is the third
run in a row it has paid.

The sharper find was a green test asserting the fix in prose. It says subclassing
`ValueError` is "the property keeping the CLI's exit-2 translation working without
a new arm", and neither judge seam has ever caught the broad `ValueError`. The test
passes because it only checks the class relationship; the CLI behaviour it narrates
was never true. The same claim had spread by citation to two more places, each
naming the broken case as its precedent. All three now describe the mechanism that
actually holds, which is an explicit `except` arm and nothing else.

Shipped: parse errors and the construction `ImportError` translated to exit 2 at
both seams, the two judge loops re-raising with the failing row's id so the message
names the site and not just the symptom, and the grid pinned as a test - including
the clean baseline, so the table cannot pass vacuously, and the rows I deliberately
did not change. Those are remote backend failures and bugs in a caller's own
`Backend`; catching them would need `except Exception`, which turns someone else's
real bug into a usage error. That is issue #220, and pinning the current behaviour
means it has to edit the test on purpose.

Two process notes worth keeping. My anti-vacuous probe grepped pytest's tail for
"N failed" and read a collection error as zero failures - reverting the arm also
removed the import - which is a trap my own notes already warn about; grep the
summary line. And a stash-plus-restore loop nearly lost one file's edit, because I
had backed up three of the four files I touched. Diffing the stash against the
working tree before dropping it is what caught it.

## 2026-08-31 — Issue #222: the plugin's failure-context hook never fired
**Duration:** ~18 min · **Branch:** `session/2026-08-31-0711-issue-222`

- `pytest_runtest_makereport`'s docstring promised that when something other than the threshold assertion raised — a judge timeout, a parse error, an answer-source failure — "the row id and the response are still surfaced". Ran it: it surfaced nothing, on all three. Three independent causes, each sufficient on its own. It returned unless the failure was in the `call` phase, but the autouse `_ensure_judge_score_runs` fixture pulls `judge_score` via `getfixturevalue`, so the answer source and the judge always run in **setup**. The row, response and score were stashed only after *both* calls returned, so the failure paths had nothing to read — a judge failure discarded a response it had already computed. And the block it built went to `item._eval_failure_extra`, whose named consumer `pytest_runtest_logreport` had an empty body.
- Fixed all three: each value is stashed the moment it becomes known, the hook handles setup and call, and the block is attached with `longrepr.addsection` — not `report.sections`, which is the captured-output channel and gets filtered by `--show-capture=no`, a common CI flag that would have quietly restored the bug. There's a test pinning that. The threshold path is unchanged and suppressed from the new section, keyed off a flag set at the raise site rather than off `AssertionError`, because a user's own `assert` in the body is an `AssertionError` too and should get the block.
- 7 new tests, 1128 → 1136 green. Each of the four reverts (phase widening, stash ordering, write-only stash, threshold suppression) turns a distinct subset red.

**Why this work, this session:** all three pre-existing open issues in this repo are gated on a JT decision (#177 needs the maintainer's intended calibration breakdown; #212 and #220 each need a recorded contract decision before an arm can be written), so the session hunted instead. `pytest_plugin.py` is 304 lines with essentially no prior issue traffic while `drift`, `cli`, `judge` and `comment` each carry 50+ — the module nobody has filed against is the unread one, not the correct one.

**Open questions / blockers:** none for this issue. A follow-up (#223) is filed and deferred: an eval-marked test with a no-arg body isn't parametrized at all and dies on `fixture 'eval_row' not found`. It needs a small contract decision (illegal, or supported) rather than a drive-by.

**Next session:** #223 if a decision is taken; otherwise the repo's backlog stays JT-gated.

## 2026-09-01 — Issue #223: an eval body that doesn't name `eval_row`
**Branch:** `session/2026-09-01-0710-issue-223`

- The pytest plugin only parametrized `eval_row` when the test body already
  named it, so the marker's own promise — one item per dataset row, "regardless
  of body signature" — was false for anything else. The issue reported it as a
  no-arg-body problem; a six-shape variant table run through `pytester` showed
  the real rule is "`eval_row` never reached the fixture closure", which also
  breaks `def test(tmp_path)` and `def test(**kwargs)`. All three collected one
  unparametrized item and then died in setup with a message naming the plugin's
  internals rather than anything the user wrote.
- Fixed by widening the closure before parametrizing, so every shape now
  collects one item per row, keyed by row id, and is scored by the judge.
  Recorded as D-019 — the issue had leaned the other way (fail at collection),
  on the grounds that always parametrizing "needs care"; measuring it showed it
  works on both ends of the supported pytest range, so the contract got wider
  instead of the API getting narrower.
- The variant table ships with an arm that guards the table itself: if someone
  trims it back to the shapes that always worked, that arm goes red rather than
  the suite quietly covering nothing.

**Why this work, this session:** #223 was split out of #222 last run and
deferred rather than ridden along; it was the only unblocked, non-decision-
revisit issue in the repo, and its `priority:low` label was a scoping judgement,
not a severity one.

**Open questions / blockers:** none.

**Next session:** #220 (judge-seam remote-failure contract) still needs a
written decision before it can be worked.

## 2026-09-02 — #226: the temp-name byte budget was counting the wrong bytes

`io_utils._cap_base_for_temp` shortens a destination's basename before it goes
into the temp filename `.<base>.<random>.tmp`, so a name already close to
NAME_MAX doesn't push the temp name over the 255-byte limit. Its comment states
the rule plainly — "Budget is in BYTES (NAME_MAX is a byte limit)" — and that
sentence is true. The code underneath it counted `base.encode("utf-8")`, which
is a *different* set of bytes from the ones NAME_MAX limits.

The two counts agree for every name that is valid UTF-8, which is why this sat
here unnoticed. They disagree for the rest by raising. On POSIX, Python decodes
path bytes — and `sys.argv` — with the `surrogateescape` handler, so a byte
that isn't valid UTF-8 arrives as a lone surrogate in the U+DC80–U+DCFF range,
and strict UTF-8 encoding refuses to encode it. `--output $'report\xff.html'`
was enough: the cap raised `UnicodeEncodeError` before it ever got as far as
asking how long the name was.

What made this worth fixing rather than shrugging at is the exception *class*.
On the CI and Action runner (ext4, which accepts any non-NUL byte in a
filename) the write would have gone through fine. On macOS it fails either way,
but a plain `Path.write_text` of that target raises `OSError [Errno 92]
Illegal byte sequence` — which is what every write seam in this package is
written to catch. `drift --output` catches `OSError` only, so it turned into a
raw traceback at exit 1 and broke the documented `0 = clean / 1 = findings /
2 = I/O or usage error` contract. `cli._write_output` *did* catch it, through
the `UnicodeEncodeError` arm added in #217 — and then told the operator their
rendered output wasn't encodable as UTF-8, sending them to look at their
dataset over a byte in the filename they had typed. A correct catch with the
wrong diagnosis is worse than no catch.

The fix is one line: measure with `os.fsencode`, the filesystem encoding
together with its own error handler, which is exactly what the kernel receives
and what NAME_MAX counts. It returns the identical number for every valid-UTF-8
name, so no name that worked before changes budget, and it never raises —
`surrogateescape` on POSIX, `surrogatepass` on Windows.

`cli._write_output`'s docstring says "`atomic_write_text` raises exactly two
things". That enumeration counts *causes*, and both of its arms are about
content. The cap had quietly added a third cause wearing the second arm's
class. Fixing the measurement makes the enumeration true again, which is better
than adding a third arm — and I deliberately did not widen `drift.cli` to catch
`UnicodeEncodeError`, because once the measurement is right I can't drive that
path: `render_html` doesn't interpolate the input paths (checked), and
`compute_drift` rejects unencodable content at the door (#215). An arm I can't
make fire is an unfalsifiable guard.

**Testing was harder than the fix, for one reason:** ext4 and APFS give
different, both-correct answers. Asserting the write succeeds is a Linux-only
test; asserting it fails is a macOS-only test. The property that holds on both
is "if it fails, it fails as an `OSError`" — assert the class, not the outcome.
The pure-function half of the coverage is a variant table over the real
population: short and long, crossed with pure-ASCII, multibyte, surrogate-
bearing and mixed. Each row asserts the capped name is a character-boundary
prefix, within budget, and *maximal* — that last one exists because a cap
returning the empty string for everything satisfies the first two.

Reverting the single measurement line turns 9 of the 15 new assertions red and
leaves the 6 encodable-name controls green.

**Why this work, this session:** picked by counting open issues per module —
`io_utils.py` had 4 mentions across the whole issue history against 40–60 for
`cli`, `judge` and `drift`. The least-discussed module is the one nobody has
read.

**Open questions / blockers:** none.

**Next session:** the identical `_cap_base_for_temp` body is in eight sibling
repos (`llm-cost-optimizer`, `rag-production-kit`, `chunking-strategies-lab`,
`prompt-regression-suite`, `embedding-model-shootout`, `vector-search-at-scale`,
`python-async-llm-pipelines`, and `mcp-server-cookbook`'s `filesystem-sandbox-py`).
Each needs its own issue: the fix is the same one line, but the write-seam
callers and the exit-code consequence differ per repo.

## 2026-09-03 — #228: `suite` was the one field the delta parser never type-checked

`DeltaReport.from_json` reads a delta-JSON artifact — the thing
`diff-json --format json` writes and the CI Action feeds back to
`eval-harness comment`. Its contract is deliberately two-sided: permissive
about *presence* (its docstring says "no required fields at the top level —
every field has a documented default") and strict about *type*, because the
renderers downstream are not defensive and `cli._run_comment` calls them
**outside** its exit-2 `try`.

Every field it reads is validated. `threshold_drop` must be a finite number.
`summary` must be an object; `mean_delta` finite; the six `n_*` counts
int-coercible. `rows` must be an array; each row an object; each
`example_id` a non-empty string; each `status` a string; each score finite.
`current_run_id` and `baseline_run_id` must be strings. That is eleven checks
accumulated over #42, #89, #116, #120, #150, #160 and #190 — and `suite`, the
twelfth field, had none at all.

So `{"suite": null}` in a delta artifact reached
`md_code_span(report.suite)` and died with
`AttributeError: 'NoneType' object has no attribute 'replace'` — not a
`ValueError`, not a `KeyError`, so nothing in `_run_comment` caught it, and the
CLI exited 1 with a traceback instead of the documented exit 2.

**The guard that describes this bug already exists, one level down.** The
`status` check inside `RowDelta.from_json` explains itself like this: `status`
is "a free-form string that lands in two renderers", and a non-string "would
raise a raw AttributeError (`md_table_cell(...).replace`) ... at exit 1,
breaking the exit-2 contract the comment path honors". Every clause is true of
`suite` one level up — it is free-form, operator-chosen, and it lands in
`comment.render_delta_markdown` and in `runner.render_delta_ascii`.

The two renderers fail *differently*, which is why the guard belongs at the
parse boundary and not in either of them. `md_code_span` calls `.replace` on
the value, so markdown crashes loudly. `render_delta_ascii` interpolates with a
plain `{}`, so it does not crash at all — it prints
`# delta aaaaaaaa vs bbbbbbbb (suite=None, threshold_drop=0.05)`, a header
stating the suite is literally named `None`. Both are public API. A fix in
`comment.py` would have closed the visible half and made the invisible half
permanent.

I built and ran the two plausible wrong fixes before settling. Coercing with
`str(...)` stops the traceback and exits 0 with a heading reading `None` —
it passes any test that only asserts "does not crash". Rejecting `None`
specifically stops that one case and lets `3`, `1.5`, `True`, `["a"]` and
`{"a": 1}` through. Asserting the exit *code*, over a variant table that
includes those five, is what separates the real fix from both. `True` is in
the table on purpose: `bool` is an `int` subclass and looks string-ish to a
sloppy guard, but `isinstance(True, str)` is False and the renderers break on
it exactly like `None` does.

The last test in the new file discovers `DeltaReport`'s `str`-annotated fields
from the dataclass instead of listing them, because hand-listing is precisely
how `suite` was missed: the run-id guard enumerated two of the three
`.get`-with-default string fields and read like a survey of all of them. It
carries a floor assertion — at least three fields found, `suite` among them —
because a discovery helper that matches nothing collects zero parametrized
cases and passes silently.

**Next session:** the remaining open issues here (#220, #212, #177) are a
contract decision, a `priority:low` enhancement, and a doc question needing
JT's intended breakdown.

## 2026-09-04 — Issue #230: `RowDelta.flagged` accepted any JSON value
**Branch:** `session/2026-09-04-0709-issue-230` · **PR:** #232

`RowDelta.from_json` read `flagged` with a bare `payload.get("flagged", False)`
and no type check — the last field on the row shape without one, and the
row-level sibling of the `suite` gap closed last session in #228.

What made it the last one left is that it fails differently from its
neighbours. A non-string `example_id` or `status` crashes a renderer, so it
announces itself as a traceback. `flagged` is read only by *truthiness* — in
the markdown table cell, in the ascii row, and in `regressed_ids` — so a
non-bool is read successfully, as the wrong answer, at exit 0. Before writing
any code I reproduced it: a delta artifact whose row carries `"flagged":
"false"` (the shape a shell-templated CI step produces, since every JSON string
is truthy) posts a `:warning:` on an `unchanged` row underneath a summary line
reading `flagged 0 · regressed 0 · unchanged 1`. The two halves of one PR
comment contradict each other, and the unvalidated half is the one a reviewer
sees.

The issue named one direction; there are two. A truthy non-bool invents a flag;
a falsy one — `0`, `""`, `[]`, or a present explicit `null` — suppresses a real
one. Both are now rejected as the `ValueError` the comment path translates to a
clean exit 2.

The fix is one `isinstance(bool)` check, and the work was in ruling out three
neighbours that all look right. `bool(payload.get(...))` makes the field's type
correct and fixes nothing, because `bool("false")` is `True` — it launders the
issue's own reproducer into a flag. `isinstance(v, int)` reads as correct
precisely because `isinstance(True, int)` is `True` in Python, so it passes for
every legitimate value while still accepting a raw `1`/`0` the writer can never
emit. And rejecting only `str` closes the issue's title exactly while leaving
`1`, `[0]` and `{"x": 1}` inventing flags. All three are built and run in the
test file; the separating inputs are `1` and `0`.

Honest severity, since the issue asked: the CLI's non-zero exit is *not*
affected — it gates on `summary["n_flagged"]`, which `_require_int` already
validates. This was silently-wrong output plus a phantom id in the public
`regressed_ids` property, not a wrong gate. I enumerated that property's
consumers rather than assuming.

A portfolio-wide grep for the same pattern came back with exactly one hit: the
line fixed here.
