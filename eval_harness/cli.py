"""`eval-harness` CLI entry point.

Subcommands:
- `judge calibrate` — runs the judge over `fixtures/calibration.jsonl` and writes
  `docs/calibration_report.md`. Exits non-zero if Cohen's κ < threshold.
- `run` — score a dataset, persist the run, optionally diff against a baseline.
  Exits non-zero when any row regresses beyond `--threshold-drop`.
- `diff` — show the delta between two stored runs (SQLite-backed history).
- `diff-json` — diff two `RunResult` JSON files without SQLite (D-010). Used
  by CI workflows where the action runner is ephemeral.
- `comment` — render a delta JSON as markdown and upsert it as a sticky
  comment on a PR (D-009).

Other subcommands (`list`, drift) land with their own issues.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval_harness.calibration import calibrate, load_calibration, render_report
from eval_harness.comment import (
    STICKY_MARKER,
    render_delta_markdown,
    upsert_sticky_comment,
)
from eval_harness.judge import AnthropicBackend, Judge
from eval_harness.runner import (
    DEFAULT_THRESHOLD_DROP,
    DatasetEchoSource,
    RunSpec,
    diff_runs,
    load_baseline,
    load_run_result_from_json,
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

    # `diff-json` is SQLite-free: takes two RunResult JSON files (the format
    # `eval-harness run --out` writes) and emits a DeltaReport JSON, ascii
    # table, or markdown. Used by CI where the action runner is ephemeral.
    diff_json_p = sub.add_parser(
        "diff-json", help="Diff two RunResult JSON files; no SQLite needed."
    )
    diff_json_p.add_argument("--current", required=True, help="Path to current RunResult JSON.")
    diff_json_p.add_argument("--baseline", required=True, help="Path to baseline RunResult JSON.")
    diff_json_p.add_argument("--threshold-drop", type=float, default=DEFAULT_THRESHOLD_DROP)
    diff_json_p.add_argument("--format", choices=["ascii", "json", "markdown"], default="json")
    diff_json_p.add_argument(
        "--out", default=None, help="Write the rendered delta to this path (otherwise stdout)."
    )

    # `comment` upserts a sticky comment on a PR. `--delta-json` is the
    # output of `diff-json --format json`.
    comment_p = sub.add_parser("comment", help="Upsert a sticky PR comment from a delta JSON.")
    comment_p.add_argument("--repo", required=True, help='GitHub repo in "owner/name" form.')
    comment_p.add_argument("--pr", required=True, type=int, help="PR number to comment on.")
    comment_p.add_argument("--delta-json", required=True, help="Path to a DeltaReport JSON.")
    comment_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Render and print the markdown without calling the GitHub API.",
    )

    args = parser.parse_args(argv)
    if args.command == "judge" and args.judge_command == "calibrate":
        return _run_calibrate(args)
    if args.command == "run":
        return _run_run(args)
    if args.command == "diff":
        return _run_diff(args)
    if args.command == "diff-json":
        return _run_diff_json(args)
    if args.command == "comment":
        return _run_comment(args)
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


def _run_diff_json(args: argparse.Namespace) -> int:
    current = load_run_result_from_json(args.current)
    baseline = load_run_result_from_json(args.baseline)
    report = diff_runs(current, baseline, threshold_drop=args.threshold_drop)
    if args.format == "json":
        rendered = json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n"
    elif args.format == "markdown":
        rendered = render_delta_markdown(report)
    else:
        rendered = render_delta_ascii(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 1 if report.summary["n_flagged"] > 0 else 0


def _run_comment(args: argparse.Namespace) -> int:
    # The delta JSON written by `diff-json --format json` is the
    # DeltaReport.to_json() shape; reconstruct a minimal DeltaReport for
    # rendering. We don't need the full object — just the fields the
    # markdown renderer consults — so we accept a duck-typed shim.
    raw = Path(args.delta_json).read_text(encoding="utf-8")
    payload = json.loads(raw)
    # Build a minimal report-shaped object the markdown renderer will accept.
    from types import SimpleNamespace

    rows = [
        SimpleNamespace(
            example_id=r["example_id"],
            baseline_score=r.get("baseline_score"),
            current_score=r.get("current_score"),
            delta=r.get("delta"),
            status=r["status"],
            flagged=r.get("flagged", False),
        )
        for r in payload.get("rows", [])
    ]
    report_shim = SimpleNamespace(
        current_run_id=payload.get("current_run_id", "current"),
        baseline_run_id=payload.get("baseline_run_id", "baseline"),
        suite=payload.get("suite", "(unknown)"),
        threshold_drop=float(payload.get("threshold_drop", DEFAULT_THRESHOLD_DROP)),
        rows=tuple(rows),
        summary=payload.get("summary", {}),
    )
    body = render_delta_markdown(report_shim)  # type: ignore[arg-type]
    if args.dry_run:
        print(body, end="")
        return 0
    comment_id = upsert_sticky_comment(args.repo, args.pr, body)
    print(f"upserted sticky comment id={comment_id} on {args.repo}#{args.pr}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())


# Re-export the sticky marker for tests that want to assert on it
# without importing the inner `comment` module path.
__all__ = ["main", "STICKY_MARKER"]
