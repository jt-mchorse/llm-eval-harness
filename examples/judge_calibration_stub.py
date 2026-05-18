"""Calibration with a stub Judge backend (hermetic, no API key).

Demonstrates the pattern downstream repos use in CI: instantiate `Judge` with
a deterministic stub `Backend`, run `calibrate` against the committed
calibration fixture, print Cohen's κ + Pearson r.

In production, swap `StubFaithfulnessBackend()` for `AnthropicBackend()` (which
requires the `judge` extra and an `ANTHROPIC_API_KEY`); the rest of the wiring
stays identical.
"""

from __future__ import annotations

from pathlib import Path

from eval_harness import Judge, calibrate, load_calibration

REPO_ROOT = Path(__file__).resolve().parent.parent
CALIBRATION_FIXTURE = REPO_ROOT / "fixtures" / "calibration.jsonl"


class StubFaithfulnessBackend:
    """Approximates 'is the response a faithful answer to the prompt' without an LLM.

    The heuristic is intentionally crude: if the response contains a substantive
    word from the prompt (>= 4 chars, alphabetic), call it 0.85; otherwise 0.20.
    The point of this example isn't a good faithfulness signal — it's to show
    the `Backend` Protocol seam that lets calibrate() run hermetically.

    Note this is a stub for *demonstration*, not a real judge. Real judges live
    behind the `Backend` Protocol and are calibrated against humans (κ ≥ 0.6 is
    the CI gate per D-005); a 2-line heuristic will not pass that gate.
    """

    @staticmethod
    def _content_words(text: str) -> set[str]:
        return {w.lower() for w in text.split() if len(w) >= 4 and w.isalpha()}

    def complete(self, system: str, user: str) -> str:
        # The `user` block is "RUBRIC: ...\n\nPROMPT: ...\n\nRESPONSE: ...\n";
        # extract the prompt and response by header.
        prompt = self._extract_section(user, "PROMPT")
        response = self._extract_section(user, "RESPONSE")
        score = 0.85 if self._content_words(prompt) & self._content_words(response) else 0.20
        return f"SCORE: {score:.2f}\nREASONING: stub heuristic on shared content words\n"

    @staticmethod
    def _extract_section(text: str, header: str) -> str:
        for chunk in text.split("\n\n"):
            if chunk.startswith(f"{header}:"):
                return chunk[len(header) + 1 :].strip()
        return ""


def main() -> int:
    """Run the calibration end-to-end and print the numbers. Exit code 0 on success."""
    judge = Judge(backend=StubFaithfulnessBackend())
    rows = load_calibration(CALIBRATION_FIXTURE)
    result = calibrate(judge, rows)

    print(f"[example] calibration set: {result.n} rows from {CALIBRATION_FIXTURE.name}")
    print(f"[example] Cohen's κ (binarized): {result.cohens_kappa:.3f}")
    print(f"[example] Pearson r (continuous): {result.pearson_r:.3f}")
    print(
        "[example] this stub backend is a 2-line heuristic — real judges land "
        "through AnthropicBackend and are gated at κ ≥ 0.6 in CI (D-005)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
