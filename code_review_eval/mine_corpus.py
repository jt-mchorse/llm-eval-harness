"""Mine a real public Python repo for code-review eval rows with verifiable labels.

Labeling method (no hand-authored ground truth, no synthetic bugs):

  DEFECT rows  - take an upstream bug-fix commit and REVERSE its diff. The result
                 is a patch that reintroduces a defect the project itself already
                 identified and fixed. Ground truth is the upstream fix message,
                 and anyone can verify it by reading the cited SHA.

  CLEAN rows   - take a docs/comment/formatting-only commit as-is. Nothing here
                 should be flagged as a defect. These carry the false-positive
                 signal, which is the metric the CI use case actually cares about.

Emits JSONL conforming to eval-harness docs/dataset-format.md.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

FIX_RE = re.compile(
    r"^(fix|bugfix)\b|^fix[(:]|\bfixes #\d+|\bcloses #\d+|\bresolves #\d+",
    re.IGNORECASE,
)
# Messages that look like fixes but carry no defect signal. Plurals matter:
# an earlier pass let "Fix typos discovered by codespell" through because
# \btypo\b does not match "typos", and it produced a mislabeled defect row.
FIX_NOISE_RE = re.compile(
    r"\b(typos?|spellings?|codespell|docs?|documentation|changelog|lint(ing)?|"
    r"formatting|format|whitespace|spaces?|indent(ation)?|flake8|pep8|style|"
    r"cosmetic|wording|error message|comments?|rename|refactor|link)\b",
    re.IGNORECASE,
)
DOC_SUFFIXES = {".md", ".rst", ".txt"}

# A subject must say what broke. "fix", "fix models.py" and "fix adapters.py"
# are all real commit messages in psf/requests and none of them can ground a
# label - there is nothing for the reviewer's answer to be checked against.
def subject_has_substance(subj: str, path: str) -> bool:
    s = subj.lower()
    s = re.sub(r"\(#\d+\)", " ", s)                      # PR refs
    s = re.sub(r"\b(fix(es|ed|ing)?|bugfix)\b", " ", s)  # the verb itself
    s = s.replace(Path(path).name.lower(), " ")          # "models.py"
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return len(s) >= 15 and len(s.split()) >= 3


def changes_executable_code(diff: str) -> bool:
    """True only if the diff adds/removes a line that is real code.

    The message filter is necessary but not sufficient - a commit can be
    honestly titled "fix X" and still only touch comments or a docstring.
    A defect row whose diff changes no executable line has no defect to find,
    so the reviewer is being asked an unanswerable question.
    """
    for ln in diff.splitlines():
        if not ln.startswith(("+", "-")) or ln.startswith(("+++", "---")):
            continue
        body = ln[1:].strip()
        if not body:
            continue
        if body.startswith("#"):
            continue
        # Bare docstring / string-literal-only lines.
        if re.fullmatch(r'["\']{1,3}.*?["\']{1,3},?', body):
            continue
        if body in ('"""', "'''"):
            continue
        return True
    return False


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    ).stdout


def commit_files(repo: Path, sha: str) -> list[str]:
    out = git(repo, "show", "--pretty=", "--name-only", sha)
    return [ln for ln in out.splitlines() if ln.strip()]


def commit_diff(repo: Path, sha: str) -> str:
    # -U3 keeps rows readable; --no-prefix reads more like a review payload.
    return git(repo, "show", sha, "--no-prefix", "-U3", "--pretty=")


def diff_size(diff: str) -> int:
    return sum(1 for ln in diff.splitlines() if ln.startswith(("+", "-")))


def reverse_diff(diff: str) -> str:
    """Flip a unified diff so it reintroduces what the fix removed."""
    out = []
    for ln in diff.splitlines():
        if ln.startswith("+++") or ln.startswith("---"):
            out.append(ln)
        elif ln.startswith("+"):
            out.append("-" + ln[1:])
        elif ln.startswith("-"):
            out.append("+" + ln[1:])
        elif ln.startswith("@@"):
            # Hunk headers stay; line counts swap but reviewers read context, not offsets.
            out.append(ln)
        else:
            out.append(ln)
    return "\n".join(out)


def subject(repo: Path, sha: str) -> str:
    return git(repo, "log", "-1", "--pretty=%s", sha).strip()


def body(repo: Path, sha: str) -> str:
    return git(repo, "log", "-1", "--pretty=%b", sha).strip()


def build_input(diff: str) -> str:
    """The row carries the diff and nothing else.

    An earlier version embedded the review instruction here, including "if the
    change is safe, say so and do not invent issues" - which is precisely the
    treatment arm's intervention. Baking it into every row handed the control
    arm the treatment, and the two arms would have measured nothing. Task
    framing belongs to the arm's system prompt, not the dataset.
    """
    return "```diff\n" + diff.strip() + "\n```"


SRC_PREFIXES = ("src/requests/", "requests/")


def mine(repo: Path, max_lines: int, want_defect: int, want_clean: int, scan: int):
    shas = git(repo, "log", "--no-merges", f"-n{scan}", "--pretty=%H").split()
    defects, cleans = [], []

    for sha in shas:
        if len(defects) >= want_defect and len(cleans) >= want_clean:
            break
        try:
            files = commit_files(repo, sha)
        except subprocess.CalledProcessError:
            continue
        if not files:
            continue
        subj = subject(repo, sha)

        py = [f for f in files if f.endswith(".py")]
        docs = [f for f in files if Path(f).suffix.lower() in DOC_SUFFIXES]

        # --- DEFECT candidates: real .py bug fixes, small, single-file ---------
        # Test-file changes are excluded: a defect reintroduced into a test
        # asserts nothing about production behavior, so the label is weak.
        is_test = any(
            f.startswith("tests/") or Path(f).name.startswith("test_") for f in files
        )
        # Library source only. docs/conf.py and setup.py are .py but changing
        # them cannot produce the runtime defect the reviewer is asked to find.
        in_pkg = all(f.startswith(SRC_PREFIXES) for f in py) if py else False
        if (
            len(defects) < want_defect
            and len(files) == 1
            and py
            and not is_test
            and in_pkg
            and FIX_RE.search(subj)
            and not FIX_NOISE_RE.search(subj)
            and subject_has_substance(subj, files[0])
        ):
            d = commit_diff(repo, sha)
            if 4 <= diff_size(d) <= max_lines and changes_executable_code(d):
                defects.append(
                    {
                        "sha": sha,
                        "subject": subj,
                        "body": body(repo, sha)[:400],
                        "diff": reverse_diff(d),
                        "file": files[0],
                    }
                )
                continue

        # --- CLEAN candidates: docs-only, nothing to flag ---------------------
        if len(cleans) < want_clean and docs and not py and len(files) <= 2:
            d = commit_diff(repo, sha)
            if 4 <= diff_size(d) <= max_lines:
                cleans.append(
                    {"sha": sha, "subject": subj, "diff": d, "file": files[0]}
                )

    return defects, cleans


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--slug", required=True, help="e.g. psf/requests")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--version", default="code-review-v1")
    ap.add_argument("--max-lines", type=int, default=60)
    ap.add_argument("--defects", type=int, default=15)
    ap.add_argument("--clean", type=int, default=10)
    ap.add_argument("--scan", type=int, default=4000)
    ap.add_argument("--src-prefix", default="src/requests/,requests/")
    a = ap.parse_args()
    global SRC_PREFIXES
    SRC_PREFIXES = tuple(x for x in a.src_prefix.split(",") if x)

    defects, cleans = mine(a.repo, a.max_lines, a.defects, a.clean, a.scan)
    today = date.today().isoformat()
    rows = []

    for i, d in enumerate(defects, 1):
        rows.append(
            {
                "id": f"cr_defect_{i:02d}",
                "input": build_input(d["diff"]),
                "expected_outputs": [
                    {
                        "kind": "semantic",
                        "value": (
                            "The reviewer identifies a real defect in this change. "
                            f"Upstream fixed it with: {d['subject']}"
                        ),
                    }
                ],
                "tags": ["defect", "python", Path(d["file"]).stem],
                "dataset_version": a.version,
                "provenance": {
                    "repo": a.slug,
                    "fix_commit": d["sha"],
                    "upstream_subject": d["subject"],
                    "upstream_body": d["body"],
                    "reviewed_file": d["file"],
                    "method": "reverse-applied upstream bug-fix diff",
                    "label_basis": "upstream project identified and fixed this defect",
                    "mined_on": today,
                },
            }
        )

    for i, c in enumerate(cleans, 1):
        rows.append(
            {
                "id": f"cr_clean_{i:02d}",
                "input": build_input(c["diff"]),
                "expected_outputs": [
                    {
                        "kind": "semantic",
                        "value": (
                            "The reviewer reports no runtime defect and does not "
                            "invent issues. This is a documentation-only change."
                        ),
                    }
                ],
                "tags": ["clean", "docs", "false-positive-probe"],
                "dataset_version": a.version,
                "provenance": {
                    "repo": a.slug,
                    "commit": c["sha"],
                    "upstream_subject": c["subject"],
                    "reviewed_file": c["file"],
                    "method": "documentation-only commit, applied forward",
                    "label_basis": "touches no executable code",
                    "mined_on": today,
                },
            }
        )

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")

    print(f"defects={len(defects)} clean={len(cleans)} total={len(rows)} -> {a.out}")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
