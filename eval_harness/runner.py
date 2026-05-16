"""Regression runner: score a suite, persist the run, diff against a baseline.

The runner sits on top of the existing dataset/judge/runs layers. It runs the
judge over every example in a dataset, persists the per-row + aggregate result
in SQLite, and can produce a delta against any prior run of the same suite.

Two seams keep the runner testable without API keys:

- `Backend` (existing in `judge.py`) is the judge model. Tests substitute a
  deterministic stub that returns canned SCORE/REASONING strings.
- `AnswerSource` (new here, see D-007) is the *model under test* — separate
  from the judge model so the runner can score one model's answers with
  another model's judge. The default `DatasetEchoSource` emits each
  example's `expected_outputs[0].value` so the full runner can be exercised
  hermetically; a real Anthropic-backed answer source lands when a
  consumer needs it.

Delta semantics:

- Per-example: `delta_score = current - baseline`. Rows in current but not
  baseline are tagged `new`; in baseline but not current are tagged
  `removed`.
- Regression flag: a row is flagged when `delta_score < -threshold_drop`
  (default 0.1). The set of flagged ids drives the CLI's non-zero exit.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from eval_harness.dataset import Dataset, Example, load_jsonl
from eval_harness.judge import FAITHFULNESS_RUBRIC, Judge, JudgeScore
from eval_harness.runs import (
    StoredRun,
    connect,
    init_db_on,
    latest_run_id_for_suite,
    new_run_id,
    read_run,
    utc_now_iso,
    write_run,
)

DEFAULT_THRESHOLD_DROP = 0.1


class AnswerSource(Protocol):
    """Provide a candidate response for an example. Pluggable for the same
    reason `Backend` is — tests substitute a deterministic source without
    requiring an API key, and consumers can plug their own model under test."""

    def answer(self, example: Example) -> str: ...


class DatasetEchoSource:
    """Echo the example's first `expected_outputs.value` as the response.

    Useful for two things: smoke-testing the runner machinery end-to-end
    (every score is 1.0 modulo judge noise) and as a sanity baseline when
    the harness is used in a CI pipeline before a real answer source is
    wired.
    """

    def answer(self, example: Example) -> str:
        if not example.expected_outputs:
            return ""
        return example.expected_outputs[0].value


@dataclass(frozen=True)
class RowScore:
    example_id: str
    score: float
    reasoning: str


@dataclass(frozen=True)
class RunResult:
    """Output of `run_suite`. The same shape that gets persisted to SQLite."""

    run_id: str
    started_at: str
    suite: str
    dataset_version: str
    judge_model: str | None
    judge_kappa: float | None
    mean_score: float
    n_rows: int
    git_sha: str | None
    rows: tuple[RowScore, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "suite": self.suite,
            "dataset_version": self.dataset_version,
            "judge_model": self.judge_model,
            "judge_kappa": self.judge_kappa,
            "mean_score": self.mean_score,
            "n_rows": self.n_rows,
            "git_sha": self.git_sha,
            "rows": [
                {"example_id": r.example_id, "score": r.score, "reasoning": r.reasoning}
                for r in self.rows
            ],
        }


@dataclass(frozen=True)
class RunSpec:
    suite: str
    dataset_path: str | Path
    judge: Judge
    answer_source: AnswerSource
    judge_model: str | None = None
    judge_kappa: float | None = None
    rubric: str = FAITHFULNESS_RUBRIC


@dataclass(frozen=True)
class RowDelta:
    example_id: str
    baseline_score: float | None  # None when row is `new` in current
    current_score: float | None  # None when row is `removed`
    delta: float | None  # None when either side is missing
    status: str  # "improved" | "regressed" | "unchanged" | "new" | "removed"
    flagged: bool


@dataclass(frozen=True)
class DeltaReport:
    current_run_id: str
    baseline_run_id: str
    suite: str
    threshold_drop: float
    rows: tuple[RowDelta, ...]
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def regressed_ids(self) -> list[str]:
        return [r.example_id for r in self.rows if r.flagged]

    def to_json(self) -> dict[str, Any]:
        return {
            "current_run_id": self.current_run_id,
            "baseline_run_id": self.baseline_run_id,
            "suite": self.suite,
            "threshold_drop": self.threshold_drop,
            "summary": self.summary,
            "rows": [
                {
                    "example_id": r.example_id,
                    "baseline_score": r.baseline_score,
                    "current_score": r.current_score,
                    "delta": r.delta,
                    "status": r.status,
                    "flagged": r.flagged,
                }
                for r in self.rows
            ],
        }


def _detect_git_sha(dataset_path: Path) -> str | None:
    """Best-effort current commit SHA. Returns None when not in a git repo or git is missing."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=dataset_path.parent if dataset_path.exists() else Path.cwd(),
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _load(dataset_path: str | Path) -> tuple[Dataset, list[Example]]:
    p = Path(dataset_path)
    examples = list(load_jsonl(p))
    if not examples:
        raise ValueError(f"dataset at {p} is empty")
    dataset = Dataset(version=examples[0].dataset_version, examples=examples)
    return dataset, examples


def run_suite(
    spec: RunSpec,
    *,
    db_path: str | Path,
    started_at: str | None = None,
    run_id: str | None = None,
) -> RunResult:
    """Score every example in the suite's dataset and persist a new run.

    `started_at` and `run_id` are caller-overridable so tests can pin them.
    The git SHA is best-effort: read from `git rev-parse HEAD` relative to
    the dataset's directory, or `None` when the lookup fails.
    """
    dataset, examples = _load(spec.dataset_path)
    rid = run_id or new_run_id()
    when = started_at or utc_now_iso()
    git_sha = _detect_git_sha(Path(spec.dataset_path))

    scored: list[RowScore] = []
    for ex in examples:
        response = spec.answer_source.answer(ex)
        verdict: JudgeScore = spec.judge.score(ex.input, response, spec.rubric)
        scored.append(RowScore(example_id=ex.id, score=verdict.score, reasoning=verdict.reasoning))

    mean = sum(r.score for r in scored) / len(scored)

    with connect(db_path) as conn:
        init_db_on(conn)
        write_run(
            conn,
            run_id=rid,
            started_at=when,
            suite=spec.suite,
            dataset_version=dataset.version,
            judge_model=spec.judge_model,
            judge_kappa=spec.judge_kappa,
            mean_score=mean,
            n_rows=len(scored),
            git_sha=git_sha,
            rows=[(r.example_id, r.score, r.reasoning) for r in scored],
        )

    return RunResult(
        run_id=rid,
        started_at=when,
        suite=spec.suite,
        dataset_version=dataset.version,
        judge_model=spec.judge_model,
        judge_kappa=spec.judge_kappa,
        mean_score=mean,
        n_rows=len(scored),
        git_sha=git_sha,
        rows=tuple(scored),
    )


def _status_for(delta: float, threshold_drop: float) -> tuple[str, bool]:
    if delta < -threshold_drop:
        return "regressed", True
    if delta < 0:
        return "regressed", False
    if delta > 0:
        return "improved", False
    return "unchanged", False


def diff_runs(
    current: StoredRun,
    baseline: StoredRun,
    *,
    threshold_drop: float = DEFAULT_THRESHOLD_DROP,
) -> DeltaReport:
    """Per-row delta with threshold flagging and a summary block."""
    if current.suite != baseline.suite:
        raise ValueError(
            f"cannot diff across suites: current={current.suite} baseline={baseline.suite}"
        )

    all_ids = sorted(set(current.rows) | set(baseline.rows))
    rows: list[RowDelta] = []
    n_flag = n_reg = n_imp = n_same = n_new = n_rem = 0
    for ex_id in all_ids:
        cur = current.rows.get(ex_id)
        base = baseline.rows.get(ex_id)
        if cur is not None and base is not None:
            delta = cur[0] - base[0]
            status, flagged = _status_for(delta, threshold_drop)
            rows.append(RowDelta(ex_id, base[0], cur[0], delta, status, flagged))
            if flagged:
                n_flag += 1
            if status == "regressed":
                n_reg += 1
            elif status == "improved":
                n_imp += 1
            else:
                n_same += 1
        elif cur is not None:
            rows.append(RowDelta(ex_id, None, cur[0], None, "new", False))
            n_new += 1
        else:
            assert base is not None
            rows.append(RowDelta(ex_id, base[0], None, None, "removed", False))
            n_rem += 1

    summary = {
        "mean_score_current": current.mean_score,
        "mean_score_baseline": baseline.mean_score,
        "mean_delta": current.mean_score - baseline.mean_score,
        "n_flagged": n_flag,
        "n_regressed": n_reg,
        "n_improved": n_imp,
        "n_unchanged": n_same,
        "n_new": n_new,
        "n_removed": n_rem,
    }
    return DeltaReport(
        current_run_id=current.run_id,
        baseline_run_id=baseline.run_id,
        suite=current.suite,
        threshold_drop=threshold_drop,
        rows=tuple(rows),
        summary=summary,
    )


def load_baseline(
    conn,
    suite: str,
    baseline_run_id: str | None,
    *,
    exclude_run_id: str | None = None,
) -> StoredRun | None:
    """Pick a baseline by id, or fall back to the latest prior run for the suite.

    `exclude_run_id` is the just-inserted current run — passed in to prevent
    picking the current run as its own baseline when two runs share a
    1-second-resolution `started_at`.
    """
    if baseline_run_id is not None:
        return read_run(conn, baseline_run_id)
    latest = latest_run_id_for_suite(conn, suite, exclude_run_id=exclude_run_id)
    return read_run(conn, latest) if latest is not None else None


def render_delta_ascii(report: DeltaReport) -> str:
    """Markdown-friendly ASCII table for CLI/PR-comment output."""
    header = (
        f"# delta {report.current_run_id[:8]} vs {report.baseline_run_id[:8]} "
        f"(suite={report.suite}, threshold_drop={report.threshold_drop:.2f})"
    )
    columns = ["status", "example_id", "baseline", "current", "delta", "flag"]
    sep = "  "
    lines = [header, "", sep.join(columns), sep.join("-" * len(c) for c in columns)]
    for r in report.rows:
        baseline = f"{r.baseline_score:.3f}" if r.baseline_score is not None else "  -  "
        current = f"{r.current_score:.3f}" if r.current_score is not None else "  -  "
        delta = f"{r.delta:+.3f}" if r.delta is not None else "  -   "
        flag = "FLAG" if r.flagged else "    "
        lines.append(
            sep.join([f"{r.status:9}", f"{r.example_id:12}", baseline, current, delta, flag])
        )
    s = report.summary
    lines.append("")
    lines.append(
        f"summary: mean Δ={s['mean_delta']:+.3f}  "
        f"regressed={s['n_regressed']} (flagged={s['n_flagged']})  "
        f"improved={s['n_improved']}  unchanged={s['n_unchanged']}  "
        f"new={s['n_new']}  removed={s['n_removed']}"
    )
    return "\n".join(lines) + "\n"


def load_run_result_from_json(path: str | Path) -> StoredRun:
    """Read a `RunResult.to_json()` payload from disk; return as `StoredRun`.

    `StoredRun` is the shape `diff_runs` consumes (`rows` is a dict keyed
    by example_id). Doing the conversion here lets CI workflows diff two
    JSON files without an intermediate SQLite — which is what #6's
    GitHub Action needs since the action runner is ephemeral.
    """
    raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    rows: dict[str, tuple[float, str]] = {}
    for r in payload.get("rows", []):
        rows[r["example_id"]] = (float(r["score"]), str(r.get("reasoning", "")))
    return StoredRun(
        run_id=payload["run_id"],
        started_at=payload["started_at"],
        suite=payload["suite"],
        dataset_version=payload.get("dataset_version", ""),
        judge_model=payload.get("judge_model"),
        judge_kappa=payload.get("judge_kappa"),
        mean_score=float(payload.get("mean_score", 0.0)),
        n_rows=int(payload.get("n_rows", len(rows))),
        git_sha=payload.get("git_sha"),
        rows=rows,
    )


def render_run_json(result: RunResult) -> str:
    return json.dumps(result.to_json(), indent=2, sort_keys=True)
