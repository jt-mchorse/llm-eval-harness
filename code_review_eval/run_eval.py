"""Two-arm eval: does an explicit review protocol cut false positives on clean PRs?

Arms over the same golden set (fixtures/code_review_v1.jsonl):

  control    - the reviewer is handed the diff and asked to find defects.
  treatment  - same diff, plus a protocol that (a) requires a verdict line and
               (b) states explicitly that reporting no defect is a valid,
               expected outcome on a clean change.

The interesting number is NOT recall on the defect rows. Both arms find the
obvious ones. It is the false-positive rate on the 12 clean rows, because a
reviewer that invents issues on documentation commits is the one that gets
switched off in CI.

Unlike the tokensmith eval, both arms here call the API for real - nothing is
replayed. Every run costs money; see --limit and --dry-run.

Usage:
    export ANTHROPIC_API_KEY=...
    python code_review_eval/run_eval.py --dry-run          # prompts only, no calls
    python code_review_eval/run_eval.py --limit 4          # smoke test
    python code_review_eval/run_eval.py                    # full 24-row, both arms
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval_harness import (  # noqa: E402
    Judge,
    RunSpec,
    diff_runs,
    read_run,
    render_delta_ascii,
    run_suite,
)
from eval_harness.dataset import Example  # noqa: E402

HERE = Path(__file__).resolve().parent
DATASET = HERE.parent / "fixtures" / "code_review_v1.jsonl"
DB = HERE / "runs.sqlite3"

MODEL = "claude-opus-5"
# Server-side refusal fallbacks: on a safety refusal the request is rerouted by
# category instead of returning unusable content mid-suite. Recommended default
# for Opus 5, but the parameter only exists on newer SDKs - detect rather than
# require, so this repo runs against whatever anthropic version is installed.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
_SUPPORTS_FALLBACKS = "fallbacks" in inspect.signature(
    anthropic.Anthropic(api_key="probe").beta.messages.create
).parameters


def _extra_kwargs() -> dict:
    if _SUPPORTS_FALLBACKS:
        return {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    return {}

CONTROL_SYSTEM = "You are reviewing a pull request diff."

TREATMENT_SYSTEM = """You are reviewing a pull request diff.

Protocol:
1. Read the diff and decide whether it introduces a defect that would cause
   incorrect behavior at runtime.
2. Reporting no defect is a valid and expected outcome. Many changes are
   correct. Do not manufacture a concern to appear thorough. Style, naming,
   and documentation wording are NOT runtime defects.
3. End with exactly one verdict line:
       VERDICT: DEFECT - <one sentence naming the specific failure>
   or
       VERDICT: NO DEFECT
"""

RUBRIC = (
    "The PROMPT contains a pull-request diff. The EXPECTED describes the correct "
    "review outcome. Score the RESPONSE on whether it reaches that outcome.\n"
    "1.0 - the response reaches the correct outcome. For a defect row that means "
    "naming the specific runtime failure described in EXPECTED. For a clean row "
    "it means stating no runtime defect and not inventing one.\n"
    "0.0 - the response reaches the wrong outcome: it misses the defect, or it "
    "reports a defect on a clean change.\n"
    "~0.5 - the response gestures at the right area but does not name the actual "
    "failure, or hedges without committing to a verdict.\n"
    "Style, tone, and verbosity are irrelevant. Judge only the outcome."
)


class ClaudeBackend:
    """Backend protocol for the harness Judge: complete(system, user) -> str."""

    def __init__(self, client: anthropic.Anthropic, model: str = MODEL) -> None:
        self._client = client
        self._model = model

    def complete(self, system: str, user: str) -> str:
        msg = self._client.beta.messages.create(
            model=self._model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            **_extra_kwargs(),
        )
        if msg.stop_reason == "refusal":
            # Surface rather than swallow - a refused judge call is not a 0.0.
            raise RuntimeError(f"judge refused: {getattr(msg, 'stop_details', None)}")
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


class ReviewerSource:
    """AnswerSource protocol for the harness runner: answer(example) -> str."""

    def __init__(self, client: anthropic.Anthropic, system: str, model: str = MODEL) -> None:
        self._client = client
        self._system = system
        self._model = model

    def answer(self, example: Example) -> str:
        msg = self._client.beta.messages.create(
            model=self._model,
            max_tokens=16000,
            system=self._system,
            messages=[{"role": "user", "content": example.input}],
            **_extra_kwargs(),
        )
        if msg.stop_reason == "refusal":
            return "REFUSED"
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def load_rows(limit: int | None) -> list[dict]:
    rows = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]
    if limit:
        # Keep the arms balanced when smoke-testing.
        d = [r for r in rows if "defect" in r["tags"]][: max(1, limit // 2)]
        c = [r for r in rows if "clean" in r["tags"]][: max(1, limit // 2)]
        return d + c
    return rows


def write_subset(rows: list[dict], path: Path) -> Path:
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="run only N rows (balanced)")
    ap.add_argument("--dry-run", action="store_true", help="print prompts, make no API calls")
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()

    rows = load_rows(a.limit)
    n_def = sum(1 for r in rows if "defect" in r["tags"])
    n_cln = len(rows) - n_def
    print(f"dataset: {len(rows)} rows ({n_def} defect / {n_cln} clean)  model={a.model}")

    if a.dry_run:
        print(f"\n--- CONTROL SYSTEM ---\n{CONTROL_SYSTEM}")
        print(f"\n--- TREATMENT SYSTEM ---\n{TREATMENT_SYSTEM}")
        print(f"\n--- SAMPLE USER TURN ({rows[0]['id']}) ---\n{rows[0]['input'][:600]}")
        print(f"\nwould issue {len(rows) * 2} reviewer calls + {len(rows) * 2} judge calls")
        return 0

    dataset_path = DATASET
    if a.limit:
        dataset_path = write_subset(rows, HERE / "_subset.jsonl")

    client = anthropic.Anthropic()
    judge = Judge(ClaudeBackend(client, a.model))

    results = {}
    for arm, system in (("control", CONTROL_SYSTEM), ("treatment", TREATMENT_SYSTEM)):
        spec = RunSpec(
            suite=f"code-review-{arm}",
            dataset_path=dataset_path,
            judge=judge,
            answer_source=ReviewerSource(client, system, a.model),
            judge_model=a.model,
            rubric=RUBRIC,
        )
        print(f"\nrunning arm: {arm} ...")
        results[arm] = run_suite(spec, db_path=DB)
        print(f"  {arm}: {results[arm]}")

    delta = diff_runs(
        read_run(DB, results["control"].run_id),
        read_run(DB, results["treatment"].run_id),
    )
    print("\n" + render_delta_ascii(delta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
