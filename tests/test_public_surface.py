"""Public-surface tests for ``eval_harness/__init__.py``.

``eval_harness`` re-exports ~50 names from six submodules and declares
``__all__`` + ``__version__``. Every other test in this suite imports
submodules directly (``from eval_harness.judge import Judge``), so
silent renames or accidental ``__all__`` drops in ``__init__.py`` don't
fail any test — but they break the README's quoted ``Library use``
example (``from eval_harness import Judge, calibrate, load_calibration``)
and any downstream importer that uses the top-level surface.

These five tests lock that surface:

1. ``__version__`` is set to a semver-ish string.
2. Every name in ``__all__`` is bound on the package and non-None.
3. ``__all__`` agrees with the actual top-level ``from X import ...``
   names — guards against a future export being added to the imports
   block but not ``__all__`` (or vice versa).
4. The README's quoted library-use imports succeed.
5. Anchor names from each re-exported submodule are reachable via
   ``eval_harness`` — guards against a submodule being split or
   renamed without updating ``__init__.py``.

Same hygiene posture as the README-snapshot tests landed across the
portfolio. Orthogonal axis: this locks the Python public surface;
``test_readme_snapshot.py`` locks the README's structural claims.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

import eval_harness

# Re-import the package under the coverage tracer. The ``eval-harness``
# pytest plugin is loaded by pytest's entry-point machinery before
# ``pytest-cov`` starts instrumenting, so ``eval_harness/__init__.py``
# has already executed by the time tests run. Reloading inside the
# test module forces the module body to re-execute while coverage is
# active, so the public surface actually counts as covered. (Without
# this, the package's top-level surface stays at 0% even though every
# attribute access below exercises the re-exports.)
eval_harness = importlib.reload(eval_harness)

_INIT_PATH = Path(eval_harness.__file__)
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")

# README's `Library use` section quotes these three names as
# importable directly from the top-level package.
README_LIBRARY_USE_NAMES = ("Judge", "calibrate", "load_calibration")

# Anchor names that prove each submodule's re-exports survived.
# One name per submodule; if `__init__.py` ever drops a submodule's
# whole block, the corresponding anchor goes missing.
SUBMODULE_ANCHORS = {
    "judge": "Judge",
    "calibration": "calibrate",
    "dataset": "load_jsonl",
    "drift": "compute_drift",
    "runner": "run_suite",
    "runs": "write_run",
}


def _parse_init_from_imports() -> set[str]:
    """Return the set of names imported into ``__init__.py`` via
    top-level ``from eval_harness.X import (...)`` blocks."""
    tree = ast.parse(_INIT_PATH.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("eval_harness.")
        ):
            for alias in node.names:
                # An aliased import (`from drift import render_html as render_drift_html`)
                # adds the alias to the public surface, not the original name.
                names.add(alias.asname or alias.name)
    return names


def test_version_is_set_to_semver_ish_string() -> None:
    """``__version__`` is published; downstream importers and PyPI
    builds rely on it."""
    assert hasattr(eval_harness, "__version__"), (
        "eval_harness.__version__ is missing — packaging tools and "
        "downstream `eval_harness.__version__` lookups will break."
    )
    version = eval_harness.__version__
    assert isinstance(version, str), (
        f"eval_harness.__version__ should be a string, got {type(version).__name__}: {version!r}."
    )
    assert version, "eval_harness.__version__ is an empty string."
    assert _SEMVER_PATTERN.match(version), (
        f"eval_harness.__version__ = {version!r} doesn't look like "
        f"semver (expected MAJOR.MINOR.PATCH[-prerelease][+build])."
    )


def test_all_names_are_bound_and_non_none() -> None:
    """Every name in ``__all__`` must be importable and non-None.

    Catches the silent-failure where someone removes a re-import line
    but leaves the name in ``__all__``.
    """
    missing: list[str] = []
    none_valued: list[str] = []
    for name in eval_harness.__all__:
        if not hasattr(eval_harness, name):
            missing.append(name)
            continue
        if getattr(eval_harness, name) is None:
            none_valued.append(name)
    assert not missing, (
        f"eval_harness.__all__ advertises names that are not bound on "
        f"the package: {missing}. The most likely cause is a re-import "
        f"line was deleted from __init__.py but __all__ wasn't updated."
    )
    assert not none_valued, (
        f"eval_harness.__all__ entries bound to None: {none_valued}. "
        f"A re-import probably resolved to a missing submodule attribute."
    )


def test_all_matches_actual_top_level_imports() -> None:
    """``__all__`` should equal the set of top-level re-exports.

    Catches the inverse drift: someone adds a new ``from eval_harness.X
    import Y`` but forgets to add ``Y`` to ``__all__``, so ``import *``
    silently misses the export.
    """
    advertised = set(eval_harness.__all__)
    imported = _parse_init_from_imports()
    only_imported = imported - advertised
    only_advertised = advertised - imported
    assert not only_imported, (
        f"Names imported into eval_harness/__init__.py but missing from "
        f"__all__: {sorted(only_imported)}. Add them to __all__ or stop "
        f"importing them at the top level."
    )
    assert not only_advertised, (
        f"Names in eval_harness.__all__ but not imported at the top of "
        f"__init__.py: {sorted(only_advertised)}. Add the import or "
        f"remove the __all__ entry."
    )


def test_readme_library_use_imports_resolve() -> None:
    """README's `Library use` example must keep working as written.

    The README literally quotes::

        from eval_harness import Judge, calibrate, load_calibration

    If any of those three names disappears from the top-level surface,
    every reader who copy-pastes the example hits an ImportError.
    """
    for name in README_LIBRARY_USE_NAMES:
        assert hasattr(eval_harness, name), (
            f"eval_harness.{name} is missing from the top-level surface. "
            f"The README's `Library use` example imports it directly — "
            f"either restore the export or update the README's example."
        )


@pytest.mark.parametrize(
    ("submodule", "anchor"),
    sorted(SUBMODULE_ANCHORS.items()),
    ids=sorted(SUBMODULE_ANCHORS.keys()),
)
def test_submodule_anchor_re_exported(submodule: str, anchor: str) -> None:
    """One anchor per re-exported submodule survives at the top level.

    If a submodule is split or renamed (``runner.py`` → ``runner/__init__.py``,
    ``runs.py`` → ``persistence.py``, etc.) and ``__init__.py`` isn't
    updated, the anchor name vanishes from ``eval_harness``.
    """
    assert hasattr(eval_harness, anchor), (
        f"`{anchor}` from `eval_harness.{submodule}` is no longer re-exported "
        f"at the top level. Did `{submodule}` move or get renamed? Update "
        f"`eval_harness/__init__.py` to re-export from the new path."
    )
