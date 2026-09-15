"""The JSD axes are blind to *where* out-of-support candidate mass sits (#243, D-023).

Jensen-Shannon divergence over a histogram is invariant to how the candidate
distribution redistributes mass among buckets the golden distribution never
occupies. For any bucket with ``P_i == 0`` the per-bucket term works out to
exactly ``Q_i / 2``, independent of *which* such bucket the mass lands in. So an
input can move several buckets further from the golden distribution and not move
the axis by a single bit.

That is correct behaviour for a categorical divergence over unordered buckets —
the price of D-014's bounded symmetric choice — and this module does not try to
change it. What it pins is the consequence and the companion signal D-023 adds:
``DriftReport.n_length_off_support`` / ``n_judge_off_support``, the count of
candidate inputs in that invariant regime.

Two things are worth stating precisely, because both are easy to get wrong:

1. The count does **not** distinguish "just outside the support" from "far
   outside it" — it is invariant to exactly the same redistribution the JSD is.
   What it reports is *how much of the score is frozen*, which is a different
   and cheaper question.
2. It is nonetheless a real discriminator between reports: two candidate sets
   can produce the *same* JSD with entirely different amounts of it frozen.
   ``test_the_same_jsd_can_be_mostly_frozen_or_not_frozen_at_all`` is that case,
   found by exhaustive search rather than constructed by hand.
"""

from __future__ import annotations

import itertools
import math
import random

import pytest

from eval_harness.drift import (
    _off_support_count,
    compute_drift,
    jensen_shannon,
)

# The demo corpus's golden length histogram (examples/drift_report.py): all mass
# in the first two buckets, seven buckets empty.
DEMO_GOLDEN_LENGTH_HIST = (2, 6, 0, 0, 0, 0, 0, 0, 0)
DEMO_CANDIDATE_LENGTH_HIST = (1, 1, 6, 0, 0, 0, 0, 0, 0)
DEMO_LENGTH_JSD = 0.5689626904850149


def _per_bucket_terms(g: tuple[int, ...], c: tuple[int, ...]) -> list[float]:
    """JSD decomposed per bucket: ``H(M) - (H(P) + H(Q)) / 2``, base 2.

    Written here from the definition rather than imported, so the identity
    below is checked against the mathematics and not against the shipped
    implementation's own arithmetic.
    """

    def h(x: float) -> float:
        return 0.0 if x <= 0 else -x * math.log2(x)

    sp, sq = sum(g), sum(c)
    p = [x / sp for x in g]
    q = [x / sq for x in c]
    return [h((pi + qi) / 2) - (h(pi) + h(qi)) / 2 for pi, qi in zip(p, q, strict=True)]


# ----------------------------------------------------------------------
# The invariance itself — searched, not exampled
# ----------------------------------------------------------------------


def test_every_redistribution_of_out_of_support_mass_gives_one_jsd() -> None:
    """All 28 ways to split the demo's 6 off-support inputs give one score.

    The issue demonstrated this with a single perturbation (one input growing
    79 → 479 chars). One example is consistent with the axis merely being
    coarse. Enumerating the space shows the invariance is total.
    """
    p = DEMO_GOLDEN_LENGTH_HIST
    splits = [s for s in itertools.product(range(7), repeat=3) if sum(s) == 6]
    assert len(splits) == 28, "the search space itself must be what we think it is"
    scores = {round(jensen_shannon(p, (1, 1, a, b, c, 0, 0, 0, 0)), 15) for a, b, c in splits}
    assert len(scores) == 1, f"expected one JSD across 28 redistributions, got {scores}"
    assert scores.pop() == pytest.approx(DEMO_LENGTH_JSD, abs=1e-15)


def test_the_count_is_invariant_to_the_same_redistribution() -> None:
    """Stated so nobody mistakes the companion signal for a fix.

    `n_off_support` answers "how much of the score is frozen", not "how far out
    has the mass gone". It moves with the *amount* off support, not with its
    position — exactly like the JSD.
    """
    counts = {
        _off_support_count(DEMO_GOLDEN_LENGTH_HIST, (1, 1, a, b, c, 0, 0, 0, 0))
        for a, b, c in itertools.product(range(7), repeat=3)
        if sum((a, b, c)) == 6
    }
    assert counts == {6}


# ----------------------------------------------------------------------
# The exact contribution identity
# ----------------------------------------------------------------------


def test_off_support_buckets_contribute_exactly_half_their_fraction() -> None:
    """``sum of off-support terms == (off-support fraction) / 2``, exactly.

    This is what makes the count interpretable rather than merely suggestive:
    ``n_off_support / n_candidate / 2`` *is* the portion of the JSD that cannot
    respond to further movement of that mass.
    """
    rng = random.Random(11)
    checked = 0
    for _ in range(400):
        g = tuple(rng.choice([0, 0, 0, 3, 5, 8]) for _ in range(9))
        c = tuple(rng.randint(0, 9) for _ in range(9))
        if sum(g) == 0 or sum(c) == 0:
            continue
        terms = _per_bucket_terms(g, c)
        # The decomposition must reproduce the shipped function first, or the
        # identity below would be checked against the wrong quantity.
        assert sum(terms) == pytest.approx(jensen_shannon(g, c), abs=1e-12)
        off_terms = sum(t for gi, t in zip(g, terms, strict=True) if gi == 0)
        fraction = _off_support_count(g, c) / sum(c)
        assert off_terms == pytest.approx(fraction / 2, abs=1e-12)
        checked += 1
    assert checked > 300, f"the random search must actually exercise cases; got {checked}"


def test_the_identity_on_the_demo_corpus_with_exact_numbers() -> None:
    terms = _per_bucket_terms(DEMO_GOLDEN_LENGTH_HIST, DEMO_CANDIDATE_LENGTH_HIST)
    off = sum(t for gi, t in zip(DEMO_GOLDEN_LENGTH_HIST, terms, strict=True) if gi == 0)
    assert sum(terms) == pytest.approx(DEMO_LENGTH_JSD, abs=1e-15)
    # 6 of 8 candidate inputs off support -> 0.75 / 2 = 0.375 of the score, i.e.
    # about 66% of the demo's length-axis number, frozen.
    assert off == pytest.approx(0.375, abs=1e-15)
    assert off / sum(terms) == pytest.approx(0.65909, abs=5e-6)


# ----------------------------------------------------------------------
# The separating case: same score, different amount of it frozen
# ----------------------------------------------------------------------


def test_the_same_jsd_can_be_mostly_frozen_or_not_frozen_at_all() -> None:
    """Found by exhaustive search over 8 inputs across 5 buckets.

    Both candidates score ``0.311278124459`` against the same golden set. In the
    first, every input is inside the golden support and the whole score responds
    to further change. In the second, half the inputs are outside it and 80% of
    that identical number is frozen. The JSD alone cannot tell an operator which
    report they are holding; the count can.
    """
    golden = (4, 4, 0, 0, 0)
    fully_inside = (0, 8, 0, 0, 0)
    half_outside = (2, 2, 0, 0, 4)

    assert jensen_shannon(golden, fully_inside) == pytest.approx(
        jensen_shannon(golden, half_outside), abs=1e-12
    )
    assert _off_support_count(golden, fully_inside) == 0
    assert _off_support_count(golden, half_outside) == 4

    frozen = (4 / 8) / 2
    total = jensen_shannon(golden, half_outside)
    assert frozen / total == pytest.approx(0.803, abs=5e-4)


def test_moving_that_mass_further_out_changes_neither_score_nor_count() -> None:
    """The companion to the arm above: within the off-support region, nothing moves."""
    golden = (4, 4, 0, 0, 0)
    a = (2, 2, 0, 0, 4)
    b = (2, 2, 4, 0, 0)  # same mass, a different off-support bucket
    assert jensen_shannon(golden, a) == jensen_shannon(golden, b)
    assert _off_support_count(golden, a) == _off_support_count(golden, b) == 4


# ----------------------------------------------------------------------
# The report fields
# ----------------------------------------------------------------------


def test_the_demo_corpus_reports_its_off_support_mass() -> None:
    from examples.drift_report import (
        CANDIDATE_INPUTS,
        GOLDEN_INPUTS,
        length_weighted_judge,
    )

    report = compute_drift(
        golden_inputs=GOLDEN_INPUTS,
        candidate_inputs=CANDIDATE_INPUTS,
        judge_score_fn=length_weighted_judge,
        cluster_k=4,
    )
    assert report.length_histograms == (
        DEMO_GOLDEN_LENGTH_HIST,
        DEMO_CANDIDATE_LENGTH_HIST,
    )
    # 6 of 8 on both axes: three quarters of the demo's candidate traffic sits
    # where neither axis can see it move.
    assert report.n_length_off_support == 6
    assert report.n_judge_off_support == 6


def test_no_off_support_mass_when_candidate_stays_inside_golden_support() -> None:
    """Anti-vacuity for the fields and for both surfaces.

    A count that were always non-zero, or a note always appended, would pass
    every assertion above while saying nothing.
    """
    inputs = ["hello world alpha", "the quick brown fox", "lorem ipsum dolor sit"]
    report = compute_drift(golden_inputs=inputs * 3, candidate_inputs=inputs * 2)
    assert report.n_length_off_support == 0
    # The detail string is byte-unchanged when there is nothing to report.
    assert report.length.detail == "JSD over char-length histogram across 9 buckets"
    assert "never occupies" not in report.length.detail


def test_the_judge_slot_is_none_when_the_axis_is_skipped() -> None:
    """``None`` means "not measured"; ``0`` would claim "measured, none found".

    The same distinction ``judge`` and ``judge_stats`` already draw.
    """
    inputs = ["hello world alpha", "the quick brown fox", "lorem ipsum dolor sit"]
    skipped = compute_drift(golden_inputs=inputs * 3, candidate_inputs=inputs * 2)
    assert skipped.judge is None
    assert skipped.n_judge_off_support is None

    measured = compute_drift(
        golden_inputs=inputs * 3,
        candidate_inputs=inputs * 2,
        judge_score_fn=lambda s: 0.5,
    )
    assert measured.judge is not None
    assert measured.n_judge_off_support == 0
    assert isinstance(measured.n_judge_off_support, int)


def test_the_count_is_order_independent() -> None:
    """Matches the axis scores' own contract (tests/test_drift_input_order_independence.py)."""
    golden = ["hello world alpha", "the quick brown fox jumps over"] * 4
    candidate = ["hi", "x" * 600, "y" * 90000, "hello world alpha"] * 2
    rng = random.Random(3)
    baseline = compute_drift(golden_inputs=golden, candidate_inputs=candidate)
    for _ in range(20):
        g = list(golden)
        c = list(candidate)
        rng.shuffle(g)
        rng.shuffle(c)
        shuffled = compute_drift(golden_inputs=g, candidate_inputs=c)
        assert shuffled.n_length_off_support == baseline.n_length_off_support
    assert baseline.n_length_off_support > 0, "the corpus must exercise the non-zero path"


# ----------------------------------------------------------------------
# Rendered surfaces
# ----------------------------------------------------------------------


def test_the_html_reports_the_blind_spot_only_when_there_is_one() -> None:
    from eval_harness import render_drift_html

    inputs = ["hello world alpha", "the quick brown fox", "lorem ipsum dolor sit"]
    clean = render_drift_html(compute_drift(golden_inputs=inputs * 3, candidate_inputs=inputs * 2))
    assert "never occupies" not in clean

    drifted = render_drift_html(
        compute_drift(
            golden_inputs=["hello world alpha", "the quick brown fox jumps"] * 4,
            candidate_inputs=["hello world alpha"] * 2 + ["x" * 600] * 6,
        )
    )
    assert "never occupies" in drifted
    assert "6 of 8" in drifted
    assert "length axis" in drifted
