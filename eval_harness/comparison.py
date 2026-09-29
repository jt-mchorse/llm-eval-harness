"""Rendering a comparison that has already been decided — one home for a class.

Every gate in this package decides at full float precision and then explains the
decision in a string a human reads::

    if score.score < spec.threshold:        # full precision
        raise AssertionError(f"score={score.score:.3f} < threshold={spec.threshold:.3f}")

At a near-threshold margin — the ordinary shape of a marginal eval result, and
exactly when someone reads the message most carefully — that renders::

    score=0.600 < threshold=0.600

The gate is right. The sentence is not. **Nothing in a suite that asserts on
verdicts can catch this**, because the verdict is correct in every colliding
case; the only thing wrong is that the explanation contradicts itself.

Three independent spellings of the same mistake already existed when this module
was written (#252):

* ``pytest_plugin.py`` — both sides at ``.3f``: the collision is *symmetric*,
  so the claim reads as ``0.600 < 0.600``.
* ``cli.py`` — κ at ``.3f``, threshold **unformatted**, emitted as a
  ``::error::`` GitHub Actions annotation. Mixed precision is worse than
  matched: ``Cohen's κ 0.600 < threshold 0.6`` is not ambiguous, it is
  **false** as written.
* ``calibration.render_report`` — a ``PASS``/``FAIL`` computed at full precision
  beside a ``.3f`` κ cell and an unformatted threshold line.

`eval_harness.markdown` exists for the same reason and says so: the GFM-escaping
class "kept recurring" because the fix "was written inline at three call sites",
so "a fourth emitter copies the pipe line and forgets the newline". Same posture
here, at the same count.

Duplicated from `prompt-regression-suite`'s D-012 rather than shared. The two are
separate distributions with no dependency between them, and manufacturing one so
a six-line formatter could be imported would be a worse trade than the
duplication. Recorded in D-026 so it does not read as an accident.
"""

from __future__ import annotations

#: Default starting width. Most messages in this package have always used three
#: places, and still do whenever three is enough to tell the two numbers apart.
#:
#: Callers whose surface already published a *wider* column must pass their own
#: `places` — narrowing is as much a change to a published artifact as widening.
#: `drift.render_html`'s summary table renders its JSD scores at four places and
#: is pinned at that width by `tests/test_demo_drift_published_values.py`, which
#: is what caught this: the first version of this module hardcoded three and
#: silently republished `0.5690` as `0.569`.
COMPARISON_PLACES = 3

#: Ceiling on widening. A double round-trips in at most 17 significant digits,
#: so 17 decimal places separates any two distinct doubles at the magnitudes
#: these gates work at -- a κ in ``[-1, 1]`` and a judge score in ``[0, 1]``. It
#: is a ceiling rather than a guarantee: two subnormal-scale values render
#: identically at *any* fixed number of places, which is what the `repr`
#: fallback is for.
COMPARISON_MAX_PLACES = 17


def render_comparison(
    value: float, other: float, *, places: int = COMPARISON_PLACES
) -> tuple[str, str]:
    """Render two numbers so an ordering stated between them stays readable.

    Returns ``(rendered_value, rendered_other)``, always at the same precision.

    ``places`` is the *starting* width and defaults to three. It exists because
    this function must never narrow a column: a caller already publishing four
    places has to say so, or the fix for an invisible ordering becomes a silent
    change to a pinned artifact. That is not hypothetical — it happened, and
    `tests/test_demo_drift_published_values.py` is what said so.

    **Both halves are load-bearing, and the second is the one that is easy to
    miss.** Widening only the side that needs it looks correct for as long as
    that side is the one carrying the long decimal expansion -- which is what
    happens whenever the *threshold* is a round configured number like ``0.6``.
    When the threshold is the long one instead, mixed precision renders the
    ordering **backwards**: ``cli.py``'s existing ``Cohen's κ 0.600 < threshold
    0.6`` is that failure already shipped, because ``0.600 < 0.6`` read as
    written is False.

    **The rule is on the rendered strings, not on a width.** A wider fixed width
    relocates the collision rather than removing it: ``.4f`` collides at
    ``0.59996`` and ``.6f`` at ``0.5999999995``, and a rule expressed as a
    hand-picked number of places has no way to say what it is *for*. Comparing
    the rendered strings cannot drift from what the reader sees, because it is
    what the reader sees.

    Equal inputs return the narrow rendering unwidened -- there is nothing to
    distinguish, and widening would imply a difference that is not there. The
    gates in this package only reach their messages on a strict inequality, so
    none of them depends on that, but the function is total and says what it
    does.
    """
    if value == other:
        return (f"{value:.{places}f}", f"{other:.{places}f}")
    for width in range(places, COMPARISON_MAX_PLACES + 1):
        rendered = (f"{value:.{width}f}", f"{other:.{width}f}")
        if rendered[0] != rendered[1]:
            return rendered
    # Two distinct doubles too small for any fixed-point rendering to separate.
    # `repr` round-trips a float by definition, so it always distinguishes them.
    return (repr(value), repr(other))


def _band(value: float, boundary: float) -> int:
    """Which side of *boundary* *value* falls on: ``-1`` below, ``0`` at, ``1`` above."""
    if value < boundary:
        return -1
    if value > boundary:
        return 1
    return 0


def render_classified(value: float, boundary: float, *, places: int = COMPARISON_PLACES) -> str:
    """Render one number so the label printed beside it cannot contradict it.

    The neighbouring population to :func:`render_comparison`, and the one
    D-026's own population arm wrote down as unreachable: *a value beside its
    own classification*, with the boundary **not in the string at all** (#256).

    `drift.py` publishes the same three JSD scores in seven places. Three are
    table rows carrying a score, a threshold and a status in adjacent cells --
    two numbers in one comparison, which is :func:`render_comparison`'s shape
    and was fixed in #252. The other four pair a score with its `status` and
    nothing else::

        f"Length JSD = {report.length.drift_score:.3f} ({report.length.status})"

    `status` is `"drifted" if drift > threshold else "ok"`, decided at full
    precision. At `.3f` against the shipped `DEFAULT_LENGTH_THRESHOLD = 0.10`::

        0.10001335982634979  ->  'Length JSD = 0.100 (drifted)'
        0.09999863005670209  ->  'Length JSD = 0.100 (ok)'
        0.1                  ->  'Length JSD = 0.100 (ok)'

    The first two are real Jensen-Shannon divergences over this module's own
    nine-bucket length histograms, found by search rather than constructed
    (#256), and they are carried end to end through `compute_drift` in
    `tests/test_classified_rendering_matches_status.py`. **The identical
    published string carries both statuses**, and the first is not merely
    ambiguous but self-contradicting: the boundary is strict, so `0.100` says
    "at the threshold" while `(drifted)` says "past it".

    **The property is on the band, not on two numbers differing.** There is no
    second number in the string to widen against, so the rule is stated one
    level up: *the rendered value, read back as a float, falls on the same side
    of the boundary as the true value does* -- below, at, or above, the
    boundary being its own degenerate band. Both directions of the defect fall
    out of that one sentence. A value above must not render at the boundary
    (that reads as a contradiction); a value below must not either (that
    collides with the rendering of a value above, which is how one string comes
    to carry two verdicts); and a value that really is at the boundary must
    render there, because widening it would imply a difference that is not
    real.

    **Its own loop, and not ``render_comparison(value, boundary)[0]``.** That
    delegation was the first implementation, on the argument that two
    renderings differing at width ``w`` must straddle the boundary. The
    argument is wrong twice, and both were caught by the arms in the test
    module rather than by reading:

    * **Signed zero.** ``-0.0001`` against a boundary of ``0.0`` renders
      ``'-0.000'`` while the boundary renders ``'0.000'``. The strings differ,
      so the pairwise loop stops -- and ``float('-0.000')`` is ``-0.0``, which
      is *not* below ``0.0``. Two different strings, one value.
    * **A boundary that is not representable at ``places``.** For
      ``value == boundary == 0.1004``, the pairwise rule returns the narrow
      ``'0.100'`` unwidened, which reads back as ``0.1`` -- strictly *below* a
      boundary the value is exactly *on*.

    Neither is reachable through `drift.py` today (a JSD is non-negative and
    the shipped thresholds are round), which is the point: this is a public
    helper in a ``py.typed`` package, and a rule that happens to hold for the
    current call sites is not the rule it claims to be.

    ``repr`` is the terminal fallback, as in :func:`render_comparison`: it
    round-trips a double by definition, so it classifies exactly. It is reached
    only when no fixed width up to :data:`COMPARISON_MAX_PLACES` can separate
    the value from the boundary.

    ``places`` is the starting width, for the same never-narrow reason
    :func:`render_comparison` documents. All four call sites in `drift.py`
    publish three places today and pass the default.
    """
    target = _band(value, boundary)
    for width in range(places, COMPARISON_MAX_PLACES + 1):
        rendered = f"{value:.{width}f}"
        if _band(float(rendered), boundary) == target:
            return rendered
    return repr(value)
