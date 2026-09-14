"""Value lock on the demo flow's drift numbers — the frame a recorded demo lands on.

Why this file exists (#241)
---------------------------

``scripts/capture_demo.py`` exists so "a screen recorder can re-capture the demo
over and over and land on identical frames", and the README's Demo section points
the reader at ``examples/drift_report.py``. Both publish numbers. Until this file,
**nothing read one of them.**

The two existing checks on this flow are containment locks:

- ``tests/test_examples_smoke.py::test_drift_report_runs_and_writes_html_file``
  asserts the *string* ``"embedding axis"`` appears in stdout, and that the HTML
  contains ``<svg`` and ``</html>``.
- ``tests/test_capture_demo_smoke.py`` asserts the same three axis *names* appear
  and that the artifact file exists.

Neither reads a value, so neither can see a value change. That is not a
hypothetical:

    commit 1185fe9 (#208, "make compute_drift a function of its input sets, not
    their order") moved BOTH of this repo's published drift surfaces at once.

    - README.md:464 went 0.156 -> 0.147. Its value lock
      (test_readme_defaults_snapshot.py pairing 7, added by #145) fired, and that
      is why #208 updated the line in the same commit.
    - The demo's embedding axis went 0.1722 -> 0.2454. Nothing fired. Both smoke
      tests above stayed green, and the demo's published number was wrong for the
      next 36 commits until #241 noticed by hand.

Same change, same code path, one surface pinned and one not. This file is the
missing half.

On the direction of that move
-----------------------------

0.2454 is correct and 0.1722 was not, and that is not an assumption that the newer
number wins. Before #208, ``_kmeans`` seeded from the caller's input order, so the
embedding axis was a function of list order rather than of the corpus. Measured on
this exact demo corpus at cf6cfe6 (the commit before the fix): **60 random shuffles
of the byte-identical corpus produce 19 distinct embedding scores**, and 0.1722 is
one draw that came up 3 times out of 60. At #208 and after, all 60 shuffles produce
0.2454. The value was also checked against a base-2 Jensen-Shannon divergence
computed from first principles over the cluster histograms -- golden (4, 1, 1, 2),
candidate (1, 4, 0, 3) -- which agrees with the library to 1e-15.

``test_demo_axes_are_a_function_of_the_corpus_not_its_order`` below is what makes
the literals in ``EXPECTED_*`` a pin on the input *set* instead of a pin on one
arbitrary draw. Without that arm, the literals would be a snapshot of a coin flip.

Everything here derives from actually running ``examples.drift_report.main()`` and
reading what it prints and what it writes. Nothing re-specifies the corpus or
``cluster_k``, so editing either of those in the example also trips this lock --
which is the intended behavior, because editing them invalidates any recording.
"""

from __future__ import annotations

import importlib
import io
import random
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

REGEN_HINT = (
    "The demo's published numbers changed. This is not a test to silence: any "
    "committed GIF/video of the demo (#20) now shows numbers the code no longer "
    "produces. Confirm the new value is correct (not merely newer -- see this "
    "module's docstring for how 0.1722 looked correct for 36 commits), update the "
    "literals below, and re-record the demo."
)

# The stdout frame: `examples/drift_report.py` prints each axis at `:.3f`.
EXPECTED_STDOUT_AXES = {
    "length": (0.569, "drifted"),
    "embedding": (0.245, "drifted"),
    "judge": (0.570, "drifted"),
}

# The HTML frame: `render_drift_html` prints the same axes at `:.4f` in its
# summary table. Pinned separately from stdout on purpose -- these are two
# different renderings at two different precisions, and #240 was a defect that
# lived in the HTML renderer alone while stdout was fine.
EXPECTED_HTML_AXES = {
    "length": "0.5690",
    "embedding": "0.2454",
    "judge": "0.5701",
}

# The "most distant candidate inputs" table, in rendered order. #241 observed that
# this table had drifted in row *order* as well as in distance, so order is pinned:
# it is the reading order of the frame a viewer actually looks at.
EXPECTED_REPRESENTATIVE_ROWS = [
    (
        "0.895",
        "Describe a long, slow-braised short-rib recipe with red wine and aromatics in detail.",
    ),
    ("0.822", "Walk me through making a roux for a classic gumbo, including ratios and timing."),
    ("0.754", "Explain how the Maillard reaction differs from caramelization in pan-seared steak."),
    (
        "0.749",
        "Compare wet versus dry brining for a Thanksgiving turkey across moisture and skin texture.",
    ),
    ("0.697", "What is a 12-step French croissant lamination schedule with chilling intervals?"),
]


def _run_demo() -> tuple[str, str]:
    """Run the demo example exactly as the README tells a reader to, return (stdout, html).

    Calls ``main()`` rather than re-calling ``compute_drift`` with hand-copied
    arguments. That matters: ``cluster_k=4`` is a literal inside ``main()``, not a
    module constant, so a test that passed its own ``cluster_k`` would keep passing
    after someone changed the example's -- pinning a number the demo no longer
    produces, which is this file's whole subject.
    """
    module = importlib.import_module("examples.drift_report")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = module.main()
    assert rc == 0, f"examples/drift_report.py exited {rc}; stdout:\n{buf.getvalue()}"
    out = buf.getvalue()
    match = re.search(r"HTML report written to: (.+\.html)", out)
    assert match, f"expected an HTML report path in the example's stdout; got:\n{out}"
    return out, Path(match.group(1).strip()).read_text(encoding="utf-8")


def _stdout_axes(out: str) -> dict[str, tuple[float, str]]:
    found = {}
    for axis in ("length", "embedding", "judge"):
        match = re.search(rf"{axis} axis\s+JSD=([\d.]+)\s+status=(\w+)", out)
        assert match, f"expected a '{axis} axis' JSD line in the example stdout; got:\n{out}"
        found[axis] = (float(match.group(1)), match.group(2))
    return found


def test_demo_stdout_axes_match_published_values() -> None:
    """The three JSD scores the demo prints are the published ones."""
    out, _ = _run_demo()
    assert _stdout_axes(out) == EXPECTED_STDOUT_AXES, (
        f"demo stdout axes changed.\n  expected: {EXPECTED_STDOUT_AXES}\n"
        f"  actual:   {_stdout_axes(out)}\n{REGEN_HINT}"
    )


def test_demo_html_axis_table_matches_published_values() -> None:
    """The HTML report's summary table carries the same numbers at `:.4f`.

    Separate from the stdout arm because they are separate renderings: a defect
    confined to `render_drift_html` (as #240 was) leaves stdout correct.
    """
    _, html = _run_demo()
    for axis, expected in EXPECTED_HTML_AXES.items():
        match = re.search(rf"<td>{axis}</td><td>([\d.]+)</td>", html)
        assert match, f"expected a '{axis}' row in the HTML summary table"
        assert match.group(1) == expected, (
            f"HTML {axis} axis is {match.group(1)}, expected {expected}.\n{REGEN_HINT}"
        )


def test_demo_representative_examples_match_published_rows_and_order() -> None:
    """The most-distant-inputs table matches, row for row, in order."""
    _, html = _run_demo()
    rows = re.findall(r"<tr><td>(\d\.\d+)</td><td>([^<]+)</td></tr>", html)
    assert rows == EXPECTED_REPRESENTATIVE_ROWS, (
        f"representative-examples table changed.\n  expected: {EXPECTED_REPRESENTATIVE_ROWS}\n"
        f"  actual:   {rows}\n{REGEN_HINT}"
    )


def test_demo_axes_are_a_function_of_the_corpus_not_its_order() -> None:
    """Shuffling the demo corpus must not move any axis.

    This is the arm that makes the literals above meaningful. Before #208 this
    corpus produced 19 distinct embedding scores across 60 shuffles, so pinning a
    literal would have pinned whichever draw the author happened to observe. Runs
    the example itself with its module-level corpora permuted, so it exercises the
    same `cluster_k` and the same code path as the pinned arms.
    """
    module = importlib.import_module("examples.drift_report")
    baseline, _ = _run_demo()
    expected = _stdout_axes(baseline)

    rng = random.Random(20260914)
    original_golden = list(module.GOLDEN_INPUTS)
    original_candidate = list(module.CANDIDATE_INPUTS)
    try:
        for trial in range(25):
            golden = original_golden[:]
            candidate = original_candidate[:]
            rng.shuffle(golden)
            rng.shuffle(candidate)
            module.GOLDEN_INPUTS = golden
            module.CANDIDATE_INPUTS = candidate
            out, _ = _run_demo()
            assert _stdout_axes(out) == expected, (
                f"shuffle trial {trial} moved an axis: {_stdout_axes(out)} != {expected}. "
                "compute_drift must be a function of the input sets, not their order "
                "(#208). A regression here also invalidates every literal in this file."
            )
    finally:
        module.GOLDEN_INPUTS = original_golden
        module.CANDIDATE_INPUTS = original_candidate


@pytest.mark.parametrize(
    ("axis", "replacement", "why"),
    [
        (
            "length",
            lambda s: s[:20],
            "79 -> 20 chars moves this input from bucket [64,128) to [0,32), where the "
            "golden set has 2 of its 8 inputs",
        ),
        (
            "judge",
            lambda s: s[:40],
            "79 -> 40 chars moves the stub score 0.605 -> 0.80, from judge bucket 6 to "
            "bucket 8, where the golden set has 7 of its 8 inputs",
        ),
        (
            "embedding",
            lambda s: "What is the capital of Peru?",
            "swapping cooking vocabulary for the golden set's geography vocabulary "
            "re-assigns this input to a populated golden cluster",
        ),
    ],
)
def test_perturbing_one_input_moves_the_axis_it_should(axis, replacement, why) -> None:
    """Anti-vacuity: each pinned axis is reachable, and reachable *independently*.

    A value lock that cannot go red is decoration, and a parametrized lock whose
    cases all exercise the same thing is one case wearing three hats. Each case
    below perturbs exactly one candidate input and asserts the *named* axis leaves
    its pinned value.

    Choosing these is less obvious than it looks, and the trap is worth writing
    down because the first two cases I wrote fell into it. Jensen-Shannon over a
    histogram is **invariant to how candidate mass is redistributed among buckets
    the golden set never occupies**: for any bucket with ``P_i == 0`` the summed
    contribution to ``H(M) - H(Q)/2`` is exactly ``Q_i / 2``, independent of how
    that mass splits across such buckets. The golden length histogram here is
    ``(2, 6, 0, 0, 0, 0, 0, 0, 0)``, so appending 400 characters to a candidate
    input moves it from bucket 2 to bucket 4 -- a visibly different histogram,
    ``(1, 1, 6, ...)`` -> ``(1, 1, 5, 0, 1, ...)`` -- and leaves the length JSD
    **bit-identical** at 0.5689626904850149. That is correct behaviour, not a
    defect, but a perturbation probe built on it proves nothing while looking
    thorough.

    So every case here moves mass *into* a bucket the golden set actually
    occupies, and ``why`` records which one and on what evidence.
    """
    module = importlib.import_module("examples.drift_report")
    original = list(module.CANDIDATE_INPUTS)
    try:
        perturbed = original[:]
        perturbed[1] = replacement(perturbed[1])
        module.CANDIDATE_INPUTS = perturbed
        out, _ = _run_demo()
        assert _stdout_axes(out)[axis][0] != EXPECTED_STDOUT_AXES[axis][0], (
            f"perturbing one candidate input ({why}) left the {axis} axis at its "
            f"pinned value {EXPECTED_STDOUT_AXES[axis][0]}. Either the axis no longer "
            "responds to its own input, or this lock is vacuous."
        )
    finally:
        module.CANDIDATE_INPUTS = original
