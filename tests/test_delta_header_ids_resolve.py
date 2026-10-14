"""The run ids both delta renderers print are ids `diff` accepts (#355).

`render_delta_ascii`'s header and `render_delta_markdown`'s `_current_ ... vs
_baseline_ ...` line cut each 32-hex run id to 8 characters. When `run` picks
the suite's latest run as its baseline, that header is the only place the
baseline is named, and `diff --baseline` / `run --baseline` match an id exactly,
so the id shown there was refused with "no run with id". #348 fixed the same
class in the `list` table by printing the whole id.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import main
from eval_harness.comment import render_delta_markdown
from eval_harness.runner import DeltaReport, render_delta_ascii

ROOT = Path(__file__).resolve().parent.parent
DATASET = "fixtures/sample_factuality_v1.jsonl"
CURRENT = "96b884d1ffbf430ca634a735c28601a7"
BASELINE = "8cbd2710902c4307b898b1378810fe4b"


class _Stub:
    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake-judge"

    def complete(self, system: str, user: str) -> str:
        return "SCORE: 0.9\nREASONING: stub\n"


@pytest.fixture(autouse=True)
def _at_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)


def _report() -> DeltaReport:
    summary = {
        "mean_delta": 0.0,
        "n_flagged": 0,
        "n_regressed": 0,
        "n_improved": 0,
        "n_unchanged": 0,
        "n_new": 0,
        "n_removed": 0,
    }
    return DeltaReport(
        current_run_id=CURRENT,
        baseline_run_id=BASELINE,
        suite="s",
        threshold_drop=0.1,
        rows=(),
        summary=summary,
    )


def test_the_baseline_run_names_in_its_header_is_accepted_by_diff(tmp_path: Path, capsys) -> None:
    db = tmp_path / "runs.db"
    with patch("eval_harness.cli.AnthropicBackend", _Stub):
        for _ in range(2):
            assert main(["run", "--suite", "s", "--dataset", DATASET, "--db", str(db)]) == 0
    err = capsys.readouterr().err
    header = re.search(r"^# delta (\S+) vs (\S+) ", err, re.M)
    assert header is not None, err
    current, baseline = header.groups()
    rc = main(["diff", "--db", str(db), "--current", current, "--baseline", baseline])
    assert rc == 0, capsys.readouterr().err


def test_the_ascii_header_prints_both_ids_whole() -> None:
    header = render_delta_ascii(_report()).splitlines()[0]
    assert f"# delta {CURRENT} vs {BASELINE} " in header, header


def test_the_markdown_comment_prints_both_ids_whole() -> None:
    md = render_delta_markdown(_report())
    line = next(ln for ln in md.splitlines() if ln.startswith("_current_"))
    assert f"`{CURRENT}`" in line, line
    assert f"`{BASELINE}`" in line, line
