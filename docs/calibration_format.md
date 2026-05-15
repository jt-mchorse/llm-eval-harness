# Calibration set format

The calibration set is the human-labeled ground truth the judge is measured
against. It lives at `fixtures/calibration.jsonl` (one JSON object per line)
and is loaded by `eval_harness.calibration.load_calibration`.

## Schema (v1)

```jsonc
{
  "id": "<unique str>",
  "prompt": "<str>",          // the original question
  "response": "<str>",        // the candidate answer being scored
  "rubric": "<str>",          // scoring instructions for the judge
  "human_score": <0.0..1.0>,  // the human label
  "provenance": {             // free-form, but every row needs one
    "added_on": "YYYY-MM-DD",
    "labeled_by": "<str>",
    "source": "<str>"
  }
}
```

Required fields are checked at load time; unknown top-level fields are
rejected so a typo (`scoring_rubric` vs `rubric`) doesn't silently skip
a row. Blank lines, duplicate ids, and `human_score` outside [0, 1] all
fail with a 1-indexed line number in the error message.

## What the committed 50 rows cover

The bundled `fixtures/calibration.jsonl` has **50 rows** designed to
exercise the judge across the score axis, not just clear positives:

| group              | rows | what it tests                                        |
|--------------------|------|------------------------------------------------------|
| Clear-positive     | 18   | Faithful, often terse answers (capitals, math, etc.) |
| Verbose-positive   |  3   | Faithful answers padded with extra context           |
| Partial credit     |  5   | Hedged or partially-correct answers                  |
| Clear-negative     |  8   | Wrong answers, including invented "facts"            |
| Honest refusal     |  3   | "I don't know" responses to unanswerable questions   |
| Off-topic          |  3   | Doesn't address the prompt, but doesn't invent       |
| Mostly-faithful    |  4   | Right answer with one minor added fact (true/false)  |
| Subtle errors      |  5   | Plausible-looking answers that are actually wrong    |
| Edge: empty        |  2   | Empty/whitespace-only response                       |

A judge that only handles clear positives and clear negatives would
score 78% accuracy on a balanced clear-only set but ~50% on this one,
because the partial-credit + subtle-error groups are the actual
calibration signal.

## Honest disclosure (D-006)

The set is **self-labeled by a single labeler** (jt-mchorse) on
`2026-05-15`. This is *not* a multi-rater gold standard:

- All scores reflect one person's judgment of "faithfulness".
- For ambiguous rows (especially partial-credit and refusal groups),
  reasonable labelers would disagree by ±0.1–0.2.
- The set is specifically *small* so that re-labeling on a new rubric
  is feasible — 50 rows takes about 30 minutes to relabel.

The κ ≥ 0.6 threshold is calibrated against this single-labeler set;
when a multi-rater set becomes available it should supersede this one
via a new D-NNN with a fresh κ baseline.

## Re-running the calibration

```bash
# Hermetic test of the math + loader + format (no API key needed):
pytest tests/test_calibration.py -v

# Real calibration run against Anthropic (writes docs/calibration_report.md):
ANTHROPIC_API_KEY=sk-... eval-harness judge calibrate

# CI gate: exit non-zero if Cohen's κ < 0.6
ANTHROPIC_API_KEY=sk-... eval-harness judge calibrate --threshold-kappa 0.6
```

The CLI writes the full per-row report to `docs/calibration_report.md` —
once the operator runs it for the first time, that report ships in a
follow-up commit and the regression gate becomes meaningful.
