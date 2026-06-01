"""`eval-harness` CLI entry point.

Public subcommands (issue #7 contract — `run / list / calibrate / diff`):
- `run` — score a dataset, persist the run, optionally diff against a baseline.
  Exits non-zero when any row regresses beyond `--threshold-drop`.
- `list` — show the most-recent N runs from the SQLite history. `--suite`
  filters, `--json` switches to machine output.
- `calibrate` — run the judge over `fixtures/calibration.jsonl` and write
  `docs/calibration_report.md`. Exits non-zero if Cohen's κ < threshold.
  `judge calibrate` remains as a hidden nested alias for backwards compat.
- `diff` — show the delta between two stored runs (SQLite-backed history).

Plus two consumer-workflow subcommands:
- `diff-json` — diff two `RunResult` JSON files without SQLite (D-010). Used
  by CI workflows where the action runner is ephemeral.
- `comment` — render a delta JSON as markdown and upsert it as a sticky
  comment on a PR (D-009).
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
from eval_harness.dataset import validate_dataset
from eval_harness.io_utils import atomic_write_text
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
from eval_harness.runs import RunSummary, connect, init_db_on, list_runs, read_run

DEFAULT_DB_PATH = Path.home() / ".eval-harness" / "runs.db"


def main(argv: list[str] | None = None) -> int:
    # `judge calibrate ...` is a backwards-compat alias for `calibrate ...`.
    # Rewrite the argv before argparse sees it so the alias resolves to the
    # canonical subcommand without registering a visible `judge` subparser
    # (which would clutter `eval-harness --help` and contradict the issue
    # #7 contract of `run / list / calibrate / diff` as the public surface).
    # Older scripts that already invoke `eval-harness judge calibrate ...`
    # keep working unchanged.
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) >= 2 and argv[0] == "judge" and argv[1] == "calibrate":
        argv = ["calibrate", *argv[2:]]

    parser = argparse.ArgumentParser(
        prog="eval-harness", description="Reusable LLM eval framework."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Top-level `calibrate` — equivalent to `judge calibrate`. The judge-
    # nested form stays as a hidden alias for backwards compat with scripts
    # that already invoke it. Issue #7 asks for `run/list/calibrate/diff`
    # as the public surface; this brings the CLI tree in line.
    calibrate_p = sub.add_parser(
        "calibrate", help="Run the judge over the calibration set and write the report."
    )
    _add_calibrate_args(calibrate_p)

    # List recent runs from the SQLite history (#7).
    list_p = sub.add_parser("list", help="Show the most recent runs from the SQLite history.")
    list_p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite path for run history.")
    list_p.add_argument(
        "--limit", type=int, default=20, help="Maximum number of runs to show (default 20)."
    )
    list_p.add_argument("--suite", default=None, help="Filter by suite name (default: all suites).")
    list_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit a JSON array instead of the human-readable text table.",
    )
    list_p.add_argument(
        "--out",
        default=None,
        help=(
            "Write the rendered output to this path instead of stdout. Parent dirs "
            "are auto-created. Parity with `run --out`, `diff --out`, `diff-json --out`."
        ),
    )

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
    run_p.add_argument(
        "--tags",
        default=None,
        help=(
            "Comma-separated tag filter (any-of / set-union semantics). "
            "Example: `--tags geography,history`. Default: score every row."
        ),
    )

    diff_p = sub.add_parser("diff", help="Show the delta between two stored runs.")
    diff_p.add_argument("--current", required=True)
    diff_p.add_argument("--baseline", required=True)
    diff_p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    diff_p.add_argument("--threshold-drop", type=float, default=DEFAULT_THRESHOLD_DROP)
    diff_p.add_argument("--format", choices=["ascii", "json", "markdown"], default="ascii")
    diff_p.add_argument(
        "--out", default=None, help="Write the rendered delta to this path (otherwise stdout)."
    )

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

    # `validate` lints a JSONL golden dataset without spending judge
    # tokens (#56). Collects every malformed row in one pass rather than
    # failing on the first like load_jsonl does.
    validate_p = sub.add_parser(
        "validate", help="Lint a JSONL golden dataset; report every malformed row in one pass."
    )
    validate_p.add_argument("dataset", help="Path to a JSONL dataset.")
    validate_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the report as JSON instead of the human-readable summary.",
    )

    # `drift` measures distribution drift between a golden set and a
    # candidate sample of production inputs (#4).
    drift_p = sub.add_parser(
        "drift",
        help="Measure distribution drift on length / embedding / judge axes; write an HTML report.",
    )
    drift_p.add_argument("--golden", required=True, help="Path to golden JSONL of inputs.")
    drift_p.add_argument("--candidate", required=True, help="Path to candidate JSONL of inputs.")
    drift_p.add_argument("--output", required=True, help="Output HTML report path.")
    drift_p.add_argument(
        "--judge-stub",
        action="store_true",
        help="Use the deterministic word-count judge stub (hermetic CI / smoke).",
    )
    drift_p.add_argument(
        "--cluster-k", type=int, default=8, help="K-means cluster count (default: 8)."
    )

    args = parser.parse_args(argv)
    if args.command == "judge" and args.judge_command == "calibrate":
        return _run_calibrate(args)
    if args.command == "calibrate":
        return _run_calibrate(args)
    if args.command == "run":
        return _run_run(args)
    if args.command == "list":
        return _run_list(args)
    if args.command == "diff":
        return _run_diff(args)
    if args.command == "diff-json":
        return _run_diff_json(args)
    if args.command == "comment":
        return _run_comment(args)
    if args.command == "drift":
        return _run_drift(args)
    if args.command == "validate":
        return _run_validate(args)
    parser.error(f"unknown command {args.command!r}")
    return 2  # unreachable


def _run_drift(args: argparse.Namespace) -> int:
    """Delegate to the drift module's CLI implementation."""
    from eval_harness.drift import cli as drift_cli

    drift_argv = [
        "--golden",
        args.golden,
        "--candidate",
        args.candidate,
        "--output",
        args.output,
        "--cluster-k",
        str(args.cluster_k),
    ]
    if args.judge_stub:
        drift_argv.append("--judge-stub")
    return drift_cli(drift_argv)


def _add_calibrate_args(parser: argparse.ArgumentParser) -> None:
    """Shared `--calibration / --report / --model / --threshold-kappa` set.

    Used by both `judge calibrate` (legacy nested form) and the top-level
    `calibrate` subcommand (#7) so the two surfaces stay in sync.
    """
    parser.add_argument("--calibration", default="fixtures/calibration.jsonl")
    parser.add_argument("--report", default="docs/calibration_report.md")
    parser.add_argument("--model", default=None)
    parser.add_argument("--threshold-kappa", type=float, default=0.6)


def _run_calibrate(args: argparse.Namespace) -> int:
    rows = load_calibration(args.calibration)
    backend = AnthropicBackend(model=args.model)
    judge = Judge(backend=backend)
    result = calibrate(judge, rows)

    report = render_report(result, judge_model=backend.model, threshold_kappa=args.threshold_kappa)
    atomic_write_text(args.report, report)

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


def _parse_tags_arg(raw: str | None) -> tuple[str, ...]:
    """Parse `--tags a,b,c` into a tuple. Whitespace tolerated; empty tokens dropped.

    Returns `()` when the flag is absent or only whitespace/commas — the runner
    treats `()` as "no filter", which is the default behavior.
    """
    if raw is None:
        return ()
    parts = [t.strip() for t in raw.split(",")]
    return tuple(t for t in parts if t)


def _run_run(args: argparse.Namespace) -> int:
    from eval_harness.runner import EmptyTagFilterError

    backend = AnthropicBackend(model=args.model)
    judge = Judge(backend=backend)
    spec = RunSpec(
        suite=args.suite,
        dataset_path=args.dataset,
        judge=judge,
        answer_source=_make_answer_source(args.answer_source),
        judge_model=backend.model,
        tags=_parse_tags_arg(args.tags),
    )
    try:
        result = run_suite(spec, db_path=args.db)
    except EmptyTagFilterError as e:
        # Silent-empty-run is the worst failure mode; surface the requested
        # tags and the dataset's tag inventory so the operator can self-correct.
        print(
            f"::error::--tags {list(e.requested)} matched zero rows in "
            f"{e.dataset_path}. Available tags: {e.inventory}",
            file=sys.stderr,
        )
        return 2
    json_text = render_run_json(result)
    if args.out:
        atomic_write_text(args.out, json_text)
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
        rendered = json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n"
    elif args.format == "markdown":
        rendered = render_delta_markdown(report)
    else:
        rendered = render_delta_ascii(report) + "\n"
    if args.out:
        atomic_write_text(args.out, rendered)
    else:
        print(rendered, end="")
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
        atomic_write_text(args.out, rendered)
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


def _run_list(args: argparse.Namespace) -> int:
    """List recent runs from the SQLite history.

    Default output is a fixed-width text table sized to the longest
    run_id present; ``--json`` emits a JSON array instead. An empty DB
    is not an error — emits "no runs" (text) or "[]" (json) and exits 0.

    ``--out PATH`` writes the rendered output to a file (parent dirs
    auto-created) and prints nothing to stdout — parity with ``run``,
    ``diff``, ``diff-json``.
    """
    db_path = Path(args.db)
    if not db_path.exists():
        # No DB on disk yet — equivalent to no runs. Don't auto-create
        # here (init_db is what `run` does); avoid the side effect.
        rendered = "[]\n" if args.as_json else f"# no runs (no database at {db_path})\n"
        _emit_list_output(rendered, args.out)
        return 0

    with connect(db_path) as conn:
        init_db_on(conn)  # idempotent; safe even if the file already has the schema
        runs = list_runs(conn, limit=args.limit, suite=args.suite)

    if args.as_json:
        rendered = json.dumps([_run_summary_to_json(r) for r in runs], indent=2) + "\n"
        _emit_list_output(rendered, args.out)
        return 0

    if not runs:
        if args.suite is not None:
            rendered = f"# no runs for suite {args.suite!r}\n"
        else:
            rendered = "# no runs\n"
        _emit_list_output(rendered, args.out)
        return 0

    _emit_list_output(_render_runs_table(runs) + "\n", args.out)
    return 0


def _emit_list_output(rendered: str, out: str | None) -> None:
    """Write a `list`-rendered string to ``out`` (with mkdir -p) or stdout.

    Mirrors the sink-decision shape of ``_run_diff`` / ``_run_diff_json``
    so all four subcommands route output identically. ``--out`` is silent
    on stdout; stdout-only mode prints without the trailing newline since
    the renderer already adds one.
    """
    if out:
        atomic_write_text(out, rendered)
    else:
        print(rendered, end="")


def _run_summary_to_json(r: RunSummary) -> dict[str, object]:
    return {
        "run_id": r.run_id,
        "started_at": r.started_at,
        "suite": r.suite,
        "dataset_version": r.dataset_version,
        "judge_model": r.judge_model,
        "judge_kappa": r.judge_kappa,
        "mean_score": r.mean_score,
        "n_rows": r.n_rows,
        "git_sha": r.git_sha,
    }


def _render_runs_table(runs: list[RunSummary]) -> str:
    """Fixed-width text table for `eval-harness list` default output.

    Columns: started_at, run_id (truncated to 12), suite, mean_score,
    n_rows, judge_model. Widths sized from the widest cell so the table
    fits whatever the actual history looks like.
    """
    rows = [
        [
            r.started_at,
            (r.run_id[:12] + ("…" if len(r.run_id) > 12 else "")),
            r.suite,
            f"{r.mean_score:.3f}",
            str(r.n_rows),
            r.judge_model or "-",
        ]
        for r in runs
    ]
    header = ["started_at", "run_id", "suite", "mean", "rows", "judge_model"]
    widths = [
        max(len(header[i]), max((len(row[i]) for row in rows), default=0))
        for i in range(len(header))
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*header)]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append(fmt.format(*row))
    return "\n".join(lines)


def _run_validate(args: argparse.Namespace) -> int:
    """Lint a JSONL golden dataset; exit 0 clean / 1 findings / 2 I/O error.

    The exit-code shape matches ``scripts/audit_phase_a.py`` in
    portfolio-ops so consumers can chain validators uniformly. The
    human-readable summary prints one line per finding followed by a
    one-line totals row; ``--json`` emits the full ``ValidationReport``
    dict for machine consumption.
    """
    try:
        report = validate_dataset(args.dataset)
    except FileNotFoundError as e:
        print(f"::error::dataset not found: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"::error::failed to read dataset {args.dataset}: {e}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        for finding in report.findings:
            line_label = f"line {finding.line_no}" if finding.line_no else "file"
            print(f"{line_label} [{finding.code}]: {finding.reason}", file=sys.stderr)
        status = "ok" if report.ok else "fail"
        version = report.dataset_version or "(no valid rows)"
        print(
            f"{status}: {args.dataset} rows={report.n_rows} valid={report.n_valid} "
            f"findings={len(report.findings)} version={version}"
        )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())


# Re-export the sticky marker for tests that want to assert on it
# without importing the inner `comment` module path.
__all__ = ["main", "STICKY_MARKER"]
