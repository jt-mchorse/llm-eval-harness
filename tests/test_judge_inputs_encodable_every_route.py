"""`run` and `calibrate` refuse judge input with no UTF-8 encoding on every route (#407).

#344 refused an unencodable `run --model` and #398 an unencodable judge
reasoning at its row in `run_suite`. Neither reached `calibrate`, and the model
check read the flag only, not `EVAL_HARNESS_JUDGE_MODEL`, which the backend
uses when the flag is absent. Measured on main 54ebda7 with anthropic 0.116.0
(dummy key, loopback base URL): `EVAL_HARNESS_JUDGE_MODEL=$'bad\\xff' run`,
`calibrate --model $'bad\\xff'` and `EVAL_HARNESS_JUDGE_MODEL=$'bad\\xff'
calibrate` each raised UnicodeEncodeError in the SDK's request encoder at exit
1. A stub judge whose reasoning held `\\ud83d` cost all 50 calibration calls
before the report write refused it.

The model routes use the real `AnthropicBackend`, so the environment variable is
resolved by the code that resolves it in production, over a stand-in `anthropic`
module (CI installs `[dev]`, not `[judge]`) whose `messages.create` encodes the
model the way the SDK does.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from eval_harness import cli
from eval_harness.calibration import calibrate, load_calibration
from eval_harness.judge import Judge, JudgeParseError

REPO = Path(__file__).resolve().parent.parent
DATASET = REPO / "fixtures" / "sample_factuality_v1.jsonl"
CALIBRATION = REPO / "fixtures" / "calibration.jsonl"
BAD_MODEL = "bad" + chr(0xDCFF)  # what `$'bad\xff'` arrives as through argv/environ


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Install a stand-in `anthropic`; return the model of every request sent."""
    sent: list[str] = []

    class _Messages:
        def create(self, **kwargs: Any) -> Any:
            # The real SDK JSON-encodes the request body before sending; a lone
            # surrogate fails there with UnicodeEncodeError, exactly as below.
            kwargs["model"].encode("utf-8")
            sent.append(kwargs["model"])
            block = types.SimpleNamespace(text="SCORE: 0.8\nREASONING: fine")
            return types.SimpleNamespace(content=[block])

    class _Anthropic:
        def __init__(self, **_kwargs: object) -> None:
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.delenv("EVAL_HARNESS_JUDGE_MODEL", raising=False)
    return sent


def _run(tmp_path: Path, *extra: str) -> int:
    return cli.main(
        [
            "run",
            "--suite",
            "s",
            "--dataset",
            str(DATASET),
            "--db",
            str(tmp_path / "runs.db"),
            "--no-diff",
            *extra,
        ]
    )


def _calibrate(tmp_path: Path, *extra: str) -> int:
    return cli.main(
        [
            "calibrate",
            "--calibration",
            str(CALIBRATION),
            "--report",
            str(tmp_path / "report.md"),
            *extra,
        ]
    )


def _error_lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    err = capsys.readouterr()
    return [ln for ln in (err.out + err.err).splitlines() if ln.startswith("::error::")]


ROUTES = {
    "run-env": (_run, False),
    "calibrate-flag": (_calibrate, True),
    "calibrate-env": (_calibrate, False),
}


@pytest.mark.parametrize("route", list(ROUTES), ids=list(ROUTES))
def test_an_unencodable_judge_model_exits_2_before_any_request(
    route: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sdk: list[str],
) -> None:
    command, via_flag = ROUTES[route]
    if via_flag:
        rc = command(tmp_path, "--model", BAD_MODEL)
    else:
        monkeypatch.setenv("EVAL_HARNESS_JUDGE_MODEL", BAD_MODEL)
        rc = command(tmp_path)
    assert rc == 2
    assert sdk == []
    assert not (tmp_path / "runs.db").exists()
    assert not (tmp_path / "report.md").exists()
    lines = _error_lines(capsys)
    assert len(lines) == 1
    assert "has no UTF-8 encoding" in lines[0]
    # The message names where the value came from, so the operator knows what to fix.
    source = "--model" if via_flag else "EVAL_HARNESS_JUDGE_MODEL"
    assert lines[0].startswith(f"::error::{source} ")


@pytest.mark.parametrize("route", list(ROUTES), ids=list(ROUTES))
@pytest.mark.parametrize("model", ["claude-é", "claude-\U0001f319"], ids=["latin", "astral"])
def test_an_encodable_non_ascii_model_reaches_the_judge(
    route: str,
    model: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sdk: list[str],
) -> None:
    # Control: the check is on encodability, not on ASCII-ness.
    command, via_flag = ROUTES[route]
    if via_flag:
        rc = command(tmp_path, "--model", model)
    else:
        monkeypatch.setenv("EVAL_HARNESS_JUDGE_MODEL", model)
        rc = command(tmp_path)
    assert rc in (0, 1)
    assert sdk
    assert set(sdk) == {model}


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


UNSTORABLE = {
    "lone-high": ("fine " + chr(0xD83D), chr(0xD83D), 5),
    "lone-low": (chr(0xDE00) + " fine", chr(0xDE00), 0),
    "escaped-byte": ("caf" + chr(0xDCC3), chr(0xDCC3), 3),
}


@pytest.mark.parametrize("case", list(UNSTORABLE), ids=list(UNSTORABLE))
def test_calibrate_refuses_an_unencodable_reasoning_at_its_row(case: str) -> None:
    reasoning, offender, index = UNSTORABLE[case]
    rows = load_calibration(CALIBRATION)
    backend = _Scripted(reasoning, at=3)
    with pytest.raises(JudgeParseError) as exc:
        calibrate(Judge(backend=backend), rows)
    msg = str(exc.value)
    assert msg.startswith(f"row {rows[3].id!r}: ")
    assert "has no UTF-8 encoding" in msg
    assert ascii(offender) in msg
    assert f"at index {index}," in msg
    msg.encode("utf-8")
    # Refused at the offending row: rows 4.. are never paid for.
    assert backend.calls == 4


def test_the_calibrate_cli_reports_it_at_exit_2_after_one_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = _Scripted("fine " + chr(0xD83D))
    monkeypatch.setattr(cli, "AnthropicBackend", lambda *a, **k: backend)
    assert _calibrate(tmp_path) == 2
    assert backend.calls == 1
    assert not (tmp_path / "report.md").exists()
    lines = _error_lines(capsys)
    assert len(lines) == 1
    assert lines[0].startswith("::error::judge did not return a usable verdict: row ")
    assert "has no UTF-8 encoding" in lines[0]


@pytest.mark.parametrize(
    "reasoning",
    ["café, naïve", "夜间 ok", "good \U0001f319 answer"],
    ids=["latin", "cjk", "astral-emoji"],
)
def test_encodable_non_ascii_reasoning_is_calibrated_and_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reasoning: str
) -> None:
    backend = _Scripted(reasoning, at=0)
    monkeypatch.setattr(cli, "AnthropicBackend", lambda *a, **k: backend)
    assert _calibrate(tmp_path) in (0, 1)
    assert backend.calls == len(load_calibration(CALIBRATION))
    assert reasoning in (tmp_path / "report.md").read_text(encoding="utf-8")
