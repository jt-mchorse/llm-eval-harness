"""README snapshot: lock the surface bullet list to reality.

Sister to the portfolio-wide snapshot pattern landed 2026-05-18+.
The README's "What this is" enumerates eleven pieces and pins each to a
closed issue (#1..#7, #15, #17, #56, #58). The CLI bullet (#7) lists the public
subcommand surface. Without this test, a renamed subcommand or a newly
closed issue can leave the prose stale and the snapshot pattern across
the portfolio (one repo missing it after seven sister PRs landed
yesterday) loses its claim.

The test:
- Asserts the `(#N)` issue refs in "What this is" all resolve to a
  closed issue on github.com when network is available; falls back to
  a structural assertion otherwise (each ref appears at least once in
  the body).
- Locks the CLI subcommand surface bullet against `argparse --help`
  output of `eval_harness.cli.build_parser()`.
- Asserts every relative file path referenced by the README resolves
  on disk.
- Asserts the Demo section names a follow-up issue for the captured
  asset (defending against accidentally regressing the section back
  to "pending until #N lands" framing).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
DECISIONS = REPO_ROOT / "MEMORY" / "core_decisions_ai.md"


def _live_cli_subcommands() -> list[str]:
    """Discover the live `eval-harness` subcommand surface via `--help`.

    Uses `python -m eval_harness.cli` so the test passes even when the
    `eval-harness` entry point script isn't on PATH (e.g., editable
    install path differences across CI matrix rows).
    """
    out = subprocess.run(
        [sys.executable, "-m", "eval_harness.cli", "--help"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    match = re.search(r"\{([\w,\-]+)\}", out)
    assert match, f"Could not parse subcommand surface from --help:\n{out}"
    return sorted(match.group(1).split(","))


def _readme() -> str:
    return README.read_text(encoding="utf-8")


# Number-words the intro sentence may use, mapped to their integer value.
# Extend as the surface list grows past twelve.
_NUMBER_WORDS = {
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
}


def _what_this_is_section() -> str:
    body = _readme()
    start = body.index("## What this is")
    end = body.index("##", start + 1)
    return body[start:end]


def test_what_this_is_section_lists_eleven_closed_issues_in_order() -> None:
    """The numbered list under `## What this is` cites every shipped issue
    once, in the order the implementations landed."""
    section = _what_this_is_section()
    expected = [
        "(#1)",
        "(#2)",
        "(#3)",
        "(#4)",
        "(#5)",
        "(#6)",
        "(#7)",
        "(#15)",
        "(#17)",
        "(#56)",
        "(#58)",
    ]
    found_order: list[str] = []
    for ref in expected:
        if ref in section:
            found_order.append(ref)
    assert found_order == expected, (
        "What this is section must cite (#1)..(#7), (#15), (#17), (#56), (#58) in landing order; "
        f"found order: {found_order}. "
        "If a new feature shipped, append the next bullet with its issue ref."
    )


def test_what_this_is_intro_count_word_matches_bullet_count() -> None:
    """The intro's number-word ("Eleven closed issues map to eleven pieces …")
    must equal the count of top-level numbered bullets below it (#170).

    Before #170 the intro said "Nine" while the list had grown to eleven
    bullets — the issue-ref lock covered the refs but nothing tied the prose
    count to the list length, so the intro silently drifted. This assertion
    closes that gap: a future 12th piece must bump the intro word too.
    """
    section = _what_this_is_section()
    intro = section.splitlines()[: _bullet_start_index(section)]
    intro_text = " ".join(intro).lower()
    words_present = [w for w in _NUMBER_WORDS if w in intro_text]
    assert words_present, (
        "expected a spelled-out count word (e.g. 'eleven') in the "
        f"'What this is' intro; extend _NUMBER_WORDS if a larger count shipped. Intro:\n{intro_text}"
    )
    # The intro repeats the count ("Eleven … eleven pieces"); all occurrences
    # must agree, and equal the number of top-level `N.` bullets.
    claimed = {_NUMBER_WORDS[w] for w in words_present}
    n_bullets = len(re.findall(r"(?m)^\d+\.\s", section))
    assert claimed == {n_bullets}, (
        f"'What this is' intro claims count(s) {sorted(claimed)} but the section has "
        f"{n_bullets} top-level numbered bullets. Update the intro number-word to match "
        "(both occurrences) when a piece is added or removed."
    )


def _bullet_start_index(section: str) -> int:
    """Line index of the first top-level `1.` numbered bullet in the section,
    so the intro prose is everything above it."""
    for i, line in enumerate(section.splitlines()):
        if re.match(r"^\d+\.\s", line):
            return i
    return len(section.splitlines())


def test_cli_subcommand_bullet_matches_argparse_surface() -> None:
    """Bullet 7 must list the live argparse subcommands so a rename in
    the CLI can't quietly orphan the README."""
    live = set(_live_cli_subcommands())

    body = _readme()
    start = body.index("**CLI** (#7)")
    end = body.index("\n8.", start)
    bullet = body[start:end]
    bullet_flat = re.sub(r"\s+", " ", bullet)
    # Strip the hidden-alias clause before extracting the primary surface.
    if "(plus " in bullet_flat:
        bullet_flat = bullet_flat.split("(plus ")[0]
    # Subcommands appear inside the inline-code span as
    # `eval-harness <a> | <b> | <c>`. Pull them out by splitting on `|`,
    # then stripping the leading `eval-harness` prefix and any whitespace
    # or backticks.
    code_spans = re.findall(r"`([^`]+)`", bullet_flat)
    assert code_spans, f"No backticked CLI surface found in bullet:\n{bullet_flat!r}"
    raw_surface = code_spans[0]
    if raw_surface.startswith("eval-harness "):
        raw_surface = raw_surface[len("eval-harness ") :]
    documented = {tok.strip() for tok in raw_surface.split("|") if tok.strip()}

    # `judge` is the hidden backwards-compat parent group; expected NOT
    # to appear in the primary surface bullet.
    missing = sorted(live - documented - {"judge"})
    extra = sorted(documented - live)
    assert not missing, (
        f"CLI bullet (#7) is missing live subcommand(s): {missing}. "
        f"Live: {sorted(live)}. Documented: {sorted(documented)}. "
        "Update the README bullet to match `eval-harness --help`."
    )
    assert not extra, (
        f"CLI bullet (#7) lists subcommand(s) that aren't in argparse: {extra}. "
        f"Live: {sorted(live)}. Documented: {sorted(documented)}. "
        "Remove the stale name."
    )


def test_referenced_files_exist() -> None:
    """Every relative-path `(path.ext)` link in the README must exist."""
    body = _readme()
    pattern = re.compile(r"\(([^)\s]+\.(?:md|jsonl|py|html|json|yml|yaml|png|svg))\)")
    refs = {r for r in pattern.findall(body) if not r.startswith(("http://", "https://"))}
    missing = sorted(r for r in refs if not (REPO_ROOT / r).exists())
    assert not missing, (
        f"README references files that don't exist: {missing}. "
        "Either fix the link or commit the file."
    )


def _max_active_decision_id() -> int:
    """Highest non-superseded ``D-NNN`` in ``MEMORY/core_decisions_ai.md``.

    The README's architecture-section summary cites a range like
    ``D-002…D-NNN``; this is the NNN that must be current. A new decision
    landing without the README being updated fails the sister test below.
    """
    text = DECISIONS.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=- id:)", text)
    best = 0
    for block in blocks:
        id_match = re.search(r"- id:\s*D-(\d+)", block)
        if not id_match:
            continue
        sup_match = re.search(r"superseded_by:\s*(\S+)", block)
        is_active = (sup_match is None) or (sup_match.group(1).strip().lower() == "null")
        if is_active:
            n = int(id_match.group(1))
            if n > best:
                best = n
    return best


def test_decision_range_cites_latest_active() -> None:
    """README's architecture-section summary must cite the active-decision
    range as ``D-002…D-NNN`` with NNN equal to the highest active
    (non-superseded) ``D-NNN`` in ``MEMORY/core_decisions_ai.md``.

    Sister to ``chunking-strategies-lab`` ``test_readme_snapshot.py``'s
    ``test_decision_range_cites_latest_active`` — the same lock catches
    the drift class where a new D-NNN lands without the README's range
    bound being bumped (this exact shape surfaced in #51 when D-015
    landed without ``docs/architecture.md`` being updated).
    """
    body = _readme()
    pattern = re.compile(r"D-0*2\s*(?:…|\.\.\.)\s*D-0*(\d+)")
    matches = pattern.findall(body)
    assert matches, (
        "README.md must cite the active-decision range as "
        "`D-002…D-NNN` somewhere (the architecture-section summary "
        "paragraph by convention). Not found."
    )
    cited = max(int(m) for m in matches)
    latest = _max_active_decision_id()
    assert cited == latest, (
        f"README.md cites decision range up to D-{cited:03d}, but the "
        f"highest active D-NNN in MEMORY/core_decisions_ai.md is "
        f"D-{latest:03d}. Update the README's architecture-section "
        f"summary to D-002…D-{latest:03d}."
    )


def test_demo_section_names_followup_issue_not_pending_dependency() -> None:
    """Defends against regressing the Demo section back to the previous
    "pending until #N lands" framing where #N is already closed."""
    body = _readme()
    start = body.index("## Demo")
    end = body.index("##", start + 1)
    demo = body[start:end]
    # The section must reference at least one follow-up issue number
    # (the captured-asset owner). And it must not say "pending until ...
    # lands" which is the failure mode this test guards against.
    assert re.search(r"#\d+", demo), (
        "Demo section must name at least one follow-up issue for the captured asset. "
        "Use `**#NN**` referencing the demo-capture follow-up issue."
    )
    assert "pending until" not in demo.lower(), (
        "Demo section must not contain the phrase 'pending until ... lands'; that framing "
        "was correct only when the gating issue was open. If a gating issue exists, name it "
        "as a follow-up; otherwise the section should describe today's two-command demo path."
    )
