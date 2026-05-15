"""`eval-harness` CLI entry point.

Subcommands shipped here:
- `judge calibrate` — runs the judge over `fixtures/calibration.jsonl` and writes
  `docs/calibration_report.md`. Exits non-zero if Cohen's κ < threshold.

Other subcommands (`run`, `list`) land with their own issues (#3, #7).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eval_harness.calibration import calibrate, load_calibration, render_report
from eval_harness.judge import AnthropicBackend, Judge


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eval-harness", description="Reusable LLM eval framework."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    judge_p = sub.add_parser("judge", help="Judge-related subcommands.")
    judge_sub = judge_p.add_subparsers(dest="judge_command", required=True)

    calibrate_p = judge_sub.add_parser(
        "calibrate", help="Run the judge over the calibration set and write the report."
    )
    calibrate_p.add_argument(
        "--calibration", default="fixtures/calibration.jsonl", help="Path to calibration JSONL."
    )
    calibrate_p.add_argument(
        "--report", default="docs/calibration_report.md", help="Where to write the report."
    )
    calibrate_p.add_argument(
        "--model",
        default=None,
        help="Override judge model (else EVAL_HARNESS_JUDGE_MODEL or default).",
    )
    calibrate_p.add_argument(
        "--threshold-kappa",
        type=float,
        default=0.6,
        help="Minimum Cohen's κ; exits non-zero below this.",
    )

    args = parser.parse_args(argv)
    if args.command == "judge" and args.judge_command == "calibrate":
        return _run_calibrate(args)

    parser.error(f"unknown command {args.command!r}")
    return 2  # unreachable


def _run_calibrate(args: argparse.Namespace) -> int:
    rows = load_calibration(args.calibration)
    backend = AnthropicBackend(model=args.model)
    judge = Judge(backend=backend)
    result = calibrate(judge, rows)

    report = render_report(result, judge_model=backend.model, threshold_kappa=args.threshold_kappa)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(report, encoding="utf-8")

    print(
        f"calibration: n={result.n} kappa={result.cohens_kappa:.3f} pearson_r={result.pearson_r:.3f}"
    )
    print(f"report written to {args.report}")

    if result.cohens_kappa < args.threshold_kappa:
        print(
            f"::error::Cohen's κ {result.cohens_kappa:.3f} < threshold {args.threshold_kappa}; "
            "judge is no longer calibrated to the human-labeled set",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
