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

Three kinds of number, three acceptance tests, one loop
-------------------------------------------------------

The module now holds three renderers. They differ only in *what makes a width
wide enough*, and the difference is what each number **is**:

======================  ====================================  ====================
number                  wide enough when...                   function
======================  ====================================  ====================
a decided comparison    the two render differently            `render_comparison`
a classified value      it reads back into the same band      `render_classified`
a configured parameter  it reads back as itself               `render_configured`
======================  ====================================  ====================

The third is #257 and is a *different* class from the first two, not a third
spelling of them. There is no second number and no verdict beside it: it is the
policy input an operator typed, echoed back at a fixed width. The harm is not
that the sentence contradicts itself — it is that the tool **misreports its own
configuration**. `--threshold-drop 0.001` printed as ``threshold_drop=0.00``
does not read as ambiguous; it reads as the *strictest possible setting*, the
opposite end of the range from what was asked for.

**And the class reaches into `render_comparison`, which is why `exact_other`
exists.** The pairwise loop stops as soon as the two strings differ, and the
threshold is a *configured* number at every one of this package's six call
sites. With a round threshold that is invisible — ``0.6`` renders ``0.600`` and
reads back as ``0.6``. With ``--threshold-kappa 0.6004`` against a κ of ``0.9``
the loop stops at three places and publishes ``threshold 0.600``, which is a
policy the operator did not set and which predicts the wrong verdict for any
future κ in ``[0.600, 0.6004)``. Measured: four of five probe pairs narrow the
configured side. D-026 made the *ordering* readable and had no reason to ask
whether either operand survived the trip; asking it is D-029.
"""

from __future__ import annotations

from collections.abc import Sequence

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
    value: float, other: float, *, places: int = COMPARISON_PLACES, exact_other: bool = False
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
    does. (``exact_other`` overrides that: an equal pair still widens until the
    configured side reads back as itself, because misreporting the policy is a
    false claim whether or not the measurement happens to equal it.)

    **``exact_other`` marks *other* as a configured parameter** — a policy input
    an operator typed, rather than something this package measured (#257). The
    pair then widens until the ordering is readable *and* ``other`` reads back
    as itself, still at one shared width. Without it the loop stops the instant
    the two strings differ, which at three places publishes a configured
    ``0.6004`` as ``0.600``: not a collision, and not backwards, but a
    *different policy* than the one in force. See :func:`render_configured` for
    the standalone form of the same rule.

    There is deliberately no ``exact_value``. ``value`` is the measured side at
    all six call sites, and a measurement rendered at three places is a summary
    a reader expects, not a misstatement of anything an operator set. The
    asymmetry is the finding, so the parameter is asymmetric and says so; the
    population arm in ``tests/test_configured_parameter_round_trip.py`` is what
    holds a seventh call site to the same reading of which operand is which.
    """
    for width in range(places, COMPARISON_MAX_PLACES + 1):
        rendered = (f"{value:.{width}f}", f"{other:.{width}f}")
        if exact_other and float(rendered[1]) != other:
            # Round-tripping is monotone in width -- a wider rendering is at
            # least as close to `other`, and the intervals that round to a given
            # double nest -- so skipping this width cannot skip past a narrower
            # acceptable one.
            continue
        if value == other or rendered[0] != rendered[1]:
            return rendered
    # Two distinct doubles too small for any fixed-point rendering to separate.
    # `repr` round-trips a float by definition, so it always distinguishes them
    # and, under `exact_other`, reproduces the configured value exactly. This is
    # the one exit that does not guarantee a shared precision, which is as true
    # of `repr(0.1), repr(0.25)` as it ever was.
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


def render_signed_classified(
    value: float, boundaries: Sequence[float], *, places: int = COMPARISON_PLACES
) -> str:
    """:func:`render_classified` for a signed value judged against several boundaries.

    A delta table publishes each row's delta beside a verdict decided against
    **two** boundaries -- ``-threshold_drop`` for the flag and ``0`` for
    regressed / unchanged / improved -- and both renderers printed it at
    ``+.3f`` (#291)::

        0.8 -> 0.6996   -0.100  FLAG
        0.8 -> 0.7004   -0.100
        0.5 -> 0.50004  +0.000  improved

    The same rule as :func:`render_classified`, stated over every boundary at
    once: widen until the rendered value, read back as a float, falls on the
    same side of *each* boundary as the true value does. A value exactly at a
    boundary keeps the starting width -- widening would imply a difference that
    is not there -- and ``repr`` is the fallback. Signed, because a delta's
    sign is part of what the reader is told; ``-0.000`` reads back as ``-0.0``,
    which is *at* zero, so a tiny regression widens rather than printing it.
    """
    targets = [_band(value, b) for b in boundaries]
    for width in range(places, COMPARISON_MAX_PLACES + 1):
        rendered = f"{value:+.{width}f}"
        back = float(rendered)
        if [_band(back, b) for b in boundaries] == targets:
            return rendered
    return format(value, "+")


def render_configured(value: float, *, places: int = COMPARISON_PLACES) -> str:
    """Render a configured parameter so it reads back as the value that was set.

    The third member of this module's family, and the one with neither a second
    number nor a verdict beside it (#257): a *policy input* echoed back to the
    operator who set it.

    ``runner.render_delta_ascii`` published the delta gate at ``.2f`` and
    ``comment.py`` published the same field at ``.3f``, in the same CI run::

        configured 0.05     .2f -> 0.05    .3f -> 0.050
        configured 0.0125   .2f -> 0.01    .3f -> 0.013
        configured 0.001    .2f -> 0.00    .3f -> 0.001

    Two surfaces disagreeing about one number is the visible half. The half that
    matters is the last row: ``threshold_drop=0.00`` reads as *"any drop at all
    is a regression"* — the strictest setting the flag has — for a run actually
    gated at ``0.001``. A configured value does not have a near-threshold case
    the way a measurement does; it is wrong or it is right, and rounding makes
    it wrong at every magnitude finer than the width.

    **Wide enough means it reads back as itself.** Widen from *places* until
    ``float(rendered) == value``. Stating the rule on the round trip rather than
    on a width is the same move :func:`render_comparison` documents and for the
    same reason: a hand-picked number of places has no way to say what it is
    *for*, and any fixed width is wrong for some legal ``--threshold-drop``.

    ``places`` is a floor, not a target, so this never narrows a published
    column: at the shipped ``DEFAULT_THRESHOLD_DROP = 0.1`` three places gives
    ``'0.100'``, which round-trips, so the PR comment is byte-identical to what
    it published before. (The ASCII header widens ``'0.10'`` -> ``'0.100'``,
    which is the deliberate half of D-029: it is the only way for the two
    surfaces to share a precision without narrowing the comment.)

    **Not ``repr`` or ``:g`` directly**, though both round-trip. Both would
    narrow ``'0.100'`` to ``'0.1'`` in a published artifact — the exact
    regression ``tests/test_demo_drift_published_values.py`` caught in D-026 —
    and ``repr`` reaches for exponent form at small magnitudes, so a report line
    would read ``threshold drop: 1e-05``. ``repr`` survives only as the terminal
    fallback, for the values no fixed-point rendering can reach at all: it
    round-trips a double by definition, so ``render_configured(1e-300)`` is
    ``'1e-300'`` rather than seventeen zeros, and ``--threshold-drop 1e-300``
    is a finite non-negative number the validator accepts.

    Total on every float. A non-finite ``value`` never satisfies the round trip
    (``float('nan') != nan``) and falls through to ``repr``, giving ``'nan'`` --
    though every caller in this package rejects non-finite input upstream, and
    ``runner.diff_runs`` and ``DeltaReport.from_json`` both say so by name.
    """
    for width in range(places, COMPARISON_MAX_PLACES + 1):
        rendered = f"{value:.{width}f}"
        if float(rendered) == value:
            return rendered
    return repr(value)
