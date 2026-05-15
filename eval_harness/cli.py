"""`eval-harness` CLI entry point.

Subcommands:
- `judge calibrate` — runs the judge over `fixtures/calibration.jsonl` and writes
  `docs/calibration_report.md`. Exits non-zero if Cohen's κ < threshold.
- `run` — score a dataset, persist the run, optionally diff against a baseline.
  Exits non-zero when any row regresses beyond `--threshold-drop`.
- `diff` — show the delta between two stored runs.

Other subcommands (`list`, drift) land with their own issues.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval_harness.calibration import calibrate, load_calibration, render_report
from eval_harness.judge import AnthropicBackend, Judge
from eval_harness.runner import (
    DEFAULT_THRESHOLD_DROP,
    DatasetEchoSource,
    RunSpec,
    diff_runs,
    load_baseline,
    render_delta_ascii,
    render_run_json,
    run_suite,
)
from eval_harness.runs import connect, init_db_on, read_run

DEFAULT_DB_PATH = Path.home() / ".eval-harness" / "runs.db"


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
    calibrate_p.add_argument("--calibration", default="fixtures/calibration.jsonl")
    calibrate_p.add_argument("--report", default="docs/calibration_report.md")
    calibrate_p.add_argument("--model", default=None)
    calibrate_p.add_argument("--threshold-kappa", type=float, default=0.6)

    run_p = sub.add_parser(
        "run", help="Score a dataset, persist the run, optionally diff a baseline."
    )
    run_p.add_argument("--suite", required=True, help="Suite name used to group runs.")
    run_p.add_argument("--dataset", required=True, help="Path to a JSONL dataset.")
    run_p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite path for run history.")
    run_p.add_argument("--model", default=None, help="Override the judge model id.")
    run_p.add_argument("--answer-source", choices=["dataset_echo"], default="dataset_echo")
    run_p.add_argument(
        "--baseline",
        default=None,
        help="Baseline run_id to diff against (default: latest run of the same suite).",
    )
    run_p.add_argument("--threshold-drop", type=float, default=DEFAULT_THRESHOLD_DROP)
    run_p.add_argument("--out", default=None, help="Write the JSON run result to this path.")
    run_p.add_argument(
        "--no-diff", action="store_true", help="Skip the baseline diff even if a prior run exists."
    )

    diff_p = sub.add_parser("diff", help="Show the delta between two stored runs.")
    diff_p.add_argument("--current", required=True)
    diff_p.add_argument("--baseline", required=True)
    diff_p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    diff_p.add_argument("--threshold-drop", type=float, default=DEFAULT_THRESHOLD_DROP)
    diff_p.add_argument("--format", choices=["ascii", "json"], default="ascii")

    args = parser.parse_args(argv)
    if args.command == "judge" and args.judge_command == "calibrate":
        return _run_calibrate(args)
    if args.command == "run":
        return _run_run(args)
    if args.command == "diff":
        return _run_diff(args)
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


def _make_answer_source(name: str):
    if name == "dataset_echo":
        return DatasetEchoSource()
    raise ValueError(f"unknown answer source: {name}")  # pragma: no cover - argparse rejects first


def _run_run(args: argparse.Namespace) -> int:
    backend = AnthropicBackend(model=args.model)
    judge = Judge(backend=backend)
    spec = RunSpec(
        suite=args.suite,
        dataset_path=args.dataset,
        judge=judge,
        answer_source=_make_answer_source(args.answer_source),
        judge_model=backend.model,
    )
    result = run_suite(spec, db_path=args.db)
    json_text = render_run_json(result)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json_text, encoding="utf-8")
    else:
        print(json_text)

    print(
        f"run {result.run_id} suite={result.suite} n={result.n_rows} mean={result.mean_score:.3f}",
        file=sys.stderr,
    )

    if args.no_diff:
        return 0
    with connect(args.db) as conn:
        init_db_on(conn)
        baseline = load_baseline(conn, args.suite, args.baseline, exclude_run_id=result.run_id)
        if baseline is None:
            return 0
        current_stored = read_run(conn, result.run_id)
        report = diff_runs(current_stored, baseline, threshold_drop=args.threshold_drop)
    print(render_delta_ascii(report), file=sys.stderr)
    return 1 if report.summary["n_flagged"] > 0 else 0


def _run_diff(args: argparse.Namespace) -> int:
    with connect(args.db) as conn:
        init_db_on(conn)
        current = read_run(conn, args.current)
        baseline = read_run(conn, args.baseline)
        report = diff_runs(current, baseline, threshold_drop=args.threshold_drop)
    if args.format == "json":
        print(json.dumps(report.to_json(), indent=2, sort_keys=True))
    else:
        print(render_delta_ascii(report))
    return 1 if report.summary["n_flagged"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
