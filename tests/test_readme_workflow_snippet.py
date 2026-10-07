"""The README's downstream sticky-comment workflow runs, and comments on a regression (#309).

The block under "Downstream repos ... use the same two CLI steps in their own
workflow" is the only documented consumer path for the sticky comment (#6),
and nothing ran it. It failed at three layers at once: a ``${{ }}`` inside a
flow mapping made it unparseable YAML; plain ``run:`` scalars folded the
backslash continuations into one line, so bash passed ``" --current"`` as a
single argument and argparse exited 2; and ``diff-json`` exits 1 on a flagged
row, so under Actions' ``bash -e`` the comment step never ran on exactly the
PR it is for.

So these arms do what Actions does. They parse the block, then execute each
``run:`` with ``bash -e`` in a scratch tree that has the demo fixtures at the
snippet's paths, with ``${{ }}`` substituted and ``$GITHUB_OUTPUT`` pointing
at a file. ``diff-json`` is the real CLI. ``comment`` is a stub that records
its argv, because it would otherwise call GitHub. A step whose ``if:`` is
false is skipped, the way the runner skips it.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
FIXTURES = REPO_ROOT / "fixtures"

_EXPRESSIONS = {
    "github.repository": "octo/repo",
    "github.event.pull_request.number": "7",
    "secrets.GITHUB_TOKEN": "ghs_stub",
}


def _snippet_text() -> str:
    text = README.read_text(encoding="utf-8")
    anchor = text.index("Downstream repos that import `eval-harness` use the same two")
    start = text.index("```yaml\n", anchor) + len("```yaml\n")
    return text[start : text.index("```", start)]


def _steps() -> list[dict]:
    steps = yaml.safe_load(_snippet_text())
    assert isinstance(steps, list), "the README block is not a list of steps"
    assert steps, "the README block has no steps"
    return steps


def _substitute(script: str) -> str:
    def repl(m: re.Match[str]) -> str:
        return _EXPRESSIONS[m.group(1).strip()]

    return re.sub(r"\$\{\{\s*([^}]+?)\s*\}\}", repl, script)


def _outputs(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return dict(line.split("=", 1) for line in lines if "=" in line)


def _if_holds(cond: str, outputs: dict[str, dict[str, str]]) -> bool:
    # The snippet's only condition shape: steps.<id>.outputs.<key> == '<value>'.
    m = re.fullmatch(r"steps\.(\w+)\.outputs\.(\w+)\s*==\s*'([^']*)'", cond.strip())
    assert m, f"unsupported if: {cond!r}; extend the runner if the README grew one"
    step_id, key, want = m.groups()
    return outputs.get(step_id, {}).get(key) == want


def _run_job(tmp_path: Path, *, current: Path, baseline: Path | None) -> dict:
    """Run the README's steps like a runner: in order, stop at the first failure."""
    work = tmp_path / "work"
    (work / "results").mkdir(parents=True)
    (work / "fixtures").mkdir()
    shutil.copy(current, work / "results" / "current.json")
    if baseline is not None:
        shutil.copy(baseline, work / "fixtures" / "main-baseline.json")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "comment-calls.txt"
    stub = bindir / "eval-harness"
    stub.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = comment ]; then\n'
        f'  printf "%s\\n" "$*" >> "{calls}"\n'
        f'  printf "token=%s\\n" "$GITHUB_TOKEN" >> "{calls}"\n'
        "  exit 0\n"
        "fi\n"
        f'exec "{sys.executable}" -c "import sys; from eval_harness.cli import main; '
        'sys.exit(main(sys.argv[1:]))" "$@"\n',
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)

    delta = tmp_path / "delta.json"
    outputs: dict[str, dict[str, str]] = {}
    ran: list[str] = []
    failed: tuple[str, int] | None = None
    for i, step in enumerate(_steps()):
        name = step.get("name", f"step {i}")
        if "if" in step and not _if_holds(step["if"], outputs):
            continue
        out_file = tmp_path / f"output-{i}.txt"
        env = {
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_OUTPUT": str(out_file),
        }
        env.update({k: _substitute(str(v)) for k, v in (step.get("env") or {}).items()})
        script = _substitute(step["run"]).replace("/tmp/delta.json", str(delta))
        script_path = tmp_path / f"step-{i}.sh"
        script_path.write_text(script, encoding="utf-8")
        proc = subprocess.run(
            ["bash", "-e", str(script_path)],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        ran.append(name)
        if "id" in step:
            outputs[step["id"]] = _outputs(out_file)
        if proc.returncode != 0:
            failed = (name, proc.returncode)
            break
    return {
        "ran": ran,
        "failed": failed,
        "outputs": outputs,
        "comment_calls": calls.read_text(encoding="utf-8").splitlines() if calls.exists() else [],
        "delta_written": delta.exists(),
    }


def test_snippet_parses_and_every_run_keeps_its_line_breaks() -> None:
    steps = _steps()
    runs = [s["run"] for s in steps]
    # A plain scalar folds `\`-continued lines into one; a `|` block keeps them.
    multi = [r for r in runs if "\\" in r]
    assert multi, "no continued command in the snippet; the pattern went stale"
    for r in multi:
        assert "\\\n" in r, f"a run: folded its continuations into one line: {r!r}"


def test_a_flagged_row_still_posts_the_comment_then_fails_the_job(tmp_path: Path) -> None:
    job = _run_job(
        tmp_path,
        current=FIXTURES / "demo_current.json",
        baseline=FIXTURES / "demo_baseline.json",
    )
    assert job["outputs"]["diff"] == {"rc": "1"}
    assert job["delta_written"]
    assert job["comment_calls"], "the comment step never ran"
    assert job["comment_calls"][0].startswith("comment --repo octo/repo --pr 7 --delta-json ")
    assert "token=ghs_stub" in job["comment_calls"]
    assert job["failed"] == ("Fail the job on a flagged row", 1)


def test_a_clean_diff_comments_and_passes(tmp_path: Path) -> None:
    job = _run_job(
        tmp_path,
        current=FIXTURES / "demo_baseline.json",
        baseline=FIXTURES / "demo_baseline.json",
    )
    assert job["outputs"]["diff"] == {"rc": "0"}
    assert len([c for c in job["comment_calls"] if c.startswith("comment ")]) == 1
    assert job["failed"] is None
    assert "Fail the job on a flagged row" not in job["ran"]


def test_bad_input_fails_at_the_diff_step_and_posts_nothing(tmp_path: Path) -> None:
    job = _run_job(tmp_path, current=FIXTURES / "demo_current.json", baseline=None)
    assert job["failed"] == ("Diff against the baseline", 2)
    assert job["comment_calls"] == []


@pytest.mark.parametrize("expr", sorted(_EXPRESSIONS))
def test_every_expression_the_runner_substitutes_is_used(expr: str) -> None:
    # Keeps the substitution table honest: an entry the README no longer uses
    # would mean the arms above stopped exercising part of the block.
    assert re.search(r"\$\{\{\s*" + re.escape(expr) + r"\s*\}\}", _snippet_text())
