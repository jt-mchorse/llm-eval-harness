"""The judge seam's exit-code contract, as a grid (#218).

`_fail` documents `0 = clean / 1 = findings / 2 = I/O or usage error`. Two
subcommands build a judge — `run` and `calibrate` — and before this issue
`JudgeAuthError` was the *only* judge-layer exception either of them
translated, because #194 added an explicit arm for it and nothing else.
Everything else escaped as a raw traceback at exit 1, which on these two
paths is not a spare code: it means "a row regressed past --threshold-drop"
for `run` and "Cohen's κ below threshold" for `calibrate`. A judge that
answered in the wrong format, or an install without the `judge` extra, was
therefore reported to CI as a *quality* result.

The matrix is the deliverable, so it is pinned here rather than described:
one row per judge-layer failure mode, one column per subcommand, including
the rows this issue deliberately does **not** change (see `#220`) and the
clean baseline that keeps the whole table from passing vacuously.

Hermetic: `AnthropicBackend` is replaced at the `cli` seam, so nothing here
needs the optional `judge` extra or an API key.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from eval_harness import cli
from eval_harness.judge import JudgeAuthError

# --- fixtures -------------------------------------------------------------


class _FakeBackend:
    """Backend stand-in: `complete` raises `exc`, or returns `raw`.

    `raw` may be a list, consumed one response per call, so a failure can be
    placed on a *later* row than the first — which is what makes the
    "name the failing row" assertions meaningful.
    """

    def __init__(self, *, exc: BaseException | None = None, raw=None) -> None:
        self._exc = exc
        self._raw = raw
        self._calls = 0
        self.model = "fake-judge"

    def complete(self, system: str, user: str) -> str:
        if self._exc is not None:
            raise self._exc
        self._calls += 1
        if isinstance(self._raw, list):
            return self._raw[min(self._calls - 1, len(self._raw) - 1)]
        return self._raw


class _FakeStatusError(Exception):
    """Stand-in for `anthropic.APIStatusError`: carries an int `status_code`."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


_OK = "SCORE: 0.9\nREASONING: fine"

#: A parse failure has three distinct raise sites in `parse_judge_output`;
#: all three must land on the same side of the contract.
_NO_SCORE = '{"score": 0.5, "reasoning": "ok"}'
_NO_REASONING = "SCORE: 0.5"
_NON_FINITE = "SCORE: " + "9" * 400 + "\nREASONING: degenerate loop"


def _write_dataset(path: Path, n: int = 1) -> Path:
    with path.open("w", encoding="utf-8") as f:
        for i in range(n):
            f.write(
                json.dumps(
                    {
                        "id": f"qa_{i:03d}",
                        "input": f"question {i}",
                        "expected_outputs": [{"kind": "exact", "value": "e"}],
                        "dataset_version": "grid-v1",
                        "provenance": {"source": "synthetic"},
                    }
                )
                + "\n"
            )
    return path


def _write_calibration(path: Path, n: int = 1) -> Path:
    with path.open("w", encoding="utf-8") as f:
        for i in range(n):
            f.write(
                json.dumps(
                    {
                        "id": f"c_{i:03d}",
                        "prompt": f"prompt {i}",
                        "response": "response",
                        "rubric": "rubric",
                        "human_score": 1.0,
                        "provenance": {"source": "synthetic"},
                    }
                )
                + "\n"
            )
    return path


def _invoke(subcommand: str, tmp_path: Path, backend_factory, *, rows: int = 1) -> int:
    """Run one subcommand against a stubbed backend; return its exit code."""
    if subcommand == "run":
        argv = [
            "run",
            "--suite",
            "grid",
            "--dataset",
            str(_write_dataset(tmp_path / "ds.jsonl", rows)),
            "--db",
            str(tmp_path / "runs.db"),
            "--no-diff",
            "--out",
            str(tmp_path / "out.json"),
        ]
    else:
        argv = [
            "calibrate",
            "--calibration",
            str(_write_calibration(tmp_path / "cal.jsonl", rows)),
            "--report",
            str(tmp_path / "report.md"),
            # κ over a 1-row set is degenerate; pin the threshold below every
            # possible value so the *findings* outcome can never be the reason
            # a cell reads exit 1. This test is about translation, not κ.
            "--threshold-kappa",
            "-1.0",
        ]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli, "AnthropicBackend", backend_factory)
        return cli.main(argv)


# --- the grid -------------------------------------------------------------

#: (case id, backend factory, expected exit code). `None` for the exit code
#: means "escapes as an exception" — the pre-#218 behaviour, retained
#: deliberately for the rows this issue does not close.
_TRANSLATED = [
    ("auth", lambda **kw: _FakeBackend(exc=JudgeAuthError("could not authenticate")), 2),
    ("parse-no-score", lambda **kw: _FakeBackend(raw=_NO_SCORE), 2),
    ("parse-no-reasoning", lambda **kw: _FakeBackend(raw=_NO_REASONING), 2),
    ("parse-non-finite", lambda **kw: _FakeBackend(raw=_NON_FINITE), 2),
    ("import-error", None, 2),  # factory built per-test; see `_import_boom`
    ("ok", lambda **kw: _FakeBackend(raw=_OK), 0),
]


def _import_boom(**kwargs):
    raise ImportError(
        "AnthropicBackend requires the optional `judge` extra. "
        "Install with: pip install 'eval-harness[judge]'"
    )


@pytest.mark.parametrize("subcommand", ["run", "calibrate"])
@pytest.mark.parametrize(
    ("case", "factory", "expected_rc"),
    [(c, f, rc) for c, f, rc in _TRANSLATED],
    ids=[c for c, _, _ in _TRANSLATED],
)
def test_judge_seam_exit_code_grid(
    subcommand: str, case: str, factory, expected_rc: int, tmp_path: Path, capsys
) -> None:
    """Every translated cell of the grid, for both judge-building subcommands."""
    rc = _invoke(subcommand, tmp_path, _import_boom if case == "import-error" else factory)
    assert rc == expected_rc, f"{subcommand}/{case}"
    err = capsys.readouterr().err
    if expected_rc == 2:
        # A clean operator-facing line, not a stack. `_fail` owns the prefix.
        assert "::error::" in err, f"{subcommand}/{case} did not emit an ::error:: line"
        assert "Traceback (most recent call last)" not in err


@pytest.mark.parametrize("subcommand", ["run", "calibrate"])
def test_import_error_is_translated_not_raised(subcommand: str, tmp_path: Path, capsys) -> None:
    """A minimal install (no `judge` extra) is a usage error, not a finding.

    Both seams' existing comments already reason about this exception —
    `_run_run` validates the dataset first precisely so the `ImportError`
    cannot mask a dataset error, and `_run_calibrate` names it as a contract
    break — and both then let it escape once their guard clause didn't fire.
    CI installs `.[dev]`, so this is the first thing an operator hits.
    """
    rc = _invoke(subcommand, tmp_path, _import_boom)
    assert rc == 2
    assert "judge` extra" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("subcommand", "label", "failing_id"),
    [("run", "example", "qa_002"), ("calibrate", "row", "c_002")],
)
def test_parse_failure_names_the_failing_row(
    subcommand: str, label: str, failing_id: str, tmp_path: Path, capsys
) -> None:
    """The error names *which* row the judge fumbled, not just the raw output.

    `parse_judge_output` quotes the response but has no id in scope, so on a
    multi-row set the pre-#218 message identified the symptom and not the
    site. The two judge loops are the only frames that know the id.
    """
    backend = _FakeBackend(raw=[_OK, _OK, _NO_SCORE])
    rc = _invoke(subcommand, tmp_path, lambda **kw: backend, rows=3)
    assert rc == 2
    err = capsys.readouterr().err
    assert f"{label} {failing_id!r}" in err
    # The underlying parser message survives the re-raise — the id is added
    # to it, not substituted for it.
    assert "missing SCORE" in err


# --- the boundary this issue deliberately does not cross ------------------

_UNTRANSLATED = [
    ("sdk-400", lambda **kw: _FakeBackend(exc=_FakeStatusError(400))),
    ("sdk-500-exhausted", lambda **kw: _FakeBackend(exc=_FakeStatusError(500))),
    ("byo-backend-valueerror", lambda **kw: _FakeBackend(exc=ValueError("backend bug"))),
    ("byo-backend-typeerror", lambda **kw: _FakeBackend(exc=TypeError("backend bug"))),
]


@pytest.mark.parametrize("subcommand", ["run", "calibrate"])
@pytest.mark.parametrize(("case", "factory"), _UNTRANSLATED, ids=[c for c, _ in _UNTRANSLATED])
def test_remote_and_byo_backend_failures_still_propagate(
    subcommand: str, case: str, factory, tmp_path: Path
) -> None:
    """Pinned, not endorsed.

    A remote backend failure (a non-transient 400, or a 500 that exhausted
    `retry_call`'s budget) is neither operator misconfiguration nor findings,
    and choosing its exit code interacts with the retry budget — that is
    issue #220, not a drive-by here. A bare exception from a **caller's own**
    `Backend` implementation is different again and should keep its
    traceback: swallowing it into exit 2 is how a real bug in someone's
    custom backend gets reported as a usage error.

    Pinning both means #220 has to edit this test on purpose rather than
    change the contract silently.
    """
    with pytest.raises((_FakeStatusError, ValueError, TypeError)):
        _invoke(subcommand, tmp_path, factory)


# --- the population the grid covers ---------------------------------------


def test_only_run_and_calibrate_build_a_judge_backend() -> None:
    """The grid's columns are the whole population, and stay that way.

    A future subcommand that constructs a judge inherits the same seam and
    the same contract; this fails when one appears, which is the moment to
    extend the grid above rather than the moment to discover it in CI.
    """
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    builders = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        and any(isinstance(n, ast.Name) and n.id == "AnthropicBackend" for n in ast.walk(fn))
    }
    # Anti-vacuous: an AST walk that finds nothing would pass a `<=` check.
    assert builders == {"_run_run", "_run_calibrate"}, builders
