"""Every run id `eval-harness list` prints is one `diff` accepts (#348).

The table cut each 32-hex `run_id` to 12 characters plus an ellipsis, while
`diff --current/--baseline` and `run --baseline` match an id exactly. Copying
an id out of the table therefore failed with "no run with id". The README's
sample `list` output also showed 12-character ids with no ellipsis, which the
CLI never printed.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_harness.cli import _render_runs_table, main
from eval_harness.runs import RunSummary

ROOT = Path(__file__).resolve().parent.parent
DATASET = "fixtures/sample_factuality_v1.jsonl"
README = ROOT / "README.md"


class _Stub:
    def __init__(self, model: str | None = None, max_tokens: int = 512) -> None:
        self.model = model or "fake-judge"

    def complete(self, system: str, user: str) -> str:
        return "SCORE: 0.9\nREASONING: stub\n"


@pytest.fixture(autouse=True)
def _at_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)


def _table_ids(table: str) -> list[str]:
    lines = table.splitlines()[2:]  # header, separator
    return [line.split()[1] for line in lines if line.strip()]


def test_ids_copied_from_the_table_are_accepted_by_diff(tmp_path: Path, capsys) -> None:
    db = tmp_path / "runs.db"
    with patch("eval_harness.cli.AnthropicBackend", _Stub):
        for _ in range(2):
            assert (
                main(["run", "--suite", "s", "--dataset", DATASET, "--db", str(db), "--no-diff"])
                == 0
            )
    capsys.readouterr()
    assert main(["list", "--db", str(db)]) == 0
    ids = _table_ids(capsys.readouterr().out)
    assert len(ids) == 2
    rc = main(["diff", "--db", str(db), "--current", ids[0], "--baseline", ids[1]])
    err = capsys.readouterr().err
    assert rc == 0, err


def test_the_readme_list_sample_has_the_shape_the_renderer_prints() -> None:
    text = README.read_text("utf-8")
    start = text.index("$ eval-harness list --limit 5")
    block = text[start : text.index("```", start)].splitlines()[1:]
    header, rule, first = block[0], block[1], block[2]
    sample_id = first.split()[1]
    assert re.fullmatch(r"[0-9a-f]{32}", sample_id), sample_id
    rendered = _render_runs_table(
        [
            RunSummary(
                run_id=sample_id,
                started_at=first.split()[0],
                suite=first.split()[2],
                dataset_version="v",
                judge_model=first.split()[5],
                judge_kappa=None,
                mean_score=float(first.split()[3]),
                n_rows=int(first.split()[4]),
                git_sha=None,
            )
        ]
    ).splitlines()
    assert rendered[0].rstrip() == header.rstrip()
    assert rendered[1].rstrip() == rule.rstrip()
    assert rendered[2].rstrip() == first.rstrip()
