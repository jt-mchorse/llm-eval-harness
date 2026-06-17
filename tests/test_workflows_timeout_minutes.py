"""Lock that every workflow job has a sensible `timeout-minutes` bound.

Companion to `test_workflows_yaml_parseable.py` (portfolio-ops#30 /
portfolio-ops#31, propagated here as #60) — same silent-rot prevention
arc, different failure mode.

The failure mode this catches: GitHub Actions defaults to 360 minutes
(6 hours) per job when no `timeout-minutes` is set. A hung job — network
stall during `pip install`, infinite test loop, stuck API call against a
flaky upstream — therefore burns the full 6-hour ceiling before the job
is killed. That's quota the operator pays for whether the run produced
anything or not.

Survey across the 12 portfolio repos when this lock was written
(2026-06-17): only 1/17 workflows was bounded; the other 16 ran
unguarded. `llm-eval-harness` is the canonical first hop for the
propagation; per-repo policy bands may differ as the lock spreads
(e.g., `vector-search-at-scale` benchmarks may want a wider ceiling).

Spec / origin: this repo's #62.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTIVE_WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# Policy band for this repo. The upper bound is intentionally tight —
# llm-eval-harness's matrix CI runs comfortably in <8 min/job and the
# eval comment workflow runs in <3 min/job; 30 min is a hard ceiling
# that catches "operator forgot to update the bound after a workflow
# rewrite" without flagging routine slow days.
MIN_TIMEOUT_MINUTES = 1
MAX_TIMEOUT_MINUTES = 30


def _all_workflow_files() -> list[Path]:
    if not ACTIVE_WORKFLOWS_DIR.is_dir():
        return []
    return sorted(ACTIVE_WORKFLOWS_DIR.glob("*.yml"))


def _all_jobs() -> list[tuple[str, str, dict[str, Any]]]:
    """Return (workflow_filename, job_id, job_body) for every job.

    Flattened across all workflow files so pytest parametrization
    surfaces each missing or out-of-band timeout as its own failure,
    not a single "one of 7 jobs is broken" summary line.
    """
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for path in _all_workflow_files():
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            continue
        jobs = parsed.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_id, body in jobs.items():
            if isinstance(body, dict):
                rows.append((path.name, str(job_id), body))
    return rows


ALL_JOBS = _all_jobs()


def test_at_least_one_job_discovered() -> None:
    # Smoke check: parametrization silently degrades to a no-op if the
    # discovery fixture returns []. Make that loud.
    assert ALL_JOBS, (
        f"No jobs discovered under {ACTIVE_WORKFLOWS_DIR}. Either the "
        "workflow files were removed or YAML discovery is broken; this "
        "lock should not silently pass in either case."
    )


@pytest.mark.parametrize(
    ("workflow", "job_id", "body"),
    ALL_JOBS,
    ids=[f"{wf}::{jid}" for (wf, jid, _) in ALL_JOBS],
)
def test_job_has_timeout_minutes(workflow: str, job_id: str, body: dict[str, Any]) -> None:
    timeout = body.get("timeout-minutes")
    assert timeout is not None, (
        f"{workflow}::{job_id} has no `timeout-minutes` set. GitHub "
        f"Actions defaults to 360 min/job when this is missing — a hung "
        f"job (network stall, infinite loop, stuck API call) burns the "
        f"full 6-hour ceiling before the runner kills it. Set "
        f"`timeout-minutes:` on this job. For this repo's workloads, "
        f"15 is the policy default for CI; tighten or relax to match the "
        f"job, but stay in [{MIN_TIMEOUT_MINUTES}, {MAX_TIMEOUT_MINUTES}]."
    )


@pytest.mark.parametrize(
    ("workflow", "job_id", "body"),
    ALL_JOBS,
    ids=[f"{wf}::{jid}" for (wf, jid, _) in ALL_JOBS],
)
def test_job_timeout_is_int(workflow: str, job_id: str, body: dict[str, Any]) -> None:
    timeout = body.get("timeout-minutes")
    if timeout is None:
        pytest.skip("covered by test_job_has_timeout_minutes")
    msg = (
        f"{workflow}::{job_id} has `timeout-minutes: {timeout!r}` "
        f"({type(timeout).__name__}); GitHub Actions requires an integer. "
        "A YAML string like `'15'` is parsed but rejected at workflow-load "
        "time, producing a silent failure shape similar to #60."
    )
    # `bool` is a subclass of `int` in Python; reject it explicitly so a
    # stray `timeout-minutes: true` (parsed as 1) doesn't sneak past.
    assert isinstance(timeout, int), msg
    assert not isinstance(timeout, bool), msg


@pytest.mark.parametrize(
    ("workflow", "job_id", "body"),
    ALL_JOBS,
    ids=[f"{wf}::{jid}" for (wf, jid, _) in ALL_JOBS],
)
def test_job_timeout_in_policy_band(workflow: str, job_id: str, body: dict[str, Any]) -> None:
    timeout = body.get("timeout-minutes")
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        pytest.skip("covered by test_job_timeout_is_int")
    assert MIN_TIMEOUT_MINUTES <= timeout <= MAX_TIMEOUT_MINUTES, (
        f"{workflow}::{job_id} has `timeout-minutes: {timeout}` outside the "
        f"policy band [{MIN_TIMEOUT_MINUTES}, {MAX_TIMEOUT_MINUTES}]. Values "
        f"above the ceiling reintroduce most of the unbounded-job quota burn; "
        f"values at 0 disable the timeout entirely (GitHub Actions semantics). "
        f"If this job genuinely needs a wider bound (e.g., long-running "
        f"benchmarks), bump MAX_TIMEOUT_MINUTES with a comment naming the "
        f"workload that forced the change."
    )
