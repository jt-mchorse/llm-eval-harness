"""`distance_to_nearest_golden_cluster` must rank against clusters golden occupies (#248).

D-024 (#246) established that **the support is the set of buckets the *golden*
histogram occupies, not the set of centroids that exist** — `_kmeans` retains a
centroid whose cluster went empty rather than dropping it, so
`g_cluster_counts[i] == 0` is reachable and `_assign` routes candidates there.
It applied that to the *count*. The ranking one block down still walked every
centroid:

    nearest_sim = max(_cosine(v, c) for c in centroids)

So for exactly the candidates D-024 proved reachable — the ones in the frozen
regime — a field named `distance_to_nearest_golden_cluster` reported the
distance to a centroid **no golden input occupies**.

It is an understatement by construction, never a coin flip: a candidate is
assigned to the cluster whose centroid it is nearest, so one sitting in a
golden-empty cluster is necessarily closer to that empty centroid than to any
occupied one. The inputs this list exists to surface — `compute_drift`'s
docstring calls them "the inputs that look least like anything in the golden
set" — were the exact ones reported as more golden-like than they are.

Two arms carry the weight, and neither is the distance:

- `test_the_golden_empty_cluster_candidate_is_no_longer_evicted` is the one that
  matters. The list is *truncated*, so this is #210's shape again — not merely a
  wrong ordering but a wrong membership. A distance-only arm would pass against
  a fix that corrected the number and left the sort key alone.
- `test_candidates_in_occupied_clusters_keep_their_exact_distances` is green on
  both trees and is what rejects an over-broad neighbour that re-ranks
  everything. It is bit-for-bit, because the measurement says those rows move by
  exactly `0.000000`.
"""

from __future__ import annotations

import random

import pytest

from eval_harness.drift import (
    _cosine,
    _kmeans,
    compute_drift,
    has_embeddable_content,
    hash_embed,
)

# A 7/4 corpus whose golden set leaves cluster 0 empty while a candidate is
# assigned to it. Found by search over the public `compute_drift`, not
# hand-constructed — the shape needs `_kmeans` to retain an empty centroid,
# which is not something one writes down directly.
G_SMALL = [
    "alpha delta alpha",
    "gamma iota theta",
    "eta eta theta",
    "gamma eta beta",
    "delta beta theta",
    "gamma beta theta",
    "theta beta delta",
]
C_SMALL = ["kappa zeta theta", "beta kappa alpha", "zeta eta eta", "kappa eta eta"]

# A 7/7 corpus where the understatement changes the *truncated* top-5 set.
G_EVICT = [
    "mu gamma beta",
    "kappa epsilon delta",
    "delta kappa epsilon",
    "beta lam eta",
    "theta gamma kappa",
    "kappa gamma eta",
    "epsilon delta alpha",
]
C_EVICT = [
    "kappa iota beta",
    "iota gamma delta",
    "eta delta mu",
    "kappa lam theta",
    "theta gamma epsilon",
    "theta zeta zeta",
    "iota eta gamma",
]


def _occupied_and_empty(golden: list[str], cluster_k: int = 4) -> tuple[list[int], list[int]]:
    """The golden-occupied and golden-empty centroid indices, recomputed here.

    Deliberately recomputed rather than read off the report: this module's
    premise is that a retained centroid can be golden-empty, and a test that
    took the partition from the same code under test could not distinguish
    "the partition is right" from "the partition agrees with itself".
    """
    gv = [hash_embed(s, dim=64) for s in golden]
    seeds = [v for v, ok in zip(gv, [has_embeddable_content(s) for s in golden], strict=True) if ok]
    centroids, _ = _kmeans(seeds, cluster_k)
    assigned = {max(range(len(centroids)), key=lambda i: _cosine(v, centroids[i])) for v in gv}
    occupied = sorted(assigned)
    empty = [i for i in range(len(centroids)) if i not in assigned]
    return occupied, empty


# ----------------------------------------------------------------------
# The premise: a retained centroid really is golden-empty here
# ----------------------------------------------------------------------


@pytest.mark.parametrize(("golden", "candidate"), [(G_SMALL, C_SMALL), (G_EVICT, C_EVICT)])
def test_the_corpora_really_do_leave_a_retained_centroid_golden_empty(
    golden: list[str], candidate: list[str]
) -> None:
    """Without this the rest of the module could be vacuously green.

    Both fixtures are only interesting if `_kmeans` retained a centroid no
    golden input occupies *and* a candidate landed there — which is exactly
    what `n_embedding_off_support` counts (D-024).
    """
    occupied, empty = _occupied_and_empty(golden)
    assert empty, "this corpus no longer has a golden-empty centroid"
    assert occupied, "a golden set always occupies at least one cluster"

    report = compute_drift(golden, candidate, cluster_k=4, n_representative_examples=5)
    assert 0 in report.cluster_stats[0].cluster_counts
    assert report.n_embedding_off_support > 0


# ----------------------------------------------------------------------
# The eviction — the arm that matters
# ----------------------------------------------------------------------


def test_the_golden_empty_cluster_candidate_is_no_longer_evicted() -> None:
    """#210's shape, one population over: truncation makes this a membership bug.

    `kappa lam theta` is the candidate assigned to the golden-empty cluster —
    the one genuinely least like the golden set. Ranked against every centroid
    it scored as more golden-like than it is and lost its slot to
    `theta gamma epsilon`, which does sit in the golden support.

    Pre-fix this returned `theta gamma epsilon` in the fifth slot. Measured on
    both trees through the public API.
    """
    report = compute_drift(G_EVICT, C_EVICT, cluster_k=4, n_representative_examples=5)
    texts = [e.text for e in report.representative_examples]

    assert "kappa lam theta" in texts, (
        "the candidate in the golden-empty cluster was evicted from the "
        "truncated list by one that sits inside the golden support"
    )
    assert "theta gamma epsilon" not in texts
    assert len(texts) == 5


def test_the_understated_distance_is_corrected() -> None:
    """The number, on the corpus the issue measured.

    0.602640 was the distance to a centroid no golden input occupies; 0.666667
    is the distance to the nearest cluster that has one.
    """
    report = compute_drift(G_SMALL, C_SMALL, cluster_k=4, n_representative_examples=5)
    by_text = {e.text: e.distance_to_nearest_golden_cluster for e in report.representative_examples}
    assert by_text["kappa zeta theta"] == pytest.approx(0.666667, abs=1e-6)


# ----------------------------------------------------------------------
# Green on both trees — what rejects the over-broad neighbour
# ----------------------------------------------------------------------


def test_candidates_in_occupied_clusters_keep_their_exact_distances() -> None:
    """Bit-for-bit, because the measurement says they move by exactly 0.

    A neighbour that re-ranks every candidate — say by excluding clusters empty
    on the *candidate* side, or by switching the metric — passes the two arms
    above and destroys this one.

    Compared with a tolerance rather than to the last bit, deliberately: these
    are sums of cosines over a hash embedding, and an exact float literal here
    would be a host-environment assertion that passes on the machine it was
    written on. The claim that *is* exact is the equality between the two tied
    rows, which is platform-independent because both sides come out of the same
    arithmetic.
    """
    report = compute_drift(G_SMALL, C_SMALL, cluster_k=4, n_representative_examples=5)
    by_text = {e.text: e.distance_to_nearest_golden_cluster for e in report.representative_examples}

    # These three sit in occupied clusters and are untouched by #248.
    assert by_text["beta kappa alpha"] == pytest.approx(0.483602, abs=1e-6)
    assert by_text["zeta eta eta"] == pytest.approx(0.570614, abs=1e-6)
    assert by_text["kappa eta eta"] == pytest.approx(0.570614, abs=1e-6)
    # And the two tied rows stay tied, so the text tie-break (#207) still
    # decides them rather than a perturbed distance.
    assert by_text["zeta eta eta"] == by_text["kappa eta eta"]


def test_the_occupied_set_is_never_empty_when_centroids_exist() -> None:
    """Totality of the restricted `max`, which is a crash rather than a wrong number.

    `centroids` is seeded from the *comparable* golden vectors, and a golden set
    in which nothing is comparable is rejected at the top of `compute_drift`
    (D-017). So whenever centroids exist at least one is occupied. Checked over
    a spread of shapes rather than argued, because `max()` over an empty
    sequence raises.
    """
    rng = random.Random(3)
    vocab = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    for _ in range(200):
        golden = [
            " ".join(rng.choice(vocab) for _ in range(rng.randint(1, 4)))
            for _ in range(rng.randint(1, 8))
        ]
        occupied, _empty = _occupied_and_empty(golden, cluster_k=rng.randint(2, 5))
        assert occupied, golden


def test_a_golden_set_with_no_comparable_input_is_still_rejected() -> None:
    """The precondition the totality argument rests on (D-017), pinned here too.

    If this ever stopped being an outright rejection, `occupied_clusters` could
    be empty and the restricted `max` would raise instead of reporting.
    """
    with pytest.raises(ValueError, match="at least one input with embeddable content"):
        compute_drift(["!!!", "---", "   "], ["alpha beta"], cluster_k=2)


# ----------------------------------------------------------------------
# The property, over a search rather than two fixtures
# ----------------------------------------------------------------------


def test_every_reported_distance_equals_the_distance_to_an_occupied_cluster() -> None:
    """The general statement, checked against an independent recomputation.

    For every candidate in every corpus below, the published distance is the one
    to the nearest *occupied* golden cluster — computed here from
    `hash_embed`/`_kmeans`/`_cosine` directly rather than taken from the report.

    **The known corpora are in the searched set deliberately, and the
    non-vacuity guard is on candidate mass rather than on golden emptiness.**
    My first version asserted only that some corpus had a golden-empty
    centroid, and that is the wrong population: the property differs only when
    a candidate is actually *assigned* to such a cluster. Measured — of 400
    random corpora at this seed, 6 had a golden-empty centroid and **0** had
    candidate mass in one, so the arm passed against the unfixed code. The rate
    is roughly 1 in 4,000 for this vocabulary, which is why the discriminating
    cases are supplied rather than hoped for.
    """
    rng = random.Random(17)
    vocab = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa"]
    corpora = [(G_SMALL, C_SMALL), (G_EVICT, C_EVICT)]
    for _ in range(200):
        corpora.append(
            (
                [" ".join(rng.choice(vocab) for _ in range(3)) for _ in range(rng.randint(4, 9))],
                [" ".join(rng.choice(vocab) for _ in range(3)) for _ in range(rng.randint(4, 9))],
            )
        )

    checked = 0
    with_off_support = 0
    for golden, candidate in corpora:
        occupied, _empty = _occupied_and_empty(golden)
        report = compute_drift(golden, candidate, cluster_k=4, n_representative_examples=50)
        if report.n_embedding_off_support:
            with_off_support += 1

        gv = [hash_embed(s, dim=64) for s in golden]
        seeds = [
            v for v, ok in zip(gv, [has_embeddable_content(s) for s in golden], strict=True) if ok
        ]
        centroids, _ = _kmeans(seeds, 4)
        for example in report.representative_examples:
            v = hash_embed(example.text, dim=64)
            expected = 1.0 - max(_cosine(v, centroids[i]) for i in occupied)
            assert example.distance_to_nearest_golden_cluster == pytest.approx(expected, abs=1e-12)
            checked += 1

    assert checked > 1000, f"only {checked} examples checked; the search went thin"
    assert with_off_support >= 2, (
        f"only {with_off_support} corpora put candidate mass in a golden-empty "
        "cluster, so this arm cannot tell the fixed ranking from the unfixed "
        "one — the guard is on candidate mass, not on golden emptiness"
    )


# ----------------------------------------------------------------------
# Nothing shipped moves
# ----------------------------------------------------------------------


def test_the_shipped_drift_fixtures_have_no_golden_empty_cluster() -> None:
    """Why this change moves no published number, stated as an arm.

    The README's pinned stdout line and the demo's published rows come from
    corpora whose golden set occupies every cluster, so the ranking population
    is unchanged there. Same reachability posture as D-024, which also moved
    nothing shipped. If a future fixture edit breaks this, the published
    examples become sensitive to #248 and should be re-derived deliberately.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    def load(name: str) -> list[str]:
        out = []
        for line in (root / "fixtures" / "drift" / name).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line)["input"] if line.startswith("{") else line)
        return out

    golden = load("golden_inputs.jsonl")
    _occupied, empty = _occupied_and_empty(golden)
    assert not empty, (
        "the shipped golden fixture now leaves a centroid empty; the published "
        "representative examples are no longer insensitive to #248"
    )
