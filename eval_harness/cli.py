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

from eval_harness.calibration import (
    calibrate,
    load_calibration,
    render_report,
    validate_calibration,
)
from eval_harness.comment import (
    STICKY_MARKER,
    render_delta_markdown,
    upsert_sticky_comment,
)
from eval_harness.dataset import DatasetLoadError, load_jsonl, validate_dataset
from eval_harness.io_utils import atomic_write_text
from eval_harness.judge import AnthropicBackend, Judge
from eval_harness.runner import (
    DEFAULT_THRESHOLD_DROP,
    DatasetEchoSource,
    DeltaReport,
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


def _fail(message: str) -> int:
    """Print a clean ``::error::`` line to stderr and return exit code 2.

    The read-side subcommands (``list`` / ``diff`` / ``diff-json`` /
    ``comment``) sit on top of the SQLite history, the run-JSON loader, and
    the delta loader — all of which raise data-layer exceptions
    (``ValueError`` / ``KeyError`` / ``FileNotFoundError`` / ``JSONDecodeError``)
    on bad input. Letting those escape as a raw traceback is a poor operator
    experience and breaks the CLI's ``0 = clean / 1 = findings|regression /
    2 = I/O or usage error`` exit contract — the same contract ``validate``
    (missing-file → 2) and ``run`` (``EmptyTagFilterError`` → 2) already honor.
    Translate them here so every subcommand fails uniformly (#104).
    """
    print(f"::error::{message}", file=sys.stderr)
    return 2


def _write_output(path: str, rendered: str) -> int | None:
    """Write ``rendered`` to ``path`` atomically, translating an ``OSError``
    to the clean ``::error::`` + exit-2 contract. Returns ``2`` on failure and
    ``None`` on success so callers can ``if (rc := _write_output(...)) is not
    None: return rc``.

    This is the write-seam sibling of ``_fail`` / #104: the read seams already
    translate I/O errors to exit 2, but every ``--out`` write site
    (``calibrate`` / ``run`` / ``diff`` / ``diff-json`` / ``list`` /
    ``validate``) called ``atomic_write_text`` bare, so an unwritable ``--out``
    (a directory, a read-only path, an unwritable parent) escaped as a raw
    ``OSError`` traceback at exit 1 — a poor operator experience that breaks the
    documented ``2 = I/O or usage error`` contract exactly as #104 describes.
    """
    try:
        atomic_write_text(path, rendered)
    except OSError as e:
        return _fail(f"failed to write {path}: {e}")
    return None


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
    # tokens (#56). `--calibration` routes to the calibration-schema
    # validator (#58) — same ValidationReport shape so JSON consumers and
    # CI exit codes are uniform across kinds.
    validate_p = sub.add_parser(
        "validate",
        help="Lint a JSONL golden dataset (or --calibration set); report every malformed row in one pass.",
    )
    validate_p.add_argument("dataset", help="Path to a JSONL dataset.")
    validate_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the report as JSON instead of the human-readable summary.",
    )
    validate_p.add_argument(
        "--calibration",
        action="store_true",
        help="Treat the file as a calibration JSONL (human_score/prompt/response/rubric schema).",
    )
    validate_p.add_argument(
        "--out",
        default=None,
        help=(
            "Write the rendered output to this path instead of stdout. Parent dirs "
            "are auto-created. Parity with `run --out`, `list --out`, `diff --out`, "
            "`diff-json --out`. Findings still print to stderr in human-readable mode "
            "even when --out is set, so the operator's diagnostic channel is preserved."
        ),
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
    # The `judge calibrate` legacy alias is normalized to `calibrate` by the
    # argv-rewrite at the top of main(), so `args.command` is never "judge"
    # (no `judge` subparser is registered under dest="command"). The dispatch
    # falls through to the canonical `calibrate` branch below — see #105.
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
    # `load_calibration` runs before the judge backend is constructed, and it
    # raises on bad input: FileNotFoundError/OSError (missing/unreadable file)
    # and CalibrationLoadError (a ValueError subclass — blank line, malformed
    # JSON, duplicate id, schema violation). Left untranslated those escaped as
    # a raw traceback at exit 1, breaking the `0 = clean / 1 = findings /
    # 2 = I/O or usage error` contract the sibling subcommands honor — calibrate
    # was the last subcommand left out of the #104/#110/#116/#122/#124 sweep.
    # Map them to exit 2 here. Note exit 1 is reserved for the legitimate
    # "Cohen's κ < threshold" findings outcome below, so a load/usage failure
    # must be 2, not 1. Scope is the load seam only, mirroring `_run_validate`.
    try:
        rows = load_calibration(args.calibration)
    except (FileNotFoundError, OSError) as e:
        return _fail(f"calibration not found: {e}")
    except ValueError as e:
        return _fail(str(e))
    # Empty-but-valid file (#128): load_calibration returns [] cleanly, so the
    # catch above does not fire. Downstream, `calibrate(judge, [])` raises
    # ValueError("no rows to calibrate against") (exit 1, raw traceback), and in
    # a minimal install AnthropicBackend(...) raises ImportError first — both
    # break the `2 = usage error` contract. Treat a zero-row set as a usage
    # error here, before the backend is built, so it stays hermetic (no `judge`
    # extra / API key needed) and reports exit 2 with a clean ::error:: line.
    if not rows:
        return _fail(f"no rows to calibrate against in {args.calibration}")
    backend = AnthropicBackend(model=args.model)
    judge = Judge(backend=backend)
    result = calibrate(judge, rows)

    report = render_report(result, judge_model=backend.model, threshold_kappa=args.threshold_kappa)
    if (rc := _write_output(args.report, report)) is not None:
        return rc

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

    # Validate the operator-supplied --dataset BEFORE constructing the judge
    # backend, so a missing/unreadable/malformed dataset reports exit 2
    # hermetically — matching the `validate` sibling and the `0 = clean /
    # 1 = findings / 2 = I/O or usage error` contract `_fail` documents. `run`
    # was the one input seam the #104/#110/#116/#122/#124 exit-code sweep left
    # with only the EmptyTagFilterError guard, so a bad dataset escaped as a raw
    # traceback at exit 1. Order matters: AnthropicBackend imports `anthropic`
    # at construction, so building it first would mask the dataset error with an
    # ImportError in a minimal (no `judge` extra) install — hence the
    # load-before-backend ordering `_run_calibrate` also uses. `load_jsonl` is
    # the same loader `run_suite` uses downstream (runner._load).
    try:
        list(load_jsonl(args.dataset))
    except FileNotFoundError as e:
        return _fail(f"dataset not found: {e}")
    except OSError as e:
        return _fail(f"failed to read dataset {args.dataset}: {e}")
    except UnicodeDecodeError as e:
        # load_jsonl decodes lazily while iterating the file handle, outside the
        # per-row json.loads try. A non-UTF-8 byte raises UnicodeDecodeError (a
        # ValueError subclass, NOT an OSError and NOT a DatasetLoadError), which
        # the catches here miss — so it escaped as a raw traceback at exit 1.
        return _fail(f"failed to read dataset {args.dataset}: not valid UTF-8: {e}")
    except DatasetLoadError as e:
        return _fail(str(e))

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
        if (rc := _write_output(args.out, json_text)) is not None:
            return rc
    else:
        print(json_text)

    print(
        f"run {result.run_id} suite={result.suite} n={result.n_rows} mean={result.mean_score:.3f}",
        file=sys.stderr,
    )

    if args.no_diff:
        return 0
    try:
        with connect(args.db) as conn:
            init_db_on(conn)
            baseline = load_baseline(conn, args.suite, args.baseline, exclude_run_id=result.run_id)
            if baseline is None:
                return 0
            current_stored = read_run(conn, result.run_id)
            report = diff_runs(current_stored, baseline, threshold_drop=args.threshold_drop)
    except KeyError as e:
        # An explicit --baseline that doesn't exist routes through load_baseline
        # -> read_run, which raises KeyError("no run with id 'x'"). The sibling
        # `diff` already translates this to exit 2; `run` must honor the same
        # contract instead of leaking a traceback — the KeyError half of the
        # #110 exit-code fix on this path. read_run's message is already specific.
        return _fail(e.args[0] if e.args else str(e))
    except ValueError as e:
        # An invalid --threshold-drop (negative/NaN/Inf) is a usage error, not a
        # crash: diff_runs is the single-source validator and `_run_diff` /
        # `_run_diff_json` already translate its ValueError to exit 2 via _fail.
        # `run` must honor the same contract instead of leaking a traceback (#110).
        return _fail(str(e))
    print(render_delta_ascii(report), file=sys.stderr)
    return 1 if report.summary["n_flagged"] > 0 else 0


def _run_diff(args: argparse.Namespace) -> int:
    try:
        with connect(args.db) as conn:
            init_db_on(conn)
            # `read_run` raises KeyError on an unknown run id; `diff_runs` raises
            # ValueError on a cross-suite diff or a non-finite/negative threshold.
            current = read_run(conn, args.current)
            baseline = read_run(conn, args.baseline)
            report = diff_runs(current, baseline, threshold_drop=args.threshold_drop)
    except KeyError as e:
        # read_run's KeyError message is already specific ("no run with id 'x'").
        return _fail(e.args[0] if e.args else str(e))
    except ValueError as e:
        return _fail(str(e))
    if args.format == "json":
        rendered = json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n"
    elif args.format == "markdown":
        rendered = render_delta_markdown(report)
    else:
        rendered = render_delta_ascii(report) + "\n"
    if args.out:
        if (rc := _write_output(args.out, rendered)) is not None:
            return rc
    else:
        print(rendered, end="")
    return 1 if report.summary["n_flagged"] > 0 else 0


def _run_diff_json(args: argparse.Namespace) -> int:
    try:
        # load_run_result_from_json: FileNotFoundError/OSError (missing/unreadable
        # file), json.JSONDecodeError (malformed JSON), ValueError (corrupt
        # payload — non-finite score, n_rows mismatch, missing mean_score),
        # KeyError (missing required per-row field). diff_runs: ValueError
        # (cross-suite / bad threshold).
        current = load_run_result_from_json(args.current)
        baseline = load_run_result_from_json(args.baseline)
        report = diff_runs(current, baseline, threshold_drop=args.threshold_drop)
    except (FileNotFoundError, OSError) as e:
        return _fail(f"could not read run JSON: {e}")
    except json.JSONDecodeError as e:
        return _fail(f"invalid run JSON: {e}")
    except KeyError as e:
        return _fail(f"run JSON missing required field: {e.args[0] if e.args else e}")
    except ValueError as e:
        return _fail(str(e))
    if args.format == "json":
        rendered = json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n"
    elif args.format == "markdown":
        rendered = render_delta_markdown(report)
    else:
        rendered = render_delta_ascii(report)
    if args.out:
        if (rc := _write_output(args.out, rendered)) is not None:
            return rc
    else:
        print(rendered, end="")
    return 1 if report.summary["n_flagged"] > 0 else 0


def _run_comment(args: argparse.Namespace) -> int:
    # The delta JSON written by `diff-json --format json` is the
    # DeltaReport.to_json() shape; DeltaReport.from_json (#68) is the
    # inverse — same defaulting semantics the prior SimpleNamespace
    # shim used, now expressed on the dataclass itself so the renderer
    # gets a properly-typed instance.
    try:
        # read_text: FileNotFoundError/OSError; json.loads: JSONDecodeError;
        # DeltaReport.from_json: ValueError (non-finite threshold/mean_delta) and
        # KeyError (per-row example_id/status missing).
        raw = Path(args.delta_json).read_text(encoding="utf-8")
        payload = json.loads(raw)
        report = DeltaReport.from_json(payload)
    except (FileNotFoundError, OSError) as e:
        return _fail(f"could not read delta JSON: {e}")
    except json.JSONDecodeError as e:
        return _fail(f"invalid delta JSON: {e}")
    except KeyError as e:
        return _fail(f"delta JSON missing required field: {e.args[0] if e.args else e}")
    except ValueError as e:
        return _fail(str(e))
    body = render_delta_markdown(report)
    if args.dry_run:
        print(body, end="")
        return 0
    try:
        comment_id = upsert_sticky_comment(args.repo, args.pr, body)
    except RuntimeError as e:
        # A missing GITHUB_TOKEN/GH_TOKEN (_resolve_token) and a GitHub API
        # HTTP error (_do_request) both raise RuntimeError — pure usage / I-O
        # failures, not crashes. This call sits outside the delta-load try above,
        # so the RuntimeError otherwise escaped as a raw traceback at exit 1,
        # breaking the `0 = clean / 1 = findings / 2 = I/O or usage error`
        # contract that the read-side subcommands already honor (#104/#110/#116/
        # #122). Translate it here, same as the delta-load catch (#124).
        return _fail(str(e))
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
        if (rc := _emit_list_output(rendered, args.out)) is not None:
            return rc
        return 0

    try:
        with connect(db_path) as conn:
            init_db_on(conn)  # idempotent; safe even if the file already has the schema
            # list_runs raises ValueError on a non-positive / non-int --limit.
            runs = list_runs(conn, limit=args.limit, suite=args.suite)
    except ValueError as e:
        return _fail(str(e))

    if args.as_json:
        rendered = json.dumps([_run_summary_to_json(r) for r in runs], indent=2) + "\n"
        if (rc := _emit_list_output(rendered, args.out)) is not None:
            return rc
        return 0

    if not runs:
        if args.suite is not None:
            rendered = f"# no runs for suite {args.suite!r}\n"
        else:
            rendered = "# no runs\n"
        if (rc := _emit_list_output(rendered, args.out)) is not None:
            return rc
        return 0

    if (rc := _emit_list_output(_render_runs_table(runs) + "\n", args.out)) is not None:
        return rc
    return 0


def _emit_list_output(rendered: str, out: str | None) -> int | None:
    """Write a `list`-rendered string to ``out`` (with mkdir -p) or stdout.

    Mirrors the sink-decision shape of ``_run_diff`` / ``_run_diff_json``
    so all four subcommands route output identically. ``--out`` is silent
    on stdout; stdout-only mode prints without the trailing newline since
    the renderer already adds one. Returns the exit-2 code from
    ``_write_output`` if the write fails, else ``None``.
    """
    if out:
        return _write_output(out, rendered)
    print(rendered, end="")
    return None


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
    """Lint a JSONL golden (or --calibration) dataset; exit 0 clean / 1 findings / 2 I/O error.

    The exit-code shape matches ``scripts/audit_phase_a.py`` in
    portfolio-ops so consumers can chain validators uniformly. The
    human-readable summary prints one line per finding followed by a
    one-line totals row; ``--json`` emits the full ``ValidationReport``
    dict for machine consumption. ``--calibration`` swaps the validator
    to ``validate_calibration`` so the calibration-side schema is the
    one being checked.
    """
    validator = validate_calibration if args.calibration else validate_dataset
    kind = "calibration" if args.calibration else "dataset"
    try:
        report = validator(args.dataset)
    except FileNotFoundError as e:
        print(f"::error::{kind} not found: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"::error::failed to read {kind} {args.dataset}: {e}", file=sys.stderr)
        return 2
    except UnicodeDecodeError as e:
        # The validators decode lazily while iterating the file handle, outside
        # the per-row json.loads try. A non-UTF-8 byte raises UnicodeDecodeError
        # (a ValueError subclass, NOT an OSError), which the narrow catches above
        # miss — so it escaped as a raw traceback at exit 1, breaking the
        # documented "0 clean / 1 findings / 2 I/O error" contract. A whole-file
        # decode failure is an I/O error (exit 2), not a per-row finding.
        print(
            f"::error::failed to read {kind} {args.dataset}: not valid UTF-8: {e}", file=sys.stderr
        )
        return 2

    if args.as_json:
        rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    else:
        # Findings go to stderr regardless of --out so the operator's diagnostic
        # channel is preserved even when stdout is captured to a file. Same shape
        # as `list / diff / diff-json` --out behavior.
        for finding in report.findings:
            line_label = f"line {finding.line_no}" if finding.line_no else "file"
            print(f"{line_label} [{finding.code}]: {finding.reason}", file=sys.stderr)
        status = "ok" if report.ok else "fail"
        # Calibration has no `dataset_version`; show kind instead so the
        # totals row stays informative without the "(no valid rows)" noise.
        version = (
            "calibration" if args.calibration else (report.dataset_version or "(no valid rows)")
        )
        rendered = (
            f"{status}: {args.dataset} rows={report.n_rows} valid={report.n_valid} "
            f"findings={len(report.findings)} version={version}\n"
        )
    if args.out:
        if (rc := _write_output(args.out, rendered)) is not None:
            return rc
    else:
        print(rendered, end="")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())


# Re-export the sticky marker for tests that want to assert on it
# without importing the inner `comment` module path.
__all__ = ["main", "STICKY_MARKER"]
