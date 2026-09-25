"""A decided comparison is rendered so the decision stays readable (#252).

Three gates in this package decide at full float precision and then explain the
decision in a string a human reads. Before #252 all three explained at a fixed
width, so a near-threshold margin produced a message that contradicted the
verdict it was explaining:

* `pytest_plugin.py` — `score=0.600 < threshold=0.600` (both sides `.3f`).
* `cli.py` — `Cohen's κ 0.600 < threshold 0.6` as a `::error::` annotation:
  `.3f` against an unformatted float, so read as written the claim is **false**.
* `calibration.render_report` — a `FAIL` verdict beside a `.3f` κ cell and an
  unformatted threshold bullet.

**No test in this suite could have caught any of them**, and that is the point
worth keeping: the verdict is correct in every colliding case, so an assertion
about pass/fail can never fire. The only thing wrong is that the sentence
disagrees with itself, and nothing asserted that a sentence is self-consistent.

The central arms are margin *searches*. A single hand-picked margin is a coin
flip — the old `.3f` renders correctly for wide margins and wrongly for narrow
ones, so one sampled value proves whichever the sampler happened to pick.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from eval_harness.calibration import CalibrationResult, render_report
from eval_harness.comparison import (
    COMPARISON_MAX_PLACES,
    COMPARISON_PLACES,
    render_comparison,
)

pytest_plugins = ["pytester"]

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = _ROOT / "eval_harness"

# Margins spanning both sides of the old three-place boundary, so the sweep
# covers the region `.3f` handled and the region it did not.
_MARGINS = [
    5e-1,
    1e-1,
    1e-2,
    1e-3,
    5e-4,
    1e-4,
    1e-5,
    1e-6,
    1e-8,
    1e-10,
    1e-12,
    1e-14,
    1e-15,
]
_IDS = [f"{m:g}" for m in _MARGINS]


def _places(rendered: str) -> int | None:
    """Decimal places in a fixed-point rendering; None for the `repr` fallback."""
    if "e" in rendered or "E" in rendered:
        return None
    _, _, frac = rendered.partition(".")
    return len(frac)


# --------------------------------------------------------------------------
# The helper
# --------------------------------------------------------------------------


@pytest.mark.parametrize("margin", _MARGINS, ids=_IDS)
def test_the_value_may_carry_the_extra_digits(margin: float) -> None:
    """Threshold round, value long — the orientation a round configured threshold gives."""
    threshold = 0.6
    value = threshold - margin
    rendered_value, rendered_threshold = render_comparison(value, threshold)
    assert rendered_value != rendered_threshold, (
        f"at margin {margin:g} both sides render {rendered_value!r}, so a "
        f"message asserting an ordering between them says nothing."
    )
    assert float(rendered_value) < float(rendered_threshold), (
        f"at margin {margin:g} the pair renders "
        f"({rendered_value}, {rendered_threshold}), which does not reproduce the "
        f"ordering the gate decided on."
    )


@pytest.mark.parametrize("margin", _MARGINS, ids=_IDS)
def test_the_threshold_may_carry_the_extra_digits(margin: float) -> None:
    """The other orientation, and the one that produces a *backwards* read.

    `cli.py` shipped this failure: κ at `.3f` against an unformatted threshold
    rendered `Cohen's κ 0.600 < threshold 0.6`, and `0.600 < 0.6` read as
    written is False. A sweep that only ever puts the long expansion on the
    value side cannot see it — which is exactly the half of the population the
    first sweep above walks.
    """
    value = 0.3
    threshold = value + margin
    rendered_value, rendered_threshold = render_comparison(value, threshold)
    assert rendered_value != rendered_threshold, (
        f"at margin {margin:g} both sides render {rendered_value!r}."
    )
    assert float(rendered_value) < float(rendered_threshold), (
        f"at margin {margin:g} the pair renders "
        f"({rendered_value}, {rendered_threshold}) — read as written the "
        f"ordering is reversed, which is worse than hiding it."
    )


@pytest.mark.parametrize(
    ("value", "other"),
    [
        (0.6 - 1e-8, 0.6),
        (0.3, 0.3 + 1e-8),
        (0.6 - 1e-15, 0.6),
        (0.3, 0.3 + 1e-15),
        (0.4, 0.6),
        (0.1, 0.5),
    ],
    ids=[
        "value-long",
        "threshold-long",
        "value-very-long",
        "threshold-very-long",
        "ordinary",
        "ordinary-wide",
    ],
)
def test_both_sides_render_at_the_same_precision(value: float, other: float) -> None:
    """The structural property, asserted directly rather than inferred.

    An outcome arm (`float(a) < float(b)`) only catches mixed precision in the
    orientation where the outcome comes out visibly wrong. This one catches it in
    both, and it is the property `cli.py` violated.
    """
    rendered_value, rendered_other = render_comparison(value, other)
    assert _places(rendered_value) == _places(rendered_other), (
        f"render_comparison({value!r}, {other!r}) returned "
        f"{(rendered_value, rendered_other)} — different precisions, so comparing "
        f"them as written is unreliable."
    )


def test_the_old_fixed_width_really_did_collide() -> None:
    """Anti-vacuity on the margin list.

    Without this the sweeps could be a list of comfortable margins the pre-#252
    code also passed. Green on both trees on purpose — it is a statement about
    arithmetic, and it is what says the sweeps walk the right corpus.
    """
    threshold = 0.6
    colliding = [
        m
        for m in _MARGINS
        if f"{threshold - m:.{COMPARISON_PLACES}f}" == f"{threshold:.{COMPARISON_PLACES}f}"
    ]
    assert len(colliding) >= 8, (
        f"only {len(colliding)} of {len(_MARGINS)} margins collide at "
        f"{COMPARISON_PLACES} places; the sweeps mostly exercise margins the old "
        f"renderer already handled."
    )


def test_ordinary_values_keep_the_narrow_rendering() -> None:
    """The control that separates this fix from simply widening the width.

    A wider fixed width would move every ordinary message in the package.
    """
    assert render_comparison(0.4, 0.6) == ("0.400", "0.600")
    assert render_comparison(0.0, 0.5) == ("0.000", "0.500")


def test_the_helper_never_narrows_a_callers_column() -> None:
    """`places` is the *starting* width, and honouring it is not cosmetic.

    The first version of this module hardcoded three places, which **narrowed**
    `drift.render_html`'s summary table from four to three and silently
    republished `0.5690` as `0.569`. `tests/test_demo_drift_published_values.py`
    caught it, with a message that is exactly right about why it matters: "any
    committed GIF/video of the demo now shows numbers the code no longer
    produces".

    Widening to remove an invisible ordering and narrowing a published column are
    both changes to an artifact. This fix is only allowed to do the first.
    """
    assert render_comparison(0.5690123, 0.15, places=4) == ("0.5690", "0.1500")
    assert render_comparison(0.2454, 0.15, places=4) == ("0.2454", "0.1500")
    # And it still widens past the caller's width when four is not enough.
    wide_value, wide_other = render_comparison(0.15 - 1e-8, 0.15, places=4)
    assert wide_value != wide_other
    assert _places(wide_value) > 4


def test_the_drift_tables_width_is_locked_elsewhere_and_this_says_where() -> None:
    """The rendered-side coverage for the no-narrowing property already exists.

    `tests/test_demo_drift_published_values.py` pins the summary table's JSD cells
    as literal four-place strings (`EXPECTED_HTML_AXES = {"length": "0.5690", ...}`)
    and it is what caught the narrowing. Rather than hand-assemble a fifteen-field
    `DriftReport` to re-assert the same thing less faithfully, this arm pins that
    the lock still expresses the width — so if someone rewrites those literals to
    three places, the justification for `places=4` in `drift.py` fails here
    instead of quietly becoming false.
    """
    module = (_ROOT / "tests" / "test_demo_drift_published_values.py").read_text(encoding="utf-8")
    block = re.search(r"EXPECTED_HTML_AXES = \{(.*?)\}", module, re.S)
    assert block is not None, "EXPECTED_HTML_AXES is gone from the demo-values lock"
    pinned = re.findall(r'"(\d+\.\d+)"', block.group(1))
    assert pinned, f"no numeric literals in EXPECTED_HTML_AXES: {block.group(1)!r}"
    assert all(_places(value) == 4 for value in pinned), (
        f"the demo-values lock pins the HTML axis table at {sorted({_places(v) for v in pinned})} "
        f"places: {pinned}. `drift.py` passes `places=4` to `render_comparison` to "
        f"match that column; if the published width changed, change it there too."
    )


def test_equal_values_are_not_widened() -> None:
    """Nothing to distinguish, so nothing is implied."""
    assert render_comparison(0.6, 0.6) == ("0.600", "0.600")


def test_values_too_small_for_any_fixed_width_fall_back_to_repr() -> None:
    """The ceiling is a ceiling, and the arm proves the collision before the fix."""
    assert f"{1e-300:.{COMPARISON_MAX_PLACES}f}" == f"{2e-300:.{COMPARISON_MAX_PLACES}f}"
    assert render_comparison(1e-300, 2e-300) == ("1e-300", "2e-300")


def test_a_negative_kappa_renders() -> None:
    """Cohen's κ ranges in [-1, 1], so a negative value is in contract."""
    assert render_comparison(-0.25, 0.6) == ("-0.250", "0.600")


# --------------------------------------------------------------------------
# Site 1 — the pytest assertion a developer reads when CI goes red
# --------------------------------------------------------------------------

_ROWS = [
    {
        "id": "qa_001",
        "input": "What color is the sky?",
        "expected_outputs": [{"kind": "exact", "value": "blue"}],
        "tags": ["geography"],
        "dataset_version": "demo-v0.1",
        "provenance": {"source": "self", "added_on": "2026-05-16"},
    },
]


def _run_eval_file(pytester: pytest.Pytester, *, score: str, threshold: float):
    dataset = pytester.path / "sample.jsonl"
    dataset.write_text("\n".join(json.dumps(r) for r in _ROWS) + "\n")
    pytester.makepyfile(
        f"""
        import pytest
        from eval_harness.runner import DatasetEchoSource

        class _StubBackend:
            def complete(self, system, user):
                return "SCORE: {score}\\nREASONING: stub."

        @pytest.mark.eval(
            suite="demo",
            dataset=r"{dataset}",
            answer_source=DatasetEchoSource(),
            judge_backend=_StubBackend(),
            threshold={threshold},
        )
        def test_near(eval_row, judge_score):
            pass
        """
    )
    return pytester.runpytest("-q")


def test_the_pytest_assertion_is_not_self_contradictory(pytester: pytest.Pytester) -> None:
    """The assertion message, out of a real plugin run (#252 site 1).

    Driven through `pytester` rather than by calling the formatter, so this arm
    also pins that the call site is wired up. A formatter-level check stays green
    against a call-site revert.
    """
    result = _run_eval_file(pytester, score="0.5996", threshold=0.6)
    out = "\n".join(result.outlines)
    match = re.search(r"score=(\S+) < threshold=(\S+)", out)
    assert match is not None, f"no threshold assertion in output:\n{out}"
    rendered_score, rendered_threshold = match.groups()
    assert rendered_score != rendered_threshold, (
        f"the assertion reads score={rendered_score} < threshold="
        f"{rendered_threshold} — it asserts an ordering and renders both sides "
        f"identically, in the one message a developer sees when CI goes red."
    )
    assert float(rendered_score) < float(rendered_threshold)


def test_an_ordinary_pytest_assertion_is_unchanged(pytester: pytest.Pytester) -> None:
    """A wide margin still renders at three places.

    `tests/test_pytest_plugin.py` and `..._body_signatures.py` pin `score=0.100`
    and `*score=0.000*threshold=0.500*`; this states that contract locally too.
    """
    result = _run_eval_file(pytester, score="0.1", threshold=0.5)
    result.stdout.fnmatch_lines(["*score=0.100*threshold=0.500*"])


# --------------------------------------------------------------------------
# Site 3 — the generated calibration report
# --------------------------------------------------------------------------


def _report(kappa: float, threshold: float) -> str:
    return render_report(
        CalibrationResult(n=10, cohens_kappa=kappa, pearson_r=0.8, judge_scores=[], rows=[]),
        judge_model="stub-model",
        threshold_kappa=threshold,
    )


def test_the_report_cannot_contradict_its_own_verdict() -> None:
    """A FAIL beside two numbers that read as equal is a report arguing with itself.

    Asserted over the rendered markdown rather than the helper, so a call-site
    revert cannot pass.
    """
    text = _report(0.5996, 0.6)
    assert "**FAIL**" in text, text
    bullet = re.search(r"- threshold for κ: (\S+)", text)
    cell = re.search(r"\| Cohen's κ \(binarized at 0\.5\) \| (\S+) \|", text)
    assert bullet is not None, text
    assert cell is not None, text
    rendered_threshold, rendered_kappa = bullet.group(1), cell.group(1)
    assert rendered_kappa != rendered_threshold, (
        f"the report publishes κ {rendered_kappa} against threshold "
        f"{rendered_threshold} and a FAIL verdict."
    )
    assert float(rendered_kappa) < float(rendered_threshold)
    assert _places(rendered_kappa) == _places(rendered_threshold), (
        "the κ cell and the threshold bullet are at different precisions, which "
        "is the mix that reads false."
    )


def test_a_passing_report_is_consistent_too() -> None:
    """The other verdict. A PASS whose numbers read as reversed is the same defect."""
    text = _report(0.6, 0.5996)
    assert "**PASS**" in text, text
    bullet = re.search(r"- threshold for κ: (\S+)", text)
    cell = re.search(r"\| Cohen's κ \(binarized at 0\.5\) \| (\S+) \|", text)
    assert bullet is not None
    assert cell is not None
    assert float(cell.group(1)) >= float(bullet.group(1))


# --------------------------------------------------------------------------
# The population
# --------------------------------------------------------------------------


def test_no_package_message_renders_a_threshold_beside_a_fixed_width_operand() -> None:
    """Discover the sites; do not trust a count written in prose.

    #252's body said "three sites". The first version of this arm keyed off a
    comparison *word or operator* in the message literal, and it found **three
    more** — the `length`, `embedding` and `judge` rows of `drift.py`'s report
    table, where the comparison is not spelled at all. It is spread across three
    adjacent cells: a `Drift (JSD)` score, a `Threshold`, and a `Status` that is
    `"drifted" if drift > threshold`, decided at full precision. Six, not three.

    So the population is defined by what the harm actually needs — **a threshold
    rendered in the same string as another formatted number** — rather than by
    how the comparison happens to be phrased. A row in a table and a sentence
    with the word "below" are the same defect; only one of them says so.

    Keying off a comparison operator was also how the first version produced five
    false positives: `<` and `>` match every HTML tag in `render_html`.

    `comparison.py` is exempt — it *is* the fix, and its docstring quotes the
    defective forms deliberately.
    """
    offenders: list[str] = []
    fixed_width = re.compile(r"\.\d+[fg]")
    for path in sorted(_PACKAGE.glob("*.py")):
        if path.name == "comparison.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            interpolations = [part for part in node.values if isinstance(part, ast.FormattedValue)]
            # Does this string interpolate a threshold at all?
            mentions_threshold = any(
                "threshold" in ast.unparse(part.value).lower() for part in interpolations
            )
            if not mentions_threshold:
                continue
            # ... and does it render some OTHER operand at a fixed width? That
            # other operand is the value the threshold was compared against, and
            # the two have to be rendered comparably. A fixed width on the
            # threshold *itself*, with no second number, is a standalone readout.
            offending_specs = [
                spec
                for part in interpolations
                if part.format_spec is not None
                and "threshold" not in ast.unparse(part.value).lower()
                for spec in [
                    "".join(p.value for p in part.format_spec.values if isinstance(p, ast.Constant))
                ]
                if fixed_width.fullmatch(spec)
            ]
            if offending_specs:
                offenders.append(f"{path.name}:{node.lineno} {offending_specs}")
    assert not offenders, (
        f"these strings render a threshold alongside an operand at a fixed "
        f"width: {offenders}. Route both through "
        f"`eval_harness.comparison.render_comparison` so the comparison stays "
        f"readable at a near-threshold margin (#252)."
    )


def test_the_population_arm_is_not_vacuous() -> None:
    """The discovery finds the real f-strings, so a pass means something.

    Without this, a typo in the AST walk (matching no `JoinedStr` at all) makes
    the arm above pass over an empty set. Counts strings that mention a threshold
    *regardless* of format spec — after the fix there are still several, they
    just render through the helper now.
    """
    mentioning = 0
    for path in sorted(_PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            if any(
                "threshold" in ast.unparse(part.value).lower()
                for part in node.values
                if isinstance(part, ast.FormattedValue)
            ):
                mentioning += 1
    assert mentioning >= 6, (
        f"the walk found only {mentioning} f-strings interpolating a threshold "
        f"across the package; #252 touched six sites, so the discovery has "
        f"stopped discovering."
    )
