"""README ↔ source defaults snapshot (#22).

Sister to `test_readme_snapshot.py` (which locks the structural surface
— bullet list, CLI subcommand surface, file refs, Demo section). This
module closes the orthogonal gap: numeric and identifier defaults that
the README quotes as if they were derived from source.

Source of truth is **the live source value** — if a test fails, the
remediation is to update the README quote to match, not change the
default to match the README.

Pairings locked:

1. "50 rows" in Calibration section ↔ row count of fixtures/calibration.jsonl.
2. `pip install -e '.[dev]'` and `[judge]` extras ↔ pyproject.toml keys.
3. `--threshold-drop` "default 0.1" ↔ eval_harness.runner.DEFAULT_THRESHOLD_DROP.
4. "κ ≥ 0.6 threshold" ↔ `--threshold-kappa` default in eval_harness.cli.
5. "k=8 cluster centroids" ↔ cluster_k default in eval_harness.drift.compute_drift.
6. `<!-- eval-harness:sticky-comment -->` marker ↔ eval_harness.comment.STICKY_MARKER.
"""

from __future__ import annotations

import inspect
import re
import sys
import tomllib
from pathlib import Path

from eval_harness import drift
from eval_harness.comment import STICKY_MARKER
from eval_harness.runner import DEFAULT_THRESHOLD_DROP

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
CALIBRATION = REPO_ROOT / "fixtures" / "calibration.jsonl"

REGEN_HINT = (
    "Source is the truth: update the README quote to match the new live "
    "value (not the other way around)."
)


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def test_calibration_row_count_matches_fixture() -> None:
    """README's '**50 rows**' must equal the fixture's actual line count."""
    body = _readme()
    match = re.search(r"calibration set is \*\*(\d+) rows\*\*", body)
    assert match, (
        "README Calibration section must quote the row count as "
        "'**N rows**' so this snapshot can lock it. "
        "Expected anchor: 'The calibration set is **50 rows** of ...'."
    )
    readme_n = int(match.group(1))
    live_n = sum(1 for _ in CALIBRATION.open(encoding="utf-8") if _.strip())
    assert readme_n == live_n, (
        f"README claims {readme_n} calibration rows but "
        f"fixtures/calibration.jsonl has {live_n} non-empty lines. "
        f"{REGEN_HINT}"
    )


def test_pip_extras_in_quickstart_match_pyproject() -> None:
    """Every `pip install -e '.[<extra>]'` quoted in the README must be a
    key under [project.optional-dependencies]."""
    body = _readme()
    quoted = set(re.findall(r"pip install -e '\.\[([^\]]+)\]'", body))
    assert quoted, (
        "README must quote at least one `pip install -e '.[<extra>]'` "
        "Quickstart command for this test to lock anything."
    )
    with PYPROJECT.open("rb") as fh:
        pyproject = tomllib.load(fh)
    live = set(pyproject.get("project", {}).get("optional-dependencies", {}).keys())
    missing = sorted(quoted - live)
    assert not missing, (
        f"README Quickstart quotes `pip install -e '.[{','.join(missing)}]'` "
        f"but {missing} are not keys under [project.optional-dependencies] "
        f"in pyproject.toml (live keys: {sorted(live)}). {REGEN_HINT}"
    )


def test_threshold_drop_default_matches_runner_constant() -> None:
    """README's '`--threshold-drop` (default `0.1`)' must equal
    eval_harness.runner.DEFAULT_THRESHOLD_DROP."""
    body = _readme()
    match = re.search(r"`--threshold-drop`\s*\(default `([\d.]+)`\)", body)
    assert match, (
        "README Regression runner section must quote the threshold as "
        "'`--threshold-drop` (default `<N>`)' so this snapshot can lock it."
    )
    readme_v = float(match.group(1))
    assert readme_v == DEFAULT_THRESHOLD_DROP, (
        f"README quotes --threshold-drop default as {readme_v} but "
        f"eval_harness.runner.DEFAULT_THRESHOLD_DROP = {DEFAULT_THRESHOLD_DROP}. "
        f"{REGEN_HINT}"
    )


def test_kappa_threshold_in_what_this_is_matches_cli_default() -> None:
    """README's 'κ ≥ 0.6 threshold' must equal the `--threshold-kappa`
    default in eval_harness.cli."""
    body = _readme()
    start = body.index("## What this is")
    end = body.index("##", start + 1)
    section = body[start:end]
    match = re.search(r"κ ≥ ([\d.]+) threshold", section)
    assert match, (
        "README 'What this is' bullet 2 must quote the kappa gate as "
        "'κ ≥ <N> threshold' so this snapshot can lock it."
    )
    readme_v = float(match.group(1))

    cli_src = (REPO_ROOT / "eval_harness" / "cli.py").read_text(encoding="utf-8")
    cli_match = re.search(
        r'add_argument\("--threshold-kappa",\s*type=float,\s*default=([\d.]+)\)',
        cli_src,
    )
    assert cli_match, (
        "Could not locate the `--threshold-kappa` default in eval_harness/cli.py. "
        "Has the argparse wiring moved? Update this test's regex."
    )
    live_v = float(cli_match.group(1))
    assert readme_v == live_v, (
        f"README quotes the kappa gate as κ ≥ {readme_v} but "
        f"--threshold-kappa default in eval_harness/cli.py is {live_v}. "
        f"{REGEN_HINT}"
    )


def test_cluster_k_default_matches_compute_drift_signature() -> None:
    """README's 'k=8 cluster centroids' must equal the live `cluster_k`
    default in eval_harness.drift.compute_drift."""
    body = _readme()
    match = re.search(r"builds k=(\d+) cluster centroids", body)
    assert match, (
        "README Drift detection section must quote the cluster count as "
        "'builds k=<N> cluster centroids' so this snapshot can lock it."
    )
    readme_k = int(match.group(1))
    sig = inspect.signature(drift.compute_drift)
    live_k = sig.parameters["cluster_k"].default
    assert readme_k == live_k, (
        f"README claims k={readme_k} cluster centroids but "
        f"eval_harness.drift.compute_drift's cluster_k default is {live_k}. "
        f"{REGEN_HINT}"
    )


def test_sticky_comment_marker_matches_comment_constant() -> None:
    """README must quote the live STICKY_MARKER literal so the GitHub
    Action section can't desync from the comment module."""
    body = _readme()
    # The marker is a literal HTML comment; the README quotes it inside
    # backticks. Assert the exact constant appears verbatim in the body.
    assert STICKY_MARKER in body, (
        f"README must contain the sticky-comment marker literal "
        f"{STICKY_MARKER!r} (currently quoted in the GitHub Action section "
        f"as `{STICKY_MARKER}`). Source is eval_harness.comment.STICKY_MARKER. "
        f"{REGEN_HINT}"
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(__import__("pytest").main([__file__, "-v"]))
