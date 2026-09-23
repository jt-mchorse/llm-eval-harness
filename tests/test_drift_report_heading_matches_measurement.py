"""The report heading names the quantity in the column beneath it (#250).

D-025 (#248) moved `RepresentativeExample.distance_to_nearest_golden_cluster`
off `max(_cosine(v, c) for c in centroids)` and onto the clusters the *golden*
set occupies -- `_kmeans` retains a centroid whose cluster went empty, and
ranking against one understates exactly the candidates assigned to it. It
updated the field docstring, the `compute_drift` docstring and
`docs/architecture.md`, and left the two strings an operator actually reads:
the HTML column heading and the README sentence describing it. Both said "from
any golden cluster centroid" -- the pre-D-025 expression spelled in English.

The lock runs in both directions, because either half can drift alone:

* revert the *measurement* and the rendered cell stops matching the
  occupied-only value (`test_the_rendered_distance_is_the_occupied_only_value`);
* revert the *heading* and it stops stating the restriction
  (`test_the_heading_states_the_occupancy_restriction`).

A corpus where the two readings coincide would satisfy the first arm for free,
so `test_the_corpus_separates_the_two_readings` pins that this one does not --
it is the anti-vacuity arm, and it is green on both trees by construction,
which is the point: it is what rejects a lock written over a non-separating
corpus.
"""

from __future__ import annotations

import re

from eval_harness.drift import (
    _cosine,
    _kmeans,
    compute_drift,
    has_embeddable_content,
    hash_embed,
    render_html,
)

# Found by exhaustive search over 300,000 random 3-token corpora at
# `cluster_k=4` (seed 11): the only one in that sweep on which restricting the
# ranking to occupied clusters moves a *rendered* number. Golden cluster counts
# are (1, 0, 2, 4) -- cluster 1 is retained by `_kmeans` after going empty --
# and candidate counts are (2, 1, 0, 4), so one candidate sits in it.
GOLDEN = [
    "epsilon lam omicron",
    "delta pi xi",
    "tau kappa nu",
    "nu theta pi",
    "gamma alpha sigma",
    "epsilon tau gamma",
    "epsilon omicron lam",
]
CANDIDATE = [
    "eta gamma rho",
    "mu kappa rho",
    "zeta eta pi",
    "theta delta kappa",
    "iota theta alpha",
    "tau omicron eta",
    "eta nu omicron",
]
# The candidate `_assign` routes to the golden-empty cluster.
OFF_SUPPORT_TEXT = "tau omicron eta"
CLUSTER_K = 4

# Measured, not derived in the test: printing `repr()` of the two quantities
# rather than retyping a rendered number (the standing rule after two retyping
# slips elsewhere in the portfolio).
DISTANCE_OVER_ALL_CENTROIDS = 0.6026402928804868
DISTANCE_OVER_OCCUPIED_CLUSTERS = 0.6666666666666665


def _report():
    return compute_drift(GOLDEN, CANDIDATE, cluster_k=CLUSTER_K)


def _distance_over_all_centroids(text: str) -> float:
    """The quantity the pre-D-025 heading named, recomputed from scratch.

    Deliberately not a call into the shipped code path -- the point of the arm
    is that this is a *different* number, so it is built from `_kmeans` the way
    `compute_drift` seeds it and then maxed over every centroid.
    """
    centroids, _ = _kmeans([hash_embed(s) for s in GOLDEN if has_embeddable_content(s)], CLUSTER_K)
    v = hash_embed(text)
    return 1.0 - max(_cosine(v, c) for c in centroids)


def test_the_corpus_separates_the_two_readings() -> None:
    """Anti-vacuity: on this corpus the two readings are different numbers.

    Green against both trees, and that is what it is for. Without it, the arm
    below passes on any corpus where every candidate happens to be nearest an
    occupied cluster -- which is the overwhelming majority of them: 1 corpus in
    300,000 separated.
    """
    report = _report()
    assert report.n_embedding_off_support == 1
    assert report.cluster_stats[0].cluster_counts == (1, 0, 2, 4)
    assert report.cluster_stats[1].cluster_counts == (2, 1, 0, 4)

    over_all = _distance_over_all_centroids(OFF_SUPPORT_TEXT)
    assert over_all == DISTANCE_OVER_ALL_CENTROIDS
    assert DISTANCE_OVER_ALL_CENTROIDS != DISTANCE_OVER_OCCUPIED_CLUSTERS
    # And the direction is the one D-025 argues is structural, not incidental:
    # a candidate in a golden-empty cluster is nearest that empty centroid, so
    # ranking over all centroids can only *understate* the distance.
    assert over_all < DISTANCE_OVER_OCCUPIED_CLUSTERS


def test_the_rendered_distance_is_the_occupied_only_value() -> None:
    """Direction one: the column holds the occupied-only measurement.

    Red if the measurement is reverted to `max(... for c in centroids)` while
    the heading keeps its new wording.
    """
    report = _report()
    shipped = {r.text: r.distance_to_nearest_golden_cluster for r in report.representative_examples}
    assert shipped[OFF_SUPPORT_TEXT] == DISTANCE_OVER_OCCUPIED_CLUSTERS

    # And it is the number that reaches the document, at the `.3f` the cell
    # renders -- the two readings are 0.667 and 0.603 there, so the format
    # does not collapse them.
    doc = render_html(report)
    rows = re.search(r"Most distant candidate inputs.*?<tbody>(.*?)</tbody>", doc, re.S)
    assert rows is not None
    assert f"<td>{DISTANCE_OVER_OCCUPIED_CLUSTERS:.3f}</td>" in rows.group(1)
    assert f"<td>{DISTANCE_OVER_ALL_CENTROIDS:.3f}</td>" not in rows.group(1)


def test_the_heading_states_the_occupancy_restriction() -> None:
    """Direction two: the heading names the restriction, not "any centroid".

    Red if the heading is reverted. The rule is not string equality with the
    shipped wording -- that would pin a sentence rather than a claim. It is
    that the heading must *state the restriction* (some form of "occupies"),
    because a heading that merely drops a word from the old one --
    "from any cluster centroid" -- still names the unrestricted quantity and
    is the nearest wrong neighbour.
    """
    doc = render_html(_report())
    heading = re.search(r"<h2>(Most distant candidate inputs[^<]*)</h2>", doc)
    assert heading is not None, "the representative-examples heading is missing"
    text = heading.group(1)

    assert re.search(r"\boccupie[sd]\b", text), (
        f"the heading must name the population D-025 ranks over, got {text!r}; "
        "'any golden cluster centroid' is the pre-D-025 expression in English"
    )
    # The specific pre-D-025 phrasings, and the neighbour that drops only the
    # word "golden" from it.
    assert "from any golden cluster centroid" not in text
    assert "from any golden centroid" not in text
    assert "from any cluster centroid" not in text


def test_the_shipped_fixtures_are_unaffected() -> None:
    """Nothing published moves: the drift fixtures leave no cluster golden-empty.

    The same posture D-024 and D-025 both took. This arm is green on both
    trees and exists so a future change to the ranking population cannot be
    landed on the claim that the fixtures cover it -- they do not.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    def _load(name: str) -> list[str]:
        rows = []
        for line in (root / "fixtures" / "drift" / name).read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            rows.append(row if isinstance(row, str) else row["input"])
        return rows

    report = compute_drift(_load("golden_inputs.jsonl"), _load("shifted.jsonl"))
    assert all(n > 0 for n in report.cluster_stats[0].cluster_counts)
    assert report.n_embedding_off_support == 0
