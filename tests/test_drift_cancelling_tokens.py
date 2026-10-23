"""Tokens that cancel to the zero vector are uncomparable too (#426, D-017).

`hash_embed` adds `+1` or `-1` per token into one of `dim` buckets. Two tokens
that land in the same bucket with opposite signs cancel, so `"what refund"` has
two tokens and still embeds to exactly the zero vector -- about 1 in 128 random
two-token inputs at `dim=64`. `has_embeddable_content` was `bool(_tokens(text))`
and called those comparable, so they reached the cosine-derived outputs that
D-017/#210 exclude the zero vector from. Measured on `main` 7dde645::

    has_embeddable_content("what refund")          -> True
    sum(abs(x) for x in hash_embed("what refund"))  -> 0.0
    compute_drift(["w195 w39"], ["w195 w39"], cluster_k=1).representative_examples
        -> (RepresentativeExample(text='w195 w39', distance_to_nearest_golden_cluster=1.0),)

An input identical to the golden set was reported at the maximum distance.
"""

from __future__ import annotations

import pytest

from eval_harness.drift import compute_drift, has_embeddable_content, hash_embed

# Common support words whose two hashes share a bucket with opposite signs at
# dim=64, as found by the hunt in #426. `w195 w39` is the minimal synthetic one.
CANCELLING = ["what refund", "what price", "paris ok", "ok help", "error reset"]

GOLDEN = [
    "how do i update my billing address",
    "my card was declined twice",
    "where is my package",
    "tracking number says delivered but nothing",
]
REAL_CANDIDATES = ["rotate my api key", "where is my order", "refund please"]


def test_the_cancelling_inputs_really_have_tokens_and_a_zero_vector() -> None:
    """Pins the premise, so the tests below cannot pass on inputs that are
    merely token-less (#210's route) instead of cancelling (#426's)."""
    for text in CANCELLING + ["w195 w39"]:
        assert len(text.split()) == 2, text
        assert hash_embed(text) == [0.0] * 64, text


@pytest.mark.parametrize("text", CANCELLING + ["w195 w39"])
def test_cancelling_input_has_no_embeddable_content(text: str) -> None:
    assert has_embeddable_content(text) is False


def test_predicate_follows_dim() -> None:
    """Which tokens collide depends on the bucket count, so the predicate has to
    be asked at the dimension the caller embeds at."""
    # Cancels at 64, not at 32; and the reverse.
    assert has_embeddable_content("w1 w96") is False
    assert has_embeddable_content("w1 w96", dim=32) is True
    assert has_embeddable_content("w0 w82") is True
    assert has_embeddable_content("w0 w82", dim=32) is False
    for text, dim in [("w1 w96", 64), ("w1 w96", 32), ("w0 w82", 64), ("w0 w82", 32)]:
        assert has_embeddable_content(text, dim=dim) is any(hash_embed(text, dim=dim)), (text, dim)


def test_cancelling_candidates_are_counted_and_not_examples() -> None:
    report = compute_drift(
        GOLDEN, REAL_CANDIDATES + CANCELLING, cluster_k=2, n_representative_examples=10
    )
    assert report.n_uncomparable == (0, len(CANCELLING))
    assert report.cluster_stats[1].n == len(REAL_CANDIDATES)
    texts = [e.text for e in report.representative_examples]
    assert sorted(texts) == sorted(REAL_CANDIDATES), texts
    assert f"{len(CANCELLING)}/{len(REAL_CANDIDATES) + len(CANCELLING)} candidate" in (
        report.embedding.detail
    )


def test_cancelling_candidates_do_not_move_the_embedding_score() -> None:
    clean = compute_drift(GOLDEN, REAL_CANDIDATES, cluster_k=2)
    noisy = compute_drift(GOLDEN, REAL_CANDIDATES + CANCELLING, cluster_k=2)
    assert noisy.embedding.drift_score == clean.embedding.drift_score
    assert noisy.cluster_stats[1] == clean.cluster_stats[1]


def test_identical_cancelling_input_is_not_reported_at_max_distance() -> None:
    """The headline: an input identical to golden was at distance 1.0."""
    report = compute_drift(["w195 w39", "where is my package"], ["w195 w39"], cluster_k=1)
    assert report.representative_examples == ()
    assert report.n_uncomparable == (1, 1)


def test_cancelling_partition_uses_embedding_dim() -> None:
    """`compute_drift` partitions at `embedding_dim`, not at the default 64."""
    report = compute_drift(
        GOLDEN, REAL_CANDIDATES + ["w0 w82", "w1 w96"], cluster_k=2, embedding_dim=32
    )
    # "w0 w82" cancels at 32; "w1 w96" only cancels at 64, so it stays comparable.
    assert report.n_uncomparable == (0, 1)
    texts = [e.text for e in report.representative_examples]
    assert "w0 w82" not in texts
    assert "w1 w96" in texts


def test_all_cancelling_golden_set_is_rejected() -> None:
    """Before: accepted, and the embedding axis reported a fabricated `0.0 ok`."""
    with pytest.raises(ValueError, match="at least one input with embeddable content"):
        compute_drift(CANCELLING, REAL_CANDIDATES, cluster_k=2)


# --- controls: ordinary inputs are unchanged ---------------------------------


def test_ordinary_inputs_are_comparable() -> None:
    for text in GOLDEN + REAL_CANDIDATES + ["what", "refund", "what a refund"]:
        assert has_embeddable_content(text) is True, text


def test_token_less_inputs_are_still_uncomparable() -> None:
    for text in ["", "!!!", " \n\t ", "\U0001f389"]:
        assert has_embeddable_content(text) is False, text


def test_ordinary_report_has_no_uncomparable_inputs() -> None:
    report = compute_drift(GOLDEN, REAL_CANDIDATES, cluster_k=2)
    assert report.n_uncomparable == (0, 0)
    assert len(report.representative_examples) == len(REAL_CANDIDATES)
