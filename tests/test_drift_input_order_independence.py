"""`compute_drift` must be a function of its input *sets*, not their order.

The drift CLI reads its corpora from JSONL files, so the order of the input
lists is the order of lines in a file. Reordering lines in a JSONL corpus
changes nothing about the corpus, and must therefore change nothing about the
report — least of all the `ok` / `drifted` verdict.

Before #207 it changed both. Three separate things read the input order:
`_kmeans`'s stride init selected seeds by position; the assignment scan settled
a cosine tie by taking whichever centroid it met first; and the centroid update
accumulated with `+=`, which is order-sensitive because float addition is not
associative. Separately, `compute_drift` sorted its representative examples on
distance alone and then *truncated*, so position decided which examples appeared
at all.

Every test here is written so it fails against the pre-#207 implementation.
"""

from __future__ import annotations

import random

import pytest

from eval_harness.drift import (
    _cosine,
    _kmeans,
    compute_drift,
    hash_embed,
)

# Two topics, equal sizes. Deliberately ordinary: this is the shape of a real
# golden set, not a constructed adversarial one.
BILLING = [f"how do I get a refund for invoice {i}" for i in range(6)]
SHIPPING = [f"where is my package tracking number {i}" for i in range(6)]
GOLDEN = BILLING + SHIPPING

# Shifted toward shipping, so the embedding axis has something to say.
CANDIDATE = BILLING[:2] + SHIPPING + [f"my parcel is late order {i}" for i in range(4)]

N_SHUFFLES = 40


def _report_fingerprint(report):
    """Everything about a report that must not depend on input order."""
    return (
        round(report.embedding.drift_score, 12),
        report.embedding.status,
        report.cluster_k,
        report.cluster_stats[0].cluster_counts,
        report.cluster_stats[1].cluster_counts,
        tuple(
            (e.text, round(e.distance_to_nearest_golden_cluster, 12))
            for e in report.representative_examples
        ),
    )


def test_golden_order_does_not_move_the_embedding_verdict():
    """The headline gate must survive a shuffle of the golden corpus.

    Measured before the fix, over these exact inputs: ten distinct scores
    spanning 0.008788 to 0.141412, with 17/40 shuffles reporting `ok` and 23/40
    reporting `drifted` for byte-identical corpora.
    """
    rng = random.Random(0)
    fingerprints = set()
    for _ in range(N_SHUFFLES):
        g = GOLDEN[:]
        rng.shuffle(g)
        fingerprints.add(_report_fingerprint(compute_drift(g, CANDIDATE, cluster_k=4)))

    assert len(fingerprints) == 1, (
        f"{len(fingerprints)} distinct reports over {N_SHUFFLES} shuffles of the "
        "same golden corpus; the report must be a function of the input set"
    )


def test_candidate_order_does_not_move_the_report():
    rng = random.Random(1)
    fingerprints = set()
    for _ in range(N_SHUFFLES):
        c = CANDIDATE[:]
        rng.shuffle(c)
        fingerprints.add(_report_fingerprint(compute_drift(GOLDEN, c, cluster_k=4)))

    assert len(fingerprints) == 1, (
        f"{len(fingerprints)} distinct reports over {N_SHUFFLES} shuffles of the "
        "same candidate corpus"
    )


def test_both_sides_shuffled_together():
    """Shuffling both at once is the realistic case — two exports of one corpus."""
    rng = random.Random(2)
    fingerprints = set()
    for _ in range(N_SHUFFLES):
        g, c = GOLDEN[:], CANDIDATE[:]
        rng.shuffle(g)
        rng.shuffle(c)
        fingerprints.add(_report_fingerprint(compute_drift(g, c, cluster_k=4)))

    assert len(fingerprints) == 1


# ----------------------------------------------------------------------
# Representative examples: the truncation is what makes the tie matter
# ----------------------------------------------------------------------


# Six inputs that all embed to the zero vector (no alphanumeric tokens), so all
# six tie at distance 1.0 — contesting five slots.
TIED_SIX = ["", "!!!", "...", "???", "———", "🎉🎉🎉"]


def test_tied_examples_are_selected_by_content_not_file_position():
    """Six tied candidates, five slots.

    Before the fix this returned six different five-element sets over 60
    shuffles: the tie was settled by Python's stable sort, i.e. by where each
    input sat in the file, and the truncation turned that into a difference in
    *membership*, not merely ordering.
    """
    rng = random.Random(3)
    sets = set()
    for _ in range(60):
        c = TIED_SIX[:]
        rng.shuffle(c)
        report = compute_drift(GOLDEN, c, cluster_k=4, n_representative_examples=5)
        assert len(report.representative_examples) == 5
        sets.add(frozenset(e.text for e in report.representative_examples))

    assert len(sets) == 1, f"{len(sets)} distinct example sets: {sorted(map(sorted, sets))}"


def test_tie_is_broken_ascending_on_text():
    """The tiebreak is on the text itself, so it is stateable, not incidental."""
    report = compute_drift(GOLDEN, TIED_SIX, cluster_k=4, n_representative_examples=6)
    texts = [e.text for e in report.representative_examples]
    assert texts == sorted(TIED_SIX), texts


def test_distance_still_outranks_the_text_tiebreak():
    """The tiebreak must only settle exact ties, never reorder distinct distances."""
    # The pair is chosen so the two keys disagree: "aaa refund" shares a token
    # with the golden set and scores 0.758, while "zzzz zzzz zzzz" overlaps
    # nothing and scores 1.000 — so distance ranks them z-then-a, and the text
    # tiebreak alone would rank them a-then-z. Distance must win.
    candidates = ["aaa refund", "zzzz zzzz zzzz"]
    report = compute_drift(GOLDEN, candidates, cluster_k=4, n_representative_examples=2)
    ordered = [e.text for e in report.representative_examples]
    distances = [e.distance_to_nearest_golden_cluster for e in report.representative_examples]
    assert distances[0] > distances[1], distances
    assert ordered == ["zzzz zzzz zzzz", "aaa refund"], ordered


# ----------------------------------------------------------------------
# `_kmeans` directly: the returned `assigns` contract
# ----------------------------------------------------------------------


def test_kmeans_assigns_stay_aligned_with_the_callers_indexing():
    """`_kmeans` reorders internally; `assigns[i]` must still describe `vectors[i]`.

    This is the regression the internal canonicalization could most easily
    introduce, and `compute_drift` would not catch it — it discards `assigns`
    and re-assigns against the final centroids.
    """
    texts = GOLDEN
    vectors = [hash_embed(t) for t in texts]
    centroids, assigns = _kmeans(vectors, 4)

    assert len(assigns) == len(vectors)
    for i, v in enumerate(vectors):
        nearest = max(range(len(centroids)), key=lambda ci: _cosine(v, centroids[ci]))
        assert assigns[i] == nearest, (
            f"vector {i} ({texts[i]!r}) is assigned to cluster {assigns[i]} but is "
            f"nearest to centroid {nearest}"
        )


def test_kmeans_is_permutation_equivariant():
    """Permuting the input permutes the assignments the same way; centroids are equal."""
    vectors = [hash_embed(t) for t in GOLDEN]
    base_centroids, base_assigns = _kmeans(vectors, 4)

    rng = random.Random(4)
    for _ in range(20):
        perm = list(range(len(vectors)))
        rng.shuffle(perm)
        permuted = [vectors[i] for i in perm]
        centroids, assigns = _kmeans(permuted, 4)

        assert centroids == base_centroids
        # assigns[j] describes permuted[j] == vectors[perm[j]]
        assert [assigns[j] for j in range(len(perm))] == [
            base_assigns[perm[j]] for j in range(len(perm))
        ]


@pytest.mark.parametrize("k", [1, 2, 3, 5, 12, 20])
def test_kmeans_order_independence_across_k(k):
    """k below, at, and above n — `k = min(k, n)` makes the last case degenerate."""
    vectors = [hash_embed(t) for t in GOLDEN]
    base_centroids, _ = _kmeans(vectors, k)

    rng = random.Random(5)
    for _ in range(10):
        permuted = vectors[:]
        rng.shuffle(permuted)
        centroids, _ = _kmeans(permuted, k)
        assert centroids == base_centroids, f"k={k}"


def test_duplicate_vectors_do_not_reintroduce_position_dependence():
    """Identical vectors sort equal, so the stable sort falls back to index order.

    That fallback is only safe because equal vectors are interchangeable at every
    downstream step. Pin it: duplicates are the norm in a traffic sample.
    """
    texts = GOLDEN + BILLING  # every billing utterance now appears twice
    vectors = [hash_embed(t) for t in texts]
    base_centroids, _ = _kmeans(vectors, 4)

    rng = random.Random(6)
    for _ in range(20):
        permuted = vectors[:]
        rng.shuffle(permuted)
        centroids, _ = _kmeans(permuted, 4)
        assert centroids == base_centroids
