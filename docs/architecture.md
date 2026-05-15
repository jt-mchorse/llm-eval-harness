# Architecture

Three layers, each its own module under `eval_harness/`:

```
eval_harness/
├── dataset.py         ← #1 (shipped): JSONL goldens with version pinning
├── judge.py           ← #2 (shipped): LLM-as-judge with pluggable Backend
├── calibration.py     ← #2 (shipped): κ + Pearson against human labels
├── cli.py             ← `eval-harness judge calibrate` (extends with #3, #7)
└── __init__.py        ← public surface
```

Tests in `tests/`; goldens and calibration in `fixtures/`; reports in `docs/`.

## Layer 1 — Dataset (#1)

`Dataset` and `Example` dataclasses with strict load/dump semantics. Each
example carries `expected_outputs`, a list of typed `{kind, value}` objects
(D-002) so the judge wrapper, the regression runner, and the eventual PR
diff comment can all interpret a single dataset format. `dataset_version`
is opaque metadata (D-003) — the loader enforces internal consistency
(every line must have the same `dataset_version`) but doesn't impose
semver or any specific scheme.

The dataset layer has **zero runtime dependencies** so it can be imported
in environments without an Anthropic API key, in CI sandboxes, and inside
other portfolio repos that consume the harness as a library.

## Layer 2 — Judge (#2 · this PR)

```mermaid
flowchart LR
  CALLER[caller] --> JUDGE
  JUDGE[Judge.score] --> BACKEND
  BACKEND{Backend Protocol}
  BACKEND -- production --> ANTHROPIC[AnthropicBackend<br/>messages.create]
  BACKEND -- tests --> STUB[StubBackend<br/>deterministic dict lookup]
  ANTHROPIC --> PARSE[parse_judge_output]
  STUB --> PARSE
  PARSE --> SCORE[JudgeScore<br/>{score, reasoning, raw}]
```

The Judge is a thin wrapper: it formats a system+user prompt around the
caller's `(prompt, response, rubric)`, hands the pair to a single-method
`Backend`, and parses the response using a strict `SCORE: ...\nREASONING: ...`
format. Score is clamped to [0, 1].

The Backend Protocol is the load-bearing seam (D-004). Production uses
`AnthropicBackend`; tests use a deterministic stub. New providers
implement one method and plug straight in.

## Layer 3 — Calibration (#2 · this PR)

```mermaid
flowchart TD
  CAL[(fixtures/calibration.jsonl<br/>50 human-labeled rows)] --> LOADER[load_calibration]
  LOADER --> ROWS[CalibrationRow list]
  ROWS --> CALIBRATE[calibrate(judge, rows)]
  JUDGE[Judge<br/>+ AnthropicBackend or stub] --> CALIBRATE
  CALIBRATE --> KAPPA[Cohen's κ binarized]
  CALIBRATE --> R[Pearson r continuous]
  CALIBRATE --> RESULT[CalibrationResult]
  RESULT --> RENDER[render_report]
  RENDER --> REPORT[docs/calibration_report.md]
  RESULT --> GATE{κ ≥ 0.6?}
  GATE -- no --> FAIL[CLI exit 1]
  GATE -- yes --> PASS[CLI exit 0]
```

Two metrics, one threshold. Cohen's κ on binarized scores (threshold 0.5)
gates CI (D-005). Pearson r on continuous scores is reported alongside
because κ alone hides systematic over/under-scoring biases that don't
flip the binary verdict.

The math (`cohens_kappa`, `pearson_r`) is hand-written against textbook
formulas — small enough to live in this repo without scipy, tested
against textbook examples (κ = 0.4 on a 25/20/5/10/15 contingency,
r ≈ 0.7745967 on the standard `[1..5]` vs `[2,4,5,4,5]` example).

## What's deliberately not in the harness

- **Live model traffic in tests.** Backend is a Protocol; tests stub it.
- **A web UI.** Per handoff §2, "CLI + CI is enough." Future PR
  comments + report markdown are the user surface.
- **Multi-rater calibration sets.** Honestly disclosed as future
  work; the current set is self-labeled (D-006).
- **Replacing `prompt-regression-suite`.** That repo does
  snapshot-style testing; this one does dataset-style scoring. See
  the cross-repo MEMORY for the boundary.

## Pending downstream (open issues)

- **#3** — Regression runner with per-model diffing. SQLite-backed run
  history; consumes `Dataset` + `Judge`, both shipped here.
- **#4** — Drift detection on production traffic samples.
- **#5** — Pytest plugin so evals run as tests (`pytest --eval-suite=...`).
- **#6** — GitHub Action: post eval deltas on every PR via a sticky comment.
- **#7** — CLI: `eval-harness run/list` (extending the `judge calibrate`
  scaffolding shipped here).
