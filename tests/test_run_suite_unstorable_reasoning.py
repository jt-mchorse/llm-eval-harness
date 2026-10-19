"""`run_suite` refuses a judge reasoning the run record cannot store, at the row (#398).

#344 closed this for `--suite`/`--model`. The judge's `reasoning` is the other
text `write_run` stores, and it comes from the backend: a gateway behind
`ANTHROPIC_BASE_URL` that sends a `\\ud83d` escape (half an emoji pair), or a
custom `Backend` that decoded bytes with surrogateescape. Measured on main over
a loopback Messages API: every row was judged, then SQLite raised
UnicodeEncodeError in `write_run` -- traceback, nothing saved, no `--out`,
exit 1 (the "a row regressed" code).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from eval_harness import cli
from eval_harness.judge import Judge, JudgeParseError
from eval_harness.runner import DatasetEchoSource, RunSpec, run_suite

REPO = Path(__file__).resolve().parent.parent
DATASET = REPO / "fixtures" / "sample_factuality_v1.jsonl"


class _Scripted:
    """Backend whose Nth call (0-based) carries *reasoning*; the rest are clean."""

    model = "scripted"

    def __init__(self, reasoning: str, at: int = 0) -> None:
        self.reasoning = reasoning
        self.at = at
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        n = self.calls
        self.calls += 1
        text = self.reasoning if n == self.at else "fine"
        return f"SCORE: 0.8\nREASONING: {text}"


def _spec(backend: _Scripted) -> RunSpec:
    return RunSpec(
        suite="s",
        dataset_path=DATASET,
        judge=Judge(backend=backend),
        answer_source=DatasetEchoSource(),
    )


UNSTORABLE = {
    "lone-high": ("fine " + chr(0xD83D), chr(0xD83D), 5),
    "lone-low": (chr(0xDE00) + " fine", chr(0xDE00), 0),
    "escaped-byte": ("caf" + chr(0xDCC3), chr(0xDCC3), 3),
}


@pytest.mark.parametrize("case", list(UNSTORABLE), ids=list(UNSTORABLE))
def test_unstorable_reasoning_is_a_parse_error_naming_the_row(tmp_path: Path, case: str) -> None:
    reasoning, offender, index = UNSTORABLE[case]
    backend = _Scripted(reasoning, at=3)
    db = tmp_path / "runs.db"
    with pytest.raises(JudgeParseError) as exc:
        run_suite(_spec(backend), db_path=db)
    msg = str(exc.value)
    assert "has no UTF-8 encoding" in msg
    assert ascii(offender) in msg
    assert f"at index {index}," in msg
    # The message must itself be printable: the offender is reported via ascii().
    msg.encode("utf-8")
    # Refused at the offending row: rows 4.. are never paid for.
    assert backend.calls == 4
    # And nothing half-written: no run row exists.
    if db.exists():
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_the_cli_reports_it_at_exit_2_not_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = _Scripted("fine " + chr(0xD83D))
    monkeypatch.setattr(cli, "AnthropicBackend", lambda *a, **k: backend)
    out = tmp_path / "o.json"
    rc = cli.main(
        [
            "run",
            "--suite",
            "s",
            "--dataset",
            str(DATASET),
            "--db",
            str(tmp_path / "runs.db"),
            "--out",
            str(out),
            "--no-diff",
        ]
    )
    assert rc == 2
    assert not out.exists()
    err = capsys.readouterr()
    lines = [ln for ln in (err.out + err.err).splitlines() if ln.startswith("::error::")]
    assert len(lines) == 1
    assert "has no UTF-8 encoding" in lines[0]
    assert backend.calls == 1


@pytest.mark.parametrize(
    "reasoning",
    ["café, naïve", "夜间 ok", "good \U0001f319 answer"],
    ids=["latin", "cjk", "astral-emoji"],
)
def test_encodable_non_ascii_reasoning_is_stored_unchanged(tmp_path: Path, reasoning: str) -> None:
    backend = _Scripted(reasoning, at=0)
    db = tmp_path / "runs.db"
    result = run_suite(_spec(backend), db_path=db)
    assert backend.calls == 10
    with sqlite3.connect(db) as conn:
        stored = conn.execute(
            "SELECT reasoning FROM rows WHERE run_id = ? ORDER BY rowid LIMIT 1",
            (result.run_id,),
        ).fetchone()[0]
    assert stored == reasoning
