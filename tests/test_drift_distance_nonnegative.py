"""`distance_to_nearest_golden_cluster` is a cosine distance and is never negative (#419).

`compute_drift` published `1.0 - nearest_sim` with no bound. Both vectors are
L2-normalised, but the normalisation is rounded, so an input's dot product with
an identical centroid can come out at `1.0000000000000002`. Measured on
origin/main 0f8203d:

    compute_drift(['tau gamma iota'], ['tau gamma iota'])
    -> distance_to_nearest_golden_cluster=-2.220446049250313e-16

and `eval-harness drift` rendered the row as `<td>-0.000</td>`. That is the
negative-zero cell #404/#412/#416 removed at other sites.

The red arms are the identical-input distance, the rendered cell, the CLI
report, the shipped golden set compared with itself, and a random sweep. Two
arms stay green on both trees and reject an over-broad fix:

- `test_a_far_input_keeps_its_exact_distance` is checked bit-for-bit against an
  independent `1.0 - max(cos)`. A clamp in the wrong place, such as a rounding
  step or a clamp inside `_cosine` that moved cluster assignment, would show up
  here.
- `test_published_distances_never_exceed_the_cosine_range` checks the upper end
  of `[0, 2]`.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from eval_harness.cli import main
from eval_harness.drift import (
    _cosine,
    _load_inputs_jsonl,
    compute_drift,
    hash_embed,
    render_html,
)

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "fixtures" / "drift" / "golden_inputs.jsonl"

# The issue's repro string: its hash embedding has a self-cosine of
# 1.0000000000000002, so its distance to its own centroid came out negative.
SELF_COSINE_ABOVE_ONE = "tau gamma iota"


def _distances(golden: list[str], candidate: list[str], **kw: int) -> list[float]:
    report = compute_drift(golden, candidate, n_representative_examples=len(candidate), **kw)
    return [e.distance_to_nearest_golden_cluster for e in report.representative_examples]


def test_the_repro_string_really_has_a_self_cosine_above_one() -> None:
    # Guards the premise. If `hash_embed` ever stops producing this rounding,
    # the red arms below would pass vacuously.
    v = hash_embed(SELF_COSINE_ABOVE_ONE)
    assert _cosine(v, v) > 1.0


def test_an_identical_input_is_at_distance_exactly_positive_zero() -> None:
    (d,) = _distances([SELF_COSINE_ABOVE_ONE], [SELF_COSINE_ABOVE_ONE])
    assert d == 0.0
    # Positive zero: -0.0 == 0.0 is True, but it renders as `-0.000`.
    assert math.copysign(1.0, d) == 1.0


def test_the_rendered_cell_for_an_identical_input_is_not_negative_zero() -> None:
    report = compute_drift([SELF_COSINE_ABOVE_ONE], [SELF_COSINE_ABOVE_ONE])
    page = render_html(report)
    assert "<tr><td>0.000</td><td>tau gamma iota</td></tr>" in page
    assert "-0.000" not in page


def test_the_cli_report_for_identical_files_has_no_negative_distance(tmp_path: Path) -> None:
    golden = tmp_path / "g.jsonl"
    golden.write_text(f'"{SELF_COSINE_ABOVE_ONE}"\n', encoding="utf-8")
    candidate = tmp_path / "c.jsonl"
    candidate.write_text(golden.read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "r.html"
    rc = main(
        [
            "drift",
            "--golden",
            str(golden),
            "--candidate",
            str(candidate),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    assert "-0.000" not in out.read_text(encoding="utf-8")


def test_the_shipped_golden_set_against_itself_has_no_negative_distance() -> None:
    # One sweep, not a parametrize. Before the fix, `cluster_k` 1-6 were clean
    # and 7-10 were not (`cluster_k=8`, the default, gave 2 of 20), so per-k
    # cases would be six arms that are green on both trees.
    golden = _load_inputs_jsonl(GOLDEN)
    bad = [
        (k, d)
        for k in range(1, 11)
        for d in _distances(golden, golden, cluster_k=k)
        if d < 0.0 or math.copysign(1.0, d) != 1.0
    ]
    assert bad == []


def _random_corpus(rng: random.Random, n: int) -> list[str]:
    vocab = [
        "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
        "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi", "rho",
        "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
    ]  # fmt: skip
    return [" ".join(rng.choice(vocab) for _ in range(rng.randint(1, 6))) for _ in range(n)]


def test_no_random_corpus_compared_with_itself_publishes_a_negative_distance() -> None:
    rng = random.Random(419)
    negatives = []
    for _ in range(200):
        corpus = _random_corpus(rng, 12)
        negatives += [d for d in _distances(corpus, corpus, cluster_k=4) if d < 0.0]
    assert negatives == []


def test_published_distances_never_exceed_the_cosine_range() -> None:
    rng = random.Random(4190)
    for _ in range(100):
        golden = _random_corpus(rng, 10)
        candidate = _random_corpus(rng, 10)
        for d in _distances(golden, candidate, cluster_k=3):
            assert 0.0 <= d <= 2.0, d


def test_a_far_input_keeps_its_exact_distance() -> None:
    # A single golden input means a single occupied cluster whose centroid is
    # that input's own embedding, so the expected distance can be computed
    # independently of `compute_drift`.
    golden = ["alpha beta gamma"]
    far = "omega psi chi phi"
    g, c = hash_embed(golden[0]), hash_embed(far)
    expected = 1.0 - _cosine(c, g)
    assert 0.5 < expected < 2.0
    (d,) = _distances(golden, [far])
    assert d == expected
