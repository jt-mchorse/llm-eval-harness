r"""The package must satisfy, in its own source, the rule it enforces on inputs (#217).

Writing *about* a lone surrogate is how you accidentally ship one. A `.py` file on
disk holding the six ASCII characters `\ud800` inside a *non-raw* string literal
does not contain those six characters once compiled: Python resolves the escape,
so the constant holds a real unpaired surrogate. That happened twice while writing
#217 -- once in `calibration.load_calibration`'s docstring, once in the test module
beside this one -- and both times the symptom appeared a long way from the cause.

Where it lands depends on the literal's *position*, and the two halves fail very
differently. Measured on this interpreter, feeding `compile()` source that is
pure ASCII and spells the surrogate as an escape:

    position                     compile()   constant carries surrogate
    ---------------------------- ----------- --------------------------
    module docstring             RAISES      -
    function/class docstring     RAISES      -
    return / assignment literal  ok          YES
    dict value                   ok          YES
    f-string literal piece       ok          YES
    raw string (r"...")          ok          no
    `#` comment                  ok          no

The docstring half is loud -- `UnicodeEncodeError` out of `compile()`, so the
module cannot be imported at all, and under pytest it surfaces from the assertion
-rewrite cache rather than from the file that caused it:

    .venv/.../_pytest/assertion/rewrite.py:359: in _rewrite_test
        co = compile(tree, strfn, "exec", dont_inherit=True)
    E   UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800'
        in position 575: surrogates not allowed

The other half is **silent**. A surrogate in an ordinary literal compiles, runs,
and sits in the module until something encodes it -- which is precisely the class
this package spent #213, #215 and #217 learning to reject in its *inputs*.

The bytes on disk cannot catch either half: the file is valid UTF-8 both ways. The
check has to run against the compiled objects, so that is what this does. A `#`
comment and a raw string are both safe, and this docstring is raw for that reason.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from types import CodeType

import pytest

import eval_harness
from eval_harness.io_utils import find_unencodable

ROOT = Path(__file__).resolve().parents[1]


def _module_names() -> list[str]:
    names = [eval_harness.__name__]
    names += [
        m.name for m in pkgutil.walk_packages(eval_harness.__path__, f"{eval_harness.__name__}.")
    ]
    return sorted(names)


def _strings_in(code: CodeType) -> list[str]:
    """Every `str` constant reachable from *code*, including nested definitions.

    Walked with an explicit stack for the same reason `io_utils.find_unrepresentable`
    is: a deep definition chain should not add interpreter frames on top of
    whatever the module already needs.
    """
    out: list[str] = []
    seen: set[int] = set()
    stack = [code]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        for const in node.co_consts:
            if isinstance(const, str):
                out.append(const)
            elif isinstance(const, CodeType):
                stack.append(const)
    return out


def _check(src: Path, label: str) -> None:
    text = src.read_text(encoding="utf-8")
    try:
        code = compile(text, str(src), "exec")
    except UnicodeEncodeError as e:
        # The loud half: a docstring. `compile` refuses, so the module is
        # unimportable; name the file here rather than leaving the operator with
        # a traceback pointing at pytest's rewrite cache.
        pytest.fail(
            f"{label} has a docstring carrying a lone surrogate "
            f"({ascii(e.object[e.start : e.end])}); it cannot be compiled at all. "
            "Double the backslash, make the docstring raw, or move the example "
            "into a `#` comment."
        )
    for text_const in _strings_in(code):
        found = find_unencodable(text_const)
        assert found is None, (
            f"{label} carries a string literal with no UTF-8 encoding "
            f"({ascii(found[0]) if found else ''}) -- silently, because a "
            "non-docstring literal compiles fine. Double the backslash, make the "
            "string raw, or build it from `chr(0xD800)`."
        )


@pytest.mark.parametrize("mod_name", _module_names())
def test_package_source_carries_no_unencodable_literal(mod_name: str) -> None:
    mod = importlib.import_module(mod_name)
    _check(Path(mod.__file__ or ""), mod_name)


@pytest.mark.parametrize("test_file", sorted(p.name for p in (ROOT / "tests").glob("test_*.py")))
def test_test_suite_source_carries_no_unencodable_literal(test_file: str) -> None:
    """The suite too, and for a sharper reason than the package: a test module
    that cannot be compiled does not go red, it fails to COLLECT -- so the suite's
    test *count* shrinks instead of a test failing."""
    _check(ROOT / "tests" / test_file, f"tests/{test_file}")


ESCAPE = "\\ud800"  # the six ASCII characters, as they appear in a file on disk


def test_the_docstring_half_is_caught(tmp_path: Path) -> None:
    """Anti-vacuous, loud half: `compile` refuses and `_check` names the file."""
    p = tmp_path / "mod_doc.py"
    p.write_text(f"def outer():\n    def inner():\n        'doc {ESCAPE} doc'\n", encoding="utf-8")
    assert p.read_bytes().isascii()
    with pytest.raises(BaseException, match="cannot be compiled at all"):
        _check(p, "probe")


def test_the_silent_half_is_caught(tmp_path: Path) -> None:
    """Anti-vacuous, silent half: this one compiles, so only the constant walk
    finds it. Nested two levels deep to prove the walk descends."""
    p = tmp_path / "mod_const.py"
    p.write_text(
        f"def outer():\n    def inner():\n        return {{'k': 'a{ESCAPE}b'}}\n",
        encoding="utf-8",
    )
    assert p.read_bytes().isascii()
    compile(p.read_text(encoding="utf-8"), "<probe>", "exec")  # compiles clean
    with pytest.raises(AssertionError, match="no UTF-8 encoding"):
        _check(p, "probe")


def test_clean_source_passes(tmp_path: Path) -> None:
    """...and the safe spellings really are safe, so the lock is not just 'always
    red on the word surrogate'."""
    p = tmp_path / "mod_ok.py"
    p.write_text(
        f"r'''doc {ESCAPE} doc'''\n"
        f"# comment {ESCAPE}\n"
        "def outer():\n"
        "    return chr(0xD800) + 'tail'\n",
        encoding="utf-8",
    )
    _check(p, "probe")
