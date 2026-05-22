"""Pins the `judge calibrate` legacy alias surface (#27).

Two related contracts:

1. `eval-harness --help` lists the issue #7 public surface
   (`run / list / calibrate / diff / diff-json / comment / drift`) and
   does NOT show `judge` as a visible subcommand. Until #27 the
   `judge` subparser was registered with a visible help string, which
   contradicted the module docstring that called it a "hidden nested
   alias".
2. `eval-harness judge calibrate ...` still resolves — backwards
   compat for downstream scripts. The CLI rewrites the alias to the
   canonical subcommand internally before argparse sees it.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from eval_harness.cli import main


def _capture_help(argv: list[str]) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 0, f"--help should exit 0; got {exc.value.code}"
    return buf.getvalue()


def test_top_level_help_omits_judge_subcommand() -> None:
    text = _capture_help(["--help"])
    # The subparser list is the line that starts with `{...} ...` — the
    # visible-subcommands set. `judge` must not appear there.
    # Use a tight assertion: the literal `judge` as a token at the
    # start of a stripped line in the positional-arguments listing
    # would only appear if the subparser were registered visibly.
    visible_subcommands = []
    in_positional = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("positional arguments"):
            in_positional = True
            continue
        if stripped.startswith("options"):
            in_positional = False
            continue
        if in_positional and stripped.startswith("{"):
            # The {a,b,c} summary line — parse out the subcommand names.
            inside = stripped.strip().strip("{}").split("...")[0].strip("{}").rstrip(",")
            visible_subcommands = [s.strip() for s in inside.split(",")]
            break
    assert visible_subcommands, f"could not find subcommand summary in --help; got: {text!r}"
    assert "judge" not in visible_subcommands, (
        f"`judge` is the backwards-compat alias and must be hidden from `eval-harness --help`. "
        f"Current visible subcommands: {visible_subcommands}. "
        f"See issue #27."
    )
    # Sanity: the canonical surface from issue #7 is present.
    for expected in ("run", "list", "calibrate", "diff"):
        assert expected in visible_subcommands, (
            f"public subcommand {expected!r} must remain visible; "
            f"got: {visible_subcommands}"
        )


def test_judge_calibrate_alias_still_resolves() -> None:
    # `eval-harness judge calibrate --help` should produce the same
    # `eval-harness calibrate` help output (after the argv rewrite).
    via_alias = _capture_help(["judge", "calibrate", "--help"])
    via_canonical = _capture_help(["calibrate", "--help"])
    assert via_alias == via_canonical, (
        "`judge calibrate --help` and `calibrate --help` should produce "
        "identical output — the alias rewrites argv before argparse parses. "
        "If they differ, the rewrite logic in main() lost a parameter or "
        "the canonical subparser changed."
    )


def test_judge_with_unknown_subcommand_does_not_resolve() -> None:
    # The rewrite only catches `judge calibrate`. Anything else under
    # `judge` should not silently succeed.
    with pytest.raises(SystemExit) as exc:
        main(["judge", "unknown-subcommand"])
    # SystemExit non-zero on unknown-command parser error.
    assert exc.value.code != 0


def test_judge_alone_does_not_resolve() -> None:
    # Bare `eval-harness judge` (no subcommand) is not a valid invocation
    # and should fail at the parser layer.
    with pytest.raises(SystemExit) as exc:
        main(["judge"])
    assert exc.value.code != 0
