"""Architecture-doc lock: catch drift between `docs/architecture.md` and
the actual shipped surface of the repo.

Sister to the architecture-doc lock that landed in
`embedding-model-shootout` PR #20 and `vector-search-at-scale` PR #22
in the same session. Four invariants pinned:

1. **Path-token reachability.** Every backtick-quoted path token that
   starts with one of the `RESOLVABLE_PREFIXES` resolves on disk.
   Placeholders (`<...>`, `{...}`) are skipped.

2. **Closed-feature-issue coverage.** Every issue in
   `KNOWN_SHIPPED_ISSUES` is referenced at least once.

3. **Active-decision coverage.** Every non-superseded `D-NNN` in
   `MEMORY/core_decisions_ai.md` whose numeric id is
   `>= MIN_ACTIVE_DECISION_ID` is referenced at least once. The next
   `D-NNN` landing without a doc update fails this test loud.

4. **Banned-phrase absence.** Phrases that characterized the pre-#29
   drift are absent (case-insensitive).

Hard-pin tests lock `BANNED_PHRASES`, `KNOWN_SHIPPED_ISSUES`,
`RESOLVABLE_PREFIXES`, and `MIN_ACTIVE_DECISION_ID` to their exact
values so a future loose edit of the test can't silently weaken
the guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "docs" / "architecture.md"
DECISIONS = REPO_ROOT / "MEMORY" / "core_decisions_ai.md"

# D-001 is the scope baseline (handoff §2 scope lock) and isn't tied to
# a shipped code surface; it doesn't need to be cited in architecture.md.
# Every active D-NNN with id >= MIN_ACTIVE_DECISION_ID does.
MIN_ACTIVE_DECISION_ID = 2

# Closed feature issues whose work the architecture doc should
# enumerate. Each represents a shipped surface with a code/artifact
# home in the repo.
#
# Intentionally excluded from the coverage check:
#   - #19  README session-framing pivot — README-only, locked by
#          tests/test_readme_snapshot.py
#   - #20  60-second capture (asset only; capture script shipped in
#          a separate PR and locked by tests/test_capture_demo_smoke.py)
#   - #22  README defaults snapshot — locked by
#          tests/test_readme_defaults_snapshot.py
#   - #24  Public surface lock — locked by tests/test_public_surface.py
#   - #27  CLI alias visibility fix — runtime gate locked by
#          tests/test_cli_judge_alias.py
KNOWN_SHIPPED_ISSUES = (1, 2, 3, 4, 5, 6, 7, 15, 17, 56, 58)

# Drift shapes specific to issue #29's pre-fix state. Lowercase
# substring match. Pinned in a tuple so a future loose edit of the
# test can't silently drop one.
BANNED_PHRASES = (
    "this pr",
    "pending downstream",
    "(unfiled)",
    "to-be-filed",
)

# Path-token prefixes that must resolve on disk if quoted in the doc.
# Backtick-quoted tokens only.
RESOLVABLE_PREFIXES = (
    "eval_harness/",
    "fixtures/",
    "examples/",
    "tests/",
    "docs/",
    "scripts/",
    ".github/",
)


@pytest.fixture(scope="module")
def doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def active_decisions() -> tuple[int, ...]:
    """Parse `MEMORY/core_decisions_ai.md` for non-superseded `D-NNN`
    entries whose numeric id is `>= MIN_ACTIVE_DECISION_ID`.
    """
    text = DECISIONS.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=- id:)", text)
    active: list[int] = []
    for block in blocks:
        id_match = re.search(r"- id:\s*D-(\d+)", block)
        if not id_match:
            continue
        sup_match = re.search(r"superseded_by:\s*(\S+)", block)
        is_active = (sup_match is None) or (sup_match.group(1).strip().lower() == "null")
        if is_active:
            n = int(id_match.group(1))
            if n >= MIN_ACTIVE_DECISION_ID:
                active.append(n)
    return tuple(sorted(active))


def _extract_backtick_paths(text: str) -> set[str]:
    """Collect every backtick-quoted token that starts with one of the
    RESOLVABLE_PREFIXES.

    Placeholder tokens that contain `<...>` (angle-bracket variable) or
    `{...}` (brace-expansion across multiple files) are not literal
    paths a reader would copy-paste; they document a *shape*. Those
    are excluded so the doc can still use template patterns without
    false-positives.
    """
    found: set[str] = set()
    for match in re.finditer(r"`([^`\n]+)`", text):
        token = match.group(1).strip()
        for prefix in RESOLVABLE_PREFIXES:
            if token.startswith(prefix):
                while token and token[-1] in ".,;:":
                    token = token[:-1]
                token = re.sub(r"\(\)$", "", token)
                if "<" in token or "{" in token or "*" in token:
                    # Skip placeholder shapes (`<run_id>`, `{png,svg}`,
                    # `tests/test_cli_*.py`) — they're explanatory
                    # templates, not literal paths.
                    break
                if token:
                    found.add(token)
                break
    return found


def _resolves_on_disk(token: str) -> bool:
    return (REPO_ROOT / token).exists()


# File-suffix tokens that look like a `<name>.<attr>` symbol reference but are
# really filenames (`cli.py`, `runs.sqlite`). Excluded from the dotted-symbol
# resolution check below so a filename isn't mistaken for a package attribute.
# Hard-pinned by `test_symbol_skip_extensions_hard_pin_set` so a loose edit
# can't silently widen the skip set and let a real broken symbol ref through.
SYMBOL_SKIP_EXTENSIONS = ("py", "sqlite", "json", "md", "txt", "yaml", "yml", "sh", "toml")

# Package submodules under `eval_harness/` — a `<module>.<symbol>` doc reference
# is resolved by importing `eval_harness.<module>` and checking the attribute.
_PKG_DIR = REPO_ROOT / "eval_harness"


def _extract_symbol_refs(text: str) -> tuple[set[str], set[str]]:
    """Split backtick-quoted tokens into the two symbol-citation styles the
    doc actually uses, so the resolver only checks things that are genuinely
    symbol claims (not prose, field names, or file paths).

    Returns ``(dotted, camel)``:

    - ``dotted``: ``<submodule>.<symbol>`` where ``<submodule>`` is a real
      `eval_harness/*.py` module and the token is NOT a filename — i.e. an
      attribute reference like ``io_utils.atomic_write_text``. Filename tokens
      (``cli.py``, ``runs.sqlite``) are dropped via ``SYMBOL_SKIP_EXTENSIONS``
      and an on-disk existence check.
    - ``camel``: a *multi-word* CamelCase identifier (an internal
      lowercase→uppercase transition, e.g. ``RunResult``, ``AnthropicBackend``).
      Bare snake_case is deliberately excluded — it collides with data-field
      names the doc quotes (``human_score``, ``dataset_version``,
      ``duplicate_id``), which are not importable symbols.
    """
    submodules = {p.stem for p in _PKG_DIR.glob("*.py") if p.stem != "__init__"}
    dotted: set[str] = set()
    camel: set[str] = set()
    for match in re.finditer(r"`([^`\n]+)`", text):
        token = match.group(1).strip()
        token = re.sub(r"\(\)$", "", token)
        while token and token[-1] in ".,;:":
            token = token[:-1]
        dotted_match = re.fullmatch(r"([a-z_]+)\.([A-Za-z_][A-Za-z0-9_]*)", token)
        if dotted_match:
            module, attr = dotted_match.group(1), dotted_match.group(2)
            if (
                module in submodules
                and attr not in SYMBOL_SKIP_EXTENSIONS
                and not (_PKG_DIR / token).exists()
            ):
                dotted.add(token)
            continue
        # Multi-word CamelCase: starts uppercase, contains a lowercase, and has
        # at least one internal lowercase→uppercase boundary (so `SCORE` /
        # `REASONING` / a single-word `Backend`-in-prose aren't swept in).
        if re.fullmatch(r"[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*", token) and re.search(
            r"[a-z][A-Z]", token
        ):
            camel.add(token)
    return dotted, camel


def test_doc_exists() -> None:
    assert DOC.exists(), f"missing {DOC}"


def test_decisions_file_exists() -> None:
    assert DECISIONS.exists(), f"missing {DECISIONS}"


def test_backtick_paths_resolve_on_disk(doc_text: str) -> None:
    tokens = _extract_backtick_paths(doc_text)
    unresolved = sorted(t for t in tokens if not _resolves_on_disk(t))
    assert not unresolved, (
        "docs/architecture.md quotes paths that don't exist on disk:\n"
        + "\n".join(f"  - `{t}`" for t in unresolved)
        + "\n(regenerate the doc to match the current layout, or fix the typo)"
    )


def test_doc_symbol_refs_resolve(doc_text: str) -> None:
    """Every symbol the doc names resolves to a real package attribute.

    ``test_backtick_paths_resolve_on_disk`` validates slash-path tokens only;
    a *symbol* reference — a ``<submodule>.<symbol>`` attribute or a CamelCase
    public type — was unguarded. That is exactly the drift class portfolio-ops
    #55 catalogued (e.g. llm-cost-optimizer's doc naming a nonexistent
    ``BatchAPIBackend``, embedding-model-shootout's ``compute_frontier`` for the
    real ``pareto_frontier``): the symbol never existed, yet CI stayed green.
    Propagates the embedding-model-shootout #71 / python-async #70 precedents,
    adapted to the two citation styles this doc actually uses.
    """
    import importlib

    pkg = importlib.import_module("eval_harness")
    dotted, camel = _extract_symbol_refs(doc_text)
    assert dotted or camel, (
        "expected at least one symbol reference (`<module>.<symbol>` or a "
        "CamelCase public type) in docs/architecture.md — the resolver would "
        "otherwise be vacuously green"
    )

    unresolved: list[str] = []
    for token in sorted(dotted):
        module_name, _, symbol = token.rpartition(".")
        try:
            module = importlib.import_module(f"eval_harness.{module_name}")
        except ModuleNotFoundError:
            unresolved.append(f"{token} (module eval_harness.{module_name} not importable)")
            continue
        if not hasattr(module, symbol):
            unresolved.append(token)
    for token in sorted(camel):
        if not hasattr(pkg, token):
            unresolved.append(f"{token} (not in the eval_harness public surface)")

    assert not unresolved, (
        "docs/architecture.md names symbols that don't exist in the package:\n"
        + "\n".join(f"  - {u}" for u in unresolved)
        + "\n(fix the doc to match the shipped symbol, or update the rename that orphaned it)"
    )


def test_symbol_skip_extensions_hard_pin_set() -> None:
    assert SYMBOL_SKIP_EXTENSIONS == (
        "py",
        "sqlite",
        "json",
        "md",
        "txt",
        "yaml",
        "yml",
        "sh",
        "toml",
    )


def test_every_shipped_issue_referenced(doc_text: str) -> None:
    referenced = {int(m.group(1)) for m in re.finditer(r"#(\d+)\b", doc_text)}
    missing = sorted(set(KNOWN_SHIPPED_ISSUES) - referenced)
    assert not missing, (
        "docs/architecture.md doesn't reference these closed-feature-issues "
        "even once:\n"
        + "\n".join(f"  - #{n}" for n in missing)
        + "\n(every shipped surface should have its origin issue annotated "
        "in the doc; add a `(#NN)` to the relevant component bullet or diagram node)"
    )


def test_every_active_decision_referenced(doc_text: str, active_decisions: tuple[int, ...]) -> None:
    referenced = {int(m.group(1)) for m in re.finditer(r"\bD-0*(\d+)\b", doc_text)}
    missing = sorted(set(active_decisions) - referenced)
    assert not missing, (
        "docs/architecture.md doesn't reference these active "
        "(non-superseded) core decisions even once:\n"
        + "\n".join(f"  - D-{n:03d}" for n in missing)
        + "\n(every shipped layer / posture in MEMORY/core_decisions_ai.md "
        "should be annotated in the doc where the relevant code lives; "
        "add a `D-NNN` reference to the relevant bullet)"
    )


def test_no_banned_phrases(doc_text: str) -> None:
    lowered = doc_text.lower()
    hits = [p for p in BANNED_PHRASES if p in lowered]
    assert not hits, (
        "docs/architecture.md contains pre-#29 drift phrases:\n"
        + "\n".join(f"  - {p!r}" for p in hits)
        + "\n(these phrases described the pre-shipping state; the doc is "
        "now a steady-state reference, not a PR description)"
    )


def test_banned_phrases_hard_pin_set() -> None:
    assert BANNED_PHRASES == (
        "this pr",
        "pending downstream",
        "(unfiled)",
        "to-be-filed",
    )


def test_known_shipped_issues_hard_pin_set() -> None:
    assert KNOWN_SHIPPED_ISSUES == (1, 2, 3, 4, 5, 6, 7, 15, 17, 56, 58)


def test_resolvable_prefixes_hard_pin_set() -> None:
    assert RESOLVABLE_PREFIXES == (
        "eval_harness/",
        "fixtures/",
        "examples/",
        "tests/",
        "docs/",
        "scripts/",
        ".github/",
    )


def test_min_active_decision_id_hard_pin() -> None:
    assert MIN_ACTIVE_DECISION_ID == 2


# ---------------------------------------------------------------------------
# Directory-tree completeness lock (#171).
#
# The doc opens with a fenced `eval_harness/` directory tree annotating each
# module. Its bare `foo.py` entries are neither backtick-quoted path tokens (so
# `test_backtick_paths_resolve_on_disk` skips them) nor dotted `<module>.<symbol>`
# refs (so the symbol resolver skips them), and nothing asserts the tree is
# *complete* against the package. That is exactly how `eval_harness/markdown.py`
# (the GFM escaper, #142) shipped without ever landing in the tree, CI-green.
# Lock it: every module the package actually ships is named in the doc.
_PKG = REPO_ROOT / "eval_harness"


def _package_module_basenames() -> list[str]:
    """Every `eval_harness/*.py` module basename (flat package; excludes
    dunder-only files other than the public `__init__.py`, which the tree does
    list)."""
    return sorted(p.name for p in _PKG.glob("*.py"))


def test_every_package_module_named_in_doc(doc_text: str) -> None:
    """Every `eval_harness/*.py` module basename appears in docs/architecture.md
    (#171). Catches a module that ships without a directory-tree update."""
    names = _package_module_basenames()
    assert names, "expected eval_harness/*.py modules on disk"
    missing = [n for n in names if n not in doc_text]
    assert not missing, (
        "docs/architecture.md does not name these eval_harness/ modules anywhere "
        "(add them to the directory tree so the architecture stays complete):\n"
        + "\n".join(f"  - {m}" for m in missing)
    )


def test_package_module_completeness_flags_injected_gap(doc_text: str) -> None:
    """Inverse safety net: a synthetic module absent from the doc is flagged,
    while the real modules still resolve (guards a vacuously-green check)."""
    names = [*_package_module_basenames(), "totally_unlisted_module.py"]
    missing = [n for n in names if n not in doc_text]
    assert missing == ["totally_unlisted_module.py"]
