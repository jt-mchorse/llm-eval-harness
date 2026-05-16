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
    render_html,
)
from eval_harness.drift import _judge_stub as judge_stub
from eval_harness.drift import _load_inputs_jsonl as load_inputs

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


def test_jsd_handles_zero_mass():
    assert jensen_shannon([0, 0, 0], [1, 2, 3]) == 0.0
    assert jensen_shannon([], []) == 0.0


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


def test_cli_runs_without_judge_when_flag_not_set(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
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
