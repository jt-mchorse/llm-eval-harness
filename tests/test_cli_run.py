"""End-to-end smoke test for `eval-harness run` and `eval-harness diff`.

Uses the unittest.mock seam to inject a deterministic judge backend in place
of the real `AnthropicBackend`. The acceptance criterion on issue #3 is that
the smoke test runs in <10s; on the in-repo sample dataset this finishes in
well under a second.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import main

ROOT = Path(__file__).resolve().parent.parent


class _FakeAnthropic:
    """Stand-in for `AnthropicBackend` so the CLI runs without an API key."""

    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake-judge"
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        # Score 1.0 on the Paris example, 0.4 on the hexagon example.
        if "France" in user:
            return "SCORE: 1.0\nREASONING: paris\n"
        if "hexagon" in user:
            return "SCORE: 0.4\nREASONING: weak\n"
        return "SCORE: 0.6\nREASONING: default\n"


def _run_cli(argv: list[str], *, capsys) -> tuple[int, str, str]:
    with patch("eval_harness.cli.AnthropicBackend", _FakeAnthropic):
        rc = main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


SAMPLE_DATASET = Path("fixtures/sample_factuality_v1.jsonl")


@pytest.fixture(autouse=True)
def _at_repo_root(monkeypatch):
    monkeypatch.chdir(ROOT)


def test_run_completes_quickly_and_emits_json(tmp_path: Path, capsys) -> None:
    db = tmp_path / "runs.db"
    start = time.perf_counter()
    rc, stdout, stderr = _run_cli(
        ["run", "--suite", "smoke", "--dataset", str(SAMPLE_DATASET),
         "--db", str(db), "--no-diff"],
        capsys=capsys,
    )
    elapsed = time.perf_counter() - start
    assert rc == 0
    assert elapsed < 10.0
    payload = json.loads(stdout)
    assert payload["suite"] == "smoke"
    assert payload["n_rows"] >= 1
    assert "run" in stderr  # the summary line


def test_run_then_diff_against_baseline(tmp_path: Path, capsys) -> None:
    db = tmp_path / "runs.db"
    rc1, _, _ = _run_cli(
        ["run", "--suite", "smoke", "--dataset", str(SAMPLE_DATASET),
         "--db", str(db), "--no-diff"],
        capsys=capsys,
    )
    assert rc1 == 0

    # Second run with the same backend should compare against the first and
    # exit 0 (no flagged regressions).
    rc2, stdout2, stderr2 = _run_cli(
        ["run", "--suite", "smoke", "--dataset", str(SAMPLE_DATASET),
         "--db", str(db)],
        capsys=capsys,
    )
    assert rc2 == 0
    # The delta table is rendered to stderr; the JSON run result is on stdout.
    assert "summary:" in stderr2
    json.loads(stdout2)  # still valid JSON


def test_diff_exits_nonzero_when_regression_flagged(tmp_path: Path, capsys) -> None:
    db = tmp_path / "runs.db"

    # Baseline: score every prompt 1.0 so any drop is a regression.
    class HighBackend:
        def __init__(self, model=None, max_tokens=512) -> None:
            self.model = model or "fake"
            self.max_tokens = max_tokens

        def complete(self, system, user) -> str:
            return "SCORE: 1.0\nREASONING: high\n"

    with patch("eval_harness.cli.AnthropicBackend", HighBackend):
        rc_base = main(["run", "--suite", "smoke", "--dataset", str(SAMPLE_DATASET),
                        "--db", str(db), "--no-diff"])
    assert rc_base == 0

    # Current: every prompt scores 0.5 → 0.5-point drop, flagged.
    class LowBackend:
        def __init__(self, model=None, max_tokens=512) -> None:
            self.model = model or "fake"
            self.max_tokens = max_tokens

        def complete(self, system, user) -> str:
            return "SCORE: 0.5\nREASONING: low\n"

    with patch("eval_harness.cli.AnthropicBackend", LowBackend):
        rc_cur = main(["run", "--suite", "smoke", "--dataset", str(SAMPLE_DATASET),
                       "--db", str(db)])
    captured = capsys.readouterr()
    assert rc_cur == 1
    assert "FLAG" in captured.err
