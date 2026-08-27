"""A calibration row that cannot be written down must not reach the judge (#217).

`#213` taught the golden-dataset loader to reject a record the canonical writer
cannot emit, and `#215` taught `drift.compute_drift` the same. The calibration
loader -- whose validator's docstring says it "mirrors" `validate_dataset`, and
which exists so an operator "can fix every issue before `eval-harness calibrate`
spends judge tokens" -- was not in that enumeration.

Measured before this change, on a 3-row file that is **pure ASCII on disk** (the
surrogate is the six-character escape ``\\ud800``)::

    validate --calibration        -> exit 0, "ok: ... rows=3 valid=3 findings=0"
    validate --calibration --json -> exit 0, "ok": true
    calibrate --report            -> all 3 rows judged, then
                                     UnicodeEncodeError at the report write,
                                     exit 1, no report

Exit 1 on `calibrate` is the "Cohen's kappa below threshold" outcome, so the
crash and the legitimate finding were the same signal -- and the pre-flight that
exists to prevent exactly this said the file was fine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness.calibration import (
    CalibrationLoadError,
    load_calibration,
    validate_calibration,
)
from eval_harness.dataset import _find_unrepresentable
from eval_harness.io_utils import NON_FINITE, UNENCODABLE, find_unrepresentable

# A lone surrogate, built from its codepoint rather than written as a literal.
# A literal here would put a real surrogate in this module's own constants --
# which `test_source_representability.py` refuses, for the reason it explains.
LONE = chr(0xD800)

#: A valid surrogate PAIR escape. `json.loads` combines the two escapes into one
#: U+1F389 codepoint, which encodes fine, so the rule is "does `.encode('utf-8')`
#: succeed", never "does the source contain an escape above U+FFFF".
PARTY = chr(0x1F389)

#: U+FFFD REPLACEMENT CHARACTER. Ordinary text, and encodable -- included in the
#: lockstep table because it is what a *decoder* substitutes, so it is the
#: nearest neighbour to the class under test that must stay accepted.
REPLACEMENT = chr(0xFFFD)


def _row(**over: object) -> dict:
    base: dict = {
        "id": "row-1",
        "prompt": "p",
        "response": "r",
        "rubric": "rb",
        "human_score": 0.5,
        "provenance": {"source": "hand"},
    }
    base.update(over)
    return base


def _write(tmp_path: Path, *rows: dict) -> Path:
    p = tmp_path / "cal.jsonl"
    # `ensure_ascii=True` (the default) writes the surrogate as the escape
    # `\ud800`, so the file on disk is pure ASCII -- which is the whole point:
    # nothing about the bytes is malformed.
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


# --- the four declared string fields, plus the free-form object -------------

FIELD_CASES = [
    ("id", {"id": f"row-{LONE}-1"}, "id"),
    ("prompt", {"prompt": f"a{LONE}b"}, "prompt"),
    ("response", {"response": f"a{LONE}b"}, "response"),
    ("rubric", {"rubric": f"grade{LONE}this"}, "rubric"),
    ("provenance value", {"provenance": {"source": LONE}}, "provenance.source"),
    ("provenance key", {"provenance": {LONE: "hand"}}, "(object key)"),
    ("nested in provenance", {"provenance": {"a": {"b": [LONE]}}}, "provenance.a.b[0]"),
]
FIELD_IDS = [c[0] for c in FIELD_CASES]


@pytest.mark.parametrize(("label", "over", "path_frag"), FIELD_CASES, ids=FIELD_IDS)
def test_strict_loader_rejects(tmp_path: Path, label: str, over: dict, path_frag: str) -> None:
    p = _write(tmp_path, _row(**over))
    with pytest.raises(CalibrationLoadError) as ei:
        load_calibration(p)
    assert ei.value.line_no == 1
    assert path_frag in ei.value.reason
    assert "not encodable as UTF-8" in ei.value.reason
    # The reason names the harm THIS seam has, not the one `dataset` has.
    assert "judge tokens" in ei.value.reason


@pytest.mark.parametrize(("label", "over", "path_frag"), FIELD_CASES, ids=FIELD_IDS)
def test_collecting_validator_reports(
    tmp_path: Path, label: str, over: dict, path_frag: str
) -> None:
    """Same file, the other road. Both go through `_row_from_dict`, so they
    cannot answer differently -- that is the point of fixing the choke point
    rather than each caller."""
    p = _write(tmp_path, _row(**over))
    report = validate_calibration(p)
    assert not report.ok
    assert report.n_valid == 0
    assert len(report.findings) == 1
    finding = report.findings[0]
    # `schema` is the code `validate_dataset` routes this shape to; the two
    # validators' JSON contracts stay uniform.
    assert finding.code == "schema"
    assert path_frag in finding.reason


def test_error_message_never_emits_the_raw_offender(tmp_path: Path) -> None:
    """The reason is written to stderr, so it must itself be encodable.

    The offending value is exactly the thing that cannot be encoded, so a message
    interpolating it verbatim would make the *error path* die the same way the
    write it warns about does.
    """
    p = _write(tmp_path, _row(provenance={LONE: LONE}))
    report = validate_calibration(p)
    (finding,) = report.findings
    finding.reason.encode("utf-8")  # must not raise
    assert LONE not in finding.reason


# --- what must NOT be rejected ----------------------------------------------


def test_valid_surrogate_pair_is_unaffected(tmp_path: Path) -> None:
    p = _write(tmp_path, _row(id=f"party-{PARTY}", prompt=PARTY, provenance={PARTY: PARTY}))
    rows = load_calibration(p)
    assert rows[0].id == f"party-{PARTY}"
    assert validate_calibration(p).ok


def test_non_finite_in_provenance_is_deliberately_not_rejected(tmp_path: Path) -> None:
    """The scoping decision, pinned as a test rather than left in a comment.

    `dataset` enforces NON_FINITE because `dump_jsonl` re-emits the record and a
    bare `NaN` token is not JSON. Nothing writes a calibration record back out,
    and `human_score` -- the only number with a consumer -- is already
    range-checked. Enforcing an axis with no consequence to name is how a guard
    drifts from the harm it was written for, so the absence is documented here.

    `human_score` itself stays rejected, by that range check, below.
    """
    p = tmp_path / "cal.jsonl"
    # `json.dumps` emits a bare `NaN` token and `json.loads` accepts it back.
    p.write_text(json.dumps(_row(provenance={"drift": float("nan")})) + "\n", encoding="utf-8")
    assert validate_calibration(p).ok

    p2 = tmp_path / "bad_score.jsonl"
    p2.write_text(json.dumps(_row(human_score=float("nan"))) + "\n", encoding="utf-8")
    assert not validate_calibration(p2).ok


def test_shape_errors_still_win_the_message(tmp_path: Path) -> None:
    """A row with both a shape error and an unencodable value reports the shape
    error -- the more fundamental diagnosis -- matching `_validate_record`'s
    ordering (#213)."""
    p = _write(tmp_path, {"id": f"x{LONE}", "prompt": "p"})
    report = validate_calibration(p)
    (finding,) = report.findings
    assert "missing required fields" in finding.reason


def test_only_the_bad_row_is_dropped(tmp_path: Path) -> None:
    p = _write(tmp_path, _row(id="a"), _row(id=f"b{LONE}"), _row(id="c"))
    report = validate_calibration(p)
    assert (report.n_rows, report.n_valid, len(report.findings)) == (3, 2, 1)
    assert report.findings[0].line_no == 2


# --- the two record-level enforcement sites answer identically --------------

LOCKSTEP_INPUTS = [
    "plain",
    LONE,
    f"a{LONE}b",
    PARTY,
    chr(0xDFFF),
    chr(0xDC80),  # what `surrogateescape` produces from an undecodable byte
    "",
    " ",
    REPLACEMENT,
    "\t\n",
]


@pytest.mark.parametrize("value", LOCKSTEP_INPUTS, ids=[ascii(v) for v in LOCKSTEP_INPUTS])
def test_dataset_and_calibration_agree_on_every_string(value: str) -> None:
    """The reason the walk was promoted to `io_utils`: one detector, so the two
    record-level sites cannot drift. Asserted over a table rather than by reading
    both implementations."""
    record = {"free": value}
    dataset_verdict = _find_unrepresentable(record) is not None
    calibration_verdict = find_unrepresentable(record, kinds=frozenset({UNENCODABLE})) is not None
    assert dataset_verdict == calibration_verdict
    # ... and both agree with the ground truth: does it encode?
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        encodable = False
    else:
        encodable = True
    assert dataset_verdict is not encodable


def test_kinds_selects_the_axis() -> None:
    """`kinds` is load-bearing, not decoration."""
    both = {"s": LONE, "f": float("inf")}
    assert find_unrepresentable(both, kinds=frozenset({NON_FINITE}))[1] == NON_FINITE
    assert find_unrepresentable(both, kinds=frozenset({UNENCODABLE}))[1] == UNENCODABLE
    assert find_unrepresentable({"f": float("inf")}, kinds=frozenset({UNENCODABLE})) is None
    assert find_unrepresentable({"s": LONE}, kinds=frozenset({NON_FINITE})) is None


def test_deep_nesting_does_not_recurse() -> None:
    """The walk is a stack, not recursion: a record `json.loads` accepted can be
    nested to the parser's own depth limit, and a `RecursionError` is not a
    `ValueError`, so it would escape a collecting validator's catch and abort the
    whole pass instead of becoming one finding."""
    node: object = LONE
    for _ in range(3000):
        node = {"n": node}
    found = find_unrepresentable(node, kinds=frozenset({UNENCODABLE}))
    assert found is not None
    assert found[1] == UNENCODABLE
