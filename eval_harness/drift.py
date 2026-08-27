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

from eval_harness.io_utils import atomic_write_text, find_unencodable
from eval_harness.judge import clamp_judge_score

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
    #: ``(golden, candidate)`` counts of inputs with no embeddable content, i.e.
    #: the ones `has_embeddable_content` rejects. They take part in the length
    #: axis (their char count is truthful) and in the judge axis (a judge can
    #: legitimately score them), and are excluded from everything cosine-derived
    #: -- the cluster histograms and `representative_examples` -- because the
    #: zero vector has no angle to any centroid (D-017, #210).
    #:
    #: Reported rather than silently dropped: "4,120 of 10,000 candidate inputs
    #: had no comparable content" is itself a drift finding, and often a more
    #: actionable one than the JSD on the axis it was corrupting.
    n_uncomparable: tuple[int, int]


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

    Value-domain contract (#202): "non-negative weight vector" was stated
    here in prose and enforced only for *length*. Both unenforced halves
    failed silently, and this function is the primitive every ``AxisReport``
    verdict is computed from:

    - A ``NaN`` entry made ``sum()`` ``NaN``; ``nan <= 0.0`` is ``False``, so
      both empty-side branches fell through, and ``_kl``'s
      ``if ai > 0.0 and bi > 0.0`` is ``False`` for every ``NaN``, so the
      corrupt slots contributed *nothing*. The divergence was computed over
      the surviving slots and landed on ``0.0`` -- which is this function's
      encoding of "identical distributions", i.e. ``status="ok"`` on the
      axis. The same false-negative shape as #91 and #93, reached through
      the value domain rather than through an all-zero histogram.
    - A negative entry either produced a plausible in-range number
      (``[10, -5]`` normalizes to ``[2.0, -1.0]``; ``_kl`` skips the negative
      slot and returns ``0.347...``, which passes every bounds check) or, when
      the whole vector summed non-positive (``[-1, -1]``), tripped the
      ``sp <= 0.0`` *empty* branch and was reported as **maximal drift**.

    Reject both at the boundary, the same posture as ``cluster_k``, the three
    axis thresholds, and ``_clamp01`` (#96). No internal caller can reach
    either branch -- the three call sites pass non-negative ``int`` histograms
    -- but the name is exported in ``__all__``.
    """
    if len(p) != len(q):
        raise ValueError(f"distributions must have equal length; got {len(p)} vs {len(q)}")
    if not p:
        return 0.0
    # Before the empty-side guards below: an all-negative vector sums to a
    # non-positive number and would otherwise be laundered into the "empty
    # support" branch and reported as maximal drift (1.0) rather than rejected.
    for _label, _vec in (("p", p), ("q", q)):
        for _i, _x in enumerate(_vec):
            if not math.isfinite(_x):
                raise ValueError(
                    f"{_label} must contain only finite weights; got {_x!r} at index {_i}"
                )
            if _x < 0.0:
                raise ValueError(
                    f"{_label} must be a non-negative weight vector; got {_x!r} at index {_i}"
                )
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
    """NIST type-7 linear-interp percentile (matches the rag-kit pattern).

    A non-finite value (NaN / +/-Infinity) is rejected (#202). The parity this
    docstring claims is with ``rag_kit.telemetry.percentile``, which has
    guarded this since rag-production-kit#80 -- the claim was aspirational
    until this guard existed, since the two bodies were otherwise identical.

    Unguarded, ``sorted()`` leaves a ``NaN`` in an implementation-defined slot
    (every ``NaN`` comparison is ``False``), so the result is silently wrong
    *and position-dependent*: the multiset ``{1.0, 3.0, 4.0, NaN}`` returned
    ``2.0``, ``3.5`` or ``nan`` at ``q=0.5`` depending only on where the
    ``NaN`` sat in the caller's list.

    No internal caller can reach this -- ``_length_stats`` passes
    ``float(len(s))``, always finite -- but the name is exported in
    ``__all__``, which is the same reason rag-kit guards its own copy. Fail
    loud at the metric boundary, matching the ``q``-range guard below.
    """
    if not values:
        return 0.0
    if any(not math.isfinite(v) for v in values):
        raise ValueError(f"values must all be finite numbers; got {list(values)!r}")
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


def has_embeddable_content(text: str) -> bool:
    """True when ``hash_embed(text)`` is a real unit vector, not the zero vector.

    ``hash_embed`` sums one signed unit contribution per token, so a string with
    no tokens -- ``""``, ``"!!!"``, ``"\U0001f389\U0001f389"``, ``"   \n\t "``
    -- produces the all-zero vector. That vector is not a point on the unit
    sphere at some particular angle from a centroid; it is the *absence* of a
    point, and every cosine-derived quantity for it is **undefined**, not zero
    (D-017).

    Deliberately defined as ``bool(_tokens(text))`` rather than by re-deriving
    the rule, so it cannot drift out of lockstep with the embedder it describes.
    ``tests/test_drift_uncomparable_inputs.py`` pins the parity directly against
    ``hash_embed``.
    """
    return bool(_tokens(text))


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
    """Tiny k-means on L2-normalized vectors. Stride-init over a canonical order.

    The init used to be a stride over ``vectors`` *as supplied*, and the
    docstring called that "stride-init for determinism". It is deterministic
    only for a fixed input order, which is not a property this module's callers
    have: ``_load_inputs_jsonl`` returns file order, and reordering lines in a
    JSONL corpus changes nothing about the corpus (#207).

    Measured before this change — one golden set of 6 billing + 6 shipping
    utterances against one fixed candidate set, ``cluster_k=4``, over 40 random
    shuffles of the golden list alone::

        0.008788 ok  x1     0.112800 drifted x10
        0.016265 ok  x1     0.116423 drifted x5
        0.095437 ok  x4     0.118704 drifted x1
        0.098026 ok  x6     0.129976 drifted x5
                            0.134137 drifted x6
                            0.141412 drifted x1

    Ten distinct scores across a 16x range and *both* statuses — 17/40 shuffles
    said ``ok`` and 23/40 said ``drifted``, for byte-identical corpora. That is
    the gate a drift detector exists to provide.

    The fix is to canonicalize the processing order *inside* the function rather
    than to patch the init alone. Three separate things here read the input
    order, and a partial fix leaves the others:

    1. the stride init selects ``vectors[i * step]`` by position;
    2. the assignment scan breaks a cosine tie by taking the first centroid it
       encounters at that similarity;
    3. the centroid update accumulates with ``+=``, and float addition is not
       associative, so a permuted sum differs in the last bits.

    (3) is why "just sort the seeds" is not enough: a last-bit difference in a
    centroid propagates through the next assignment round and can flip an input
    across a cluster boundary, which is a whole-bucket change in the histogram
    the JSD is computed over.

    Sorting by the vector's own components is arbitrary-but-fixed, which is
    exactly the property needed — it is *content*, not position. Vectors that
    compare equal are interchangeable for every step below (same seed value,
    same assignment, same contribution to a sum), so the stable sort's fallback
    to original index among them is not a residual position dependence.

    ``assigns`` is mapped back to the caller's indices before returning, so the
    published contract — one cluster id per input, positionally aligned with
    ``vectors`` — is unchanged.

    What this does *not* do: improve the seeding. A stride over a
    component-sorted list is still weak k-means initialization. Determinism is
    the defect being fixed; seeding quality is a separate question that would
    move already-published numbers.
    """
    n = len(vectors)
    if n == 0 or k <= 0:
        return [], []
    k = min(k, n)
    # Canonical processing order: by the vector's own components. Everything
    # below runs over `ordered`, never over `vectors`.
    order = sorted(range(n), key=lambda i: tuple(vectors[i]))
    ordered = [vectors[i] for i in order]
    step = max(n // k, 1)
    centroids = [list(ordered[i * step]) for i in range(k)]
    dim = len(centroids[0]) if centroids and centroids[0] else 0
    assigns = [0] * n
    for _ in range(max_iter):
        changed = False
        for i, v in enumerate(ordered):
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
        for i, v in enumerate(ordered):
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
    # Map back to the caller's indexing: `assigns[i]` is the cluster of
    # `ordered[i]`, i.e. of `vectors[order[i]]`.
    caller_assigns = [0] * n
    for pos, orig_i in enumerate(order):
        caller_assigns[orig_i] = assigns[pos]
    return centroids, caller_assigns


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

    Inputs with no embeddable content (``has_embeddable_content`` is
    ``False``) take part in the length and judge axes but not in
    anything cosine-derived; they are counted in ``n_uncomparable`` and
    excluded from the cluster histograms and from
    ``representative_examples`` (D-017, #210). A golden set in which
    *nothing* is comparable is rejected outright, because such a
    baseline can only report a fabricated ``"ok"``.

    An input with **no UTF-8 encoding** -- in practice a lone surrogate --
    is rejected on *both* sides (#215, D-018), because the HTML report
    cannot be written at all if one reaches it. That is deliberately not
    D-017's split: a token-less input is representable and merely
    unembeddable, whereas this one cannot be written down.
    """
    if not golden_inputs:
        raise ValueError("golden_inputs must be non-empty")
    if not candidate_inputs:
        raise ValueError("candidate_inputs must be non-empty")

    # --- representability (#215) ----------------------------------------
    # Every string that reaches the report has to survive a UTF-8 encode, and a
    # lone surrogate does not. `"\ud800"` is legal JSON escape syntax, so
    # `_load_inputs_jsonl` reads it without complaint from a file whose bytes are
    # themselves valid UTF-8 -- and it then killed the run at the very last step,
    # inside `atomic_write_text`, with a raw `UnicodeEncodeError` traceback at
    # exit 1. Exit 1 is this CLI's code for *findings*, so a gate that treats 1 as
    # "drift detected" and 2 as "infrastructure error" was told there was drift
    # when no report had been produced at all.
    #
    # Checked here rather than in `_load_inputs_jsonl` because there are two roads
    # into `render_html` and only one of them has a loader. The other is the
    # library snippet the README ships:
    #
    #     report = compute_drift(golden_inputs=[...], candidate_inputs=[...])
    #     Path("drift.html").write_text(render_drift_html(report))
    #
    # `compute_drift` is the one function both roads pass through, and it is
    # already this module's input-contract choke point (emptiness, the three
    # thresholds, `cluster_k`, `n_representative_examples`, golden
    # comparability). A `ValueError` from here lands in `drift.cli`'s existing
    # `except ValueError`, so the exit-2 contract holds with no new catch --
    # which the old `except OSError` around the write could never have given,
    # since `UnicodeEncodeError` subclasses `ValueError`, not `OSError`.
    #
    # Measured before this check, with the surrogate on a *candidate* row and
    # everything else identical, the outcome was decided by data position rather
    # than by the data being bad -- `render_html` puts raw input text in exactly
    # one place, `html.escape(r.text)[:200]` over `representative_examples`:
    #
    #   surrogate on a highly-distant candidate row   -> UnicodeEncodeError, exit 1
    #   surrogate on a near-duplicate of a golden row -> ranked out of the top-N,
    #                                                    report written, row absent
    #   surrogate at char 240 of a distant row        -> `[:200]` drops it, report
    #                                                    written
    #   surrogate in the golden set only              -> golden text is never
    #                                                    rendered, report written
    #
    # Both sides reject, and that is deliberately *not* D-017's split (D-018).
    # D-017 lets token-less candidate rows through because a single emoji must
    # not abort a 10k-line traffic slice -- but a token-less row is representable
    # and merely unembeddable, whereas this one cannot be written down at all.
    # Dropping it instead would deflate `n_candidate` and both histograms with no
    # diagnostic, which is the same false-negative class as #91 and #93.
    for _side, _inputs in (
        ("golden_inputs", golden_inputs),
        ("candidate_inputs", candidate_inputs),
    ):
        for _i, _text in enumerate(_inputs):
            _bad = find_unencodable(_text)
            if _bad is not None:
                _chars, _pos = _bad
                raise ValueError(
                    f"{_side}[{_i}] is not encodable as UTF-8 ({_chars!r} at position "
                    f"{_pos}); a lone surrogate is legal JSON escape syntax but has no "
                    f"UTF-8 encoding, so the HTML report cannot be written. Same rule "
                    f"`load_jsonl` enforces on a golden dataset (#213)"
                )

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

    # --- Comparability partition (D-017, #210) --------------------------
    # `hash_embed` returns the all-zero vector for an input with no tokens, and
    # `_cosine` of the zero vector with anything is exactly 0.0. Nothing here
    # treated that as "undefined"; it flowed through as a genuine cosine of 0.0,
    # i.e. as the *maximum* distance 1.0 and as a real tie at the top of
    # `_assign`'s scan. Both sides of the comparison were corrupted:
    #
    #   representative_examples, golden = 6 billing + 6 shipping, cluster_k=4,
    #   candidates = 4 real + 6 token-less, n_representative_examples=5:
    #       ['', ' \n\t ', '!!!', '---', '???']   <- 0 of the 4 real inputs
    #
    #   embedding JSD, same golden set:
    #       4 real candidates              0.1909   histogram (1, 3, 0, 0)
    #       the same 4 + 6 token-less      0.3122   histogram (7, 3, 0, 0)
    #
    # Cluster 0 goes 1 -> 7 because `_assign` starts at `best_sim = -2.0` and
    # every centroid ties at 0.0, so the first one always wins. Six inputs with
    # no content moved a published drift score by 0.12.
    #
    # The remedy is split by side, because the two sides have different
    # economics. A golden set is *authored* -- small, reviewed, fixable -- so a
    # golden set with nothing to embed is a broken baseline and fails loud. A
    # candidate set is a *sampled traffic slice* -- large, unreviewed -- so a
    # single emoji must not abort a 10k-line drift run; those are counted in
    # `n_uncomparable` and excluded from the cosine-derived outputs.
    g_comparable = [has_embeddable_content(s) for s in golden_inputs]
    c_comparable = [has_embeddable_content(s) for s in candidate_inputs]

    # Not a cosmetic guard. Measured before this check, `compute_drift(['!!!',
    # '???'], [4 real inputs], cluster_k=2)` was ACCEPTED and reported
    # `embedding drift_score=0.000, status="ok"`: every centroid is the zero
    # vector, every candidate assigns to cluster 0, and the two histograms come
    # out identical, which is this module's encoding of "no drift". A maximal
    # false negative on the gate, from a baseline that can measure nothing --
    # the same shape as #91 (one-empty JSD) and #93 (length-histogram open
    # bucket), reached through the embedder instead.
    if not any(g_comparable):
        raise ValueError(
            f"golden_inputs must contain at least one input with embeddable content "
            f"(alphanumeric tokens); all {len(golden_inputs)} are token-less, so every "
            f"hash_embed vector is the zero vector and the embedding axis can only "
            f"report a fabricated 'ok'"
        )

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
    # Seed k-means from comparable golden vectors only. A zero vector is not a
    # seed -- it drags a centroid toward the origin, and a centroid that stays
    # at the origin then ties with every input at cosine 0.0. Measured: one
    # `'!!!'` row added to the 12-utterance golden set above moved the golden
    # histogram to (6, 5, 0, 2) and the embedding JSD from 0.1909 to 0.1432,
    # for a row carrying no information.
    g_seed_vecs = [v for v, ok in zip(g_vecs, g_comparable, strict=True) if ok]
    centroids, _ = _kmeans(g_seed_vecs, cluster_k)
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

        # Comparable inputs only, on both sides. An uncomparable input is not
        # in cluster 0; it is in no cluster. `sum(cluster_counts)` therefore
        # equals the number of *clustered* inputs, which is what `ClusterStats.n`
        # is set to below -- the invariant `sum(counts) == n` is preserved, and
        # `n_golden - n` (resp. `n_candidate`) is the uncomparable count.
        g_clusters = [_assign(v) for v, ok in zip(g_vecs, g_comparable, strict=True) if ok]
        c_clusters = [_assign(v) for v, ok in zip(c_vecs, c_comparable, strict=True) if ok]
        k_eff = len(centroids)
        g_cluster_counts = tuple(sum(1 for x in g_clusters if x == i) for i in range(k_eff))
        c_cluster_counts = tuple(sum(1 for x in c_clusters if x == i) for i in range(k_eff))
        # A candidate sample in which *nothing* is comparable leaves the
        # candidate side at zero mass against a populated golden side, which
        # `jensen_shannon` reports as 1.0 -- maximal drift -- per its documented
        # one-empty contract (#91). That is the right answer, and it is loud:
        # 100% content-free traffic is the most drifted a sample can be.
        emb_drift = jensen_shannon(g_cluster_counts, c_cluster_counts)
    else:  # pragma: no cover - degenerate empty-vector case caught above
        g_cluster_counts = ()
        c_cluster_counts = ()
        emb_drift = 0.0
    n_uncomparable = (g_comparable.count(False), c_comparable.count(False))
    uncomparable_note = (
        ""
        if n_uncomparable == (0, 0)
        else (
            f"; {n_uncomparable[0]}/{len(golden_inputs)} golden and "
            f"{n_uncomparable[1]}/{len(candidate_inputs)} candidate inputs had no "
            f"embeddable content and are excluded from this axis"
        )
    )
    embedding_report = AxisReport(
        name="embedding",
        drift_score=emb_drift,
        status="drifted" if emb_drift > embedding_threshold else "ok",
        threshold=embedding_threshold,
        detail=(
            f"JSD over k={len(centroids)} cluster-id histogram from "
            f"{embedding_dim}-dim hash-embedded inputs{uncomparable_note}"
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
        for v, text, ok in zip(c_vecs, candidate_inputs, c_comparable, strict=True):
            # Skip uncomparable candidates. This list is documented as "the
            # inputs that look least like anything in the golden set", and a
            # content-free input does not look unlike the golden set -- it has
            # nothing to look like anything with. It scored 1.0 (the ceiling)
            # and, because the list is *truncated*, it did not merely rank
            # wrongly, it evicted the inputs the operator needs to see: 5 of 5
            # slots went to punctuation in the measurement above (#210). Same
            # class as the extreme-default findings in
            # embedding-model-shootout#123 and chunking-strategies-lab#160 -- a
            # value standing in for "not measurable" that sits at an end of the
            # scale, so it does not abstain, it ranks. The count survives in
            # `n_uncomparable`.
            if not ok:
                continue
            nearest_sim = max(_cosine(v, c) for c in centroids)
            examples.append(
                RepresentativeExample(
                    text=text, distance_to_nearest_golden_cluster=1.0 - nearest_sim
                )
            )
        # Sort on (distance desc, text asc). The distance key alone left ties
        # to Python's stable sort, i.e. to the order the inputs happened to sit
        # in the file -- and because the list is then *truncated*, position
        # decided not merely the ordering but which examples appeared at all.
        # Same shape as `list_runs` + `--limit` (#206), one module over.
        #
        # Ties are the ordinary case here, not a corner. `hash_embed` sums
        # per-token vectors, so it is a bag of tokens: duplicate inputs embed
        # identically, and so do token permutations of each other. Duplicates
        # are the norm in the production traffic sample this module ingests.
        # Measured on 6 tied candidates contesting 5 slots, 60 shuffles gave
        # six different five-element sets (#207).
        #
        # The tiebreak is on the text -- content, not position -- so any two
        # callers holding the same candidate *set* agree. `reverse=True` cannot
        # express "descending, then ascending", so negate the distance instead
        # of reversing; this is why the key is written as a tuple rather than
        # passed with `reverse`.
        examples.sort(key=lambda r: (-r.distance_to_nearest_golden_cluster, r.text))
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
            # `n` is the number of *clustered* inputs, not the input count, so
            # `sum(cluster_counts) == n` holds. It was `len(golden_inputs)`
            # while every input was assigned a cluster; excluding uncomparable
            # inputs without moving `n` would have made the two disagree
            # silently, which is the shape of defect this change exists to fix.
            ClusterStats(n=sum(g_cluster_counts), cluster_counts=g_cluster_counts),
            ClusterStats(n=sum(c_cluster_counts), cluster_counts=c_cluster_counts),
        ),
        judge_stats=judge_stats,
        representative_examples=tuple(examples),
        cluster_k=len(centroids),
        n_uncomparable=n_uncomparable,
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

    The rules now live in ``judge.clamp_judge_score`` and this delegates to
    them. They were stated here and hand-rolled a *second* time in
    ``judge.parse_judge_output``, which kept the clamp and dropped the
    finiteness half — so the seam closest to the actual model output was the
    one place ±Inf still silently became 1.0/0.0 (#192). One implementation,
    two call sites; the behavior and error message here are unchanged.
    """
    return clamp_judge_score(x)


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
    # Surfaced in the document, not merely available on the dataclass. "4,120 of
    # 10,000 candidate inputs had no comparable content" is itself a drift
    # finding, and the operator reading this report is the person who can act on
    # it. Rendered only when non-zero so the ordinary report is unchanged
    # (D-017, #210).
    g_uncomparable, c_uncomparable = report.n_uncomparable
    uncomparable_block = (
        ""
        if (g_uncomparable, c_uncomparable) == (0, 0)
        else (
            '<p style="color:#b04127;font-size:12px;margin-top:8px">'
            f"<strong>{g_uncomparable} of {report.n_golden}</strong> golden and "
            f"<strong>{c_uncomparable} of {report.n_candidate}</strong> candidate inputs "
            "have no embeddable content (no alphanumeric tokens). They are counted in the "
            "length and judge axes and excluded from the embedding cluster axis and from "
            "the representative-example list, because the zero embedding vector has no "
            "angle to any centroid.</p>"
        )
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
        f"{uncomparable_block}"
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
    "has_embeddable_content",
    "hash_embed",
    "jensen_shannon",
    "percentile",
    "render_html",
]
