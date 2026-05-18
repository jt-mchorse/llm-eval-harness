"""Three-axis drift on a synthetic golden vs. shifted input pair.

Demonstrates `compute_drift` end-to-end with a deterministic `judge_score_fn`
stub so all three axes (length / embedding cluster / judge) populate. Writes
the single-file HTML report to a tempfile and prints the path plus the JSD
score per axis.

The synthetic shift: the golden corpus is short geography questions; the
candidate corpus mixes in longer cooking questions, which shifts the length
distribution, the embedding-cluster distribution, and (because the judge stub
weights longer inputs lower) the judge-score distribution.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from eval_harness import compute_drift, render_drift_html

GOLDEN_INPUTS = [
    "What is the capital of France?",
    "Which planet is closest to the Sun?",
    "What is the chemical symbol for gold?",
    "Who painted the Mona Lisa?",
    "In what year did the Berlin Wall fall?",
    "What is the largest ocean on Earth?",
    "Which gas makes up most of the atmosphere?",
    "What is the tallest mountain on Earth?",
]

CANDIDATE_INPUTS = [
    "What is the capital of France?",
    "Walk me through making a roux for a classic gumbo, including ratios and timing.",
    "If I substitute Greek yogurt for sour cream in a coffee cake recipe, what happens?",
    "Explain how the Maillard reaction differs from caramelization in pan-seared steak.",
    "What is a 12-step French croissant lamination schedule with chilling intervals?",
    "Which planet is closest to the Sun?",
    "Describe a long, slow-braised short-rib recipe with red wine and aromatics in detail.",
    "Compare wet versus dry brining for a Thanksgiving turkey across moisture and skin texture.",
]


def length_weighted_judge(text: str) -> float:
    """Deterministic judge stub: shorter inputs score higher.

    Score = clamp(1.0 - len(text)/200, 0.0, 1.0). The point is to give the
    judge axis a real signal that diverges from the golden distribution; no
    semantic claim is being made here.
    """
    return max(0.0, min(1.0, 1.0 - len(text) / 200.0))


def main() -> int:
    """Compute drift and write an HTML report to a tempfile. Exit 0 on success."""
    report = compute_drift(
        golden_inputs=GOLDEN_INPUTS,
        candidate_inputs=CANDIDATE_INPUTS,
        judge_score_fn=length_weighted_judge,
        cluster_k=4,  # tiny corpus, keep k modest so the cluster axis is meaningful
    )

    print(f"[example] golden inputs: {report.n_golden}; candidate inputs: {report.n_candidate}")
    print(
        f"[example] length axis    JSD={report.length.drift_score:.3f}  status={report.length.status}"
    )
    print(
        f"[example] embedding axis JSD={report.embedding.drift_score:.3f}  status={report.embedding.status}"
    )
    if report.judge is not None:
        print(
            f"[example] judge axis     JSD={report.judge.drift_score:.3f}  status={report.judge.status}"
        )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", prefix="eval-harness-drift-", delete=False
    ) as fh:
        fh.write(render_drift_html(report))
        html_path = Path(fh.name)
    print(f"[example] HTML report written to: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
