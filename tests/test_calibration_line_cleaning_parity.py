"""`load_calibration` and `validate_calibration` clean a line the same way (#415).

The loader used `raw.rstrip("\\n")` while the validator used `raw_line.strip()`.
`str.strip()` also removes Unicode whitespace that JSON does not allow
(U+00A0, U+3000, `\\x1c`-`\\x1f`, ...). Measured on `main` (f547a04): with
U+00A0 prepended to row 1 of `fixtures/calibration.jsonl`,
`validate --calibration` printed `ok ... valid=50 findings=0` at exit 0, and
`load_calibration` (what `calibrate` runs) raised `line 1: invalid JSON`. That
is the validate-passes / calibrate-fails gap #217 closed for lone surrogates.

Both now `.strip()`, which is the contract `load_jsonl` / `validate_dataset`
already share.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from eval_harness import cli
from eval_harness.calibration import CalibrationLoadError, load_calibration, validate_calibration

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "calibration.jsonl"

# The three codepoints the issue names: a Latin-1 space, a CJK space and an
# ASCII control that `str.isspace()` counts but JSON's grammar does not.
EDGE_CHARS = {"nbsp": " ", "ideographic_space": "　", "file_separator": "\x1c"}


def _row(row_id: str) -> str:
    return json.dumps(
        {
            "id": row_id,
            "prompt": "p",
            "response": "r",
            "rubric": "x",
            "human_score": 0.5,
            "provenance": {},
        }
    )


def _write(tmp_path: Path, *lines: str) -> Path:
    p = tmp_path / "cal.jsonl"
    p.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return p


def _loader_accepts(p: Path) -> bool:
    try:
        load_calibration(p)
    except CalibrationLoadError:
        return False
    return True


@pytest.mark.parametrize("where", ["lead", "trail"])
@pytest.mark.parametrize("name", sorted(EDGE_CHARS))
def test_edge_whitespace_row_loads_and_validates(tmp_path: Path, name: str, where: str) -> None:
    ch = EDGE_CHARS[name]
    edged = ch + _row("a") if where == "lead" else _row("a") + ch
    p = _write(tmp_path, edged, _row("b"))
    assert ch in p.read_text(encoding="utf-8")

    rows = load_calibration(p)
    assert [r.id for r in rows] == ["a", "b"]

    report = validate_calibration(p)
    assert report.findings == ()
    assert (report.n_rows, report.n_valid) == (2, 2)


@pytest.mark.parametrize("name", sorted(EDGE_CHARS))
def test_fixture_with_edged_first_row_passes_both(tmp_path: Path, name: str) -> None:
    # The issue's exact repro: the shipped fixture with the char prepended to row 1.
    lines = FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[0] = EDGE_CHARS[name] + lines[0]
    p = tmp_path / "cal.jsonl"
    p.write_text("".join(lines), encoding="utf-8")

    report = validate_calibration(p)
    assert report.findings == ()
    assert len(load_calibration(p)) == report.n_valid == len(lines)


def test_cli_validate_ok_matches_what_calibrate_loads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = _write(tmp_path, " " + _row("a"))
    rc = cli.main(["validate", "--calibration", str(p)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "findings=0" in out
    # `calibrate` calls `load_calibration` before it builds a judge (cli.py).
    assert [r.id for r in load_calibration(p)] == ["a"]


def test_every_strippable_codepoint_gets_the_same_verdict_from_both(tmp_path: Path) -> None:
    # Search the whole space instead of trusting the three named chars: every
    # codepoint `str.strip()` removes, at either edge of a valid row, must get
    # the same accept/refuse verdict from both functions.
    disagreements = []
    for cp in range(sys.maxunicode + 1):
        ch = chr(cp)
        if not ch.isspace():
            continue
        for where in ("lead", "trail"):
            edged = ch + _row("a") if where == "lead" else _row("a") + ch
            p = tmp_path / f"cal_{cp:x}_{where}.jsonl"
            p.write_text(edged + "\n", encoding="utf-8")
            loaded = _loader_accepts(p)
            validated = validate_calibration(p).findings == ()
            if loaded != validated:
                disagreements.append((f"U+{cp:04X}", where, loaded, validated))
    assert disagreements == []


# --- controls: what neither function may accept, before or after #415 ---


def test_control_inner_nbsp_between_tokens_is_invalid_json_in_both(tmp_path: Path) -> None:
    # `.strip()` only touches the edges; non-JSON whitespace inside the object
    # is still a parse failure for both.
    p = _write(tmp_path, _row("a").replace('"id": ', '"id": '))
    with pytest.raises(CalibrationLoadError, match="invalid JSON"):
        load_calibration(p)
    report = validate_calibration(p)
    assert [(f.line_no, f.code) for f in report.findings] == [(1, "parse")]


def test_control_whitespace_only_line_is_refused_by_both(tmp_path: Path) -> None:
    p = _write(tmp_path, _row("a"), " 　")
    with pytest.raises(CalibrationLoadError) as exc:
        load_calibration(p)
    assert exc.value.line_no == 2
    report = validate_calibration(p)
    assert [(f.line_no, f.code) for f in report.findings] == [(2, "parse")]


def test_control_ascii_space_edges_already_agree(tmp_path: Path) -> None:
    # JSON's own whitespace was never in the gap: both accept it.
    p = _write(tmp_path, " \t" + _row("a") + " \t")
    assert [r.id for r in load_calibration(p)] == ["a"]
    assert validate_calibration(p).findings == ()
