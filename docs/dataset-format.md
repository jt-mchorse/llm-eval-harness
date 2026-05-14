# Golden-dataset JSONL format

> Stable contract for what an `eval-harness` golden dataset looks like on
> disk. Anything outside this spec is up to the dataset author; anything
> inside it the loader enforces.

## File shape

One example per line, one compact JSON object per line, UTF-8, single
trailing newline. Blank lines are rejected (they're almost always the
result of a broken pipeline, and silent skips would hide that).

The loader (`eval_harness.dataset.load_jsonl`) fails on the first malformed
line with a `DatasetLoadError` that carries the 1-indexed `line_no` and a
human-readable `reason`. Fix-and-rerun is the intended workflow.

## Required fields

| field             | type                       | notes                                                                                  |
|-------------------|----------------------------|----------------------------------------------------------------------------------------|
| `id`              | `str`, non-empty           | Unique within the file. Used by PR-comment eval diffs (issue #6) to reference rows.    |
| `input`           | `str`                      | The prompt/question/payload fed to the model.                                          |
| `expected_outputs`| `list[ExpectedOutput]`, ≥1 | At least one acceptable answer. Multiple entries are OR'd (any matching one passes).   |
| `dataset_version` | `str`, non-empty           | Free-form; the loader treats it as opaque metadata. Must be identical on every line.   |
| `provenance`      | `object`                   | Where the example came from. Free-form keys; honesty is the only rule.                 |

## Optional fields

| field   | type        | default | notes                                                                |
|---------|-------------|---------|----------------------------------------------------------------------|
| `tags`  | `list[str]` | `[]`    | Used by the regression runner (#3) to filter/group. Omitted on dump. |

Any **unknown** top-level field is rejected with `unknown top-level field(s)`
so that a typo (e.g. `expected_output` singular) doesn't silently no-op.

## `ExpectedOutput`

```jsonc
{ "kind": "exact" | "semantic" | "regex", "value": "<string>" }
```

| `kind`     | how the comparator interprets `value`                                            |
|------------|----------------------------------------------------------------------------------|
| `exact`    | Case-insensitive substring match, post-trim. For literal short answers.          |
| `semantic` | Judged by the LLM-as-judge wrapper (#2) for meaning equivalence against `value`. |
| `regex`    | `value` is a Python regex pattern; match anywhere in the model's output.         |

New kinds may be added in a minor harness version. Readers must reject
unknown kinds — eval semantics depend on the kind, and accepting an unknown
kind silently would skew pass rates.

## `dataset_version` semantics

The harness treats this as opaque, so dataset authors own the naming
convention. Two recommendations, no enforcement:

- Embed a domain in the name, e.g. `factuality-v0.1`, `customer-support-2026q2`.
- Bump the version on any change to inputs or expected outputs. The CI eval
  diff (#6) uses `dataset_version` as the join key, so changing the version
  on a stable dataset will register as a churn signal.

A single file must carry one version on every line. Mixed-version files are
rejected — split them into separate files.

## Example: a 3-line file

```jsonl
{"id":"qa_001","input":"What is the capital of France?","expected_outputs":[{"kind":"exact","value":"Paris"}],"dataset_version":"factuality-v0.1","provenance":{"source":"public_domain_trivia"}}
{"id":"qa_002","input":"How many sides does a hexagon have?","expected_outputs":[{"kind":"exact","value":"6"},{"kind":"exact","value":"six"}],"dataset_version":"factuality-v0.1","provenance":{"source":"public_domain_trivia"},"tags":["geometry"]}
{"id":"qa_003","input":"In what year did the Berlin Wall fall?","expected_outputs":[{"kind":"regex","value":"\\b1989\\b"}],"dataset_version":"factuality-v0.1","provenance":{"source":"public_domain_trivia"}}
```

See `fixtures/sample_factuality_v1.jsonl` for the 10-line reference dataset
that ships with the repo.

## Round-trip identity

`Dataset.dump_jsonl` emits canonical JSONL: keys sorted, no extra
whitespace, single trailing newline. So:

```
load → dump → re-load
```

is byte-stable for any well-formed input. The test suite enforces this so
that the format itself can't drift between releases without us noticing.
