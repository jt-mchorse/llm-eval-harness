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
