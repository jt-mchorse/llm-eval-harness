# Code-review eval

A second application of `llm-eval-harness`, in a different domain from the
tokensmith design-token eval. Same harness, same dataset contract, same judge
machinery — new golden set, new question.

**Question:** does an explicit review protocol reduce *false positives* on clean
pull requests, without costing recall on real defects?

Recall is the easy half. A reviewer that flags a genuine off-by-one is table
stakes. The number that decides whether a review bot survives contact with CI is
what it does on the 80% of PRs that are fine — because a reviewer that
manufactures a concern on a documentation commit gets muted within a week.

## The dataset

`fixtures/code_review_v1.jsonl` — 24 rows, `dataset_version: code-review-v1`,
mined from the real commit history of `psf/requests`.

| | rows | construction | correct outcome |
|---|---|---|---|
| defect | 12 | upstream bug-fix commit, **diff reversed** | name the specific runtime failure |
| clean | 12 | documentation-only commit, applied forward | report no defect, invent nothing |

Reversing a fix is what makes the labels checkable. The project already decided
that code was wrong and shipped the fix; the reversal reintroduces exactly that
defect, and the cited SHA lets anyone audit the label. No synthetic bugs, no
hand-authored ground truth.

Every row carries provenance: repo, commit SHA, upstream subject, the file under
review, the construction method, and the basis for the label.

## Two things the build got wrong first

Both are recorded because they are the interesting part.

**1. The dataset leaked the treatment into the control.**
The first version of the row builder wrapped every diff in an instruction that
ended *"If the change is safe, say so explicitly and do not invent issues."*
That sentence **is** the treatment arm's intervention. Shipped as written, both
arms would have received it and the experiment would have measured nothing while
producing a confident-looking delta. Rows now carry the diff and nothing else;
task framing belongs to the arm.

**2. Mining cannot produce a golden set on its own.**
Two passes over `psf/requests` both emitted mislabeled rows — a comment typo
reversed into "a defect", a `setattr` rewrite whose reversal is functionally
identical. The miner now emits *candidates*; `accepted.txt` is the dataset
boundary and it is a human artifact. Full accept/reject record with reasons is
in `VERIFICATION.md`.

## Running it

```bash
python code_review_eval/mine_corpus.py --repo /path/to/requests --slug psf/requests \
    --out /tmp/cr_candidates.jsonl --defects 40 --clean 12 --scan 6494
python code_review_eval/select.py --candidates /tmp/cr_candidates.jsonl \
    --accept code_review_eval/accepted.txt --out fixtures/code_review_v1.jsonl

python code_review_eval/run_eval.py --dry-run     # prompts only, no API calls
python code_review_eval/run_eval.py --limit 4     # smoke test
python code_review_eval/run_eval.py               # full: 48 reviewer + 48 judge calls
```

Both arms call the API for real — nothing is replayed. The runner detects whether
the installed `anthropic` SDK supports server-side refusal fallbacks and includes
them only when available, so it runs against 0.x and 1.x alike.

## Status: built, not yet run

The dataset is complete and verified. The runner passes `--dry-run` and executes
end to end up to the API boundary. **It has not produced results yet** — the
smoke test failed with:

```
400 invalid_request_error: Your credit balance is too low to access the Anthropic API.
```

There are no numbers in this README because the eval has not been run. Numbers go
here after `run_eval.py` completes, alongside the per-arm false-positive counts
and any rows where the judge and the label disagree.

## Calibration

Not yet performed. The harness gates on Cohen's κ ≥ 0.6 against a calibration
set, and this dataset does not have one yet. Until it does, judge scores here are
uncalibrated and should be read as directional.

The dataset labels are also single-labeler: one person read each diff and decided.
That is the same limitation the harness discloses for its own calibration set, and
it is the honest ceiling on what 24 rows from one repository can tell you.

## What would make this stronger

- A calibration set + κ gate, so the judge is measured rather than trusted.
- A second labeler on the defect rows, to put a number on the label noise.
- More repositories. `psf/requests` has one house style; a reviewer tuned on it
  may not transfer.
- A third arm with the repository's own tests in context, to separate "reads the
  diff" from "reasons about behavior".
