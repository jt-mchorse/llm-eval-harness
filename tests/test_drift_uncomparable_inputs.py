"""Token-less inputs are *uncomparable*, not maximally distant (#210, D-017).

`hash_embed` sums one signed unit contribution per alphanumeric token, so an
input with no tokens -- `""`, `"!!!"`, an emoji run, whitespace -- produces the
all-zero vector. `_cosine` of the zero vector with any centroid is exactly
`0.0`, and nothing distinguished that from a genuine cosine of 0.0. Two
consequences, both silent, both measured on `main` before this change:

1. `representative_examples` is documented as "the inputs that look least like
   anything in the golden set". A content-free input scored `1.0 - 0.0 = 1.000`,
   at or near the ceiling of the range in practice, so it outranked *every*
   input with real content -- and because the list is truncated it did not
   merely rank wrongly, it *evicted*::

       golden = 6 billing + 6 shipping utterances, cluster_k=4
       candidates = 4 real + 6 token-less, n_representative_examples=5
       -> ['', ' \n\t ', '!!!', '---', '???']      0 of the 4 real inputs

2. `_assign` starts at `best_sim = -2.0` and every centroid ties at `0.0`, so
   the first one always wins and token-less inputs all pile into cluster 0,
   skewing the histogram the embedding JSD is computed over::

       4 real candidates            emb JSD 0.1909   histogram (1, 3, 0, 0)
       the same 4 + 6 token-less    emb JSD 0.3122   histogram (7, 3, 0, 0)

   Six inputs with no content moved a published drift score by 0.12.

D-017 splits the remedy by side. A golden set is authored -- small, reviewed,
fixable -- so one with nothing embeddable fails loud; before this change it was
accepted and reported `drift_score=0.000, status="ok"`, a maximal false negative
from a baseline that can measure nothing. A candidate set is a sampled traffic
slice, so a single emoji must not abort a 10k-line run: those are counted in
`n_uncomparable` and excluded from everything cosine-derived.
"""

from __future__ import annotations

import pytest

from eval_harness.drift import (
    ClusterStats,
    compute_drift,
    has_embeddable_content,
    hash_embed,
    render_html,
)

GOLDEN = [
    "how do i update my billing address",
    "charge me monthly not yearly",
    "my card was declined twice",
    "cancel my subscription and refund",
    "invoice pdf download link",
    "update payment method to amex",
    "where is my package",
    "tracking number says delivered but nothing",
    "shipping to canada cost",
    "change delivery address before it ships",
    "package arrived damaged",
    "expedite my shipment please",
]

REAL_CANDIDATES = ["rotate my api key", "package", "where is my order", "refund please"]

# Every one of these is accepted by the loader and has a truthful char length;
# none of them has a single alphanumeric token.
TOKEN_LESS = ["\U0001f389\U0001f389\U0001f389", "!!!", "", " \n\t ", "---", "???"]


# ----------------------------------------------------------------------
# has_embeddable_content: parity with the embedder it describes
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # comparable
        "hello world",
        "package",
        "café",  # accented Latin (#108)
        "天気は良い",  # CJK (#108)
        "foo_bar",  # underscore is a separator, but `foo`/`bar` are tokens
        "7",
        "a!!!",
        # uncomparable
        "",
        "   ",
        " \n\t ",
        "!!!",
        "---",
        "???",
        "\U0001f389\U0001f389\U0001f389",
        "_",
        "———",
    ],
)
def test_has_embeddable_content_agrees_with_hash_embed(text: str) -> None:
    """The predicate must never disagree with the vector it predicts.

    Stated as a parity assertion rather than a list of expected booleans: the
    property that matters is "True exactly when `hash_embed` returns something
    other than the zero vector", and asserting it against `hash_embed` directly
    means a future change to `_HASH_TOKEN_RE` cannot move one without the other.
    """
    vector_is_nonzero = any(v != 0.0 for v in hash_embed(text))
    assert has_embeddable_content(text) is vector_is_nonzero, text


def test_hash_embed_still_returns_the_zero_vector_for_token_less_input() -> None:
    """The sentinel itself is unchanged -- this change reinterprets it, not it."""
    for text in TOKEN_LESS:
        assert hash_embed(text) == [0.0] * 64, text


# ----------------------------------------------------------------------
# representative_examples: the eviction
# ----------------------------------------------------------------------


def test_token_less_inputs_do_not_evict_real_inputs_from_examples() -> None:
    """The headline defect: 5 of 5 slots went to punctuation.

    Fails on `main` with `['', ' \\n\\t ', '!!!', '---', '???']`.
    """
    report = compute_drift(
        GOLDEN, REAL_CANDIDATES + TOKEN_LESS, cluster_k=4, n_representative_examples=5
    )
    texts = [e.text for e in report.representative_examples]
    assert set(texts) == set(REAL_CANDIDATES), texts
    assert not any(t in TOKEN_LESS for t in texts), texts


def test_examples_are_identical_with_and_without_token_less_noise() -> None:
    """Adding content-free traffic must not change which real inputs surface."""
    clean = compute_drift(GOLDEN, REAL_CANDIDATES, cluster_k=4, n_representative_examples=5)
    noisy = compute_drift(
        GOLDEN, REAL_CANDIDATES + TOKEN_LESS, cluster_k=4, n_representative_examples=5
    )
    assert [
        (e.text, round(e.distance_to_nearest_golden_cluster, 12))
        for e in clean.representative_examples
    ] == [
        (e.text, round(e.distance_to_nearest_golden_cluster, 12))
        for e in noisy.representative_examples
    ]


def test_no_example_carries_the_fabricated_ceiling_distance() -> None:
    """A `1.000` produced by the zero vector is a fabricated measurement.

    A genuine 1.000 (an input sharing no token with any centroid) is still
    allowed through; this asserts the *token-less* ones are gone, not that the
    value 1.0 is unreachable.
    """
    report = compute_drift(
        GOLDEN, REAL_CANDIDATES + TOKEN_LESS, cluster_k=4, n_representative_examples=10
    )
    for e in report.representative_examples:
        assert has_embeddable_content(e.text), e.text


# ----------------------------------------------------------------------
# The cluster histogram skew
# ----------------------------------------------------------------------


def test_token_less_candidates_do_not_move_the_embedding_verdict() -> None:
    """Measured on `main`: 0.1909 -> 0.3122, histogram (1, 3, 0, 0) -> (7, 3, 0, 0)."""
    clean = compute_drift(GOLDEN, REAL_CANDIDATES, cluster_k=4)
    noisy = compute_drift(GOLDEN, REAL_CANDIDATES + TOKEN_LESS, cluster_k=4)
    assert clean.embedding.drift_score == noisy.embedding.drift_score
    assert clean.embedding.status == noisy.embedding.status
    assert clean.cluster_stats[1].cluster_counts == noisy.cluster_stats[1].cluster_counts
    assert noisy.cluster_stats[1].cluster_counts == (1, 3, 0, 0)


def test_token_less_golden_rows_do_not_move_the_golden_histogram() -> None:
    """A zero vector is not a k-means seed.

    Measured on `main`: one `'!!!'` row appended to `GOLDEN` moved the golden
    histogram to `(6, 5, 0, 2)` and the embedding JSD from 0.1909 to 0.1432.
    """
    clean = compute_drift(GOLDEN, REAL_CANDIDATES, cluster_k=4)
    noisy = compute_drift(GOLDEN + ["!!!"], REAL_CANDIDATES, cluster_k=4)
    assert clean.cluster_stats[0].cluster_counts == noisy.cluster_stats[0].cluster_counts
    assert clean.embedding.drift_score == noisy.embedding.drift_score


@pytest.mark.parametrize(
    ("golden", "candidates"),
    [
        (GOLDEN, REAL_CANDIDATES),
        (GOLDEN, REAL_CANDIDATES + TOKEN_LESS),
        (GOLDEN + TOKEN_LESS, REAL_CANDIDATES + TOKEN_LESS),
        (GOLDEN + ["!!!"], TOKEN_LESS[:2] + ["one real"]),
    ],
)
def test_cluster_counts_sum_to_the_reported_n(golden: list[str], candidates: list[str]) -> None:
    """`sum(cluster_counts) == ClusterStats.n` is the invariant that keeps the
    exclusion honest -- `n` is the number of *clustered* inputs, so
    `n_golden - n` is exactly the uncomparable count and nothing goes missing
    without a number to account for it."""
    report = compute_drift(golden, candidates, cluster_k=4)
    for stats, n_inputs, n_unc in (
        (report.cluster_stats[0], report.n_golden, report.n_uncomparable[0]),
        (report.cluster_stats[1], report.n_candidate, report.n_uncomparable[1]),
    ):
        assert isinstance(stats, ClusterStats)
        assert sum(stats.cluster_counts) == stats.n
        assert stats.n == n_inputs - n_unc


# ----------------------------------------------------------------------
# n_uncomparable: the count survives
# ----------------------------------------------------------------------


def test_n_uncomparable_counts_both_sides() -> None:
    report = compute_drift(GOLDEN + TOKEN_LESS, REAL_CANDIDATES + TOKEN_LESS[:2], cluster_k=4)
    assert report.n_uncomparable == (len(TOKEN_LESS), 2)


def test_n_uncomparable_is_zero_zero_for_an_ordinary_report() -> None:
    """The ordinary path is unchanged, including the rendered detail string."""
    report = compute_drift(GOLDEN, REAL_CANDIDATES, cluster_k=4)
    assert report.n_uncomparable == (0, 0)
    assert "embeddable content" not in report.embedding.detail


def test_embedding_detail_names_the_excluded_counts() -> None:
    report = compute_drift(GOLDEN, REAL_CANDIDATES + TOKEN_LESS, cluster_k=4)
    assert "0/12 golden" in report.embedding.detail
    assert "6/10 candidate" in report.embedding.detail


# ----------------------------------------------------------------------
# The golden side fails loud
# ----------------------------------------------------------------------


@pytest.mark.parametrize("golden", [["!!!"], ["!!!", "???"], TOKEN_LESS])
def test_all_token_less_golden_set_is_rejected(golden: list[str]) -> None:
    """On `main` this was accepted and reported `0.000 / ok`.

    Every centroid is the zero vector, every candidate assigns to cluster 0, and
    the two histograms come out identical -- which is this module's encoding of
    "no drift". A gate that cannot fail is worse than no gate.
    """
    with pytest.raises(ValueError, match=r"golden_inputs must contain at least one input"):
        compute_drift(golden, REAL_CANDIDATES, cluster_k=2)


def test_one_comparable_golden_input_is_enough() -> None:
    """The boundary is `>= 1`, not "mostly comparable" -- an authored baseline
    with one real utterance is degenerate but measurable, and this module does
    not invent quality bars it cannot justify."""
    report = compute_drift(["refund my order"] + TOKEN_LESS, REAL_CANDIDATES, cluster_k=4)
    assert report.n_uncomparable[0] == len(TOKEN_LESS)
    assert sum(report.cluster_stats[0].cluster_counts) == 1


def test_an_empty_golden_set_still_raises_the_older_error() -> None:
    """The new check must not shadow the pre-existing empty-input contract."""
    with pytest.raises(ValueError, match=r"golden_inputs must be non-empty"):
        compute_drift([], REAL_CANDIDATES)


# ----------------------------------------------------------------------
# The candidate side stays loud when it should
# ----------------------------------------------------------------------


def test_a_wholly_token_less_candidate_sample_reports_maximal_drift() -> None:
    """Excluding uncomparable inputs must not create a *new* false negative.

    With nothing comparable on the candidate side the histogram has zero mass,
    which `jensen_shannon` reports as 1.0 by its documented one-empty contract
    (#91). 100% content-free traffic is the most drifted a sample can be, and it
    is the operator's loudest possible signal -- not a silent `ok`.
    """
    report = compute_drift(GOLDEN, TOKEN_LESS, cluster_k=4)
    assert report.embedding.drift_score == 1.0
    assert report.embedding.status == "drifted"
    assert report.representative_examples == ()
    assert report.n_uncomparable == (0, len(TOKEN_LESS))
    assert report.cluster_stats[1].n == 0


# ----------------------------------------------------------------------
# The other two axes are untouched
# ----------------------------------------------------------------------


def test_length_and_judge_axes_still_see_uncomparable_inputs() -> None:
    """A token-less input has a truthful char count and a judge can score it, so
    neither axis is affected by D-017. Asserted rather than assumed: silently
    dropping such inputs from *every* axis would trade one wrong number for
    three."""

    def judge(text: str) -> float:
        return 0.9 if has_embeddable_content(text) else 0.1

    report = compute_drift(GOLDEN, REAL_CANDIDATES + TOKEN_LESS, cluster_k=4, judge_score_fn=judge)
    assert report.judge is not None
    assert report.judge_stats is not None
    # Both axes see all 10 candidate inputs; only the embedding axis sees 4.
    assert sum(report.length_histograms[1]) == 10
    assert report.judge_stats[1].n == 10
    assert sum(report.cluster_stats[1].cluster_counts) == 4
    assert report.n_candidate == 10


# ----------------------------------------------------------------------
# The HTML report surfaces the finding
# ----------------------------------------------------------------------


def test_html_report_names_the_uncomparable_counts() -> None:
    html_out = render_html(compute_drift(GOLDEN, REAL_CANDIDATES + TOKEN_LESS, cluster_k=4))
    assert "no embeddable content" in html_out
    assert "<strong>6 of 10</strong> candidate inputs" in html_out
    assert "<strong>0 of 12</strong> golden" in html_out


def test_html_report_omits_the_block_when_everything_is_comparable() -> None:
    html_out = render_html(compute_drift(GOLDEN, REAL_CANDIDATES, cluster_k=4))
    assert "no embeddable content" not in html_out
