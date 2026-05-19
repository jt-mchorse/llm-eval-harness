# Session History (human-readable)

Chronological log of work sessions. Most recent first below the divider.

---

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
