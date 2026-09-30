"""A configured parameter is echoed back as the value that was set (#257).

The third class in `eval_harness.comparison`'s family, and the one that is not a
comparison at all. D-026 fixed *a decided comparison* (two numbers, one ordering)
and D-028 fixed *a value beside its own classification* (one number, one verdict).
This is **one number and nothing else** — the policy input an operator typed,
echoed back at a fixed width::

    # runner.py, the ASCII/Markdown delta header
    f"(suite={report.suite}, threshold_drop={report.threshold_drop:.2f})"

    # comment.py, the sticky PR comment
    f"· threshold drop: `{report.threshold_drop:.3f}`"

`--threshold-drop` is `type=float` with no width constraint, so:

===============  ==========  ==========
configured       `.2f`       `.3f`
===============  ==========  ==========
0.05             0.05        0.050
0.025            0.03        0.025
0.0125           0.01        0.013
0.001            0.00        0.001
0.1234           0.12        0.123
===============  ==========  ==========

Two surfaces disagreeing about one number in the same CI run is the visible
half. The half that matters is the last-but-one row: `threshold_drop=0.00` reads
as *"any drop at all is a regression"* — the strictest setting the flag has —
for a run actually gated at `0.001`. A measurement has a near-threshold case; a
configured value does not. It is the number that was set, or it is wrong.

**The population is eight sites, not the two the issue named.** Six more reach
`render_comparison` as its *second* operand, and that loop stops as soon as the
two strings differ — which at three places publishes a configured `0.6004` as
`0.600`, a policy nobody set and one that predicts the wrong verdict for any
future κ in `[0.600, 0.6004)`. That half is invisible for as long as the
threshold is round, which every shipped default in this package is; it is the
`cli.py` lesson of D-026 recurring one level up, where "the side that happens to
carry the long expansion" is now "the side that happens to be a round number".

The arms below are deliberately *structural* where they can be. Asserting that a
rendering "looks right" for a hand-picked threshold is a coin flip; asserting
that `float(rendered) == configured` is the contract itself.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from eval_harness.calibration import CalibrationResult, CalibrationRow, render_report
from eval_harness.comment import render_delta_markdown
from eval_harness.comparison import (
    COMPARISON_MAX_PLACES,
    COMPARISON_PLACES,
    render_comparison,
    render_configured,
)
from eval_harness.judge import JudgeScore
from eval_harness.runner import DEFAULT_THRESHOLD_DROP, DeltaReport, RowDelta, render_delta_ascii

pytest_plugins = ["pytester"]

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = _ROOT / "eval_harness"

# Configured values spanning the region a fixed width handles and the region it
# does not. Every one is a legal `--threshold-drop`: `diff_runs` requires only
# "finite and >= 0". `0.1` is the shipped default and `0.0` its floor.
_CONFIGURED = [
    0.0,
    0.1,
    0.05,
    0.025,
    0.0125,
    0.001,
    0.1234,
    0.12345,
    1e-4,
    1e-5,
    1e-7,
    0.30000000000000004,  # 0.1 + 0.2, the shape an operator gets from arithmetic
    1.0,
]
_IDS = [repr(c) for c in _CONFIGURED]


def _report(threshold_drop: float) -> DeltaReport:
    return DeltaReport(
        current_run_id="cur_runid_abcdef0123",
        baseline_run_id="base_runid_0123abcdef",
        suite="demo-suite",
        threshold_drop=threshold_drop,
        rows=(
            RowDelta(
                example_id="q1",
                baseline_score=0.8,
                current_score=0.5,
                delta=-0.3,
                status="regressed",
                flagged=True,
            ),
        ),
        summary={
            "mean_delta": -0.3,
            "n_flagged": 1,
            "n_regressed": 1,
            "n_improved": 0,
            "n_unchanged": 0,
            "n_new": 0,
            "n_removed": 0,
        },
    )


def _header_value(ascii_report: str) -> str:
    """The `threshold_drop=...` token out of the ASCII header."""
    m = re.search(r"threshold_drop=([^)]+)\)", ascii_report)
    assert m is not None, f"no threshold_drop in header: {ascii_report.splitlines()[0]!r}"
    return m.group(1)


def _comment_value(markdown: str) -> str:
    """The `threshold drop: \\`...\\`` token out of the sticky PR comment."""
    m = re.search(r"threshold drop: `([^`]+)`", markdown)
    assert m is not None, "no threshold drop line in the sticky comment"
    return m.group(1)


def _places(rendered: str) -> int | None:
    """Decimal places in a fixed-point rendering; None for the `repr` fallback."""
    if "e" in rendered or "E" in rendered:
        return None
    _, _, frac = rendered.partition(".")
    return len(frac)


# --------------------------------------------------------------------------
# The helper
# --------------------------------------------------------------------------


@pytest.mark.parametrize("configured", _CONFIGURED, ids=_IDS)
def test_a_configured_value_reads_back_as_itself(configured: float) -> None:
    """The contract, stated as the contract rather than as a width.

    This is the whole of D-029 for the standalone form. Any rule phrased as a
    number of places is wrong for some legal `--threshold-drop`, which is why
    `.2f` and `.3f` were each wrong for a different part of this table.
    """
    assert float(render_configured(configured)) == configured


@pytest.mark.parametrize("configured", _CONFIGURED, ids=_IDS)
def test_the_helper_never_narrows_a_callers_column(configured: float) -> None:
    """`places` is a floor, not a target — the never-narrow half of D-026.

    A published column is an artifact. The first version of `render_comparison`
    hardcoded three places and silently republished `0.5690` as `0.569`, which
    `tests/test_demo_drift_published_values.py` caught. Same rule here, and it
    is why the answer is not `repr`: `repr(0.1)` is `'0.1'`, which would narrow
    the PR comment from the `0.100` it has always published.
    """
    rendered = render_configured(configured)
    width = _places(rendered)
    if width is None:  # the `repr` fallback; unreachable at these magnitudes
        return
    assert width >= COMPARISON_PLACES


def test_the_shipped_default_is_byte_identical_to_what_was_published_before() -> None:
    """`0.1` at three places is `0.100`, and `0.100` reads back as `0.1`.

    #257's fourth acceptance criterion asked for this to be *verified*, not
    assumed. It holds for the PR comment, which has always published three
    places. It deliberately does **not** hold for the ASCII header, which
    published two — see
    `test_the_ascii_header_widens_by_one_place_and_that_is_the_deliberate_half`.
    """
    assert DEFAULT_THRESHOLD_DROP == 0.1
    assert render_configured(DEFAULT_THRESHOLD_DROP) == "0.100"
    assert _comment_value(render_delta_markdown(_report(DEFAULT_THRESHOLD_DROP))) == "0.100"


def test_the_ascii_header_widens_by_one_place_and_that_is_the_deliberate_half() -> None:
    """`0.10` -> `0.100`, on purpose, and there is no third option.

    The two surfaces have to share a precision (#257's first criterion) and
    neither may narrow (D-026). Unifying at two places narrows the PR comment;
    unifying at three widens the header. Widening is the allowed direction, so
    the header moves. Nothing in `tests/`, `README.md` or `docs/` pinned the
    old literal — checked before the change, not after.
    """
    header = _header_value(render_delta_ascii(_report(DEFAULT_THRESHOLD_DROP)))
    assert header == "0.100"
    assert float(header) == DEFAULT_THRESHOLD_DROP


def test_values_too_small_for_any_fixed_width_fall_back_to_repr() -> None:
    """`--threshold-drop 1e-300` is finite and >= 0, so `diff_runs` accepts it.

    Seventeen places renders it as zeros, which reads back as `0.0` — the
    strictest possible gate, for the loosest possible configuration. `repr`
    round-trips a double by definition.
    """
    assert f"{1e-300:.{COMPARISON_MAX_PLACES}f}" == "0." + "0" * COMPARISON_MAX_PLACES
    assert float(render_configured(1e-300)) == 1e-300
    assert render_configured(1e-300) == "1e-300"


def test_zero_still_renders_as_a_fixed_point_zero() -> None:
    """`--threshold-drop 0` is the documented strictest setting and stays legible.

    `0.0` round-trips at the starting width, so the loop stops there and the
    `repr` fallback — which would print a bare `0.0` — is never reached.
    """
    assert render_configured(0.0) == "0.000"


def test_the_two_surfaces_agree_on_every_configured_value() -> None:
    """The structural arm, and the one that separates this fix from its neighbours.

    Asserting each surface renders "correctly" passes for a neighbour that
    widens one of them; asserting the two strings are **identical** does not.
    This is the same move that took `prompt-regression-suite`'s widen-one-side
    neighbour from green to 13 red: when the property is a *relationship*, an
    arm on either side alone cannot see it.
    """
    disagreements = []
    for configured in _CONFIGURED:
        report = _report(configured)
        header = _header_value(render_delta_ascii(report))
        comment = _comment_value(render_delta_markdown(report))
        if header != comment:
            disagreements.append((configured, header, comment))
    assert not disagreements, (
        f"the ASCII header and the sticky PR comment published different strings "
        f"for the same configured threshold_drop: {disagreements}"
    )


@pytest.mark.parametrize("configured", _CONFIGURED, ids=_IDS)
def test_neither_published_surface_rounds_the_configured_value(configured: float) -> None:
    """End to end through both renderers, not through the helper.

    An arm that calls `render_configured` directly is green against a revert of
    the *call sites* — the trap `llm-cost-optimizer` #227 fell into, where every
    arm called the helper and a call-site revert went 0 red. These two go
    through `render_delta_ascii` and `render_delta_markdown`.
    """
    report = _report(configured)
    assert float(_header_value(render_delta_ascii(report))) == configured
    assert float(_comment_value(render_delta_markdown(report))) == configured


def test_the_collapse_to_an_extreme_is_what_this_is_for() -> None:
    """The row from #257's table that is not merely inconsistent but backwards.

    At `.2f` a run gated at `0.001` published `threshold_drop=0.00`: a reader
    who trusts the header believes *any* drop is flagged. It is the loosest
    legal setting rendered as the strictest one.
    """
    assert f"{0.001:.2f}" == "0.00"
    assert _header_value(render_delta_ascii(_report(0.001))) == "0.001"


# --------------------------------------------------------------------------
# The same class inside `render_comparison`
# --------------------------------------------------------------------------

# (measured, configured) pairs. The configured side carries the long expansion
# in most of them, because that is exactly the orientation `render_comparison`
# could not see: it stops the instant the two strings differ, and a measured
# score at three places differs from almost anything.
_PAIRS = [
    (0.9, 0.6004),
    (0.5, 0.0001),
    (0.9, 0.12345),
    (0.5, 0.6004),
    (0.5996, 0.6),
    (0.6004, 0.6004),
    (0.25, 0.3000000000000001),
    (-0.5, -0.6004),
]
_PAIR_IDS = [f"{v!r}-vs-{o!r}" for v, o in _PAIRS]


@pytest.mark.parametrize(("measured", "configured"), _PAIRS, ids=_PAIR_IDS)
def test_the_configured_operand_reads_back_as_itself(measured: float, configured: float) -> None:
    """`exact_other` is the same contract, applied to the threshold side of a pair."""
    _, rendered_other = render_comparison(measured, configured, exact_other=True)
    assert float(rendered_other) == configured


@pytest.mark.parametrize(("measured", "configured"), _PAIRS, ids=_PAIR_IDS)
def test_exact_other_still_renders_both_sides_at_one_precision(
    measured: float, configured: float
) -> None:
    """D-026's invariant survives D-029, and this is the arm that says so.

    The obvious wrong way to make a configured threshold exact is to widen *it*
    and leave the measurement where it was. That is `cli.py`'s pre-#252 shape —
    `Cohen's κ 0.600 < threshold 0.6004` states an ordering that is false as
    written. Both sides move together or neither does.
    """
    rendered_value, rendered_other = render_comparison(measured, configured, exact_other=True)
    assert _places(rendered_value) == _places(rendered_other)


def test_exact_other_is_off_by_default_so_d_026s_callers_are_unchanged() -> None:
    """A measurement is not a policy, and there is no `exact_value`.

    The asymmetry is the finding. `value` is the measured side at all six call
    sites; rendering a measurement at three places is a summary a reader
    expects, not a misstatement of anything an operator set.
    """
    assert render_comparison(0.9, 0.6004) == ("0.900", "0.600")
    assert render_comparison(0.9, 0.6004, exact_other=True) == ("0.9000", "0.6004")


def test_an_equal_pair_still_widens_for_a_configured_operand() -> None:
    """The one place `exact_other` overrides a documented D-026 behaviour.

    D-026 returns an equal pair unwidened because "there is nothing to
    distinguish". True of the ordering, false of the policy: publishing a
    configured `0.6004` as `0.600` is a wrong claim about the configuration
    whether or not the measurement happens to equal it.
    """
    assert render_comparison(0.6004, 0.6004) == ("0.600", "0.600")
    assert render_comparison(0.6004, 0.6004, exact_other=True) == ("0.6004", "0.6004")


def test_a_round_threshold_is_unchanged_which_is_why_this_was_invisible() -> None:
    """Every shipped default in this package round-trips at its published width.

    `DEFAULT_THRESHOLD_DROP = 0.1`, the three drift thresholds, and
    `--threshold-kappa 0.6` are all round. That is precisely why six call sites
    carried this for as long as they did: the defect needs an operator who
    configured something, and the test suite never did.
    """
    for configured in (0.1, 0.10, 0.15, 0.2, 0.6):
        assert render_comparison(0.9, configured) == render_comparison(
            0.9, configured, exact_other=True
        )


# A κ *far* from the threshold is the orientation this class needs, and getting
# it wrong is how the first draft of the arms below went green against a call-site
# revert. The pairwise loop stops the instant the two strings differ: at a
# NEAR-threshold κ (D-026's shape) it widens on its own and the configured side
# comes out exact by accident. The configured value is only truncated when the
# measurement is nowhere near it — which is the ordinary case, not the corner one.
_FAR_KAPPA = 0.9
_FINE_KAPPA_THRESHOLD = 0.6004


def _calibration_result(kappa: float) -> CalibrationResult:
    return CalibrationResult(
        n=1,
        cohens_kappa=kappa,
        pearson_r=0.9,
        judge_scores=[JudgeScore(score=0.6, reasoning="r", raw="SCORE: 0.6")],
        rows=[
            CalibrationRow(
                id="c1", prompt="p", response="r", rubric="rub", human_score=0.6, provenance={}
            )
        ],
    )


def test_a_near_threshold_kappa_hides_this_defect_and_that_is_why_the_arms_use_a_far_one() -> None:
    """Stated as an arm because it is the trap, not a footnote.

    At κ = 0.6002 against a configured 0.6004 the plain pairwise loop already
    widens to four places, so the threshold survives — and an arm built on that
    κ is green against a revert of `exact_other`. It proves nothing about this
    class. The distinction is the whole reason `exact_other` is not redundant.
    """
    near = render_comparison(0.6002, _FINE_KAPPA_THRESHOLD)
    assert float(near[1]) == _FINE_KAPPA_THRESHOLD  # exact by accident
    far = render_comparison(_FAR_KAPPA, _FINE_KAPPA_THRESHOLD)
    assert float(far[1]) != _FINE_KAPPA_THRESHOLD  # truncated to 0.6


def test_the_calibration_report_states_the_threshold_that_is_in_force() -> None:
    """Through `render_report`, not through the helper — the call-site arm.

    The bullet `- threshold for κ: ...` is the line that tells a reader what
    this report's PASS/FAIL means. At three places a `--threshold-kappa 0.6004`
    run published `0.600`, under which a future κ of 0.6002 would read as
    passing against the threshold this very report printed.
    """
    report = render_report(
        _calibration_result(_FAR_KAPPA), judge_model="m", threshold_kappa=_FINE_KAPPA_THRESHOLD
    )
    m = re.search(r"- threshold for κ: (\S+)", report)
    assert m is not None, report
    assert float(m.group(1)) == _FINE_KAPPA_THRESHOLD
    assert "**PASS**" in report


def test_a_failing_calibration_report_states_it_too() -> None:
    """Both verdicts, because the bullet is rendered on the same path for each."""
    report = render_report(
        _calibration_result(0.1), judge_model="m", threshold_kappa=_FINE_KAPPA_THRESHOLD
    )
    m = re.search(r"- threshold for κ: (\S+)", report)
    assert m is not None, report
    assert float(m.group(1)) == _FINE_KAPPA_THRESHOLD
    assert "**FAIL**" in report


def test_the_cli_error_annotation_names_the_threshold_the_run_was_gated_at(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `::error::` GitHub Actions annotation, out of `_run_calibrate`.

    This is the surface this repo's CI story is built on: it is what a reviewer
    reads on a red check. Before D-029 a run gated at 0.6004 annotated
    `< threshold 0.600` — a number nobody configured.
    """
    from eval_harness import cli as cli_module

    calibration = tmp_path / "calibration.jsonl"
    calibration.write_text("")
    monkeypatch.setattr(
        cli_module, "load_calibration", lambda _p: [_calibration_result(0.1).rows[0]]
    )
    monkeypatch.setattr(cli_module, "calibrate", lambda *_a, **_k: _calibration_result(0.1))

    class _Backend:
        model = "stub-model"

        def complete(self, system: str, user: str) -> str:
            return "SCORE: 0.1\nREASONING: stub."

    monkeypatch.setattr(cli_module, "AnthropicBackend", lambda **_k: _Backend())
    rc = cli_module.main(
        [
            "calibrate",
            "--calibration",
            str(calibration),
            "--report",
            str(tmp_path / "report.md"),
            "--threshold-kappa",
            repr(_FINE_KAPPA_THRESHOLD),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    m = re.search(r"< threshold (\S+);", err)
    assert m is not None, err
    assert float(m.group(1)) == _FINE_KAPPA_THRESHOLD


def test_the_pytest_assertion_names_the_threshold_the_test_declared(
    pytester: pytest.Pytester,
) -> None:
    """Out of a real plugin run, so a call-site revert cannot stay green.

    `@pytest.mark.eval(threshold=0.6004)` with a score of 0.1: the pair differs
    at three places, so before D-029 the failure message sent the reader to
    `threshold=0.600` — a threshold the test does not declare and which they
    would not find by grepping for it.
    """
    dataset = pytester.path / "sample.jsonl"
    dataset.write_text(
        '{"id": "qa_001", "input": "q?", "expected_outputs": '
        '[{"kind": "exact", "value": "blue"}], "tags": [], '
        '"dataset_version": "demo-v0.1", '
        '"provenance": {"source": "self", "added_on": "2026-05-16"}}\n'
    )
    pytester.makepyfile(
        f"""
        import pytest
        from eval_harness.runner import DatasetEchoSource

        class _StubBackend:
            def complete(self, system, user):
                return "SCORE: 0.1\\nREASONING: stub."

        @pytest.mark.eval(
            suite="demo",
            dataset=r"{dataset}",
            answer_source=DatasetEchoSource(),
            judge_backend=_StubBackend(),
            threshold={_FINE_KAPPA_THRESHOLD!r},
        )
        def test_near(eval_row, judge_score):
            pass
        """
    )
    out = "\n".join(pytester.runpytest("-q").outlines)
    m = re.search(r"score=(\S+) < threshold=(\S+)", out)
    assert m is not None, out
    assert float(m.group(2)) == _FINE_KAPPA_THRESHOLD, (
        f"the failure message names threshold={m.group(2)}, which is not the "
        f"{_FINE_KAPPA_THRESHOLD} the test declared"
    )


def test_the_drift_report_table_states_the_caller_set_threshold() -> None:
    """Through `compute_drift` -> `render_html`, not through the helper.

    The Threshold column is four places wide and pinned there by
    `tests/test_demo_drift_published_values.py`. Four places is still a fixed
    width, so a caller-set `length_threshold=0.100004` published as `0.1000`.
    """
    from eval_harness.drift import compute_drift, render_html

    fine = 0.100004
    report = compute_drift(
        ["alpha beta gamma", "delta epsilon", "a much longer golden input here"] * 4,
        ["zeta", "eta theta iota kappa lambda mu nu xi omicron pi rho sigma"] * 4,
        length_threshold=fine,
    )
    html_out = render_html(report)
    cells = re.findall(r"<td>(\d+\.\d+)</td>", html_out)
    assert any(float(c) == fine for c in cells), (
        f"no Threshold cell reads back as the caller-set {fine}; cells were {cells}"
    )


def test_the_drift_tables_threshold_column_states_the_configured_threshold() -> None:
    """`render_html`'s three Threshold cells publish four places and now round-trip.

    The shipped `DriftThresholds` are round, so the committed report is
    unchanged — `tests/test_demo_drift_published_values.py` is the lock that
    says so. This arm is about a caller who sets one that is not.
    """
    value, other = render_comparison(0.2, 0.10004, places=4, exact_other=True)
    assert float(other) == 0.10004
    assert _places(value) == _places(other)
    # ... and the shipped default still renders at exactly four places.
    assert render_comparison(0.2, 0.10, places=4, exact_other=True) == ("0.2000", "0.1000")


# --------------------------------------------------------------------------
# The population
# --------------------------------------------------------------------------

# A configured parameter, structurally: the final segment of a name or dotted
# attribute access, against a closed set. D-028 learned this the hard way —
# keying on a *substring* flagged every SVG tick caption that happened to
# contain the word. `threshold` is the only configured float this package has
# (`--threshold-drop`, `--threshold-kappa`, `DriftThresholds`, and the
# `@pytest.mark.eval` threshold); ints like `limit` and `max_tokens` cannot be
# rounded by a float format spec and are not in scope.
_CONFIGURED_NAMES = frozenset({"threshold", "threshold_drop", "threshold_kappa"})
_FIXED_WIDTH = re.compile(r"\.\d+[feg]")


def _final_segment(node: ast.expr) -> str:
    """`report.length.threshold` -> `threshold`; `threshold_drop` -> `threshold_drop`."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_configured(node: ast.expr) -> bool:
    return _final_segment(node) in _CONFIGURED_NAMES


def _spec_text(part: ast.FormattedValue) -> str:
    if part.format_spec is None:
        return ""
    return "".join(p.value for p in part.format_spec.values if isinstance(p, ast.Constant))


def _package_modules() -> list[Path]:
    # `comparison.py` is exempt by *scope*, not by text: it is the fix, and its
    # docstring quotes every defective form on purpose. A text-keyed exemption
    # is a wildcard that keeps exempting whatever resembles the string.
    return [p for p in sorted(_PACKAGE.glob("*.py")) if p.name != "comparison.py"]


def test_no_configured_parameter_is_published_at_a_fixed_width() -> None:
    """Discover the population; do not trust the two sites the issue listed.

    **This arm and D-026's partition the surface rather than overlap.** D-026's
    (`test_no_package_message_renders_a_threshold_beside_a_fixed_width_operand`)
    *requires* a second formatted operand in the string, and was narrowed from
    V2 to V3 specifically to stop matching these two — correctly, because a
    standalone readout claims no ordering and D-026 was about orderings. This
    arm is the complement: the threshold **itself** at a fixed width, with or
    without anything beside it. Each keeps its own reason to exist and neither
    silently covers for the other.

    A `!r` conversion is not an offence: `repr` round-trips a double, which is
    exactly what the validator messages in `runner.py` and `calibration.py`
    need when they echo a rejected value back.
    """
    offenders: list[str] = []
    for path in _package_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            for part in node.values:
                if not isinstance(part, ast.FormattedValue):
                    continue
                if not _is_configured(part.value):
                    continue
                spec = _spec_text(part)
                if _FIXED_WIDTH.fullmatch(spec):
                    offenders.append(f"{path.name}:{node.lineno} {ast.unparse(part.value)}:{spec}")
    assert not offenders, (
        f"these strings publish a configured parameter at a fixed width, so the "
        f"tool misreports its own configuration: {offenders}. Route them through "
        f"`eval_harness.comparison.render_configured` (#257, D-029)."
    )


def test_every_render_comparison_call_marks_its_configured_operand() -> None:
    """The other half of the population, and the half the issue did not name.

    Six call sites pass a configured threshold as `other`. Without
    `exact_other=True` the pairwise loop stops the instant the two strings
    differ and republishes the policy at three or four places. A seventh call
    site added later inherits the same reading of which operand is which.
    """
    missing: list[str] = []
    for path in _package_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _final_segment(node.func) != "render_comparison":
                continue
            if len(node.args) < 2 or not _is_configured(node.args[1]):
                continue
            marked = any(
                kw.arg == "exact_other"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in node.keywords
            )
            if not marked:
                missing.append(f"{path.name}:{node.lineno} {ast.unparse(node.args[1])}")
    assert not missing, (
        f"these `render_comparison` calls compare against a configured threshold "
        f"but do not pass `exact_other=True`, so the threshold they print is not "
        f"necessarily the one in force: {missing} (#257, D-029)."
    )


def test_the_population_arms_are_not_vacuous() -> None:
    """Both walks find real nodes, so a green pass means something.

    Without this, a typo in either walk (matching no `JoinedStr`, or no `Call`)
    makes the arms above pass over an empty set. Counts *unconditionally* —
    after the fix the f-strings interpolating a threshold are still there, they
    just carry no format spec now.
    """
    interpolating = 0
    comparison_calls = 0
    for path in _package_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                interpolating += sum(
                    1
                    for part in node.values
                    if isinstance(part, ast.FormattedValue) and _is_configured(part.value)
                )
            elif isinstance(node, ast.Call) and _final_segment(node.func) == "render_comparison":
                comparison_calls += 1
    assert interpolating >= 4, (
        f"only {interpolating} interpolations of a configured parameter found "
        f"across the package; the discovery has stopped discovering."
    )
    assert comparison_calls == 6, (
        f"found {comparison_calls} `render_comparison` call sites, not the six "
        f"D-026 left behind. If a seventh landed, the arm above already holds it "
        f"to the rule — update this count deliberately."
    )


def test_the_configured_predicate_rejects_the_things_it_should() -> None:
    """The closed set is a closed set, and this pins both directions.

    D-028's population arm had to be redefined once because a substring match
    flagged every caption containing the word. A predicate keyed on the *final
    segment* of a dotted access against an enumerated set is what distinguishes
    `report.length.threshold` from `thresholds_seen` and from `r.mean_score`.
    An enumerated set can go stale silently, which is what the CLI arm below is
    for.
    """
    accepted = ["threshold", "threshold_drop", "threshold_kappa", "report.length.threshold"]
    # `threshold_note_text` is why the set is enumerated rather than matched by
    # suffix: `(?:^|_)threshold(?:_\w+)?$` accepts it, and it is prose.
    rejected = ["thresholds_seen", "threshold_note_text", "score", "i / 10", "r.mean_score"]
    for src in accepted:
        assert _is_configured(ast.parse(src, mode="eval").body), src
    for src in rejected:
        assert not _is_configured(ast.parse(src, mode="eval").body), src


def test_the_closed_set_covers_every_float_the_cli_accepts() -> None:
    """An enumerated set is only as good as the thing that notices it went stale.

    This is the arm that *discovers* rather than lists. Walk `cli.py` for every
    `add_argument(..., type=float, ...)`, derive the `dest` argparse would, and
    require it to be a name the population arms above recognise. A future
    `--max-drift 0.0001` lands here as a red test naming itself, rather than as
    a silent hole in a frozenset written months earlier.

    `type=float` is the operator surface. An `int` flag cannot be rounded by a
    float format spec, which is why `--limit` and `--max-tokens` are not in
    scope and why this walk filters on the type rather than on the name.
    """
    tree = ast.parse((_PACKAGE / "cli.py").read_text(encoding="utf-8"))
    float_dests: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _final_segment(node.func) != "add_argument":
            continue
        is_float = any(
            kw.arg == "type" and _final_segment(kw.value) == "float" for kw in node.keywords
        )
        if not is_float:
            continue
        explicit = [kw.value for kw in node.keywords if kw.arg == "dest"]
        if explicit and isinstance(explicit[0], ast.Constant):
            float_dests.add(str(explicit[0].value))
            continue
        flags = [a.value for a in node.args if isinstance(a, ast.Constant)]
        longest = max((f for f in flags if isinstance(f, str)), key=len, default="")
        float_dests.add(longest.lstrip("-").replace("-", "_"))
    assert float_dests, "no `type=float` arguments found in cli.py; the walk has stopped walking"
    unrecognised = sorted(float_dests - _CONFIGURED_NAMES)
    assert not unrecognised, (
        f"cli.py accepts these configured floats, and the population arms in this "
        f"module do not recognise them: {unrecognised}. Add them to "
        f"`_CONFIGURED_NAMES` and check how each one is published (#257, D-029)."
    )


# --------------------------------------------------------------------------
# The neighbours that are green against every arm but one
# --------------------------------------------------------------------------


def test_the_repr_neighbour_narrows_a_published_column() -> None:
    """`repr` round-trips, so it passes the central contract — and still fails.

    It was the first option #257's third criterion offered, and the reason to
    reject it is the reason `places` exists at all: `repr(0.1)` is `'0.1'`,
    which narrows the PR comment's long-published `0.100`. Narrowing a
    published artifact is the regression `test_demo_drift_published_values.py`
    caught in D-026, and it is not made acceptable by being correct.
    """
    assert float(repr(0.1)) == 0.1  # the contract holds ...
    assert repr(0.1) == "0.1"  # ... and it narrows anyway
    assert render_configured(0.1) == "0.100"


def test_the_g_neighbour_also_reaches_for_exponent_form() -> None:
    """`:g` narrows like `repr` and additionally prints `1e-05` in a report line.

    `render_configured` reaches exponent form only where no fixed-point
    rendering can express the value at all — five orders of magnitude further
    down than `:g` does.
    """
    assert f"{1e-5:g}" == "1e-05"
    assert render_configured(1e-5) == "0.00001"
    assert float(render_configured(1e-5)) == 1e-5


@pytest.mark.parametrize("width", [2, 3, 4, 6, 12])
def test_no_fixed_width_neighbour_survives_the_table(width: int) -> None:
    """A wider fixed width relocates the failure; it does not remove it.

    The same argument D-026 made about collisions and D-028 made about bands,
    at its simplest: for any width there is a legal `--threshold-drop` one digit
    finer, and `type=float` puts no constraint on it.
    """
    victim = 10.0 ** -(width + 1)
    assert float(f"{victim:.{width}f}") != victim
    assert float(render_configured(victim)) == victim


def test_unifying_at_two_places_would_narrow_the_pr_comment() -> None:
    """The other way to satisfy "same precision", and the one D-026 forbids.

    Both surfaces at `.2f` makes them agree and keeps the shipped default
    readable — and republishes the comment's `0.100` as `0.10`. Same precision
    is one criterion; never narrowing is the other, and only widening the header
    satisfies both.
    """
    assert f"{0.1:.2f}" == "0.10"
    assert _comment_value(render_delta_markdown(_report(0.1))) == "0.100"


def test_delegating_to_the_pairwise_rule_would_return_the_narrow_rendering() -> None:
    """`render_comparison(v, v)[0]` is the tempting one-line implementation.

    It is D-028's mistake in a new costume: the pairwise loop's stopping
    condition is about *two* numbers, and with only one there is nothing to
    separate, so it returns the starting width unwidened for every value.
    """
    assert render_comparison(0.0125, 0.0125)[0] == "0.013"
    assert render_configured(0.0125) == "0.0125"
