"""Lock tests for #104: the read-side CLI subcommands (`list` / `diff` /
`diff-json` / `comment`) translate data-layer exceptions into a clean
`::error::` line on stderr + exit 2, instead of letting them escape as a raw
traceback.

Before the fix each of these inputs raised an uncaught
`ValueError` / `KeyError` / `FileNotFoundError` out of `cli.main`, breaking the
CLI's `0 = clean / 1 = findings|regression / 2 = I/O or usage error` exit
contract (the contract `validate` and `run` already honor). The
success-path guards at the bottom pin the unchanged exit-0 / exit-1 behavior so
the error translation can't silently swallow a real diff result.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness import runs
from eval_harness.cli import main


def _seed_one_run(db: Path, *, run_id: str, suite: str = "s") -> None:
    with runs.connect(db) as conn:
        runs.init_db_on(conn)
        runs.write_run(
            conn,
            run_id=run_id,
            started_at="2026-01-01T00:00:00Z",
            suite=suite,
            dataset_version="v0.1",
            judge_model="fake",
            judge_kappa=0.8,
            mean_score=0.9,
            n_rows=1,
            git_sha=None,
            rows=[("ex1", 0.9, "ok")],
        )


def _run_result_json(path: Path, *, run_id: str, score: float = 0.9) -> None:
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "started_at": "2026-01-01T00:00:00Z",
                "suite": "s",
                "mean_score": score,
                "n_rows": 1,
                "rows": [{"example_id": "ex1", "score": score, "reasoning": "ok"}],
            }
        ),
        encoding="utf-8",
    )


# --- error translation: every read-side path → ::error:: + exit 2 -----------


@pytest.mark.parametrize("limit", ["0", "-3"])
def test_list_bad_limit_exits_two(tmp_path: Path, capsys, limit: str) -> None:
    db = tmp_path / "r.db"
    with runs.connect(db) as conn:
        runs.init_db_on(conn)
    rc = main(["list", "--db", str(db), "--limit", limit])
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


def test_diff_unknown_run_exits_two(tmp_path: Path, capsys) -> None:
    db = tmp_path / "r.db"
    _seed_one_run(db, run_id="real")
    rc = main(["diff", "--db", str(db), "--current", "nope", "--baseline", "real"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "nope" in err


def test_diff_json_missing_file_exits_two(tmp_path: Path, capsys) -> None:
    rc = main(
        ["diff-json", "--current", str(tmp_path / "a.json"), "--baseline", str(tmp_path / "b.json")]
    )
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


def test_diff_json_corrupt_payload_exits_two(tmp_path: Path, capsys) -> None:
    # A non-finite row score is rejected by load_run_result_from_json (ValueError);
    # it must surface as a clean exit 2, not a traceback. `json.loads` parses the
    # bare `NaN` token natively, so this is a reachable on-disk corruption.
    cur = tmp_path / "cur.json"
    cur.write_text(
        '{"run_id":"c","started_at":"t","suite":"s","mean_score":0.9,'
        '"rows":[{"example_id":"ex1","score":NaN,"reasoning":"x"}]}',
        encoding="utf-8",
    )
    base = tmp_path / "base.json"
    _run_result_json(base, run_id="b")
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


def test_diff_json_invalid_json_exits_two(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    base = tmp_path / "base.json"
    _run_result_json(base, run_id="b")
    rc = main(["diff-json", "--current", str(bad), "--baseline", str(base)])
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


def test_comment_missing_file_exits_two(tmp_path: Path, capsys) -> None:
    rc = main(
        [
            "comment",
            "--repo",
            "o/n",
            "--pr",
            "1",
            "--delta-json",
            str(tmp_path / "d.json"),
            "--dry-run",
        ]
    )
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


# --- success-path regression guards: exit 0/1 unchanged ---------------------


def test_diff_json_success_path_unchanged(tmp_path: Path, capsys) -> None:
    # Two identical runs → no regression → exit 0 (the error translation must not
    # swallow a legitimate diff result).
    cur = tmp_path / "cur.json"
    base = tmp_path / "base.json"
    _run_result_json(cur, run_id="c", score=0.9)
    _run_result_json(base, run_id="b", score=0.9)
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 0
    assert "::error::" not in capsys.readouterr().err


def test_diff_json_regression_still_exits_one(tmp_path: Path, capsys) -> None:
    # A real regression (score drops past the default 0.1 threshold) must still
    # exit 1 — the flagged-row exit code is not collapsed into the error path.
    cur = tmp_path / "cur.json"
    base = tmp_path / "base.json"
    _run_result_json(cur, run_id="c", score=0.2)
    _run_result_json(base, run_id="b", score=0.9)
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 1


# --- #116: null run_id / null summary count must not escape as a raw TypeError -----


def _delta_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _comment_dry_run(delta: Path) -> list[str]:
    return ["comment", "--repo", "o/n", "--pr", "1", "--delta-json", str(delta), "--dry-run"]


@pytest.mark.parametrize("fmt", ["ascii", "markdown"])
def test_diff_json_null_run_id_exits_two(tmp_path: Path, capsys, fmt: str) -> None:
    # A null run_id in a RunResult JSON reached `run_id[:8]` in the delta renderers
    # and raised an uncaught TypeError (exit 1). `json` can't emit a bare null run
    # field except by hand-editing, but that's exactly the corrupt-artifact threat
    # model the finiteness guards already cover. Must now fail clean → exit 2.
    cur = tmp_path / "cur.json"
    cur.write_text(
        json.dumps(
            {
                "run_id": None,
                "started_at": "2026-01-01T00:00:00Z",
                "suite": "s",
                "mean_score": 0.9,
                "n_rows": 1,
                "rows": [{"example_id": "ex1", "score": 0.9, "reasoning": "ok"}],
            }
        ),
        encoding="utf-8",
    )
    base = tmp_path / "base.json"
    _run_result_json(base, run_id="b")
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base), "--format", fmt])
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


# --- #160: container/null-typed numeric field must not escape as a raw TypeError --


@pytest.mark.parametrize("bad", [[1, 2], {"x": 1}, None])
def test_diff_json_container_score_exits_two(tmp_path: Path, capsys, bad) -> None:
    # A container/null-typed per-row `score` reached a bare `float(r["score"])`
    # and raised an uncaught TypeError (exit 1) — #150/#156 guarded the container
    # *shape*, not the scalar numeric coercion. Must now fail clean → exit 2.
    cur = tmp_path / "cur.json"
    cur.write_text(
        json.dumps(
            {
                "run_id": "a",
                "started_at": "2026-01-01T00:00:00Z",
                "suite": "s",
                "mean_score": 0.9,
                "n_rows": 1,
                "rows": [{"example_id": "ex1", "score": bad, "reasoning": "ok"}],
            }
        ),
        encoding="utf-8",
    )
    base = tmp_path / "base.json"
    _run_result_json(base, run_id="b")
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "score must be a number" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("field", ["mean_score", "n_rows"])
def test_diff_json_container_top_level_number_exits_two(tmp_path: Path, capsys, field: str) -> None:
    # `mean_score` (float) and `n_rows` (int) fed a bare float()/int() too — a
    # container value raised an uncaught TypeError at exit 1. Must be exit 2.
    payload = {
        "run_id": "a",
        "started_at": "2026-01-01T00:00:00Z",
        "suite": "s",
        "mean_score": 0.9,
        "n_rows": 1,
        "rows": [{"example_id": "ex1", "score": 0.9, "reasoning": "ok"}],
    }
    payload[field] = [1, 2]
    cur = tmp_path / "cur.json"
    cur.write_text(json.dumps(payload), encoding="utf-8")
    base = tmp_path / "base.json"
    _run_result_json(base, run_id="b")
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert f"{field} must be a number" in err
    assert "Traceback" not in err


def test_comment_container_threshold_drop_exits_two(tmp_path: Path, capsys) -> None:
    # `threshold_drop` fed a bare float() in DeltaReport.from_json — a container
    # value raised an uncaught TypeError at exit 1. Must be exit 2.
    delta = tmp_path / "d.json"
    _delta_json(
        delta,
        {
            "current_run_id": "c",
            "baseline_run_id": "b",
            "suite": "s",
            "threshold_drop": [0.1],
            "rows": [],
            "summary": {},
        },
    )
    rc = main(_comment_dry_run(delta))
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "threshold_drop must be a number" in err
    assert "Traceback" not in err


def test_comment_container_mean_delta_exits_two(tmp_path: Path, capsys) -> None:
    # `summary.mean_delta` fed a bare float() — a container value raised an
    # uncaught TypeError at exit 1. Must be exit 2.
    delta = tmp_path / "d.json"
    _delta_json(
        delta,
        {
            "current_run_id": "c",
            "baseline_run_id": "b",
            "suite": "s",
            "threshold_drop": 0.1,
            "rows": [],
            "summary": {"mean_delta": [0.0]},
        },
    )
    rc = main(_comment_dry_run(delta))
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "mean_delta must be a number" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("field", ["baseline_score", "current_score", "delta"])
def test_comment_container_row_score_exits_two(tmp_path: Path, capsys, field: str) -> None:
    # A container-typed per-row score field fed `_finite_or_none`'s bare float()
    # — an uncaught TypeError at exit 1. Must be exit 2.
    row = {
        "example_id": "ex1",
        "status": "changed",
        "baseline_score": 0.8,
        "current_score": 0.9,
        "delta": 0.1,
        "flagged": False,
    }
    row[field] = [1, 2]
    delta = tmp_path / "d.json"
    _delta_json(
        delta,
        {
            "current_run_id": "c",
            "baseline_run_id": "b",
            "suite": "s",
            "threshold_drop": 0.1,
            "rows": [row],
            "summary": {},
        },
    )
    rc = main(_comment_dry_run(delta))
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert f"{field} must be a number" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("field", ["current_run_id", "baseline_run_id"])
def test_comment_null_run_id_exits_two(tmp_path: Path, capsys, field: str) -> None:
    # A present-null current/baseline run id in a delta JSON reached
    # `current_run_id[:8]` in render_delta_markdown (TypeError, exit 1). Must
    # surface via DeltaReport.from_json as a clean ValueError → exit 2.
    payload = {
        "current_run_id": "c",
        "baseline_run_id": "b",
        "suite": "s",
        "threshold_drop": 0.1,
        "rows": [],
        "summary": {},
    }
    payload[field] = None
    delta = tmp_path / "d.json"
    _delta_json(delta, payload)
    rc = main(_comment_dry_run(delta))
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert field in err


# --- #120: null / non-string per-row example_id must not escape the exit-2 contract ----


@pytest.mark.parametrize("fmt", ["ascii", "markdown", "json"])
def test_diff_json_null_example_id_exits_two(tmp_path: Path, capsys, fmt: str) -> None:
    # A present-null example_id in a RunResult JSON became a `None` dict key, then
    # `diff_runs`' `sorted(set(current.rows) | set(baseline.rows))` raised an
    # uncaught TypeError ('<' not supported between str and NoneType) — exit 1,
    # bypassing the exit-2 fail-clean contract. `load_run_result_from_json` must
    # now reject it as a clean ValueError → exit 2. Same corrupt-artifact threat
    # model as the null run_id lock above.
    cur = tmp_path / "cur.json"
    cur.write_text(
        json.dumps(
            {
                "run_id": "c",
                "started_at": "2026-01-01T00:00:00Z",
                "suite": "s",
                "mean_score": 0.9,
                "n_rows": 1,
                "rows": [{"example_id": None, "score": 0.9, "reasoning": "ok"}],
            }
        ),
        encoding="utf-8",
    )
    base = tmp_path / "base.json"
    _run_result_json(base, run_id="b")
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base), "--format", fmt])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "example_id" in err


def test_comment_null_example_id_exits_two(tmp_path: Path, capsys) -> None:
    # A present-null per-row example_id in a delta JSON otherwise flowed through
    # RowDelta.from_json into render_delta_markdown and posted the literal string
    # "None" as the row id in the PR comment (exit 0, silently wrong). Must now
    # surface via RowDelta.from_json as a clean ValueError → exit 2, never the
    # silent "None" row.
    delta = tmp_path / "d.json"
    _delta_json(
        delta,
        {
            "current_run_id": "c",
            "baseline_run_id": "b",
            "suite": "s",
            "threshold_drop": 0.1,
            "rows": [
                {
                    "example_id": None,
                    "status": "new",
                    "baseline_score": None,
                    "current_score": 0.9,
                    "delta": None,
                    "flagged": False,
                }
            ],
            "summary": {"n_new": 1},
        },
    )
    rc = main(_comment_dry_run(delta))
    assert rc == 2
    captured = capsys.readouterr()
    assert "::error::" in captured.err
    assert "example_id" in captured.err
    # The clean failure must replace the silent "None" row, not sit alongside it.
    assert "None" not in captured.out


@pytest.mark.parametrize(
    "count_key",
    ["n_flagged", "n_regressed", "n_improved", "n_unchanged", "n_new", "n_removed"],
)
def test_comment_null_summary_count_renders_clean(tmp_path: Path, capsys, count_key: str) -> None:
    # A present-null summary count reached `int(None)` in render_delta_markdown
    # (TypeError, exit 1) — the count siblings of the already-guarded mean_delta.
    # Coerced to 0: the comment renders and exits 0 (dry-run, no flagged rows).
    delta = tmp_path / "d.json"
    _delta_json(
        delta,
        {
            "current_run_id": "c",
            "baseline_run_id": "b",
            "suite": "s",
            "threshold_drop": 0.1,
            "rows": [],
            "summary": {count_key: None},
        },
    )
    rc = main(_comment_dry_run(delta))
    assert rc == 0
    out = capsys.readouterr().out
    assert "::error::" not in out
    # The coerced count renders as 0, never the literal "None".
    assert "None" not in out


def test_render_delta_ascii_null_count_renders_zero_not_none() -> None:
    # render_delta_ascii isn't reachable with a null count via diff-json (diff_runs
    # always emits int counts), but it's a public renderer and was interpolating a
    # present-null count as the literal string "None" — the silent-output sibling of
    # the markdown TypeError. Lock the coercion to 0 directly.
    from eval_harness.runner import DeltaReport, render_delta_ascii

    report = DeltaReport(
        current_run_id="cccccccccc",
        baseline_run_id="bbbbbbbbbb",
        suite="s",
        threshold_drop=0.1,
        rows=(),
        summary={"n_regressed": None, "n_flagged": None},
    )
    out = render_delta_ascii(report)
    assert "regressed=0" in out
    assert "flagged=0" in out
    assert "None" not in out


# --- #122: `drift` is the last user-facing subcommand outside the exit-2 contract ----
#
# `drift.cli` delegated straight to `_load_inputs_jsonl` / `compute_drift` with no
# exception translation, so a missing input path (FileNotFoundError), an empty input
# or zero valid rows (ValueError: "no inputs loaded"), and malformed JSON (ValueError,
# already wrapped from json.JSONDecodeError by `_load_inputs_jsonl`) each escaped
# `cli.main` as a raw exit-1 traceback — bypassing the `2 = I/O or usage error`
# contract the read-side subcommands above already uphold. All three were reproduced
# firsthand on pre-fix code; these locks were confirmed failing (exit 1, traceback)
# before the `drift.cli` guard was added.


def _drift_argv(golden: Path, candidate: Path, output: Path) -> list[str]:
    # `--judge-stub` keeps the run hermetic (no Anthropic backend); the error paths
    # under test all fire during input loading, before the judge is ever consulted.
    return [
        "drift",
        "--golden",
        str(golden),
        "--candidate",
        str(candidate),
        "--output",
        str(output),
        "--judge-stub",
    ]


def _valid_inputs_jsonl(path: Path) -> None:
    path.write_text('"a quick brown fox"\n"the lazy dog sleeps here"\n', encoding="utf-8")


@pytest.mark.parametrize("side", ["golden", "candidate"])
def test_drift_missing_input_exits_two(tmp_path: Path, capsys, side: str) -> None:
    # A missing --golden/--candidate path leaked a raw FileNotFoundError (exit 1);
    # must now fail clean. Both sides are checked so a one-sided guard can't pass.
    good = tmp_path / "good.jsonl"
    _valid_inputs_jsonl(good)
    missing = tmp_path / "nope.jsonl"
    golden, candidate = (missing, good) if side == "golden" else (good, missing)
    rc = main(_drift_argv(golden, candidate, tmp_path / "r.html"))
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("side", ["golden", "candidate"])
def test_drift_empty_input_exits_two(tmp_path: Path, capsys, side: str) -> None:
    # An empty input (zero valid rows) raised ValueError "no inputs loaded" (exit 1).
    good = tmp_path / "good.jsonl"
    _valid_inputs_jsonl(good)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    golden, candidate = (empty, good) if side == "golden" else (good, empty)
    rc = main(_drift_argv(golden, candidate, tmp_path / "r.html"))
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("side", ["golden", "candidate"])
def test_drift_invalid_json_exits_two(tmp_path: Path, capsys, side: str) -> None:
    # Malformed JSON leaked a ValueError wrapping json.JSONDecodeError (exit 1).
    good = tmp_path / "good.jsonl"
    _valid_inputs_jsonl(good)
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not valid json\n", encoding="utf-8")
    golden, candidate = (bad, good) if side == "golden" else (good, bad)
    rc = main(_drift_argv(golden, candidate, tmp_path / "r.html"))
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "Traceback" not in err


def test_drift_valid_inputs_exits_zero(tmp_path: Path, capsys) -> None:
    # Success-path guard: the error translation must not swallow a real run. Two
    # valid input files write the HTML report and exit 0 (the contract's clean case).
    good = tmp_path / "good.jsonl"
    _valid_inputs_jsonl(good)
    out = tmp_path / "r.html"
    rc = main(_drift_argv(good, good, out))
    assert rc == 0
    assert "::error::" not in capsys.readouterr().err
    assert out.exists()


# --- #124: `comment` leaked a RuntimeError (exit 1) on missing GITHUB_TOKEN -----
#
# The `upsert_sticky_comment` call in `_run_comment` sits OUTSIDE the delta-load
# try/except. With no GITHUB_TOKEN/GH_TOKEN, `_resolve_token` raises RuntimeError,
# which escaped `main` as a raw exit-1 traceback — breaking the `2 = I/O or usage
# error` contract the read-side subcommands already uphold. The token path is
# network-free (the check fires before any HTTP call), so it's deterministically
# testable. These locks were confirmed failing (exit 1, traceback) on pre-fix code.


def _valid_delta_json(path: Path) -> None:
    # A minimal, fully-valid delta payload: renders clean (no flagged rows → the
    # render step and exit code are not under test here; the token failure is).
    _delta_json(
        path,
        {
            "current_run_id": "cccccccccc",
            "baseline_run_id": "bbbbbbbbbb",
            "suite": "s",
            "threshold_drop": 0.1,
            "rows": [],
            "summary": {
                "n_flagged": 0,
                "n_regressed": 0,
                "n_improved": 0,
                "n_unchanged": 0,
                "n_new": 0,
                "n_removed": 0,
            },
        },
    )


def _comment_live(delta: Path) -> list[str]:
    # Non-dry-run: this is the path that resolves a token and calls the API.
    return ["comment", "--repo", "o/n", "--pr", "1", "--delta-json", str(delta)]


def test_comment_missing_token_exits_two(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    delta = tmp_path / "d.json"
    _valid_delta_json(delta)
    rc = main(_comment_live(delta))
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "token missing" in err
    assert "Traceback" not in err


def test_comment_dry_run_success_path_unchanged(tmp_path: Path, capsys, monkeypatch) -> None:
    # Companion regression: even with no token, `--dry-run` never resolves one, so
    # it still renders and exits 0 — the error translation must not perturb it.
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    delta = tmp_path / "d.json"
    _valid_delta_json(delta)
    rc = main(_comment_dry_run(delta))
    assert rc == 0
    assert "::error::" not in capsys.readouterr().err


# --- #126: `calibrate` leaked a raw traceback (exit 1) on a missing/malformed ---
# calibration file -------------------------------------------------------------
#
# `_run_calibrate` called `load_calibration(args.calibration)` with no error
# translation — the one subcommand left out of the #104/#110/#116/#122/#124
# exit-code sweep. A missing file (FileNotFoundError) or a malformed row
# (CalibrationLoadError, a ValueError subclass) escaped `cli.main` as a raw
# traceback at exit 1, breaking the `2 = I/O or usage error` contract. The load
# fires before the judge backend is constructed, so these are hermetic (no API
# key, no `judge` extra). These locks were confirmed failing (exit 1, traceback)
# on pre-fix code. calibrate's exit 1 is reserved for "Cohen's κ < threshold"
# (a findings outcome), so a load/usage failure must map to 2, not 1.


def test_calibrate_missing_file_exits_two(tmp_path: Path, capsys) -> None:
    rc = main(["calibrate", "--calibration", str(tmp_path / "nope.jsonl")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "calibration not found" in err
    assert "Traceback" not in err


def test_calibrate_malformed_row_exits_two(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{ not valid json\n", encoding="utf-8")
    rc = main(["calibrate", "--calibration", str(bad)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "invalid JSON" in err
    assert "Traceback" not in err


def test_calibrate_empty_but_valid_file_exits_two(tmp_path: Path, capsys) -> None:
    # Issue #128: an empty-but-valid (0-row) calibration file loads cleanly, so
    # the #126 load-seam catch does not fire. Without the guard it reached
    # `calibrate(judge, [])` → ValueError (exit 1 traceback) or, in a minimal
    # install, AnthropicBackend ImportError — both break the `2 = usage error`
    # contract. The zero-row check must report exit 2 + ::error::, hermetically.
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    rc = main(["calibrate", "--calibration", str(empty)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert "no rows to calibrate against" in err
    assert str(empty) in err
    assert "Traceback" not in err


def test_calibrate_empty_file_does_not_construct_backend(tmp_path: Path, monkeypatch) -> None:
    # Hermeticity guard: the zero-row check fires *before* the backend, so the
    # empty-file path must never touch AnthropicBackend (which needs the `judge`
    # extra / API key). If construction were reached this sentinel would raise.
    import eval_harness.cli as cli

    def _boom(*_a, **_k):  # pragma: no cover - reached only on regression
        raise AssertionError("backend constructed on an empty calibration set")

    monkeypatch.setattr(cli, "AnthropicBackend", _boom)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert main(["calibrate", "--calibration", str(empty)]) == 2


def test_calibrate_load_translation_does_not_swallow_downstream_valueerror(
    tmp_path: Path, monkeypatch
) -> None:
    # Over-rejection / scoping guard: the new try/except wraps ONLY the
    # `load_calibration` line, so a ValueError raised *downstream* (e.g. backend
    # construction, `calibrate()` on a degenerate set, report rendering) must
    # still propagate — it must NOT be masked as an exit-2 usage error, which
    # would hide a real bug. We let the load succeed and make the next step raise
    # a sentinel ValueError; if the catch were too broad it would translate it to
    # 2 instead of letting it escape.
    import eval_harness.cli as cli

    monkeypatch.setattr(cli, "load_calibration", lambda _path: ["sentinel-row"])

    def _boom(*_a, **_k):
        raise ValueError("downstream sentinel — not a load error")

    monkeypatch.setattr(cli, "AnthropicBackend", _boom)

    with pytest.raises(ValueError, match="downstream sentinel"):
        main(["calibrate", "--calibration", str(tmp_path / "ignored.jsonl")])


# --- #150: valid-JSON-but-not-an-object payloads must not escape as a raw
# AttributeError/TypeError -----------------------------------------------------
# `json.loads` happily returns a bare list/number/string/null; the loaders then
# did `payload.get(...)` / `r["example_id"]` with no `isinstance(..., dict)`
# guard, leaking an uncaught AttributeError/TypeError (exit 1) that the CLI catch
# blocks — tuned for ValueError/KeyError — never translated. The four guards
# (top-level + per-row in both the run-JSON and delta-JSON loaders) turn every
# shape into a clean exit-2, mirroring `dataset._validate_record`.


@pytest.mark.parametrize("bad", ["[1, 2, 3]", "42", '"a string"', "null"])
def test_diff_json_non_object_payload_exits_two(tmp_path: Path, capsys, bad: str) -> None:
    cur = tmp_path / "cur.json"
    cur.write_text(bad, encoding="utf-8")
    base = tmp_path / "base.json"
    _run_result_json(base, run_id="b")
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


def test_diff_json_non_object_row_exits_two(tmp_path: Path, capsys) -> None:
    # A `rows` array holding a bare string reached `r["example_id"]` and raised
    # `TypeError: string indices must be integers` (exit 1). Now a clean exit 2.
    cur = tmp_path / "cur.json"
    cur.write_text(
        '{"run_id":"c","started_at":"t","suite":"s","mean_score":0.9,"rows":["x"]}',
        encoding="utf-8",
    )
    base = tmp_path / "base.json"
    _run_result_json(base, run_id="b")
    rc = main(["diff-json", "--current", str(cur), "--baseline", str(base)])
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["[1, 2, 3]", "42", '"a string"', "null"])
def test_comment_non_object_delta_exits_two(tmp_path: Path, capsys, bad: str) -> None:
    # `DeltaReport.from_json` did `payload.get(...)` on the parsed value; a bare
    # list/number/string/null raised an uncaught AttributeError (exit 1).
    delta = tmp_path / "delta.json"
    delta.write_text(bad, encoding="utf-8")
    rc = main(_comment_dry_run(delta))
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


def test_comment_non_object_delta_row_exits_two(tmp_path: Path, capsys) -> None:
    # A non-object entry in the delta `rows` array reached `RowDelta.from_json`'s
    # `payload["example_id"]` and raised a raw TypeError (exit 1). Now exit 2.
    delta = tmp_path / "delta.json"
    delta.write_text('{"rows": ["x"]}', encoding="utf-8")
    rc = main(_comment_dry_run(delta))
    assert rc == 2
    assert "::error::" in capsys.readouterr().err


@pytest.mark.parametrize(
    "count_key",
    ["n_flagged", "n_regressed", "n_improved", "n_new", "n_removed", "n_unchanged"],
)
@pytest.mark.parametrize("bad", [[1, 2], {"x": 1}, "abc"])
def test_comment_malformed_summary_count_exits_two(
    tmp_path: Path, capsys, count_key: str, bad
) -> None:
    # A present-but-non-numeric summary count field (a JSON array/object →
    # `int([1,2])` TypeError, or a non-numeric string → `int("abc")` ValueError)
    # reached comment._count's bare `int(v)`; #116 guarded only the null case,
    # and render_delta_markdown runs *outside* _run_comment's exit-2 try, so it
    # escaped as a raw traceback at exit 1. DeltaReport.from_json now validates
    # each count at the parse boundary (sibling of the mean_delta guard) → exit 2.
    delta = tmp_path / "d.json"
    _delta_json(
        delta,
        {
            "current_run_id": "c",
            "baseline_run_id": "b",
            "suite": "s",
            "threshold_drop": 0.1,
            "rows": [],
            "summary": {"mean_delta": 0.0, count_key: bad},
        },
    )
    rc = main(_comment_dry_run(delta))
    assert rc == 2
    err = capsys.readouterr().err
    assert "::error::" in err
    assert count_key in err
    assert "Traceback" not in err


@pytest.mark.parametrize("good", [2, 0, "3", 2.0, None])
def test_comment_valid_summary_count_exits_zero(tmp_path: Path, capsys, good) -> None:
    # A valid integer count (incl. a numeric string, a whole float, a genuine 0,
    # or an explicit null that the renderer coerces to 0) must not regress to a
    # usage error — the comment renders cleanly and --dry-run exits 0.
    delta = tmp_path / "d.json"
    _delta_json(
        delta,
        {
            "current_run_id": "c",
            "baseline_run_id": "b",
            "suite": "s",
            "threshold_drop": 0.1,
            "rows": [],
            "summary": {"mean_delta": 0.0, "n_flagged": good},
        },
    )
    rc = main(_comment_dry_run(delta))
    assert rc == 0
    assert "Traceback" not in capsys.readouterr().err
