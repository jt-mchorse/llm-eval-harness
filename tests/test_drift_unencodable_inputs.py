"""A lone surrogate in a traffic sample is rejected, on both sides (#215, D-018).

`#213` closed this hole on the *dataset* seam: `load_jsonl` rejects a string
with no UTF-8 encoding because `dump_jsonl` cannot emit it. `drift` reads
through a different loader and writes through a different writer, and neither
got the rule -- even though `#213`'s own rationale names this seam as the
source ("they reach traffic samples from broken UTF-16 handling upstream").

Measured on `main` before this change, end to end through
`python -m eval_harness.drift`, with the surrogate built from `chr(0xD800)`
and serialised through `json.dumps` so the file's bytes are valid UTF-8::

    case                     exit   report written   stderr
    CONTROL clean/clean        0     yes             summary line
    CONTROL emoji pair         0     yes             summary line
    surrogate in CANDIDATE     1     NO              UnicodeEncodeError traceback
    surrogate in GOLDEN        0     yes             summary line          <- silent
    surrogate in BOTH          1     NO              UnicodeEncodeError traceback

Exit 1 is this CLI's code for *findings*. A gate that treats `1` as "drift
detected, alert the team" and `2` as "infrastructure error, retry" was told
there was drift when no report had been produced at all. The write-seam
`except OSError` could not catch it: `UnicodeEncodeError` subclasses
`ValueError`, not `OSError`.

And whether it crashed at all was decided by data *position*, not by the data
being bad, because `render_html` puts raw input text in exactly one place --
`html.escape(r.text)[:200]` over `representative_examples`::

    variant                                        picked into rep list   result
    surrogate on a highly-distant candidate row    True                   crash @4717
    surrogate on a near-duplicate of a golden row  False                  no crash
    surrogate at char 240 of a distant row         True                   no crash
    surrogate in the golden set only               n/a                    no crash

`test_rejection_does_not_depend_on_data_position` is the direct regression on
that row: all of them now raise, from one check that never consults the ranking.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from eval_harness.dataset import DatasetLoadError, load_jsonl
from eval_harness.drift import compute_drift, render_html
from eval_harness.io_utils import find_unencodable

# Built from codepoints, never written literally: a source file containing a
# literal lone surrogate has no UTF-8 encoding and so cannot be saved at all.
HIGH = chr(0xD800)
LOW = chr(0xDC00)
NUL = chr(0)
# `json.loads` combines a *valid* pair of escapes into one astral codepoint,
# which encodes fine. The rule under test is "does `.encode('utf-8')` succeed",
# never "does the source contain an escape above U+FFFF".
EMOJI = json.loads('"\\ud83c\\udf89"')

GOLDEN = [
    "how do I reset my password",
    "what is the refund policy",
    "where is my order",
    "cancel my subscription",
    "update my billing address",
    "track my shipment",
    "reset password again please",
    "refund policy details",
]
CANDIDATE = [
    "refund my order now",
    "reset password help",
    "where is order",
    "cancel plan",
]


# ----------------------------------------------------------------------
# The shared definition
# ----------------------------------------------------------------------

# (text, expected offending slice or None, expected position or None)
ENCODABILITY_TABLE: list[tuple[str, str | None, int | None]] = [
    ("plain ascii", None, None),
    ("café résumé 日本語", None, None),
    ("", None, None),
    (EMOJI, None, None),
    ("party " + EMOJI + " time", None, None),
    ("\U0001f389\U0001f389", None, None),
    ("a" + NUL + "b is encodable", None, None),
    (HIGH, HIGH, 0),
    (LOW, LOW, 0),
    ("a" + HIGH + "b", HIGH, 1),
    # Low-then-high is not a valid pair; `json.loads` leaves both as surrogates.
    (LOW + HIGH, LOW + HIGH, 0),
    (HIGH + "A", HIGH, 0),
    ("x" * 250 + HIGH, HIGH, 250),
]


@pytest.mark.parametrize(("text", "bad", "pos"), ENCODABILITY_TABLE)
def test_find_unencodable_table(text: str, bad: str | None, pos: int | None) -> None:
    result = find_unencodable(text)
    if bad is None:
        assert result is None, f"{text!r} is encodable but was flagged {result!r}"
        text.encode("utf-8")  # the property the helper claims to answer
    else:
        assert result == (bad, pos)
        with pytest.raises(UnicodeEncodeError):
            text.encode("utf-8")


@pytest.mark.parametrize(("text", "bad", "_pos"), ENCODABILITY_TABLE)
def test_dataset_and_drift_agree_on_every_row(text: str, bad: str | None, _pos: int | None) -> None:
    """One definition, two enforcement sites -- they cannot answer differently.

    `dataset.load_jsonl` (#213) and `drift.compute_drift` (#215) describe
    different consequences for the same rule. This is the lock that keeps the
    rule itself single: the same string is accepted by both or refused by both.
    """
    record = {
        "id": "qa_001",
        "input": text,
        "expected_outputs": [{"kind": "exact", "value": "x"}],
        "dataset_version": "v1",
        "provenance": {"source": "test"},
    }
    path = Path(tempfile.mkdtemp()) / "ds.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    dataset_refused = False
    try:
        load_jsonl(path)
    except DatasetLoadError:
        dataset_refused = True

    drift_refused = False
    try:
        compute_drift(GOLDEN, [text, *CANDIDATE], cluster_k=2)
    except ValueError as e:
        # Only the representability rejection counts; other input contracts on
        # this function (D-017 comparability, thresholds) are not under test.
        drift_refused = "not encodable as UTF-8" in str(e)

    assert dataset_refused == drift_refused == (bad is not None)


# ----------------------------------------------------------------------
# compute_drift rejects, on both sides
# ----------------------------------------------------------------------


def test_rejects_a_candidate_side_surrogate() -> None:
    with pytest.raises(ValueError, match=r"candidate_inputs\[0\] is not encodable as UTF-8"):
        compute_drift(GOLDEN, [HIGH + " refund", *CANDIDATE], cluster_k=2)


def test_rejects_a_golden_side_surrogate() -> None:
    """The silent row of the before-table. Golden text is never rendered, so
    this one produced a clean exit 0 and a written report on `main`."""
    with pytest.raises(ValueError, match=r"golden_inputs\[0\] is not encodable as UTF-8"):
        compute_drift(["reset " + HIGH, *GOLDEN[1:]], CANDIDATE, cluster_k=2)


def test_message_names_the_side_the_index_the_codepoint_and_the_position() -> None:
    with pytest.raises(ValueError, match="not encodable as UTF-8") as exc:
        compute_drift(GOLDEN, [*CANDIDATE, "refund my order " + HIGH], cluster_k=2)
    msg = str(exc.value)
    assert "candidate_inputs[4]" in msg
    assert repr(HIGH) in msg
    assert "at position 16" in msg
    assert "#213" in msg  # points at the rule's other enforcement site


def test_golden_is_reported_before_candidate_when_both_are_bad() -> None:
    with pytest.raises(ValueError, match=r"golden_inputs\[0\]"):
        compute_drift(["reset " + HIGH, *GOLDEN[1:]], [HIGH + " refund", *CANDIDATE], cluster_k=2)


@pytest.mark.parametrize(
    ("label", "candidate"),
    [
        # Ranked into the top-N representative examples: the only variant that
        # crashed before this change.
        ("highly distant row", ["zzz quantum flux " + HIGH, *CANDIDATE]),
        # Ranked out of the top-N: report was written, row silently absent.
        (
            "near-duplicate of golden",
            [
                "how do I reset my password " + HIGH,
                "aardvark xylophone glockenspiel",
                "quasar nebula pulsar",
                "obscure arcane lexicon",
                "unrelated gibberish tokens",
            ],
        ),
        # Past `html.escape(r.text)[:200]`: the slice dropped it.
        (
            "past the 200-char render truncation",
            ["alpha beta gamma delta epsilon " * 8 + HIGH, *CANDIDATE],
        ),
    ],
)
def test_rejection_does_not_depend_on_data_position(label: str, candidate: list[str]) -> None:
    """One check, no consultation of the ranking or of the render truncation.

    Before #215, whether the same byte aborted the run was decided by the JSD
    ranking and by the character offset. All three variants now raise for the
    same reason, and the golden-side sibling is covered above.
    """
    with pytest.raises(ValueError, match="not encodable as UTF-8"):
        compute_drift(GOLDEN, candidate, cluster_k=2, n_representative_examples=3)


# ----------------------------------------------------------------------
# Controls -- the check must not be a blanket ban on astral codepoints
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("emoji from a valid surrogate-pair escape", EMOJI),
        ("emoji inline", "refund my order " + EMOJI + " please"),
        ("astral literal", "\U0001f389 party"),
        ("accented + CJK", "café résumé 日本語"),
        ("embedded NUL", "a" + NUL + "b order"),
    ],
)
def test_encodable_unicode_still_flows_through_to_a_written_report(label: str, text: str) -> None:
    report = compute_drift(GOLDEN, [text, *CANDIDATE], cluster_k=2)
    assert report.n_candidate == len(CANDIDATE) + 1
    render_html(report).encode("utf-8")  # the operation that used to blow up


def test_control_report_is_unchanged_in_shape() -> None:
    """The guard is a rejection, not a transformation: nothing about an
    all-encodable run changes."""
    report = compute_drift(GOLDEN, CANDIDATE, cluster_k=2)
    assert report.n_golden == len(GOLDEN)
    assert report.n_candidate == len(CANDIDATE)
    assert report.n_uncomparable == (0, 0)
    render_html(report).encode("utf-8")


# ----------------------------------------------------------------------
# The CLI exit-code contract, on both entrypoints
# ----------------------------------------------------------------------


def _write_jsonl(path: Path, rows: list[str]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


ENTRYPOINTS = [
    pytest.param(["-m", "eval_harness.drift"], id="module"),
    pytest.param(["-m", "eval_harness.cli", "drift"], id="cli-subcommand"),
]

CLI_CASES = [
    pytest.param(GOLDEN, CANDIDATE, 0, id="CONTROL-clean"),
    pytest.param(GOLDEN, [EMOJI + " refund", *CANDIDATE], 0, id="CONTROL-emoji-pair"),
    pytest.param(GOLDEN, [HIGH + " refund", *CANDIDATE], 2, id="surrogate-candidate"),
    pytest.param(["reset " + HIGH, *GOLDEN[1:]], CANDIDATE, 2, id="surrogate-golden"),
    pytest.param(
        ["reset " + HIGH, *GOLDEN[1:]], [HIGH + " refund", *CANDIDATE], 2, id="surrogate-both"
    ),
    pytest.param(
        GOLDEN, ["x" * 250 + HIGH, *CANDIDATE], 2, id="surrogate-past-200-char-truncation"
    ),
]


@pytest.mark.parametrize("argv_head", ENTRYPOINTS)
@pytest.mark.parametrize(("golden", "candidate", "expected_exit"), CLI_CASES)
def test_cli_exit_code_contract(
    tmp_path: Path,
    argv_head: list[str],
    golden: list[str],
    candidate: list[str],
    expected_exit: int,
) -> None:
    """0 = clean / 1 = findings / 2 = I/O or usage error.

    Before #215 the surrogate rows exited **1** with a raw traceback -- the
    *findings* code -- having written no report.
    """
    g = _write_jsonl(tmp_path / "golden.jsonl", golden)
    c = _write_jsonl(tmp_path / "candidate.jsonl", candidate)
    out = tmp_path / "report.html"
    proc = subprocess.run(
        [
            sys.executable,
            *argv_head,
            "--golden",
            str(g),
            "--candidate",
            str(c),
            "--output",
            str(out),
            "--judge-stub",
            "--cluster-k",
            "2",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == expected_exit, proc.stderr
    if expected_exit == 0:
        assert out.exists()
        return
    assert not out.exists(), "a rejected run must not leave a report behind"
    assert "Traceback" not in proc.stderr, "must be a clean ::error:: line, not a traceback"
    assert "UnicodeEncodeError" not in proc.stderr
    error_lines = [ln for ln in proc.stderr.splitlines() if ln.startswith("::error::")]
    assert len(error_lines) == 1, proc.stderr
    assert "not encodable as UTF-8" in error_lines[0]


@pytest.mark.parametrize("argv_head", ENTRYPOINTS)
def test_a_rejected_run_leaves_an_existing_output_untouched(
    tmp_path: Path, argv_head: list[str]
) -> None:
    g = _write_jsonl(tmp_path / "golden.jsonl", GOLDEN)
    c = _write_jsonl(tmp_path / "candidate.jsonl", [HIGH + " refund", *CANDIDATE])
    out = tmp_path / "report.html"
    out.write_text("<html>previous run</html>", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            *argv_head,
            "--golden",
            str(g),
            "--candidate",
            str(c),
            "--output",
            str(out),
            "--judge-stub",
            "--cluster-k",
            "2",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert out.read_text(encoding="utf-8") == "<html>previous run</html>"


@pytest.mark.parametrize("argv_head", ENTRYPOINTS)
def test_no_temp_file_is_left_in_the_output_directory(tmp_path: Path, argv_head: list[str]) -> None:
    g = _write_jsonl(tmp_path / "golden.jsonl", GOLDEN)
    c = _write_jsonl(tmp_path / "candidate.jsonl", [HIGH + " refund", *CANDIDATE])
    out = tmp_path / "sub" / "report.html"
    proc = subprocess.run(
        [
            sys.executable,
            *argv_head,
            "--golden",
            str(g),
            "--candidate",
            str(c),
            "--output",
            str(out),
            "--judge-stub",
            "--cluster-k",
            "2",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    leftovers = list(tmp_path.rglob("*.tmp"))
    assert leftovers == [], leftovers
