r"""The package must satisfy, in its own source, the rule it enforces on inputs (#217).

Writing *about* a lone surrogate is how you accidentally ship one. A `.py` file on
disk holding the six ASCII characters `\ud800` inside a *non-raw* string literal
does not contain those six characters once compiled: Python resolves the escape,
so the constant holds a real unpaired surrogate. That happened twice while writing
#217 -- once in `calibration.load_calibration`'s docstring, once in the test module
beside this one -- and both times the symptom appeared a long way from the cause.

**Whether that is loud or silent is a property of the interpreter, not of the
code.** Measured, feeding `compile()` source that is pure ASCII and spells the
surrogate as an escape:

    position                     3.11 / 3.12          3.14
    ---------------------------- -------------------- --------------------
    module docstring             ok, carries it       compile() RAISES
    function/class docstring     ok, carries it       compile() RAISES
    return / assignment literal  ok, carries it       ok, carries it
    dict value                   ok, carries it       ok, carries it
    f-string literal piece       ok, carries it       ok, carries it
    raw string (r"...")          ok, clean            ok, clean
    `#` comment                  ok, clean            ok, clean

On 3.14 a docstring is the loud half: `UnicodeEncodeError` straight out of
`compile()`, so the module cannot be imported at all -- and under pytest it
surfaces from the assertion-rewrite cache rather than from the file that caused
it, which is a long way from the cause:

    .venv/.../_pytest/assertion/rewrite.py:359: in _rewrite_test
        co = compile(tree, strfn, "exec", dont_inherit=True)
    E   UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800'
        in position 575: surrogates not allowed

On 3.11 and 3.12 -- which is what CI runs -- there is **no loud half at all**.
Every position compiles, runs, and carries a real unpaired surrogate until
something tries to encode it. So the two slips that produced this file would have
sailed through CI silently rather than crashing at import, which is the argument
for the check rather than against it.

That is also why nothing below asserts *which* road catches a file. `_check`
handles both and the outcome is the contract; the road is an interpreter detail,
and pinning it would make this a host-environment assertion that passes on the
author's machine and fails on CI. It did exactly that once (#217).

The bytes on disk cannot catch either road: the file is valid UTF-8 both ways. The
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


#: Every literal position that ends up carrying a real surrogate on at least one
#: supported interpreter. Deliberately not split into "loud" and "silent" groups:
#: which road catches a file is an interpreter detail (see the table above), and
#: the outcome is the contract.
BAD_SOURCES = {
    "module docstring": f"'mod {ESCAPE} doc'\n",
    "nested function docstring": f"def outer():\n    def inner():\n        'doc {ESCAPE} doc'\n",
    "nested return literal": (
        f"def outer():\n    def inner():\n        return {{'k': 'a{ESCAPE}b'}}\n"
    ),
    "module assignment": f"X = 'a{ESCAPE}b'\n",
}


@pytest.mark.parametrize("label", sorted(BAD_SOURCES), ids=lambda s: s.replace(" ", "-"))
def test_a_surrogate_bearing_literal_is_caught_wherever_it_sits(tmp_path: Path, label: str) -> None:
    """Anti-vacuous, and interpreter-independent by construction.

    On 3.14 a docstring makes `compile()` raise and `_check` fails with "cannot be
    compiled at all"; on 3.11/3.12 the same file compiles and the constant walk
    catches it with "no UTF-8 encoding". Both are a failure, which is the whole
    contract -- so this asserts a failure, not a *particular* failure. Asserting
    the road is what turned this file red on CI while it was green locally (#217),
    and it is the same host-environment-assertion trap that rule names.

    The nested cases are two levels deep on purpose, to prove the walk descends
    into nested code objects rather than only scanning module scope.
    """
    p = tmp_path / "probe_mod.py"
    p.write_text(BAD_SOURCES[label], encoding="utf-8")
    assert p.read_bytes().isascii(), "the file itself must be plain ASCII on disk"
    # `BaseException` with an explicit alternation, not two narrower blocks: the
    # compile road raises `Failed` (pytest's own, not an `Exception` subclass in
    # every version) and the walk road raises `AssertionError`, and which one
    # fires is the interpreter detail this test refuses to pin.
    with pytest.raises(BaseException, match="cannot be compiled at all|no UTF-8 encoding") as exc:
        _check(p, "probe")
    assert "probe" in str(exc.value)


def test_the_silent_road_exists_on_this_interpreter(tmp_path: Path) -> None:
    """A non-docstring literal compiles on *every* supported interpreter, so the
    constant walk is never dead code -- it is the only road on 3.11/3.12 and the
    road for non-docstring positions everywhere.

    Pinned separately from the parametrized test above because it asserts the
    *premise* (this file really does compile) rather than the outcome.
    """
    p = tmp_path / "probe_const.py"
    p.write_text(BAD_SOURCES["nested return literal"], encoding="utf-8")
    compile(p.read_text(encoding="utf-8"), "<probe>", "exec")  # must not raise
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
