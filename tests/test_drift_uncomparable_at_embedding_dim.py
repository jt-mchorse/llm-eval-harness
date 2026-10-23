"""`n_uncomparable` is decided at `embedding_dim`, and so is its documentation (#429).

#428 (for #426) made `has_embeddable_content(text, dim=64)` depend on the bucket
count, because two tokens cancel only when they hash to the same bucket with
opposite signs, and which tokens share a bucket depends on `dim`. `compute_drift`
partitions on the vectors it actually clusters, at `embedding_dim`. The two
docs that define the count still named the predicate with no `dim`, and
following them gives the wrong split in both directions. Measured on `main`
before this change::

    r = compute_drift(["refund please", "where is my parcel"],
                      ["w1 w96", "w0 w82"], embedding_dim=32)
    has_embeddable_content("w1 w96"), has_embeddable_content("w0 w82")  # (False, True)
    r.n_uncomparable, [e.text for e in r.representative_examples]      # ((0, 1), ['w1 w96'])

The input the documented predicate rejects is clustered and reported, and the
one it accepts is counted as uncomparable. The behaviour was right; the
contract was not. So the behavioural tests here are controls that pin the
partition at a non-default `dim`, and the doc tests are the ones that fail
against the old wording.
"""

from __future__ import annotations

import inspect
import re

import pytest

from eval_harness.drift import DriftReport, compute_drift, has_embeddable_content

GOLDEN = ["refund please", "where is my parcel", "cancel my order", "update billing address"]

# The issue's repro: at dim=32, "w1 w96" is comparable and "w0 w82" cancels;
# at the default dim=64 it is the other way round.
REPRO_CANDIDATES = ["w1 w96", "w0 w82"]

PRESCRIBED = "has_embeddable_content(text, dim=embedding_dim)"


def _disagreeing_pairs(dim: int) -> list[str]:
    """Two-token inputs whose comparability at `dim` differs from at 64.

    Searched rather than hand-listed so every parametrized `dim` gets inputs
    that actually separate the two predicates; a corpus on which they agree
    could not tell a dim-less partition from the right one.
    """
    found: list[str] = []
    want = {True: 0, False: 0}
    for i in range(200):
        for j in range(i + 1, 200):
            text = f"w{i} w{j}"
            at_dim = has_embeddable_content(text, dim=dim)
            if at_dim != has_embeddable_content(text) and want[at_dim] < 2:
                want[at_dim] += 1
                found.append(text)
            if all(n == 2 for n in want.values()):
                return found
    raise AssertionError(f"no disagreeing pairs found at dim={dim}")


# ----------------------------------------------------------------------
# Behaviour: controls (green before and after #429)
# ----------------------------------------------------------------------


def test_issue_repro_partitions_at_embedding_dim() -> None:
    assert (has_embeddable_content("w1 w96"), has_embeddable_content("w0 w82")) == (False, True)
    assert (
        has_embeddable_content("w1 w96", dim=32),
        has_embeddable_content("w0 w82", dim=32),
    ) == (True, False)

    report = compute_drift(GOLDEN, REPRO_CANDIDATES, embedding_dim=32, cluster_k=2)
    assert report.n_uncomparable == (0, 1)
    assert [e.text for e in report.representative_examples] == ["w1 w96"]


@pytest.mark.parametrize("dim", [16, 32, 128])
def test_n_uncomparable_counts_the_predicate_at_embedding_dim(dim: int) -> None:
    """`n_uncomparable` == count of `not has_embeddable_content(t, dim=embedding_dim)`."""
    golden = GOLDEN + _disagreeing_pairs(dim)[:1]
    candidates = ["where is my refund", "!!!", *_disagreeing_pairs(dim)]

    report = compute_drift(golden, candidates, embedding_dim=dim, cluster_k=2)

    expected = tuple(
        sum(not has_embeddable_content(t, dim=dim) for t in side) for side in (golden, candidates)
    )
    assert report.n_uncomparable == expected
    # Anti-vacuity: the dim-less predicate gives a different count on this
    # corpus, so the assertion above discriminates between the two.
    dimless = tuple(
        sum(not has_embeddable_content(t) for t in side) for side in (golden, candidates)
    )
    assert dimless != expected
    # And the example list is drawn from exactly the comparable side.
    assert all(has_embeddable_content(e.text, dim=dim) for e in report.representative_examples)


# ----------------------------------------------------------------------
# Documentation: red against the dim-less wording
# ----------------------------------------------------------------------


def _n_uncomparable_field_doc() -> str:
    """The `#:` comment block attached to `DriftReport.n_uncomparable`."""
    lines = inspect.getsource(DriftReport).splitlines()
    end = next(i for i, ln in enumerate(lines) if ln.strip().startswith("n_uncomparable:"))
    block: list[str] = []
    for ln in reversed(lines[:end]):
        if not ln.strip().startswith("#:"):
            break
        block.append(ln.strip()[2:].strip())
    assert block, "n_uncomparable has no #: field doc"
    return " ".join(reversed(block))


def _normalise(doc: str) -> str:
    return re.sub(r"\s+", " ", doc)


def test_n_uncomparable_field_doc_names_the_dim() -> None:
    assert PRESCRIBED in _normalise(_n_uncomparable_field_doc())


def test_compute_drift_docstring_names_the_dim() -> None:
    doc = _normalise(compute_drift.__doc__ or "")
    assert PRESCRIBED in doc
    # The old definition, with the predicate named and no dim, is gone.
    assert "(``has_embeddable_content`` is ``False``)" not in doc
