"""`run` refuses a --suite or --model the run record cannot store, before judging (#344).

A non-UTF-8 argv byte arrives as a lone surrogate (`\\xff` -> '\\udcff'). It
passed every preflight and the whole judge loop, and the SQLite insert in
`write_run` refused it last. Measured on main with a counting backend over the
10-row sample: `--suite 'nightly-\\udcff'` made 10 judge calls, then raised
UnicodeEncodeError (exit 1, the "a row regressed" code).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_harness import cli

REPO = Path(__file__).resolve().parent.parent
CALLS: list[int] = []


class _Counting:
    model = "counting"

    def __init__(self, *_a: object, **_k: object) -> None:
        pass

    def complete(self, system: str, user: str) -> str:
        CALLS.append(1)
        return "SCORE: 0.8\nREASONING: fine"


@pytest.fixture(autouse=True)
def _backend(monkeypatch: pytest.MonkeyPatch) -> None:
    CALLS.clear()
    monkeypatch.setattr(cli, "AnthropicBackend", _Counting)


def _run(tmp_path: Path, *extra: str) -> int:
    dataset = str(REPO / "fixtures" / "sample_factuality_v1.jsonl")
    return cli.main(
        ["run", "--dataset", dataset, "--db", str(tmp_path / "runs.db"), "--no-diff", *extra]
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["--suite", "nightly-" + chr(0xDCFF)],
        ["--suite", chr(0xD800)],
        ["--suite", "ok", "--model", "claude-" + chr(0xDCFF)],
    ],
    ids=["suite-escaped-byte", "suite-lone-high", "model"],
)
def test_an_unstorable_flag_exits_2_before_any_judge_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    assert _run(tmp_path, *argv) == 2
    assert CALLS == []
    assert not (tmp_path / "runs.db").exists()
    err = capsys.readouterr()
    lines = [ln for ln in (err.out + err.err).splitlines() if ln.startswith("::error::")]
    assert len(lines) == 1
    assert "has no UTF-8 encoding" in lines[0]


@pytest.mark.parametrize("suite", ["nightly-é", "夜间", "nightly-\U0001f319"])
def test_a_non_ascii_suite_still_runs_and_is_stored(tmp_path: Path, suite: str) -> None:
    assert _run(tmp_path, "--suite", suite) in (0, 1)
    assert len(CALLS) == 10
    assert (tmp_path / "runs.db").exists()
