"""Drift detection on production traffic samples (#4, D-014).

Given a golden dataset (the one you calibrated against) and a candidate
sample of production *inputs* (no outputs required), this module
measures distribution drift along three axes:

- **Length** — char-count histogram of inputs.
- **Embedding cluster** — a dep-free hash embedder (lexical-overlap
  pattern matching the portfolio's other repos) embeds each input to
  a fixed-dim vector; k-means on the golden set gives cluster
  centroids; each candidate input is assigned to the nearest centroid
  by cosine; the resulting cluster-id distributions are compared.
- **Judge-score** — operator-supplied ``judge_score_fn(input) -> float``
  (a closure over a ``Judge``, or a stub for hermetic CI). Skipped
  when no function is provided so the rest of the analysis still
  renders.

The drift score on each axis is the **Jensen-Shannon divergence**
between the golden and candidate histograms, base-2 so values are
bounded in ``[0, 1]``. JSD over KL/KS is recorded as D-014: KL is
unbounded and asymmetric (the comparison reads the wrong way under
direction swap); KS works only for ordered scalars (it doesn't
generalize to the cluster-id axis); JSD does both with one formula
and one threshold per axis.

The HTML report renders all three axes as inline-SVG overlays plus a
representative-examples list. Dep-free — no external CDN, no chart
library; mirrors the dashboard pattern in
``rag-production-kit/scripts/telemetry_dashboard.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from eval_harness.io_utils import atomic_write_text

# ----------------------------------------------------------------------
# Public types
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class LengthStats:
    n: int
    mean: float
    median: float
    p95: float


@dataclass(frozen=True)
class ClusterStats:
    n: int
    cluster_counts: tuple[int, ...]  # one entry per cluster id 0..k-1


@dataclass(frozen=True)
class JudgeStats:
    n: int
    bucket_counts: tuple[int, ...]  # 10 buckets over [0.0, 1.0]
    mean_score: float


@dataclass(frozen=True)
class AxisReport:
    """One drift-axis result.

    ``status`` is ``"ok"`` when drift is below threshold, ``"drifted"``
    when above; thresholds are caller-set since "drifted" is a policy
    decision, not a math one.
    """

    name: str
    drift_score: float  # JSD in [0, 1]
    status: str  # "ok" | "drifted"
    threshold: float
    detail: str


@dataclass(frozen=True)
class RepresentativeExample:
    text: str
    distance_to_nearest_golden_cluster: float


@dataclass(frozen=True)
class DriftReport:
    n_golden: int
    n_candidate: int
    length: AxisReport
    embedding: AxisReport
    judge: AxisReport | None
    length_stats: tuple[LengthStats, LengthStats]
    length_histograms: tuple[tuple[int, ...], tuple[int, ...]]  # (golden, candidate)
    cluster_stats: tuple[ClusterStats, ClusterStats]
    judge_stats: tuple[JudgeStats, JudgeStats] | None
    representative_examples: tuple[RepresentativeExample, ...]
    cluster_k: int


# ----------------------------------------------------------------------
# Math primitives
# ----------------------------------------------------------------------


def jensen_shannon(p: Sequence[float], q: Sequence[float]) -> float:
    """Jensen-Shannon divergence (base-2). Bounded in ``[0, 1]``.

    ``p`` and ``q`` are non-negative weight vectors of equal length;
    they're normalized internally so the caller can pass raw counts.
    Returns 0.0 when distributions are identical after normalization
    and approaches 1.0 as supports become disjoint.

    Empty-distribution contract (a zero-mass side can't be normalized):
    two empty distributions are identical "nothing" -> ``0.0``; exactly
    one empty side is the *maximally disjoint* case (empty support vs a
    populated one, identical in kind to ``[1, 0]`` vs ``[0, 1]``) and
    returns ``1.0``, the JSD upper bound. The earlier ``sp <= 0 or
    sq <= 0 -> 0.0`` guard collapsed both into 0.0, so a drift axis whose
    histogram collapsed to all-zero on one side (e.g. a `_length_histogram`
    that silently drops every >=1M-char input) reported "no drift" when
    drift was maximal -- a false-negative that bypassed the regression gate
    (#91). Consistent with D-014 (JSD base-2 bounded [0, 1]).
    """
    if len(p) != len(q):
        raise ValueError(f"distributions must have equal length; got {len(p)} vs {len(q)}")
    if not p:
        return 0.0
    sp = sum(p)
    sq = sum(q)
    if sp <= 0.0 and sq <= 0.0:
        # Both empty: identical "nothing".
        return 0.0
    if sp <= 0.0 or sq <= 0.0:
        # Exactly one empty: disjoint supports -> JSD upper bound.
        return 1.0
    pp = [x / sp for x in p]
    qq = [x / sq for x in q]
    m = [(a + b) / 2.0 for a, b in zip(pp, qq, strict=True)]

    def _kl(a: Sequence[float], b: Sequence[float]) -> float:
        out = 0.0
        for ai, bi in zip(a, b, strict=True):
            if ai > 0.0 and bi > 0.0:
                out += ai * math.log2(ai / bi)
        return out

    jsd = (_kl(pp, m) + _kl(qq, m)) / 2.0
    if jsd < 0.0:
        return 0.0
    if jsd > 1.0:
        return 1.0
    return jsd


def percentile(values: Sequence[float], q: float) -> float:
    """NIST type-7 linear-interp percentile (matches the rag-kit pattern)."""
    if not values:
        return 0.0
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"q must be in [0.0, 1.0]; got {q}")
    s = sorted(values)
    if q == 0.0:
        return s[0]
    if q == 1.0:
        return s[-1]
    idx = q * (len(s) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return s[int(idx)]
    frac = idx - lo
    return s[lo] + (s[hi] - s[lo]) * frac


# Unicode alphanumerics, excluding underscore (`[^\W_]` = a `\w` char that is
# not `_`). The drift module scores *production traffic samples*, which are
# inherently multilingual; an ASCII-only `[A-Za-z0-9]+` matched zero tokens for
# non-Latin text (CJK/Cyrillic/…), so `hash_embed` returned the all-zero vector
# — the sentinel reserved for *empty* input — collapsing every distinct
# non-ASCII input to identical "empty" content, and dropped accents from Latin
# text (`café` -> `caf`). `[^\W_]+` keeps ASCII tokenization byte-identical
# (underscore is still a separator: `foo_bar` -> `foo`, `bar`) and only changes
# non-ASCII behavior. See #108.
_HASH_TOKEN_RE = re.compile(r"[^\W_]+")


def _tokens(text: str) -> list[str]:
    return _HASH_TOKEN_RE.findall(text.lower())


def hash_embed(text: str, dim: int = 64) -> list[float]:
    """L2-normalized hash embedding. Deterministic, dep-free.

    Each lowercased alphanumeric token is hashed (SHA-1) to a bucket
    in ``[0, dim)`` with a deterministic sign; the resulting vector is
    L2-normalized so cosine similarity is a dot product. Same shape as
    the ``HashEmbedder`` reference in ``rag-production-kit``.
    """
    if dim <= 0:
        raise ValueError(f"dim must be positive; got {dim}")
    vec = [0.0] * dim
    for tok in _tokens(text):
        h = int(hashlib.sha1(tok.encode("utf-8")).hexdigest(), 16)
        bucket = h % dim
        sign = 1.0 if (h // dim) & 1 else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0.0:
        vec = [v / norm for v in vec]
    return vec


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _kmeans(
    vectors: Sequence[Sequence[float]],
    k: int,
    *,
    max_iter: int = 25,
) -> tuple[list[list[float]], list[int]]:
    """Tiny k-means on L2-normalized vectors. Stride-init for determinism."""
    n = len(vectors)
    if n == 0 or k <= 0:
        return [], []
    k = min(k, n)
    step = max(n // k, 1)
    centroids = [list(vectors[i * step]) for i in range(k)]
    dim = len(centroids[0]) if centroids and centroids[0] else 0
    assigns = [0] * n
    for _ in range(max_iter):
        changed = False
        for i, v in enumerate(vectors):
            best = 0
            best_sim = -2.0
            for ci, centroid in enumerate(centroids):
                sim = _cosine(v, centroid)
                if sim > best_sim:
                    best_sim = sim
                    best = ci
            if assigns[i] != best:
                assigns[i] = best
                changed = True
        new_centroids = [[0.0] * dim for _ in range(k)]
        counts = [0] * k
        for i, v in enumerate(vectors):
            c = assigns[i]
            counts[c] += 1
            for d, vv in enumerate(v):
                new_centroids[c][d] += vv
        for ci in range(k):
            if counts[ci] == 0:
                new_centroids[ci] = list(centroids[ci])
                continue
            norm = math.sqrt(sum(x * x for x in new_centroids[ci]))
            if norm > 0.0:
                new_centroids[ci] = [x / norm for x in new_centroids[ci]]
        centroids = new_centroids
        if not changed:
            break
    return centroids, assigns


# ----------------------------------------------------------------------
# Axis computations
# ----------------------------------------------------------------------


_LENGTH_BUCKETS = (0, 32, 64, 128, 256, 512, 1024, 2048, 4096, 1_000_000)


def _length_histogram(inputs: Sequence[str]) -> tuple[int, ...]:
    n_buckets = len(_LENGTH_BUCKETS) - 1
    buckets = [0] * n_buckets
    for s in inputs:
        n = len(s)
        for i in range(n_buckets):
            # The final bucket is open-ended: `_LENGTH_BUCKETS[-1]`
            # (1_000_000) is an ∞ sentinel, not a hard ceiling — `render_html`
            # already labels it `4096-∞`. The strict `n < upper` check dropped
            # any input of length >= 1_000_000 chars on the floor (no matching
            # bucket), leaving an all-zero histogram that read as "no drift"
            # — the reachability mechanism for the jensen_shannon one-empty
            # false-negative (#93, sibling to #91). Catch everything at or
            # above the last lower bound so no input is silently uncounted.
            is_last = i == n_buckets - 1
            if _LENGTH_BUCKETS[i] <= n and (is_last or n < _LENGTH_BUCKETS[i + 1]):
                buckets[i] += 1
                break
    return tuple(buckets)


def _length_stats(inputs: Sequence[str]) -> LengthStats:
    if not inputs:
        return LengthStats(0, 0.0, 0.0, 0.0)
    lens = [float(len(s)) for s in inputs]
    return LengthStats(
        n=len(lens),
        mean=sum(lens) / len(lens),
        median=percentile(lens, 0.5),
        p95=percentile(lens, 0.95),
    )


def _judge_histogram(scores: Sequence[float]) -> tuple[int, ...]:
    """10 buckets over ``[0.0, 1.0]``."""
    buckets = [0] * 10
    for s in scores:
        if s < 0.0:
            buckets[0] += 1
        elif s >= 1.0:
            buckets[-1] += 1
        else:
            buckets[int(s * 10)] += 1
    return tuple(buckets)


# ----------------------------------------------------------------------
# Top-level entry point
# ----------------------------------------------------------------------


DEFAULT_LENGTH_THRESHOLD = 0.10
DEFAULT_EMBEDDING_THRESHOLD = 0.10
DEFAULT_JUDGE_THRESHOLD = 0.10


def compute_drift(
    golden_inputs: Sequence[str],
    candidate_inputs: Sequence[str],
    *,
    judge_score_fn: Callable[[str], float] | None = None,
    embedding_dim: int = 64,
    cluster_k: int = 8,
    length_threshold: float = DEFAULT_LENGTH_THRESHOLD,
    embedding_threshold: float = DEFAULT_EMBEDDING_THRESHOLD,
    judge_threshold: float = DEFAULT_JUDGE_THRESHOLD,
    n_representative_examples: int = 5,
) -> DriftReport:
    """Compute a three-axis drift report.

    ``length`` and ``embedding`` axes are always computed; ``judge`` is
    computed only when ``judge_score_fn`` is provided so hermetic CI
    runs that don't pay for a judge still get the other two axes.

    ``representative_examples`` is the list of candidate inputs whose
    nearest-golden-centroid cosine distance is largest — the inputs
    that look least like anything in the golden set.
    """
    if not golden_inputs:
        raise ValueError("golden_inputs must be non-empty")
    if not candidate_inputs:
        raise ValueError("candidate_inputs must be non-empty")

    # JSD is base-2 and bounded [0, 1] per D-014. A threshold outside that
    # range silently disables (threshold > 1.0) or always-fires (threshold < 0)
    # the per-axis gate. Validate at the boundary so the failure is proximate.
    for _name, _value in (
        ("length_threshold", length_threshold),
        ("embedding_threshold", embedding_threshold),
        ("judge_threshold", judge_threshold),
    ):
        if not (0.0 <= _value <= 1.0):
            raise ValueError(f"{_name} must be in [0.0, 1.0]; got {_value}")

    # cluster_k <= 0 makes `_kmeans` return ([], []), so `compute_drift` takes
    # the no-centroids branch: emb_drift=0.0, status="ok", empty histograms.
    # That is a silent false-negative on the embedding gate -- "no drift"
    # reported regardless of actual drift -- the same class already fixed for
    # jensen_shannon one-empty (#91) and the length-histogram open bucket (#93).
    # n_representative_examples < 0 turns `examples[:n]` into a negative slice
    # that silently returns a large, wrong set (dropping the most-distant tail
    # the list is sorted to surface). Fail loud at the choke point, matching
    # the threshold block above and `_clamp01`'s philosophy (#96).
    if cluster_k <= 0:
        raise ValueError(f"cluster_k must be >= 1; got {cluster_k}")
    if n_representative_examples < 0:
        raise ValueError(f"n_representative_examples must be >= 0; got {n_representative_examples}")

    # --- Length axis ----------------------------------------------------
    g_len_hist = _length_histogram(golden_inputs)
    c_len_hist = _length_histogram(candidate_inputs)
    length_drift = jensen_shannon(g_len_hist, c_len_hist)
    length_report = AxisReport(
        name="length",
        drift_score=length_drift,
        status="drifted" if length_drift > length_threshold else "ok",
        threshold=length_threshold,
        detail=f"JSD over char-length histogram across {len(_LENGTH_BUCKETS) - 1} buckets",
    )

    # --- Embedding axis -------------------------------------------------
    g_vecs = [hash_embed(s, dim=embedding_dim) for s in golden_inputs]
    c_vecs = [hash_embed(s, dim=embedding_dim) for s in candidate_inputs]
    centroids, _ = _kmeans(g_vecs, cluster_k)
    if centroids:

        def _assign(v: Sequence[float]) -> int:
            best = 0
            best_sim = -2.0
            for ci, c in enumerate(centroids):
                sim = _cosine(v, c)
                if sim > best_sim:
                    best_sim = sim
                    best = ci
            return best

        g_clusters = [_assign(v) for v in g_vecs]
        c_clusters = [_assign(v) for v in c_vecs]
        k_eff = len(centroids)
        g_cluster_counts = tuple(sum(1 for x in g_clusters if x == i) for i in range(k_eff))
        c_cluster_counts = tuple(sum(1 for x in c_clusters if x == i) for i in range(k_eff))
        emb_drift = jensen_shannon(g_cluster_counts, c_cluster_counts)
    else:  # pragma: no cover - degenerate empty-vector case caught above
        g_cluster_counts = ()
        c_cluster_counts = ()
        emb_drift = 0.0
    embedding_report = AxisReport(
        name="embedding",
        drift_score=emb_drift,
        status="drifted" if emb_drift > embedding_threshold else "ok",
        threshold=embedding_threshold,
        detail=(
            f"JSD over k={len(centroids)} cluster-id histogram from "
            f"{embedding_dim}-dim hash-embedded inputs"
        ),
    )

    # --- Judge axis (optional) -----------------------------------------
    judge_report: AxisReport | None = None
    judge_stats: tuple[JudgeStats, JudgeStats] | None = None
    if judge_score_fn is not None:
        g_scores = [_clamp01(judge_score_fn(s)) for s in golden_inputs]
        c_scores = [_clamp01(judge_score_fn(s)) for s in candidate_inputs]
        g_hist = _judge_histogram(g_scores)
        c_hist = _judge_histogram(c_scores)
        judge_drift = jensen_shannon(g_hist, c_hist)
        judge_report = AxisReport(
            name="judge",
            drift_score=judge_drift,
            status="drifted" if judge_drift > judge_threshold else "ok",
            threshold=judge_threshold,
            detail="JSD over 10-bucket histogram of judge_score_fn(input) in [0, 1]",
        )
        judge_stats = (
            JudgeStats(
                n=len(g_scores),
                bucket_counts=g_hist,
                mean_score=sum(g_scores) / len(g_scores) if g_scores else 0.0,
            ),
            JudgeStats(
                n=len(c_scores),
                bucket_counts=c_hist,
                mean_score=sum(c_scores) / len(c_scores) if c_scores else 0.0,
            ),
        )

    # --- Representative examples ---------------------------------------
    examples: list[RepresentativeExample] = []
    if centroids:
        for v, text in zip(c_vecs, candidate_inputs, strict=True):
            nearest_sim = max(_cosine(v, c) for c in centroids)
            examples.append(
                RepresentativeExample(
                    text=text, distance_to_nearest_golden_cluster=1.0 - nearest_sim
                )
            )
        examples.sort(key=lambda r: r.distance_to_nearest_golden_cluster, reverse=True)
        examples = examples[:n_representative_examples]

    return DriftReport(
        n_golden=len(golden_inputs),
        n_candidate=len(candidate_inputs),
        length=length_report,
        embedding=embedding_report,
        judge=judge_report,
        length_stats=(_length_stats(golden_inputs), _length_stats(candidate_inputs)),
        length_histograms=(g_len_hist, c_len_hist),
        cluster_stats=(
            ClusterStats(n=len(golden_inputs), cluster_counts=g_cluster_counts),
            ClusterStats(n=len(candidate_inputs), cluster_counts=c_cluster_counts),
        ),
        judge_stats=judge_stats,
        representative_examples=tuple(examples),
        cluster_k=len(centroids),
    )


def _clamp01(x: float) -> float:
    """Clamp a judge score into ``[0, 1]``.

    Every operator-supplied ``judge_score_fn(input)`` result passes through
    here. Clamping is for finite-but-out-of-range values; a *non-finite*
    score (NaN/±Inf) is corruption, not something to clamp — NaN would
    later crash ``_judge_histogram`` cryptically at ``int(s * 10)`` and
    ±Inf would silently clamp to 1.0/0.0, poisoning ``mean_score`` and the
    JSD histogram. Fail loud at the choke point instead, matching the
    finiteness guards in ``runner.load_run_result_from_json`` (#86) and
    ``calibration.binarize`` (#45).

    A *present-but-non-numeric* result (a ``str``/``None``/``list`` off the
    same BYO ``judge_score_fn`` seam — a judge that forgot to parse its model
    output to ``float``, or returned ``None`` on an abstain) hit the bare
    ``math.isfinite(x)`` and raised a raw ``TypeError`` instead of this clean
    ``ValueError`` — the non-numeric branch the cited ``binarize`` (#45) guards
    but this only-non-finite guard missed. Reject it (and ``bool``, which
    ``binarize`` also rejects) the same way so the parity contract holds.
    """
    if not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x):
        raise ValueError(f"judge score must be finite; got {x!r}")
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


# ----------------------------------------------------------------------
# HTML rendering
# ----------------------------------------------------------------------


def _bar_chart_svg(
    title: str,
    labels: Sequence[str],
    golden: Sequence[int],
    candidate: Sequence[int],
    width: int = 540,
    height: int = 180,
) -> str:
    if not labels:
        return f'<svg width="{width}" height="{height}"><text x="50%" y="50%" text-anchor="middle">empty</text></svg>'
    margin_l, margin_r, margin_t, margin_b = 30, 12, 22, 26
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b
    sg = sum(golden) or 1
    sc = sum(candidate) or 1
    g_norm = [x / sg for x in golden]
    c_norm = [x / sc for x in candidate]
    max_v = max(max(g_norm, default=0.0), max(c_norm, default=0.0), 0.01)
    bar_w = plot_w / len(labels) / 2.5
    parts = [
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" '
        'style="background:#fafafa;border:1px solid #eee">',
        f'<text x="{margin_l}" y="{margin_t - 6}" font-size="11" fill="#444">{html.escape(title)}</text>',
    ]
    for i in range(len(labels)):
        cx = margin_l + (i + 0.5) * (plot_w / len(labels))
        gh_ = plot_h * (g_norm[i] / max_v) if i < len(g_norm) else 0.0
        ch_ = plot_h * (c_norm[i] / max_v) if i < len(c_norm) else 0.0
        gy = margin_t + plot_h - gh_
        cy = margin_t + plot_h - ch_
        parts.append(
            f'<rect x="{cx - bar_w:.1f}" y="{gy:.1f}" width="{bar_w:.1f}" height="{gh_:.1f}" '
            'fill="#888" opacity="0.7"/>'
        )
        parts.append(
            f'<rect x="{cx + 0.5:.1f}" y="{cy:.1f}" width="{bar_w:.1f}" height="{ch_:.1f}" '
            'fill="#1f6feb" opacity="0.85"/>'
        )
    for i, label in enumerate(labels):
        cx = margin_l + (i + 0.5) * (plot_w / len(labels))
        parts.append(
            f'<text x="{cx:.1f}" y="{height - 8}" text-anchor="middle" font-size="9" fill="#666">'
            f"{html.escape(label)}</text>"
        )
    parts.append(
        f'<text x="{width - 30}" y="{margin_t + 8}" text-anchor="end" font-size="9" fill="#666">'
        "golden / candidate</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def render_html(report: DriftReport) -> str:
    """Render the drift report to a single HTML document. Dep-free."""
    length_labels = [
        f"{_LENGTH_BUCKETS[i]}-{_LENGTH_BUCKETS[i + 1] - 1 if _LENGTH_BUCKETS[i + 1] < 1_000_000 else '∞'}"
        for i in range(len(_LENGTH_BUCKETS) - 1)
    ]
    length_svg = _bar_chart_svg(
        f"Length JSD = {report.length.drift_score:.3f} ({report.length.status})",
        length_labels,
        list(report.length_histograms[0]),
        list(report.length_histograms[1]),
    )
    cluster_labels = [f"c{i}" for i in range(report.cluster_k)]
    cluster_svg = _bar_chart_svg(
        f"Embedding cluster JSD = {report.embedding.drift_score:.3f} ({report.embedding.status})",
        cluster_labels,
        list(report.cluster_stats[0].cluster_counts),
        list(report.cluster_stats[1].cluster_counts),
    )
    judge_block = ""
    if report.judge is not None and report.judge_stats is not None:
        judge_labels = [f"{i / 10:.1f}" for i in range(10)]
        judge_svg = _bar_chart_svg(
            f"Judge-score JSD = {report.judge.drift_score:.3f} ({report.judge.status})",
            judge_labels,
            list(report.judge_stats[0].bucket_counts),
            list(report.judge_stats[1].bucket_counts),
        )
        judge_block = f"<h2>Judge axis</h2>{judge_svg}"

    examples_rows = "\n".join(
        f"<tr><td>{r.distance_to_nearest_golden_cluster:.3f}</td>"
        f"<td>{html.escape(r.text)[:200]}</td></tr>"
        for r in report.representative_examples
    )
    if report.judge is not None:
        judge_row = (
            f"<tr><td>judge</td><td>{report.judge.drift_score:.4f}</td>"
            f"<td>{report.judge.threshold}</td>"
            f'<td class="status-{report.judge.status}">{report.judge.status}</td>'
            f"<td>{html.escape(report.judge.detail)}</td></tr>"
        )
    else:
        judge_row = (
            "<tr><td>judge</td>"
            '<td colspan="4" style="color:#999">no judge_score_fn supplied; axis skipped</td></tr>'
        )

    empty_examples_row = (
        '<tr><td colspan="2" style="text-align:center;color:#999">no examples</td></tr>'
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>eval-harness drift report</title>"
        "<style>"
        "body{font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;"
        "max-width:720px;margin:24px auto;padding:0 16px;color:#222}"
        "h1{font-size:20px}h2{font-size:13px;color:#555;margin-top:18px}"
        "table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}"
        "th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #eee}"
        "th{background:#fafafa}.status-ok{color:#1f8848;font-weight:600}"
        ".status-drifted{color:#b04127;font-weight:600}"
        "</style></head><body>"
        f"<h1>Drift report — {report.n_golden} golden vs {report.n_candidate} candidate inputs</h1>"
        "<table>"
        "<thead><tr><th>Axis</th><th>Drift (JSD)</th><th>Threshold</th><th>Status</th><th>Detail</th></tr></thead>"
        "<tbody>"
        f"<tr><td>length</td><td>{report.length.drift_score:.4f}</td>"
        f"<td>{report.length.threshold}</td>"
        f'<td class="status-{report.length.status}">{report.length.status}</td>'
        f"<td>{html.escape(report.length.detail)}</td></tr>"
        f"<tr><td>embedding</td><td>{report.embedding.drift_score:.4f}</td>"
        f"<td>{report.embedding.threshold}</td>"
        f'<td class="status-{report.embedding.status}">{report.embedding.status}</td>'
        f"<td>{html.escape(report.embedding.detail)}</td></tr>"
        f"{judge_row}"
        "</tbody></table>"
        f"<h2>Length axis</h2>{length_svg}"
        f"<h2>Embedding cluster axis</h2>{cluster_svg}"
        f"{judge_block}"
        "<h2>Most distant candidate inputs from any golden cluster centroid</h2>"
        "<table><thead><tr><th>Distance</th><th>Text</th></tr></thead><tbody>"
        f"{examples_rows or empty_examples_row}"
        "</tbody></table>"
        '<p style="color:#888;font-size:11px;margin-top:18px">'
        "Drift score is Jensen-Shannon divergence (base-2, bounded in [0, 1]) between "
        "golden and candidate histograms on each axis (D-014). Drift &gt; threshold is the "
        "operator's signal to look at the representative examples and decide whether to "
        "re-baseline or investigate.</p>"
        "</body></html>"
    )


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def _load_inputs_jsonl(path: Path) -> list[str]:
    """Read a JSONL of inputs. Each row is a bare string OR an object with input/prompt/text."""
    out: list[str] = []
    raw = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {e}") from e
        if isinstance(row, str):
            out.append(row)
        elif isinstance(row, dict):
            for key in ("input", "prompt", "text"):
                val = row.get(key)
                if isinstance(val, str):
                    out.append(val)
                    break
            else:
                raise ValueError(f"{path}:{lineno}: object row missing input/prompt/text: {row!r}")
        else:
            raise ValueError(f"{path}:{lineno}: row is not a string or object: {row!r}")
    if not out:
        raise ValueError(f"{path}: no inputs loaded")
    return out


def _judge_stub(text: str) -> float:
    """Deterministic hermetic-CI judge stub.

    Returns a score in [0, 1] driven by token-count modulo a fixed
    constant — not meaningful, but stable across runs so tests can
    assert exact drift numbers.
    """
    n = len(_tokens(text))
    return ((n * 7) % 100) / 100.0


def cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eval-harness drift",
        description="Detect distribution drift between a golden set and a production-input sample.",
    )
    parser.add_argument("--golden", required=True, help="Path to golden JSONL of inputs.")
    parser.add_argument("--candidate", required=True, help="Path to candidate JSONL of inputs.")
    parser.add_argument("--output", required=True, help="Output HTML report path.")
    parser.add_argument(
        "--judge-stub",
        action="store_true",
        help="Use the deterministic word-count judge stub (hermetic CI; smoke testing).",
    )
    parser.add_argument(
        "--cluster-k", type=int, default=8, help="K-means cluster count (default: 8)."
    )
    args = parser.parse_args(argv)

    # Honor the CLI's `0 = clean / 1 = findings / 2 = I/O or usage error` exit
    # contract that the read-side subcommands already uphold (#104/#110/#116).
    # `_load_inputs_jsonl` otherwise leaks FileNotFoundError (missing path),
    # OSError (present-but-unreadable input — e.g. a directory), and ValueError
    # (empty input / zero valid rows / malformed JSON, already wrapped from
    # json.JSONDecodeError) as raw exit-1 tracebacks (#122). Translate the
    # input-loading failures to a clean `::error::` line + exit 2 here, mirroring
    # `cli._run_diff_json`'s catch shape. The guard lives in `drift.cli` (not
    # `cli._run_drift`) so the contract holds on both the `eval-harness drift`
    # path and the direct `python -m eval_harness.drift` entrypoint.
    #
    # An unwritable `--output` (a directory, read-only path, unwritable parent)
    # is itself an I/O error and must honor the same exit-2 contract, not escape
    # as a raw OSError traceback at exit 1 (#104 write-seam sibling; mirrors
    # cli._write_output). The no-half-written-report guarantee is a property of
    # `atomic_write_text` itself (temp file + os.replace + cleanup) and holds
    # whether or not the caller catches the OSError — so catching it to return a
    # clean exit 2 does not weaken the atomicity invariant.
    try:
        golden = _load_inputs_jsonl(Path(args.golden))
        candidate = _load_inputs_jsonl(Path(args.candidate))
        judge_fn: Callable[[str], float] | None = _judge_stub if args.judge_stub else None
        report = compute_drift(
            golden,
            candidate,
            judge_score_fn=judge_fn,
            cluster_k=args.cluster_k,
        )
    except FileNotFoundError as e:
        print(f"::error::could not read drift input: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"::error::drift input I/O error: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 2
    try:
        atomic_write_text(args.output, render_html(report))
    except OSError as e:
        print(f"::error::failed to write {args.output}: {e}", file=sys.stderr)
        return 2
    summary = (
        f"wrote {args.output}: "
        f"length={report.length.drift_score:.3f} ({report.length.status}), "
        f"embedding={report.embedding.drift_score:.3f} ({report.embedding.status})"
    )
    if report.judge is not None:
        summary += f", judge={report.judge.drift_score:.3f} ({report.judge.status})"
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())


__all__ = [
    "AxisReport",
    "ClusterStats",
    "DEFAULT_EMBEDDING_THRESHOLD",
    "DEFAULT_JUDGE_THRESHOLD",
    "DEFAULT_LENGTH_THRESHOLD",
    "DriftReport",
    "JudgeStats",
    "LengthStats",
    "RepresentativeExample",
    "cli",
    "compute_drift",
    "hash_embed",
    "jensen_shannon",
    "percentile",
    "render_html",
]
