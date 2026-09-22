"""D-023 excluded the embedding axis on a false premise (#246, D-024).

D-023 gave `DriftReport` an off-support count on the two histogram axes and
deliberately left the embedding axis out, reasoning that "every comparable
candidate is assigned to some golden centroid, so 'outside the support' has no
counterpart there".

The premise is true. The conclusion does not follow. *The support* is the set of
buckets the **golden** histogram occupies, not the set of centroids that exist,
and `_kmeans` retains a centroid whose cluster went empty rather than dropping
it::

    for ci in range(k):
        if counts[ci] == 0:
            new_centroids[ci] = list(centroids[ci])   # retained, not dropped
            continue

So `g_cluster_counts[i] == 0` is reachable, `_assign` will route a candidate to
that centroid, and the embedding score is the same `jensen_shannon` over a
histogram with the same `Q_i / 2` invariance. This module pins that it is
reachable, that the invariance really is present on this axis, and the one thing
about the embedding count that differs from its two siblings: its denominator.

**The denominator is the clustered candidate count, not `n_candidate`.** This
axis drops inputs with no embeddable content, and the JSD normalises the
histogram it is actually handed. `test_the_frozen_contribution_is_measured_over_
the_clustered_candidates` is the arm that rejects the other unit: on a corpus
with one uncomparable candidate the true frozen contribution is `(1/2)/2 = 0.25`
of a 0.4733 score, while an `n_candidate` base would claim `(1/3)/2 = 0.1667`.

Neither corpus below was constructed by hand. Both were found by random search
over the module's own `hash_embed` / `_kmeans` / `_assign` path and then reduced
by greedy delta-debugging, which is why the golden set in case B carries five
copies of `"rollback"` — the duplicates are load-bearing for the cluster
structure that leaves a centroid empty, and every attempt to drop one loses the
property.
"""

from __future__ import annotations

import dataclasses
import math
import re

import pytest

from eval_harness.drift import (
    _kmeans,
    _off_support_count,
    compute_drift,
    hash_embed,
    jensen_shannon,
    render_html,
)

# --- Case A: reachable off-support mass at a mid-range score ---------------
# Random search + delta-debugging. Two golden-empty clusters (ids 1 and 2), two
# of the three candidates landing in one of them.
A_GOLDEN = ["charge", "billing delivery", "package", "delivery billing"]
A_CANDIDATE = ["zebra", "enzyme", "enzyme"]
A_KWARGS = {"cluster_k": 8, "embedding_dim": 64}
A_GOLDEN_HIST = (3, 0, 0, 1)
A_CANDIDATE_HIST = (1, 2, 0, 0)
A_JSD = 0.5176503615477757

# --- Case B: the denominator case ----------------------------------------
# One candidate has no embeddable content, so the clustered count (2) and
# `n_candidate` (3) differ and the two candidate denominators disagree.
B_GOLDEN = [
    "rollback",
    "rollback",
    "replica",
    "rollback",
    "canary",
    "cluster namespace",
    "cluster",
    "rollback",
    "rollback",
]
B_CANDIDATE = ["deployment", "!!!", "namespace"]
B_KWARGS = {"cluster_k": 3, "embedding_dim": 16}
B_GOLDEN_HIST = (4, 5, 0)
B_CANDIDATE_HIST = (0, 1, 1)
B_JSD = 0.4732773112896197

# --- Case C: an ordinary report, nothing off support ----------------------
C_GOLDEN = [
    "where is my package",
    "track my shipment",
    "refund my charge",
    "invoice for march",
]
C_CANDIDATE = ["where is my order", "tracking please", "refund the charge", "march invoice"]
C_KWARGS = {"cluster_k": 3, "embedding_dim": 32}


def _per_bucket_terms(g: tuple[int, ...], c: tuple[int, ...]) -> list[float]:
    """JSD decomposed per bucket: ``H(M) - (H(P) + H(Q)) / 2``, base 2.

    Written from the definition rather than imported, so the identity below is
    checked against the mathematics and not against the shipped function's own
    arithmetic. Same helper shape as `test_drift_off_support_mass.py`.
    """

    def h(x: float) -> float:
        return 0.0 if x <= 0 else -x * math.log2(x)

    sp, sq = sum(g), sum(c)
    p = [x / sp for x in g]
    q = [x / sq for x in c]
    return [h((p[i] + q[i]) / 2) - (h(p[i]) + h(q[i])) / 2 for i in range(len(g))]


# ----------------------------------------------------------------------
# The premise D-023 reasoned from
# ----------------------------------------------------------------------


def test_kmeans_retains_a_centroid_whose_cluster_went_empty() -> None:
    """The mechanism that makes an off-support cluster reachable at all.

    If someone later changes `_kmeans` to *drop* an empty cluster instead of
    freezing its centroid, D-023's original reasoning becomes true and this
    whole module's premise changes. That is a thing to notice deliberately, so
    it is pinned here rather than left implicit in the corpora below.
    """
    vecs = [hash_embed(s, dim=64) for s in A_GOLDEN]
    centroids, assigns = _kmeans(vecs, 8)

    # k is clamped to n, and every centroid slot survives the run...
    assert len(centroids) == len(A_GOLDEN) == 4
    # ...including the ones no input is assigned to.
    occupied = set(assigns)
    assert occupied != set(range(len(centroids)))
    assert sorted(set(range(len(centroids))) - occupied) == [1, 2]


def test_a_candidate_reaches_a_cluster_no_golden_input_occupies() -> None:
    """The conclusion D-023 drew does not follow from its premise.

    Every candidate is indeed assigned to *some* centroid -- and two of these
    three are assigned to a centroid the golden set never occupies, which is
    what "outside the support" means for a histogram.
    """
    report = compute_drift(A_GOLDEN, A_CANDIDATE, **A_KWARGS)
    golden_hist, candidate_hist = (cs.cluster_counts for cs in report.cluster_stats)

    assert golden_hist == A_GOLDEN_HIST
    assert candidate_hist == A_CANDIDATE_HIST
    assert golden_hist[1] == 0
    assert candidate_hist[1] == 2
    assert report.n_embedding_off_support == 2


# ----------------------------------------------------------------------
# The invariance, on this axis
# ----------------------------------------------------------------------


def test_every_redistribution_among_the_empty_clusters_gives_one_score() -> None:
    """The `Q_i / 2` invariance is present on the embedding axis too.

    Redistributing the off-support mass among the golden-empty clusters moves
    the candidate distribution and leaves the score bit-identical -- the exact
    property D-023 documented for the other two axes.
    """
    zeros = [i for i, g in enumerate(A_GOLDEN_HIST) if g == 0]
    assert len(zeros) == 2, "need at least two empty clusters for this to say anything"
    off = _off_support_count(A_GOLDEN_HIST, A_CANDIDATE_HIST)

    scores = set()
    for left in range(off + 1):
        moved = list(A_CANDIDATE_HIST)
        moved[zeros[0]] = left
        moved[zeros[1]] = off - left
        scores.add(jensen_shannon(A_GOLDEN_HIST, tuple(moved)))

    assert scores == {A_JSD}


def test_the_off_support_clusters_contribute_exactly_half_their_fraction() -> None:
    """Checked against a from-definition decomposition, not the shipped code."""
    terms = _per_bucket_terms(A_GOLDEN_HIST, A_CANDIDATE_HIST)
    # The decomposition must reproduce the shipped function first, or the
    # identity below is being checked against the wrong quantity.
    assert sum(terms) == pytest.approx(A_JSD, abs=1e-15)

    frozen = sum(t for t, g in zip(terms, A_GOLDEN_HIST, strict=True) if g == 0)
    off = _off_support_count(A_GOLDEN_HIST, A_CANDIDATE_HIST)
    clustered = sum(A_CANDIDATE_HIST)

    assert frozen == pytest.approx((off / clustered) / 2, abs=1e-15)
    # Just under two thirds of this score cannot respond to the traffic moving.
    assert frozen / A_JSD == pytest.approx(0.6439, abs=5e-5)


# ----------------------------------------------------------------------
# The denominator -- the one thing this axis does not share with its siblings
# ----------------------------------------------------------------------


def test_the_frozen_contribution_is_measured_over_the_clustered_candidates() -> None:
    """The arm that rejects the other unit.

    `n_candidate` counts every candidate input; the embedding axis drops the
    uncomparable ones, and the JSD normalises the histogram it is handed. On
    this corpus the two bases disagree, and only the clustered one reproduces
    the measured frozen contribution.
    """
    report = compute_drift(B_GOLDEN, B_CANDIDATE, **B_KWARGS)
    golden_hist, candidate_hist = (cs.cluster_counts for cs in report.cluster_stats)

    assert (golden_hist, candidate_hist) == (B_GOLDEN_HIST, B_CANDIDATE_HIST)
    assert report.n_uncomparable == (0, 1)
    assert report.cluster_stats[1].n == 2 != report.n_candidate == 3

    off = report.n_embedding_off_support
    assert off == 1

    # The base the module *published*, not one this test recomputed. Reading it
    # back off the detail string is what makes this arm pin the code's choice of
    # unit rather than the test's own arithmetic -- with the base recomputed
    # here, a neighbour that emits `n_candidate` passes every line below.
    published = re.search(r"; (\d+)/(\d+) clustered candidate inputs", report.embedding.detail)
    assert published is not None, report.embedding.detail
    published_off, published_base = (int(g) for g in published.groups())
    assert (published_off, published_base) == (off, report.cluster_stats[1].n)

    terms = _per_bucket_terms(golden_hist, candidate_hist)
    assert sum(terms) == pytest.approx(B_JSD, abs=1e-15)
    frozen = sum(t for t, g in zip(terms, golden_hist, strict=True) if g == 0)

    assert frozen == pytest.approx(0.25, abs=1e-15)
    assert frozen == pytest.approx((published_off / published_base) / 2, abs=1e-15)
    # The rejection: the other unit is wrong, not merely differently rounded.
    assert (off / report.n_candidate) / 2 == pytest.approx(0.1666666, abs=1e-6)
    assert frozen != pytest.approx((off / report.n_candidate) / 2, abs=1e-6)


def test_the_detail_string_quotes_the_clustered_base() -> None:
    report = compute_drift(B_GOLDEN, B_CANDIDATE, **B_KWARGS)
    assert "1/2 clustered candidate inputs" in report.embedding.detail
    assert "1/3 clustered candidate inputs" not in report.embedding.detail
    # The pre-existing uncomparable note still leads, and is unchanged.
    assert "1/3 candidate inputs had no embeddable content" in report.embedding.detail


# ----------------------------------------------------------------------
# Silence when there is nothing to say
# ----------------------------------------------------------------------


def test_an_ordinary_report_is_byte_unchanged() -> None:
    """D-023's rule: the count is rendered only when non-zero."""
    report = compute_drift(C_GOLDEN, C_CANDIDATE, **C_KWARGS)
    golden_hist = report.cluster_stats[0].cluster_counts

    assert all(g > 0 for g in golden_hist), "this corpus must occupy every cluster"
    assert report.n_embedding_off_support == 0
    assert report.embedding.detail == (
        "JSD over k=3 cluster-id histogram from 32-dim hash-embedded inputs"
    )
    assert "clusters no golden input occupies" not in render_html(report)


def test_a_fully_uncomparable_candidate_sample_reports_zero_not_frozen_mass() -> None:
    """The #91 one-empty interaction.

    Nothing comparable on the candidate side leaves the cluster histogram at
    zero mass, which `jensen_shannon` reports as 1.0 by its documented
    one-empty contract. There is no candidate mass anywhere, so there is none
    off support either: the count must be 0, and must not be read as "none of
    this score is frozen" -- the whole axis is running on the abstention.
    """
    report = compute_drift(C_GOLDEN, ["!!!", "---", "   "], **C_KWARGS)

    assert report.cluster_stats[1].cluster_counts == (0, 0, 0)
    assert report.cluster_stats[1].n == 0
    assert report.embedding.drift_score == 1.0
    assert report.n_uncomparable == (0, 3)
    assert report.n_embedding_off_support == 0
    # No division by the zero clustered count on the way there.
    assert "clustered candidate inputs" not in report.embedding.detail


# ----------------------------------------------------------------------
# Properties the count has to keep
# ----------------------------------------------------------------------


def test_the_count_is_order_independent() -> None:
    """#207/#208: reordering a corpus is not a change to the corpus.

    `_kmeans` canonicalises its processing order internally; a count derived
    from its output inherits that, and pinning it here means a regression in
    the canonicalisation shows up as a count change and not only as a score
    change.
    """
    base = compute_drift(A_GOLDEN, A_CANDIDATE, **A_KWARGS)
    for golden, candidate in (
        (list(reversed(A_GOLDEN)), A_CANDIDATE),
        (A_GOLDEN, list(reversed(A_CANDIDATE))),
        (list(reversed(A_GOLDEN)), list(reversed(A_CANDIDATE))),
        (A_GOLDEN[2:] + A_GOLDEN[:2], A_CANDIDATE[1:] + A_CANDIDATE[:1]),
    ):
        shuffled = compute_drift(golden, candidate, **A_KWARGS)
        assert shuffled.n_embedding_off_support == base.n_embedding_off_support
        assert shuffled.embedding.drift_score == base.embedding.drift_score


def test_counting_clusters_instead_of_inputs_is_a_different_number() -> None:
    """A wrong-unit neighbour, kept as a live discriminator.

    Counting *how many clusters* hold off-support mass rather than *how many
    inputs* sit in them gives 1 where the truth is 2 -- and the frozen-fraction
    identity is over inputs, so the neighbour would silently halve the reported
    blind spot on this corpus.
    """
    by_input = _off_support_count(A_GOLDEN_HIST, A_CANDIDATE_HIST)
    by_cluster = sum(
        1 for g, c in zip(A_GOLDEN_HIST, A_CANDIDATE_HIST, strict=True) if g == 0 and c > 0
    )
    assert (by_input, by_cluster) == (2, 1)
    assert compute_drift(A_GOLDEN, A_CANDIDATE, **A_KWARGS).n_embedding_off_support == by_input


def test_the_other_side_of_the_zero_test_is_a_different_number() -> None:
    """The `g == 0` / `c == 0` neighbour.

    Swapping the side tested asks "golden mass in clusters the *candidate*
    never occupies", which is a real quantity and the wrong one -- it is what
    the axis can see, not what it cannot.
    """
    wrong_side = sum(g for g, c in zip(A_GOLDEN_HIST, A_CANDIDATE_HIST, strict=True) if c == 0)
    assert wrong_side == 1
    assert _off_support_count(A_GOLDEN_HIST, A_CANDIDATE_HIST) == 2


# ----------------------------------------------------------------------
# The operator-facing surface
# ----------------------------------------------------------------------


def test_the_html_names_the_embedding_axis_with_its_own_denominator() -> None:
    report = compute_drift(A_GOLDEN, A_CANDIDATE, **A_KWARGS)
    html = render_html(report)

    # 3 is the clustered count here (nothing is uncomparable in case A), so the
    # denominator is pinned again on the corpus where the two bases *differ*.
    assert "<strong>2 of 3</strong> on the embedding axis" in html
    b = render_html(compute_drift(B_GOLDEN, B_CANDIDATE, **B_KWARGS))
    assert "<strong>1 of 2</strong> on the embedding axis" in b
    assert "<strong>1 of 3</strong> on the embedding axis" not in b
    assert "clusters no golden input occupies" in report.embedding.detail
    assert "the golden set never" in html


def test_three_axes_render_as_a_list_and_two_still_render_as_a_pair() -> None:
    """The join rule.

    D-023 shipped `" and ".join(...)` over at most two bits. A third bit would
    have read "A and B and C"; one and two bits must still render exactly as
    they did.
    """
    base = compute_drift(A_GOLDEN, A_CANDIDATE, **A_KWARGS)

    one = dataclasses.replace(base, n_length_off_support=0, n_judge_off_support=None)
    two = dataclasses.replace(base, n_length_off_support=3, n_judge_off_support=None)
    three = dataclasses.replace(base, n_length_off_support=3, n_judge_off_support=1)

    assert "<strong>2 of 3</strong> on the embedding axis candidate inputs" in render_html(one)
    assert "on the length axis and <strong>2 of 3</strong> on the embedding axis" in render_html(
        two
    )
    html3 = render_html(three)
    assert "on the length axis, <strong>2 of 3</strong> on the embedding axis and " in html3
    assert "and <strong>1 of 3</strong> on the judge axis" in html3
    # ...and never the "A and B and C" form the two-bit join would have produced.
    assert "axis and <strong>2 of 3</strong>" not in html3
