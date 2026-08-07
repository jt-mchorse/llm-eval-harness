"""Lock the README's dataset-validator examples to the committed fixture.

The README's "Dataset validator (#56)" section documents two commands
against ``fixtures/broken.jsonl``. Before #196 that file wasn't committed,
so both commands exited 2 (`dataset not found`) on a fresh clone and the
section's whole point — the *findings* output — was undemonstrable.

`tests/test_readme_snapshot.py::test_referenced_files_exist` did not catch
it: its pattern only matches paths inside markdown-link parens `(path)`,
and every path in the README that an operator actually *types* lives in a
```bash fence. That enumeration gap is closed by the sister test
`test_bash_fence_fixture_paths_exist` in that module.

This module locks the *behaviour* rather than mere existence, so the
fixture is a tested artifact and not a second thing to hand-sync:

- Both README commands run verbatim and exit 1.
- The payload carries one finding of each of `parse` / `schema` /
  `duplicate_id` / `version_drift`, each on a specific line.
- `--out` writes that same payload and leaves stdout silent.
- The documented exit-2 contrast really does leave `--out` untouched.

The line-number assertions are deliberate: they anchor the lock to the
*corruption* rather than to a finding count, so an edit that removes one
class of breakage and adds another somewhere else fails here instead of
passing on a coincidental total.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "fixtures" / "broken.jsonl"

# code -> the 1-based line in fixtures/broken.jsonl that provokes it.
EXPECTED_FINDINGS = {
    "parse": 2,
    "schema": 3,
    "duplicate_id": 4,
    "version_drift": 5,
}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI the way the README does, from the repo root.

    Goes through `python -m eval_harness.cli` rather than the
    `eval-harness` console script so the test passes without depending on
    the package being installed in the runner's PATH.
    """
    return subprocess.run(
        [sys.executable, "-m", "eval_harness.cli", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_fixture_is_committed() -> None:
    assert FIXTURE.exists(), (
        "fixtures/broken.jsonl is referenced by the README's validator "
        "section; without it both documented commands exit 2 on a fresh clone"
    )


def test_readme_json_command_exits_1_with_one_of_each_finding_code() -> None:
    """The first documented command: `validate fixtures/broken.jsonl --json`."""
    proc = _run("validate", "fixtures/broken.jsonl", "--json")

    assert proc.returncode == 1, (
        f"README documents exit 1 (findings present); got {proc.returncode}. stderr={proc.stderr!r}"
    )
    payload = json.loads(proc.stdout)

    assert payload["ok"] is False
    assert payload["n_rows"] == 6
    # Not 6 minus the one parse failure: duplicate_id and version_drift rows
    # are rejected too, which is the point the README calls out.
    assert payload["n_valid"] == 2
    assert payload["dataset_version"] == "broken-v0.1"

    by_code = {f["code"]: f["line_no"] for f in payload["findings"]}
    assert by_code == EXPECTED_FINDINGS, (
        "the fixture must provoke exactly one finding of each non-`empty` "
        f"code, on a known line; got {by_code}"
    )

    # `empty` is mutually exclusive with the other four by construction —
    # it only fires when a file yields zero valid rows AND no other finding.
    assert "empty" not in by_code


def test_readme_out_command_writes_the_same_payload_and_silences_stdout(
    tmp_path: Path,
) -> None:
    """The second documented command: the same, plus `--out report.json`."""
    out = tmp_path / "report.json"
    stdout_proc = _run("validate", "fixtures/broken.jsonl", "--json")
    proc = _run("validate", "fixtures/broken.jsonl", "--json", "--out", str(out))

    assert proc.returncode == 1
    assert proc.stdout == "", "README documents `stdout silent` when --out is set"
    assert out.exists(), "--out path was not written on the exit-1 path"
    assert json.loads(out.read_text()) == json.loads(stdout_proc.stdout), (
        "--out must render the same payload the command would have printed"
    )


def test_exit_2_leaves_out_untouched(tmp_path: Path) -> None:
    """The README documents exit 2 as a *contrast* with the exit-1 path.

    Locking it here keeps that sentence honest: a missing dataset must not
    leave a half-written or stale report behind for CI to consume.
    """
    out = tmp_path / "report.json"
    proc = _run("validate", "fixtures/does-not-exist.jsonl", "--json", "--out", str(out))

    assert proc.returncode == 2
    assert not out.exists(), "exit 2 must leave --out untouched"


def test_readme_payload_block_matches_the_live_output() -> None:
    """The README pastes a real payload; keep it the *shipped* payload.

    Compares the fenced ```json block that follows the documented command
    against live output, so a change to the fixture or to the report shape
    can't leave the README quietly describing an older run.
    """
    readme = (REPO_ROOT / "README.md").read_text()
    marker = "eval-harness validate fixtures/broken.jsonl --json\n"
    assert marker in readme, "README no longer documents the validator command verbatim"

    after = readme.split(marker, 1)[1]
    _, _, rest = after.partition("```json\n")
    documented, _, _ = rest.partition("```")
    assert documented.strip(), "README's validator section has no ```json payload block"

    live = json.loads(_run("validate", "fixtures/broken.jsonl", "--json").stdout)
    assert json.loads(documented) == live, (
        "the README's pasted payload has drifted from what the command prints"
    )
