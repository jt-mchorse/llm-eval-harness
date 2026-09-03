# Code-review eval

A second application of `llm-eval-harness`, in a different domain from the
tokensmith design-token eval. Same harness, same dataset contract, same judge
machinery — new golden set, new question.

**Question:** does an explicit review protocol reduce *false positives* on clean
pull requests, without costing recall on real defects?

## Headline

**The intervention bought precision with recall — and the LLM judge reported it
as a perfect score.**

Treatment arm, scored deterministically from the required `VERDICT:` line, no
judge involved:

```
clean rows    11/11 correct     0 false positives     FP rate 0.000
defect rows    8/12 caught      4 MISSED              recall  0.667
                                                      overall 0.826

LLM judge reported:  1.000  (perfect, all 23 rows)
```

Two results, and the second matters more.

**The substantive one.** Telling the reviewer *"reporting no defect is a valid and
expected outcome, do not manufacture a concern"* drove invented defects to exactly
zero — which is what it was for — and also made the model miss one real defect in
three. That is the precision/recall trade a CI review bot lives on, and it is now
a number rather than an intuition.

**The methodological one.** On four defect rows the reviewer wrote
`VERDICT: NO DEFECT` in plain text and the judge scored each 1.0, reasoning
*"correctly identifies that the change introduces no runtime defect."* The judge
was grading whether a response was well-argued, not whether it reached the
labeled outcome. A judge that returns a perfect score for an arm failing a third
of its cases is not a measurement instrument.

Reproduce the real number with `python code_review_eval/score_deterministic.py`.

### What this is not

**Not an arm-vs-arm result.** The control arm has no verdict contract, so it
cannot be scored deterministically, and its judged numbers come from the same
unreliable judge. The honest claim is *here is what the treatment prompt does* —
not *treatment beats control*.

## The dataset

`fixtures/code_review_v1.jsonl` — 23 rows, `dataset_version: code-review-v1`,
mined from the real commit history of `psf/requests`.

| | rows | construction | correct outcome |
|---|---|---|---|
| defect | 12 | upstream bug-fix commit, **diff reversed** | name the specific runtime failure |
| clean | 11 | documentation-only commit, applied forward | report no defect, invent nothing |

Reversing a fix is what makes the labels checkable. The project already decided
that code was wrong and shipped the fix; the reversal reintroduces exactly that
defect, and the cited SHA lets anyone audit the label. No synthetic bugs, no
hand-authored ground truth.

## Four things this build got wrong first

All four are recorded because they are the interesting part.

**1. The dataset leaked the treatment into the control.** The first row builder
wrapped every diff in an instruction ending *"If the change is safe, say so
explicitly and do not invent issues."* That sentence **is** the treatment arm's
intervention. Shipped as written, both arms receive it, the experiment measures
nothing, and it still produces a confident-looking delta. Rows now carry the diff
and nothing else; task framing belongs to the arm.

**2. Mining cannot produce a golden set on its own.** Two passes over
`psf/requests` both emitted mislabeled rows — a comment typo reversed into "a
defect", a `setattr` rewrite whose reversal is functionally identical. The miner
emits *candidates*; `accepted.txt` is the dataset boundary and it is a human
artifact. Full accept/reject record in `VERIFICATION.md`.

**3. Sampling and context defaults silently corrupted the scores.** Both local
models default to `temperature 1`, so the same review scored differently on
repeated runs. Ollama defaults `num_ctx` to 4096 regardless of the 131k/262k the
models support, and truncation drops the *front* of the prompt — where the rubric
lives. Fixing both moved the control arm from 0.688 to 0.848 and cut detectable
judge errors substantially. Neither default announces itself.

**4. Interleaving two models thrashed the machine.** The harness calls
reviewer then judge per row. Ollama keeps one model resident, so it reloaded
17.7 GB between every call — **157 model loads**, which was nearly all of the
wall-clock. Generating every review first and judging them all second costs
**two** model loads and cut a multi-hour run to ~50 minutes.

## Running it

```bash
# build the dataset
python code_review_eval/mine_corpus.py --repo /path/to/requests --slug psf/requests \
    --out /tmp/cr_candidates.jsonl --defects 40 --clean 12 --scan 6494
python code_review_eval/curate.py --candidates /tmp/cr_candidates.jsonl \
    --accept code_review_eval/accepted.txt --out fixtures/code_review_v1.jsonl

# run both arms
python code_review_eval/run_eval.py --dry-run                  # prompts only
python code_review_eval/run_eval.py --provider ollama \
    --model qwen3.8:27b --judge-provider ollama --judge-model gemma3:12b

# the number to actually trust
python code_review_eval/score_deterministic.py
```

Reviews are cached to `answers_<provider>_<model>.json` after the generation
phase, so a failure in judging does not cost the expensive half.

### Providers

`--provider` selects the backend. The harness defines `Backend.complete()` and
`AnswerSource.answer()` as single-method protocols, so a provider is an adapter
in `providers.py`, not a fork of the runner.

| `--provider` | model | endpoint |
|---|---|---|
| `anthropic` | `claude-opus-5` | Anthropic SDK |
| `zai` | `glm-4.6` | z.ai, OpenAI-compatible |
| `ollama` | `qwen3.8:27b` | local Ollama, **native `/api/chat`** |

Ollama deliberately bypasses the OpenAI-compatible endpoint: that layer has no
way to express `num_ctx`, and inheriting the 4096 default is the exact bug
above. Reviewer and judge are selected independently (`--judge-model`); if they
resolve to the same model the runner warns, because a model grading its own
output inflates scores in a direction this design cannot measure.

### Cost, in wall-clock

Local inference is not free in time. Measured on an M5 (32 GB) with
`qwen3.8:27b` reviewing and `gemma3:12b` judging: **~50 minutes** for 23 rows
across both arms, at roughly 54s per review. A fanless chassis throttles under
sustained load, so later calls run slower than earlier ones.

## Calibration

Not yet performed, and it is the gap that let a broken judge produce a headline.
The harness gates on Cohen's κ ≥ 0.6 against a calibration set; this dataset does
not have one, so `judge_kappa` is `None` on both runs. A calibration set would
have caught the failure before any number was reported.

Dataset labels are also single-labeler. That is the honest ceiling on what 23
rows from one repository can tell you.

## What would make this stronger

1. **A calibration set and the κ gate.** The judge should be measured, not
   trusted. This is the highest-value next step.
2. **A verdict contract on the control arm too** — as a third arm rather than a
   replacement, so the comparison becomes deterministic on both sides.
3. **A stronger judge**, tested only after the first two, since the first is free
   and the second tells you whether any judge is trustworthy here.
4. **More repositories.** `psf/requests` has one house style; a reviewer tuned on
   it may not transfer.
