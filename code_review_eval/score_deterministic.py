"""Score the treatment arm without the LLM judge.

The treatment prompt requires a `VERDICT: DEFECT` / `VERDICT: NO DEFECT` line, so
its output is machine-checkable against the row label. No judgment call, no
model, no rubric interpretation - just a regex and the ground truth.

This exists because the judge was wrong. On the 2026-09-03 run it returned a
perfect 1.000 for an arm that missed a third of the defects, scoring responses
that said "VERDICT: NO DEFECT" on defect rows as correct. Wherever a deterministic
check is available, it beats an LLM judge, and it is the thing to reach for first
when a score looks too good.

    python code_review_eval/score_deterministic.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASET = HERE.parent / "fixtures" / "code_review_v1.jsonl"
VERDICT_RE = re.compile(r"VERDICT:\s*(NO DEFECT|DEFECT)", re.IGNORECASE)


def verdict(text: str) -> str | None:
    """Last verdict wins - models sometimes restate it after a summary."""
    found = VERDICT_RE.findall(text or "")
    return found[-1].upper() if found else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", type=Path,
                    default=HERE / "answers_ollama_qwen3.8_27b.json")
    ap.add_argument("--arm", default="treatment")
    a = ap.parse_args()

    if not a.answers.exists():
        print(f"no cached answers at {a.answers}", file=sys.stderr)
        return 1

    rows = {json.loads(l)["id"]: json.loads(l)
            for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()}
    label = {k: ("defect" if "defect" in v["tags"] else "clean") for k, v in rows.items()}
    answers = json.loads(a.answers.read_text(encoding="utf-8"))[a.arm]

    tp = fn = tn = fp = unparsed = 0
    missed, false_alarms = [], []
    for rid, text in answers.items():
        v = verdict(text)
        if v is None:
            unparsed += 1
            continue
        said_defect = v == "DEFECT"
        if label[rid] == "defect":
            if said_defect:
                tp += 1
            else:
                fn += 1
                missed.append(rid)
        else:
            if said_defect:
                fp += 1
                false_alarms.append(rid)
            else:
                tn += 1

    total = tp + fn + tn + fp
    print(f"arm: {a.arm}   rows scored: {total}   unparsed verdicts: {unparsed}")
    print(f"  defect rows: {tp} caught / {fn} missed   recall  {tp / (tp + fn):.3f}")
    print(f"  clean rows : {tn} correct / {fp} false   FP rate {fp / (tn + fp):.3f}")
    print(f"  overall accuracy: {(tp + tn) / total:.3f}")
    if missed:
        print(f"  missed defects: {sorted(missed)}")
    if false_alarms:
        print(f"  false positives: {sorted(false_alarms)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
