"""Tests for the drift detection layer (#4, D-014).

Three concerns:

1. JSD math is correct on textbook inputs (identical → 0; disjoint → ~1; rejects mismatched length).
2. ``compute_drift`` produces ``ok`` status on identical inputs and ``drifted`` status on a shifted
   sample for *all three* axes (length axis when lengths shift, embedding axis when topics shift,
   judge axis when the judge stub's score distribution shifts).
3. ``render_html`` produces a valid-looking single-document HTML response (title, table rows,
   three SVG plots when a judge is provided, two SVGs + a "skipped" row when not).

Smoke fixtures live in ``fixtures/drift/``; they are part of the contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_harness.drift import (
    DEFAULT_EMBEDDING_THRESHOLD,
    DEFAULT_JUDGE_THRESHOLD,
    DEFAULT_LENGTH_THRESHOLD,
    cli,
    compute_drift,
    hash_embed,
    jensen_shannon,
    percentile,
    render_html,
)
from eval_harness.drift import _clamp01 as clamp01
from eval_harness.drift import _judge_stub as judge_stub
from eval_harness.drift import _length_histogram as length_histogram
from eval_harness.drift import _load_inputs_jsonl as load_inputs
from eval_harness.drift import _tokens as tokens

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "drift"


# ----------------------------------------------------------------------
# JSD math
# ----------------------------------------------------------------------


def test_jsd_identical_distributions_is_zero():
    assert jensen_shannon([10, 20, 30, 40], [10, 20, 30, 40]) == pytest.approx(0.0)


def test_jsd_identical_after_normalization_is_zero():
    # JSD operates on normalized weights, so scale-only differences are zero.
    assert jensen_shannon([1, 2, 3], [10, 20, 30]) == pytest.approx(0.0)


def test_jsd_disjoint_distributions_is_one():
    # Disjoint supports = maximally divergent under JSD with base-2 logs.
    assert jensen_shannon([1, 0, 0, 0], [0, 0, 0, 1]) == pytest.approx(1.0)


def test_jsd_partial_overlap_in_open_interval():
    # Non-disjoint, non-identical → strictly between 0 and 1.
    v = jensen_shannon([1, 1, 1, 0], [0, 1, 1, 1])
    assert 0.0 < v < 1.0


def test_jsd_rejects_length_mismatch():
    with pytest.raises(ValueError, match="equal length"):
        jensen_shannon([1, 2, 3], [1, 2])


def test_jsd_empty_vectors_is_zero():
    # Zero-length vectors (no buckets at all): nothing to compare -> 0.0.
    assert jensen_shannon([], []) == 0.0


def test_jsd_both_sides_zero_mass_is_zero():
    # Both histograms collapsed to all-zero = two empty distributions, which
    # are identical "nothing" -> 0.0 (#91).
    assert jensen_shannon([0, 0, 0], [0, 0, 0]) == 0.0


def test_jsd_one_side_zero_mass_is_one():
    # Exactly one side empty is the maximally-disjoint case (empty support vs a
    # populated one) -> 1.0, identical in kind to test_jsd_disjoint above. Was
    # silently 0.0 (read as "no drift") before #91, a regression-gate
    # false-negative whenever an axis histogram collapses on one side only.
    assert jensen_shannon([0, 0, 0], [1, 2, 3]) == 1.0
    assert jensen_shannon([1, 2, 3], [0, 0, 0]) == 1.0  # symmetric


# ----------------------------------------------------------------------
# hash_embed
# ----------------------------------------------------------------------


def test_hash_embed_is_deterministic():
    a = hash_embed("hello world example")
    b = hash_embed("hello world example")
    assert a == b


def test_hash_embed_returns_l2_normalized_vector():
    v = hash_embed("some tokens here that are real")
    norm = sum(x * x for x in v) ** 0.5
    assert norm == pytest.approx(1.0)


def test_hash_embed_blank_input_returns_zero_vector():
    v = hash_embed("")
    assert all(x == 0.0 for x in v)


def test_hash_embed_rejects_non_positive_dim():
    with pytest.raises(ValueError, match="dim"):
        hash_embed("anything", dim=0)


# ----------------------------------------------------------------------
# tokenization (#108): the hash tokenizer must be Unicode-aware. The drift
# module scores multilingual production traffic, so an ASCII-only token class
# blinded the embedding axis — non-Latin text produced zero tokens and the
# all-zero vector (the sentinel for *empty* input), and accents were dropped.
# ----------------------------------------------------------------------


def test_tokens_preserves_accented_latin():
    # `café` previously tokenized to `caf` (the `é` was dropped); accents are
    # part of the word and must survive.
    assert tokens("Café Résumé") == ["café", "résumé"]


def test_tokens_keeps_non_latin_scripts():
    # CJK / Cyrillic produced an empty token list under the ASCII regex.
    assert tokens("こんにちは 世界") == ["こんにちは", "世界"]
    assert tokens("Привет мир") == ["привет", "мир"]


def test_tokens_ascii_behavior_unchanged_including_underscore_split():
    # The `[^\W_]+` fix must leave ASCII tokenization byte-identical to the old
    # `[A-Za-z0-9]+`: underscore stays a separator, punctuation splits.
    assert tokens("foo_bar baz") == ["foo", "bar", "baz"]
    assert tokens("Hello, World! 123") == ["hello", "world", "123"]


def test_hash_embed_distinguishes_non_ascii_inputs_from_empty():
    # Two semantically-distinct non-ASCII strings must not collapse to the same
    # vector, and neither may equal the empty-input zero vector (the bug: both
    # returned all-zeros and so compared equal).
    a = hash_embed("天気は良い")
    b = hash_embed("株価が下落")
    empty = hash_embed("")
    assert a != b
    assert a != empty
    assert b != empty
    assert any(x != 0.0 for x in a)


# ----------------------------------------------------------------------
# compute_drift over the smoke fixtures
# ----------------------------------------------------------------------


def _read(name: str) -> list[str]:
    return load_inputs(FIXTURES / name)


def test_compute_drift_identical_inputs_all_axes_ok():
    golden = _read("golden_inputs.jsonl")
    candidate = _read("identical.jsonl")
    report = compute_drift(golden, candidate, judge_score_fn=judge_stub)
    # All three axes flat-equal → status ok and drift ~0.
    assert report.length.status == "ok"
    assert report.embedding.status == "ok"
    assert report.judge is not None
    assert report.judge.status == "ok"
    assert report.length.drift_score < 1e-9
    assert report.embedding.drift_score < 1e-9
    assert report.judge.drift_score < 1e-9
    # Representative examples are still produced (cosine distance to nearest centroid).
    assert len(report.representative_examples) == 5


def test_compute_drift_shifted_inputs_all_axes_drifted():
    golden = _read("golden_inputs.jsonl")
    candidate = _read("shifted.jsonl")
    report = compute_drift(golden, candidate, judge_score_fn=judge_stub)
    assert report.length.status == "drifted", report.length
    assert report.embedding.status == "drifted", report.embedding
    assert report.judge is not None
    assert report.judge.status == "drifted", report.judge
    # And the drift scores are well above the defaults.
    assert report.length.drift_score > DEFAULT_LENGTH_THRESHOLD
    assert report.embedding.drift_score > DEFAULT_EMBEDDING_THRESHOLD
    assert report.judge.drift_score > DEFAULT_JUDGE_THRESHOLD


def test_compute_drift_skips_judge_axis_when_no_fn():
    golden = _read("golden_inputs.jsonl")
    candidate = _read("shifted.jsonl")
    report = compute_drift(golden, candidate, judge_score_fn=None)
    assert report.judge is None
    assert report.judge_stats is None
    # Length and embedding still computed.
    assert report.length.status in {"ok", "drifted"}
    assert report.embedding.status in {"ok", "drifted"}


def test_compute_drift_rejects_empty_inputs():
    with pytest.raises(ValueError, match="golden_inputs must be non-empty"):
        compute_drift([], ["hi"])
    with pytest.raises(ValueError, match="candidate_inputs must be non-empty"):
        compute_drift(["hi"], [])


# Issue #40: JSD is bounded [0, 1] per D-014; thresholds outside that range
# silently disable (> 1.0) or always-fire (< 0.0) the per-axis gate. Validate
# at the function boundary so the failure is proximate to the misconfiguration.
@pytest.mark.parametrize(
    "kwarg",
    ["length_threshold", "embedding_threshold", "judge_threshold"],
)
@pytest.mark.parametrize("bad_value", [-0.01, -1.0, 1.01, 1.5, 2.0])
def test_compute_drift_rejects_out_of_range_threshold(kwarg: str, bad_value: float):
    with pytest.raises(ValueError, match=rf"{kwarg} must be in \[0\.0, 1\.0\]"):
        compute_drift(["alpha"], ["beta"], **{kwarg: bad_value})


@pytest.mark.parametrize(
    "kwarg",
    ["length_threshold", "embedding_threshold", "judge_threshold"],
)
@pytest.mark.parametrize("good_value", [0.0, 0.5, 1.0])
def test_compute_drift_accepts_inclusive_bound_thresholds(kwarg: str, good_value: float):
    # Boundary check should accept the closed interval. 0.0 means "any drift trips it";
    # 1.0 is the upper bound of JSD itself and the gate then never fires — both meaningful.
    report = compute_drift(["alpha"], ["beta"], **{kwarg: good_value})
    assert report.length.status in {"ok", "drifted"}


def test_compute_drift_representative_examples_are_furthest_first():
    golden = _read("golden_inputs.jsonl")
    candidate = _read("shifted.jsonl")
    report = compute_drift(golden, candidate)
    dists = [r.distance_to_nearest_golden_cluster for r in report.representative_examples]
    assert dists == sorted(dists, reverse=True)


def test_compute_drift_cluster_k_is_capped_by_golden_size():
    # Tiny golden set with cluster_k larger than its size should still work.
    report = compute_drift(["alpha beta"], ["gamma delta"], cluster_k=8)
    assert report.cluster_k == 1


# ----------------------------------------------------------------------
# compute_drift — cluster_k / n_representative_examples boundary (#96)
#
# cluster_k <= 0 makes _kmeans return ([], []), so the embedding axis takes the
# no-centroids branch (emb_drift=0.0, status="ok") and silently reports "no
# drift" regardless of actual drift -- the false-negative class fixed for
# jensen_shannon one-empty (#91) and the length-histogram open bucket (#93).
# n_representative_examples < 0 turns examples[:n] into a negative slice that
# silently returns a wrong-sized set. Both must fail loud at the boundary.
# ----------------------------------------------------------------------


@pytest.mark.parametrize("bad_k", [0, -1, -8])
def test_compute_drift_rejects_nonpositive_cluster_k(bad_k: int):
    with pytest.raises(ValueError, match=r"cluster_k must be >= 1"):
        compute_drift(["alpha beta"], ["gamma delta"], cluster_k=bad_k)


def test_compute_drift_accepts_cluster_k_one():
    # 1 is the inclusive lower bound: a single cluster is a valid (degenerate
    # but real) clustering, not the empty-centroids false-negative.
    report = compute_drift(["alpha beta"], ["gamma delta"], cluster_k=1)
    assert report.cluster_k == 1


@pytest.mark.parametrize("bad_n", [-1, -5])
def test_compute_drift_rejects_negative_n_representative_examples(bad_n: int):
    with pytest.raises(ValueError, match=r"n_representative_examples must be >= 0"):
        compute_drift(["alpha"], ["beta"], n_representative_examples=bad_n)


def test_compute_drift_accepts_zero_representative_examples():
    # 0 is the inclusive lower bound: "surface no examples" is a legitimate ask
    # and must yield an empty tuple, not a negative-slice surprise.
    report = compute_drift(["alpha"], ["beta"], n_representative_examples=0)
    assert report.representative_examples == ()


def test_compute_drift_nonpositive_cluster_k_no_longer_masks_real_drift():
    # Regression guard for the gate-bypass: two clearly-different distributions
    # drift on the embedding axis under a valid cluster_k. The buggy path
    # (cluster_k=0) used to report 0.0/"ok" for the same inputs; it now raises
    # rather than silently masking the signal.
    golden = [f"alpha beta gamma delta number {i}" for i in range(40)]
    candidate = [f"zeta eta theta iota kappa lambda mu nu xi {i} {i * 7}" for i in range(40)]
    report = compute_drift(golden, candidate, cluster_k=8)
    assert report.embedding.drift_score > 0.0
    with pytest.raises(ValueError, match=r"cluster_k must be >= 1"):
        compute_drift(golden, candidate, cluster_k=0)


# ----------------------------------------------------------------------
# _length_histogram — open-ended top bucket (#93)
# ----------------------------------------------------------------------


def test_length_histogram_counts_huge_input_in_last_bucket():
    # An input of length >= 1_000_000 has no upper bucket boundary; the final
    # bucket is open-ended, so it must be counted there, not dropped (#93).
    hist = length_histogram(["x" * 1_000_000])
    assert sum(hist) == 1
    assert hist[-1] == 1


def test_length_histogram_counts_every_input_no_silent_drop():
    # Total count must equal the number of inputs for any length, including
    # one far past the sentinel — nothing falls on the floor.
    inputs = ["", "x" * 50, "x" * 5000, "x" * 2_000_000]
    hist = length_histogram(inputs)
    assert sum(hist) == len(inputs)
    # Both the 5000-char and the 2M-char input are >= 4096, so both land in the
    # open-ended final bucket; the point is that none of the four is dropped.
    assert hist[-1] == 2


def test_length_histogram_normal_lengths_unchanged():
    # Regression guard: ordinary lengths bucket exactly as before. "" -> [0,32),
    # 50 -> [32,64), 5000 -> [4096,∞). One each in three distinct buckets.
    hist = length_histogram(["", "x" * 50, "x" * 5000])
    assert sum(hist) == 3
    assert hist[0] == 1  # 0 chars
    assert hist[1] == 1  # 50 chars
    assert hist[-1] == 1  # 5000 chars (>= 4096)


def test_compute_drift_flags_all_huge_candidate_as_length_drifted():
    # End-to-end: a candidate set whose inputs are all >= 1M chars vs a
    # normal-length golden set. Pre-#93 every candidate was dropped, leaving
    # an all-zero candidate histogram (no drift signal); now they're counted
    # in the open-ended bucket, so the length axis registers genuine drift.
    golden = ["short input", "another short one", "tiny", "a normal length string here"]
    candidate = ["x" * 1_000_000, "y" * 1_500_000, "z" * 2_000_000]
    report = compute_drift(golden, candidate, judge_score_fn=None)
    assert report.length_histograms[1][-1] == len(candidate)  # all in top bucket
    assert report.length.status == "drifted", report.length
    assert report.length.drift_score > DEFAULT_LENGTH_THRESHOLD


# ----------------------------------------------------------------------
# HTML rendering
# ----------------------------------------------------------------------


def test_render_html_contains_required_structure():
    golden = _read("golden_inputs.jsonl")
    candidate = _read("shifted.jsonl")
    report = compute_drift(golden, candidate, judge_score_fn=judge_stub)
    html = render_html(report)
    assert "<title>eval-harness drift report</title>" in html
    # Three SVGs (length, embedding, judge) when a judge fn was supplied.
    assert html.count("<svg") == 3
    # Status classes on a drifted report.
    assert "status-drifted" in html
    # Drift report table headers.
    assert "Drift (JSD)" in html
    assert "Threshold" in html


def test_render_html_drops_judge_axis_when_skipped():
    golden = _read("golden_inputs.jsonl")
    candidate = _read("identical.jsonl")
    report = compute_drift(golden, candidate, judge_score_fn=None)
    html = render_html(report)
    # Two SVGs (length + embedding).
    assert html.count("<svg") == 2
    # And an explicit "skipped" message for the judge axis.
    assert "axis skipped" in html


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def test_cli_writes_html_and_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    out = tmp_path / "report.html"
    rc = cli(
        [
            "--golden",
            str(FIXTURES / "golden_inputs.jsonl"),
            "--candidate",
            str(FIXTURES / "shifted.jsonl"),
            "--output",
            str(out),
            "--judge-stub",
        ]
    )
    assert rc == 0
    assert out.exists()
    text = out.read_text()
    assert "<title>eval-harness drift report</title>" in text
    captured = capsys.readouterr()
    assert "drifted" in captured.out
    assert "judge=" in captured.out


def test_cli_runs_without_judge_when_flag_not_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    out = tmp_path / "report.html"
    rc = cli(
        [
            "--golden",
            str(FIXTURES / "golden_inputs.jsonl"),
            "--candidate",
            str(FIXTURES / "identical.jsonl"),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    # No judge summary line when --judge-stub is absent.
    assert "judge=" not in captured.out


# ----------------------------------------------------------------------
# Input loader
# ----------------------------------------------------------------------


def test_load_inputs_jsonl_accepts_bare_strings_and_objects(tmp_path: Path):
    p = tmp_path / "mixed.jsonl"
    p.write_text(
        '"a bare string"\n'
        '{"input": "from input key"}\n'
        '{"prompt": "from prompt key"}\n'
        '{"text": "from text key"}\n'
    )
    out = load_inputs(p)
    assert out == ["a bare string", "from input key", "from prompt key", "from text key"]


def test_load_inputs_jsonl_rejects_invalid_json(tmp_path: Path):
    p = tmp_path / "bad.jsonl"
    p.write_text("not json\n")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_inputs(p)


def test_load_inputs_jsonl_rejects_object_without_input_keys(tmp_path: Path):
    p = tmp_path / "wrong.jsonl"
    p.write_text('{"other_key": "value"}\n')
    with pytest.raises(ValueError, match="missing input/prompt/text"):
        load_inputs(p)


def test_load_inputs_jsonl_rejects_empty_file(tmp_path: Path):
    p = tmp_path / "empty.jsonl"
    p.write_text("\n\n")
    with pytest.raises(ValueError, match="no inputs loaded"):
        load_inputs(p)


# ----------------------------------------------------------------------
# Non-finite judge-score validation (#87)
# ----------------------------------------------------------------------
#
# `_clamp01` is the choke point every operator-supplied judge_score_fn result
# passes through. Sign-only clamping let NaN crash `_judge_histogram` cryptically
# (`int(s * 10)`) and let ±Inf silently clamp to 1.0/0.0, poisoning mean_score
# and the JSD histogram. It now fails loud, matching runner #86 / calibration #45.


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_clamp01_rejects_non_finite(bad):
    with pytest.raises(ValueError, match="judge score must be finite"):
        clamp01(bad)


# #166: the present-but-non-numeric sibling of the non-finite guard. A str/None/
# list/bool judge score (a BYO judge_score_fn that forgot to parse to float, or
# returned None on an abstain) hit the bare math.isfinite and raised a raw
# TypeError; must now raise the same clean ValueError, matching the cited
# calibration.binarize (#45) parity contract.
@pytest.mark.parametrize("bad", ["0.7", None, [0.5], {"s": 1}, True, False])
def test_clamp01_rejects_non_numeric(bad):
    with pytest.raises(ValueError, match="judge score must be finite"):
        clamp01(bad)  # type: ignore[arg-type]


def test_compute_drift_rejects_non_numeric_judge_score_with_clear_error():
    # A non-numeric judge_score_fn return previously raised a raw TypeError deep
    # in _clamp01; now surfaces the same judge-score contract violation as NaN.
    with pytest.raises(ValueError, match="judge score must be finite"):
        compute_drift(
            ["good"],
            ["bad"],
            judge_score_fn=lambda t: "0.7" if "bad" in t else 0.5,
        )


def test_clamp01_still_clamps_finite_out_of_range():
    assert clamp01(-0.5) == 0.0
    assert clamp01(1.5) == 1.0
    assert clamp01(0.5) == 0.5
    assert clamp01(0.0) == 0.0
    assert clamp01(1.0) == 1.0


def test_compute_drift_rejects_nan_judge_score_with_clear_error():
    # Previously crashed with the cryptic "cannot convert float NaN to integer"
    # deep in _judge_histogram; now surfaces the judge-score contract violation.
    with pytest.raises(ValueError, match="judge score must be finite"):
        compute_drift(
            ["good"],
            ["bad"],
            judge_score_fn=lambda t: float("nan") if "bad" in t else 0.5,
        )


def test_compute_drift_rejects_inf_judge_score_instead_of_silent_clamp():
    # Previously +inf silently clamped to 1.0, corrupting mean_score/histogram.
    with pytest.raises(ValueError, match="judge score must be finite"):
        compute_drift(
            ["good"],
            ["big"],
            judge_score_fn=lambda t: float("inf") if "big" in t else 0.5,
        )


# ----------------------------------------------------------------------
# percentile — NIST type-7 linear-interp percentile (#136)
#
# `percentile` is public (in `drift.__all__`) and drives the length-drift
# report's `median` and `p95` (drift.py build_length_report), but had no
# direct test. These cases lock its documented contract branch-by-branch;
# every expected value was verified firsthand against the real function.
# ----------------------------------------------------------------------


def test_percentile_empty_returns_zero():
    # Documented degenerate: no values → 0.0 (not an error), so an empty
    # length sample yields median=p95=0.0 rather than crashing the report.
    assert percentile([], 0.5) == 0.0


def test_percentile_single_element_is_that_element_for_any_q():
    for q in (0.0, 0.25, 0.5, 0.95, 1.0):
        assert percentile([42.0], q) == 42.0


def test_percentile_q0_is_min_and_q1_is_max_even_when_unsorted():
    # The function sorts internally, so input order must not matter.
    assert percentile([3.0, 1.0, 2.0], 0.0) == 1.0
    assert percentile([3.0, 1.0, 2.0], 1.0) == 3.0


def test_percentile_even_n_median_interpolates_between_middle_pair():
    # type-7 median of [1,2,3,4] is the midpoint of the middle pair: 2.5.
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5


def test_percentile_odd_n_median_is_the_middle_element():
    # idx = 0.5*(5-1) = 2 is integral (lo == hi), so the exact middle
    # element is returned with no interpolation.
    assert percentile([5.0, 4.0, 3.0, 2.0, 1.0], 0.5) == 3.0


def test_percentile_integral_index_branch_returns_exact_element():
    # [10,20,30,40,50] q=0.5 → idx=2.0 (lo == hi) → s[2] == 30.0 exactly.
    assert percentile([10.0, 20.0, 30.0, 40.0, 50.0], 0.5) == 30.0


def test_percentile_fractional_index_interpolates_linearly():
    # [0,10] q=0.25 → idx=0.25 → 0 + (10-0)*0.25 = 2.5.
    assert percentile([0.0, 10.0], 0.25) == 2.5
    # [1..100] q=0.95 → idx=0.95*99=94.05 → s[94]=95 + (96-95)*0.05 = 95.05.
    assert percentile([float(i) for i in range(1, 101)], 0.95) == pytest.approx(95.05)


def test_percentile_rejects_q_out_of_unit_range():
    with pytest.raises(ValueError, match=r"q must be in \[0.0, 1.0\]"):
        percentile([1.0, 2.0], -0.1)
    with pytest.raises(ValueError, match=r"q must be in \[0.0, 1.0\]"):
        percentile([1.0, 2.0], 1.5)
