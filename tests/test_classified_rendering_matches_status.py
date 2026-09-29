"""A value published beside its own status cannot contradict it (#256).

The neighbouring population to `test_comparison_rendering_matches_gate.py`, and
the one D-026's own population arm wrote down as unreachable. That arm requires
a *threshold* and a differently-spelled fixed-width operand in one f-string;
these four sites carry a score and its `status` **and no threshold at all**::

    f"Length JSD = {report.length.drift_score:.3f} ({report.length.status})"

`status` is `"drifted" if drift > threshold else "ok"`, decided at full
precision against `DEFAULT_LENGTH_THRESHOLD = 0.10`. At `.3f`::

    0.10023738103794930  ->  'Length JSD = 0.100 (drifted)'
    0.09982675025460241  ->  'Length JSD = 0.100 (ok)'

The same published string carries both statuses, and the first is not merely
ambiguous: the boundary is strict, so `0.100` claims "at the threshold" while
`(drifted)` claims "past it".

On where the numbers in this file come from
-------------------------------------------

Not hand-picked. `COLLIDING_HISTOGRAMS` below are Jensen-Shannon divergences
over the drift module's **own** histogram shapes with ordinary small integer
counts, found by random search (~2M draws) and kept because they land inside
the `.3f` collision band around the **shipped default** threshold. A
hand-constructed float would leave open whether the band is reachable at all;
these say it is, from corpora of thirty-odd inputs, with no operator
configuration involved.

`test_the_old_fixed_width_collided_on_a_real_corpus` then carries them all the
way through `compute_drift` -> `render_html`, so the arm reads the drawn thing
rather than the computed one.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from eval_harness.comparison import (
    COMPARISON_PLACES,
    render_classified,
    render_comparison,
)
from eval_harness.drift import (
    DEFAULT_LENGTH_THRESHOLD,
    _length_histogram,
    compute_drift,
    jensen_shannon,
    render_html,
)

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = _ROOT / "eval_harness"

#: `(golden_histogram, candidate_histogram, expected_status)` over the nine
#: length buckets. Every one of these renders `0.100` at `.3f` against the
#: shipped 0.10 default, and they do not all carry the same status — which is
#: the whole defect in one table.
COLLIDING_HISTOGRAMS = [
    ((0, 2, 0, 4, 6, 6, 4, 3, 1), (1, 6, 1, 2, 5, 5, 5, 6, 0), "drifted"),
    ((4, 6, 3, 5, 6, 0, 4, 6, 4), (3, 3, 3, 4, 4, 6, 6, 6, 3), "drifted"),
    ((5, 6, 6, 0, 5, 6, 1, 1, 3), (4, 3, 4, 1, 3, 4, 2, 6, 6), "ok"),
    ((2, 0, 3, 6, 6, 3, 3, 2, 1), (1, 1, 2, 5, 3, 5, 5, 6, 0), "ok"),
]

#: One length per bucket of `drift._LENGTH_BUCKETS`, so a histogram can be
#: turned back into a corpus that reproduces it exactly.
_BUCKET_LENGTHS = (16, 48, 96, 192, 384, 768, 1536, 3072, 6144)

# Margins spanning both sides of the three-place boundary, matching the sweep
# `test_comparison_rendering_matches_gate.py` uses.
_MARGINS = [1e-1, 1e-2, 1e-3, 5e-4, 1e-4, 1e-5, 1e-6, 1e-8, 1e-10, 1e-12, 1e-14]
_IDS = [f"{m:g}" for m in _MARGINS]

_BOUNDARIES = [0.1, 0.5, 0.6, 0.85, 0.0, 0.1004, 0.33333333333333331]


def _corpus(histogram: tuple[int, ...], tag: str) -> list[str]:
    """Build a text corpus whose `_length_histogram` is exactly *histogram*."""
    out: list[str] = []
    for bucket, count in enumerate(histogram):
        for item in range(count):
            seed = f"{tag}-bucket{bucket}-item{item} alpha beta gamma delta "
            out.append(
                (seed * (_BUCKET_LENGTHS[bucket] // len(seed) + 1))[: _BUCKET_LENGTHS[bucket]]
            )
    return out


def _band(value: float, boundary: float) -> int:
    """Independent restatement of the property, so the arms do not import the rule they test."""
    if value < boundary:
        return -1
    if value > boundary:
        return 1
    return 0


# --------------------------------------------------------------------------
# The property
# --------------------------------------------------------------------------


@pytest.mark.parametrize("boundary", _BOUNDARIES, ids=[f"{b:g}" for b in _BOUNDARIES])
@pytest.mark.parametrize("margin", _MARGINS, ids=_IDS)
def test_the_rendered_value_falls_in_the_same_band(boundary: float, margin: float) -> None:
    """Below stays below, above stays above, and neither lands on the boundary.

    Three levels rather than two, and that is the arm that carries both
    directions of the issue at once. A two-level `is it still above` predicate
    is satisfied by a below-boundary value rendering *at* the boundary — which
    is exactly the string an above-boundary value used to render as, so the
    collision survives a check that only asks whether the status would flip.
    """
    for value in (boundary - margin, boundary + margin):
        rendered = render_classified(value, boundary)
        assert _band(float(rendered), boundary) == _band(value, boundary), (
            f"render_classified({value!r}, {boundary!r}) == {rendered!r}, which reads "
            f"back as {float(rendered)!r} — band {_band(float(rendered), boundary)} "
            f"against the value's own band {_band(value, boundary)}."
        )


@pytest.mark.parametrize("boundary", _BOUNDARIES, ids=[f"{b:g}" for b in _BOUNDARIES])
@pytest.mark.parametrize("margin", _MARGINS, ids=_IDS)
def test_no_rendered_string_carries_two_statuses(boundary: float, margin: float) -> None:
    """The harm stated as the reader sees it: one string, one verdict.

    The band property implies this, but the implication runs through an
    argument about decimal rounding, and the thing the issue actually reports
    is that `Length JSD = 0.100` was printed with `(drifted)` in one run and
    `(ok)` in another. Assert the reported symptom directly.
    """
    below, above = boundary - margin, boundary + margin
    assert render_classified(below, boundary) != render_classified(above, boundary), (
        f"{below!r} (ok) and {above!r} (drifted) both render as "
        f"{render_classified(below, boundary)!r} against boundary {boundary!r}."
    )


def test_a_value_exactly_at_the_boundary_renders_there() -> None:
    """The one value that *may* render at the boundary, because it is there.

    Not "renders narrow" — that was this arm's first claim and it is only a
    consequence, true whenever the boundary itself survives a three-place
    round trip. For a boundary that does not (`0.1004`), the narrow `0.100`
    reads back as `0.1`, strictly *below* a boundary the value sits exactly on,
    so widening is the truthful answer rather than an implied difference. The
    contract is the band; the width is whatever the band costs.
    """
    for boundary in _BOUNDARIES:
        rendered = render_classified(boundary, boundary)
        assert _band(float(rendered), boundary) == 0, (
            f"a value at the boundary rendered {rendered!r}, which reads back on the "
            f"{'below' if float(rendered) < boundary else 'above'} side of {boundary!r}."
        )
        if float(f"{boundary:.{COMPARISON_PLACES}f}") == boundary:
            assert rendered == f"{boundary:.{COMPARISON_PLACES}f}", (
                "a boundary representable at the default width must not be widened — "
                "there is nothing to distinguish it from."
            )


@pytest.mark.parametrize(
    "value",
    [0.569, 0.2454, 0.5701, 0.412, 0.0, 1.0, 0.95],
    ids=lambda v: f"{v:g}",
)
def test_an_unambiguous_value_is_byte_identical_to_the_old_rendering(value: float) -> None:
    """Ordinary output must not move (#256 acceptance criterion 4).

    The four values in front are the demo's own published axes plus the issue's
    `0.412 (drifted)`. `tests/test_demo_drift_published_values.py` is the lock
    that actually guards the artifact; this arm states the intent locally so a
    future change to this helper fails here with the reason attached.
    """
    assert render_classified(value, DEFAULT_LENGTH_THRESHOLD) == f"{value:.3f}"


def test_the_delegating_neighbour_is_wrong_on_two_inputs() -> None:
    """`render_comparison(value, boundary)[0]` was the first implementation, and it is wrong.

    It is the obvious neighbour — one widening loop in the package instead of
    two — and the argument for it is that two renderings differing at width `w`
    must straddle the boundary. Both counterexamples below were found by the
    arms above, not by reading, and each is a distinct hole:

    * **Signed zero.** `-0.0001` renders `'-0.000'` and `0.0` renders
      `'0.000'`. The *strings* differ, so the pairwise loop stops — and
      `float('-0.000')` is `-0.0`, which is not below `0.0`. String difference
      does not imply value difference.
    * **A boundary not representable at `places`.** For
      `value == boundary == 0.1004` the pairwise rule short-circuits on
      equality and returns `'0.100'`, which reads back as `0.1` — strictly
      below a boundary the value sits exactly on.

    Neither is reachable through `drift.py` today, and that is why this arm
    exists: a JSD is non-negative and the shipped thresholds are round, so the
    call sites cannot falsify the delegation. `render_classified` is public in
    a `py.typed` package, so the rule has to hold where the callers do not go.
    """
    for value, boundary in [(-1e-4, 0.0), (0.1004, 0.1004)]:
        delegated, _ = render_comparison(value, boundary)
        assert _band(float(delegated), boundary) != _band(value, boundary), (
            f"render_comparison({value!r}, {boundary!r})[0] == {delegated!r} now "
            f"classifies correctly. If that is a deliberate change to the pairwise "
            f"rule, `render_classified` can go back to delegating — but say so."
        )
        assert _band(float(render_classified(value, boundary)), boundary) == _band(value, boundary)


def test_the_repr_backstop_classifies_exactly() -> None:
    """Two distinct doubles no fixed width can separate still classify correctly.

    `render_comparison` ends on `repr` for this case and `render_classified`
    inherits it, plus reaches for it on its own whenever the verified band does
    not hold. `repr` round-trips a double by definition, so the band is exact.
    """
    boundary = 5e-324
    value = 1e-323
    rendered = render_classified(value, boundary)
    assert float(rendered) == value
    assert _band(float(rendered), boundary) == _band(value, boundary) == 1


# --------------------------------------------------------------------------
# Reachability: the band is not a theoretical region
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("golden", "candidate", "status"),
    COLLIDING_HISTOGRAMS,
    ids=[f"{s}-{i}" for i, (_, _, s) in enumerate(COLLIDING_HISTOGRAMS)],
)
def test_the_colliding_histograms_are_real_and_land_on_the_shipped_default(
    golden: tuple[int, ...], candidate: tuple[int, ...], status: str
) -> None:
    """The table's premise, checked rather than trusted.

    Each row must (a) be a genuine `jensen_shannon` over integer histograms,
    (b) render `0.100` at the old `.3f`, and (c) carry the status the table
    claims against the **shipped** `DEFAULT_LENGTH_THRESHOLD`. No operator
    configuration, no constructed float.
    """
    score = jensen_shannon(golden, candidate)
    assert f"{score:.3f}" == "0.100"
    assert ("drifted" if score > DEFAULT_LENGTH_THRESHOLD else "ok") == status


def test_the_table_holds_both_statuses() -> None:
    """A table of four `drifted` rows would prove ambiguity, not contradiction.

    The defect is that *one* string carries *two* verdicts, so the fixture has
    to contain both — otherwise every arm below passes on a table that cannot
    express the harm.
    """
    assert {status for _, _, status in COLLIDING_HISTOGRAMS} == {"drifted", "ok"}


@pytest.mark.parametrize(
    ("golden", "candidate", "status"),
    COLLIDING_HISTOGRAMS[:1] + COLLIDING_HISTOGRAMS[2:3],
    ids=["drifted", "ok"],
)
def test_the_old_fixed_width_collided_on_a_real_corpus(
    golden: tuple[int, ...], candidate: tuple[int, ...], status: str
) -> None:
    """Read the *drawn* thing: a corpus through `compute_drift` into the SVG title.

    Two of the four rows carried end to end, one per status, because
    `compute_drift` also runs k-means over every input. The arm asserts the
    title the reader sees, not the number the module computed — the distinction
    that made `vector-search-at-scale#148`'s first set of arms vacuous.
    """
    g_corpus, c_corpus = _corpus(golden, "g"), _corpus(candidate, "c")
    assert _length_histogram(g_corpus) == golden
    assert _length_histogram(c_corpus) == candidate

    report = compute_drift(g_corpus, c_corpus, cluster_k=4)
    assert report.length.status == status
    assert f"{report.length.drift_score:.3f}" == "0.100", "corpus no longer lands in the band"

    title = _svg_title(render_html(report), "Length JSD")
    assert title != f"Length JSD = 0.100 ({status})"
    assert title.endswith(f" ({status})")
    value = title.removeprefix("Length JSD = ").removesuffix(f" ({status})")
    assert _band(float(value), report.length.threshold) == _band(
        report.length.drift_score, report.length.threshold
    ), f"the published title {title!r} classifies differently from the score it reports"


@pytest.mark.parametrize("width", [3, 4, 6, 12], ids=lambda w: f".{w}f")
def test_no_fixed_width_survives_a_caller_set_threshold(width: int) -> None:
    """The arm that rejects "just publish more decimals", on a real corpus.

    `compute_drift`'s thresholds are documented as caller-set policy — "drifted
    is a policy decision, not a math one" — and deriving one from a previous
    run's measured score is an ordinary way to set it. So for **any** fixed
    width there is a reachable threshold that collides with it, which is the
    half of D-026 that a corpus sweep against the shipped 0.10 default cannot
    show: `.6f` happens to separate every score in `COLLIDING_HISTOGRAMS`, so
    those arms stay green against a `.6f` neighbour.

    Here the threshold is placed one ULP-ish below and exactly at the measured
    score, so the two runs differ in status and agree to *width* places
    whatever *width* is. The fix passes because it widens until the band is
    right; a rendering pinned at any number of places cannot.
    """
    golden, candidate, _ = COLLIDING_HISTOGRAMS[0]
    g_corpus, c_corpus = _corpus(golden, "g"), _corpus(candidate, "c")
    score = jensen_shannon(_length_histogram(g_corpus), _length_histogram(c_corpus))

    just_under = score - score * 1e-15
    assert just_under < score, "the perturbation vanished into the float"
    assert f"{just_under:.{width}f}" == f"{score:.{width}f}", (
        f"the two thresholds separate at .{width}f, so this arm would not exercise a collision"
    )

    titles = {}
    for threshold, expected in ((just_under, "drifted"), (score, "ok")):
        report = compute_drift(g_corpus, c_corpus, cluster_k=4, length_threshold=threshold)
        assert report.length.status == expected
        title = _svg_title(render_html(report), "Length JSD")
        assert _band(
            float(title.removeprefix("Length JSD = ").removesuffix(f" ({expected})")),
            threshold,
        ) == _band(report.length.drift_score, threshold), (
            f"published {title!r} against threshold {threshold!r} classifies "
            f"differently from the score it reports"
        )
        titles[expected] = title
    assert titles["drifted"] != titles["ok"], (
        f"both runs published {titles['ok']!r} with opposite statuses"
    )


def _svg_title(document: str, prefix: str) -> str:
    """Pull one `<text>` chart title out of the rendered HTML."""
    match = re.search(rf">({re.escape(prefix)}[^<]*)<", document)
    assert match is not None, f"no {prefix!r} title in the rendered report"
    return match.group(1)


# --------------------------------------------------------------------------
# The population
# --------------------------------------------------------------------------

#: A *classification* — a value drawn from a small closed set by a comparison —
#: and not merely a caption. Matched against a bare name or the final attribute
#: of a dotted access, never as a substring: the first draft of this arm keyed
#: on `"label" in source` and flagged `_bar_chart_svg`'s x-axis tick captions,
#: which is D-026's V1-to-V3 lesson recurring in the neighbouring population.
_STATUS_NAMES = frozenset({"status", "verdict", "outcome", "state"})


def _classification_name(node: ast.expr) -> str | None:
    """The identifier a status interpolation resolves to, or None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_classification(node: ast.expr) -> bool:
    return _classification_name(node) in _STATUS_NAMES


def _is_fixed_width(spec: ast.expr | None) -> bool:
    if spec is None or not isinstance(spec, ast.JoinedStr):
        return False
    text = "".join(p.value for p in spec.values if isinstance(p, ast.Constant))
    return re.fullmatch(r"\.\d+[fg]", text) is not None


def _package_joined_strings() -> list[tuple[str, ast.JoinedStr]]:
    found = []
    for path in sorted(_PACKAGE.glob("*.py")):
        if path.name == "comparison.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend(
            (path.name, node) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)
        )
    return found


def test_no_package_message_renders_a_fixed_width_value_beside_its_own_status() -> None:
    """Discover the four sites; do not trust the list in the issue body.

    Keyed on what the harm needs — a value at a fixed width and a
    classification label **in the same string** — rather than on the three
    chart titles and the summary line the issue happened to name. The three
    titles and the CLI summary are spelled differently enough (one is an
    argument to `_bar_chart_svg`, one is built by `+=` in a branch) that a
    hand-list is precisely what would leave a fifth axis behind, and a fifth
    axis is the obvious next change to this module.

    Deliberately disjoint from
    `test_comparison_rendering_matches_gate.py::test_no_package_message_renders_a_threshold_beside_a_fixed_width_operand`:
    that arm requires a threshold **in the string**, which is why it could not
    see these. This one excludes strings that mention a threshold, so the two
    partition the surface instead of overlapping and each keeps its own reason
    for existing.

    `comparison.py` is exempt — it is the fix, and its docstring quotes the
    defective forms on purpose.
    """
    offenders: list[str] = []
    for name, node in _package_joined_strings():
        interpolations = [p for p in node.values if isinstance(p, ast.FormattedValue)]
        sources = [ast.unparse(p.value).lower() for p in interpolations]
        if any("threshold" in src for src in sources):
            continue  # the two-number shape; D-026's arm owns it
        mentions_status = any(any(word in src for word in _STATUS_NAMES) for src in sources)
        if not mentions_status:
            continue
        bad = [
            ast.unparse(p.value)
            for p in interpolations
            if _is_fixed_width(p.format_spec)
            and not any(word in ast.unparse(p.value).lower() for word in _STATUS_NAMES)
        ]
        if bad:
            offenders.append(f"{name}:{node.lineno} {bad}")
    assert not offenders, (
        f"these strings publish a value at a fixed width beside a status decided "
        f"at full precision: {offenders}. Route the value through "
        f"`eval_harness.comparison.render_classified` so the number and the label "
        f"beside it cannot disagree (#256)."
    )


def test_the_population_arm_is_not_vacuous() -> None:
    """The walk reaches the real f-strings, so a pass means something.

    Counts strings interpolating a status *regardless* of format spec. After
    the fix the four sites are still here — they render through the helper now,
    so the offending arm is empty while this one is not. A typo in the AST walk
    makes both empty, and only this one notices.
    """
    mentioning = 0
    for _, node in _package_joined_strings():
        if any(
            _is_classification(p.value) for p in node.values if isinstance(p, ast.FormattedValue)
        ):
            mentioning += 1
    assert mentioning >= 4, (
        f"the walk found only {mentioning} f-strings interpolating a status across "
        f"the package; #256 touched four sites, so the discovery has stopped "
        f"discovering."
    )


def test_every_drift_axis_title_is_routed() -> None:
    """A per-axis count, because the three titles are three separate literals.

    The population arm above is satisfied by zero offenders, which a deletion
    would also satisfy. This one names the three axes and the summary line and
    requires each to call the helper — the `run the command the artifact
    documents` half: assert the routing exists, not only that the defect is
    absent.
    """
    source = (_PACKAGE / "drift.py").read_text(encoding="utf-8")
    assert "from eval_harness.comparison import render_classified" in source
    calls = source.count("render_classified(")
    assert calls == 6, (
        f"drift.py calls render_classified {calls} times; expected 6 — three chart "
        f"titles and the three axes of the CLI summary line. The import is asserted "
        f"separately above because it carries no parenthesis."
    )
    for axis in ("length", "embedding", "judge"):
        assert f"render_classified(report.{axis}.drift_score, report.{axis}.threshold)" in source
