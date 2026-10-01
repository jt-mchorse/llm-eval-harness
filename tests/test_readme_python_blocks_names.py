"""Every name a README Python block uses is defined, imported, or a stated
placeholder (#267).

The drift library snippet ended `Path("drift.html").write_text(...)` without
importing `Path`, so copying it raised `NameError`. The check is pyflakes'
undefined-name rule over each ```python block, with an explicit allowlist for
the names the README deliberately leaves to the reader.
"""

from __future__ import annotations

import ast
import builtins
import re
from pathlib import Path

import pytest

_README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")

#: Names the README leaves for the reader to supply, and where.
PLACEHOLDERS = {"my_judge"}  # drift library snippet: "your judge"


def undefined_names(source: str) -> set[str]:
    tree = ast.parse(source)
    bound = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return used - bound


_BLOCKS = re.findall(r"```python\n(.*?)```", _README, re.S)


@pytest.mark.parametrize("index", range(len(_BLOCKS)))
def test_a_readme_block_uses_only_defined_names(index: int) -> None:
    missing = undefined_names(_BLOCKS[index]) - PLACEHOLDERS
    assert not missing, f"README python block #{index} uses undefined {sorted(missing)}"


def test_the_check_is_not_vacuous() -> None:
    assert len(_BLOCKS) >= 3
    assert undefined_names('Path("x").write_text("y")') == {"Path"}
    assert undefined_names('from pathlib import Path\nPath("x")') == set()
    # Every placeholder is actually used somewhere, or the allowlist is stale.
    used = set().union(*(undefined_names(b) for b in _BLOCKS))
    assert used >= PLACEHOLDERS
