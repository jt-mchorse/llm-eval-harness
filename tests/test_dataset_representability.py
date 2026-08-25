"""`load_jsonl` must not admit a record `dump_jsonl` cannot faithfully emit (#213).

`Dataset.dump_jsonl`'s docstring claims that, together with `load_jsonl`,
``load -> dump -> re-load`` is byte-stable for any well-formed input. That was a
prose assertion, and it was false for two classes of value that the loader
accepted and `eval-harness validate` reported as ``findings=0``:

* a non-finite number anywhere on the record -- `json.loads` parses the bare
  ``NaN`` / ``Infinity`` / ``-Infinity`` tokens natively and `json.dumps`
  re-emits them, producing a line that is not JSON. Measured on the emitted
  bytes: ``JSON.parse`` raised ``SyntaxError: Unexpected token 'I'``; ``jq``
  1.7.1 parsed it silently, coercing ``Infinity`` to 1.7976931348623157e+308 and
  ``NaN`` to ``null``.
* a string with no UTF-8 encoding (a lone surrogate) -- legal JSON escape syntax
  that Python decodes, and that `dump_jsonl` then died on with
  ``UnicodeEncodeError``, *after* the file had validated clean.

This module turns the docstring into an executable property. The table below is
the probe that found the defect, kept as the regression: every row is run
through the real loader, and the rows that survive are run through
``load -> dump -> re-load -> dump`` and compared byte for byte.

The ACCEPT rows are load-bearing in both directions. They are the anti-vacuous
control: a representability check written too broadly (rejecting all non-ASCII,
say, or every string containing a codepoint outside the BMP) would make the
REJECT rows pass while quietly breaking real datasets. U+2028, U+0085, NBSP and
an astral emoji are all encodable and must keep round-tripping.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval_harness.dataset import DatasetLoadError, load_jsonl, validate_dataset


def _record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "qa_001",
        "input": "What is the capital of France?",
        "expected_outputs": [{"kind": "exact", "value": "Paris"}],
        "dataset_version": "factuality-v0.1",
        "provenance": {"source": "public_domain_trivia"},
    }
    base.update(overrides)
    return base


def _line(**overrides: object) -> str:
    return json.dumps(_record(**overrides), ensure_ascii=False) + "\n"


# (label, one-line JSONL file body). Raw text for the rows whose whole point is
# a JSON escape Python cannot re-emit -- writing those via `json.dumps` would
# defeat the fixture.
_ACCEPT: list[tuple[str, str]] = [
    ("plain ascii", _line()),
    ("non-ascii latin", _line(input="café über")),
    ("astral emoji", _line(input="\U0001f389 party")),
    ("U+2028 line separator", _line(input="a" + chr(0x2028) + "b")),
    ("U+0085 next line", _line(input="a" + chr(0x85) + "b")),
    ("U+00A0 no-break space", _line(input="a" + chr(0xA0) + "b")),
    ("escaped newline", _line(input="a\nb")),
    ("escaped carriage return", _line(input="a\rb")),
    ("escaped NUL", _line(input="a\x00b")),
    ("empty tags list", _line(tags=[])),
    ("populated tags", _line(tags=["b", "a"])),
    ("nested provenance", _line(provenance={"z": 1, "a": {"n": [1, 2]}})),
    ("huge int in provenance", _line(provenance={"n": 10**30})),
    ("ordinary float in provenance", _line(provenance={"n": 0.1})),
    ("non-ascii provenance key", _line(provenance={"café": "x"})),
]

_REJECT: list[tuple[str, str, str]] = [
    (
        "NaN in provenance",
        '{"id":"qa_001","input":"x","expected_outputs":[{"kind":"exact","value":"v"}],'
        '"dataset_version":"v0.1","provenance":{"latency_ms":NaN}}\n',
        "must be finite",
    ),
    (
        "+Infinity in provenance",
        '{"id":"qa_001","input":"x","expected_outputs":[{"kind":"exact","value":"v"}],'
        '"dataset_version":"v0.1","provenance":{"cost_usd":Infinity}}\n',
        "must be finite",
    ),
    (
        "-Infinity nested in provenance",
        '{"id":"qa_001","input":"x","expected_outputs":[{"kind":"exact","value":"v"}],'
        '"dataset_version":"v0.1","provenance":{"a":{"b":[1,-Infinity]}}}\n',
        "must be finite",
    ),
    (
        "lone high surrogate in input",
        '{"id":"qa_001","input":"a\\ud800b","expected_outputs":[{"kind":"exact","value":"v"}],'
        '"dataset_version":"v0.1","provenance":{"source":"s"}}\n',
        "not encodable as UTF-8",
    ),
    (
        "lone low surrogate in expected_outputs value",
        '{"id":"qa_001","input":"x","expected_outputs":[{"kind":"exact","value":"\\udfff"}],'
        '"dataset_version":"v0.1","provenance":{"source":"s"}}\n',
        "not encodable as UTF-8",
    ),
    (
        "lone surrogate in id",
        '{"id":"\\ud83d","input":"x","expected_outputs":[{"kind":"exact","value":"v"}],'
        '"dataset_version":"v0.1","provenance":{"source":"s"}}\n',
        "not encodable as UTF-8",
    ),
    (
        "lone surrogate in a tag",
        '{"id":"qa_001","input":"x","expected_outputs":[{"kind":"exact","value":"v"}],'
        '"dataset_version":"v0.1","provenance":{"source":"s"},"tags":["ok","a\\ud800"]}\n',
        "not encodable as UTF-8",
    ),
    (
        "lone surrogate in a provenance key",
        '{"id":"qa_001","input":"x","expected_outputs":[{"kind":"exact","value":"v"}],'
        '"dataset_version":"v0.1","provenance":{"a\\ud800b":1}}\n',
        "not encodable as UTF-8",
    ),
]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    # `surrogatepass` is needed only because the REJECT fixtures deliberately
    # carry escapes Python decodes into unencodable characters; the escapes
    # themselves are pure ASCII on disk, so nothing invalid is written.
    p.write_text(body, encoding="utf-8", errors="surrogatepass")
    return p


def test_the_table_is_not_vacuous() -> None:
    """Both halves must be populated, or the parametrized tests prove nothing."""
    assert len(_ACCEPT) >= 12
    assert len(_REJECT) >= 6


@pytest.mark.parametrize(("label", "body"), _ACCEPT, ids=[r[0] for r in _ACCEPT])
def test_representable_records_round_trip_byte_stably(
    tmp_path: Path, label: str, body: str
) -> None:
    """The docstring's guarantee, executed: dump -> re-load -> dump is identical."""
    src = _write(tmp_path, "in.jsonl", body)
    ds = load_jsonl(src)

    first = tmp_path / "first.jsonl"
    ds.dump_jsonl(first)
    second = tmp_path / "second.jsonl"
    load_jsonl(first).dump_jsonl(second)

    assert first.read_bytes() == second.read_bytes(), f"{label} was not byte-stable"
    # And what was written is real JSON, which is the point of rejecting the
    # other half of the table.
    json.loads(first.read_text(encoding="utf-8"))


@pytest.mark.parametrize(("label", "body", "expected_reason"), _REJECT, ids=[r[0] for r in _REJECT])
def test_unrepresentable_records_are_rejected_at_load(
    tmp_path: Path, label: str, body: str, expected_reason: str
) -> None:
    src = _write(tmp_path, "in.jsonl", body)
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(src)
    assert expected_reason in exc.value.reason
    assert exc.value.line_no == 1


@pytest.mark.parametrize(("label", "body", "expected_reason"), _REJECT, ids=[r[0] for r in _REJECT])
def test_the_collecting_validator_sees_exactly_what_the_loader_sees(
    tmp_path: Path, label: str, body: str, expected_reason: str
) -> None:
    """`validate_dataset` and `load_jsonl` share `_validate_record`, so this is a
    lockstep assertion, not a duplicated rule: if the check were ever added to
    only one of them, this fails."""
    src = _write(tmp_path, "in.jsonl", body)
    report = validate_dataset(src)
    assert not report.ok
    assert report.n_valid == 0
    assert [f.code for f in report.findings] == ["schema"]
    assert expected_reason in report.findings[0].reason


def test_validate_cli_exits_nonzero_on_an_unrepresentable_record(tmp_path: Path) -> None:
    """End-to-end: before #213 this printed `ok: ... findings=0` and exited 0."""
    body = (
        '{"id":"qa_001","input":"x","expected_outputs":[{"kind":"exact","value":"v"}],'
        '"dataset_version":"v0.1","provenance":{"cost_usd":Infinity}}\n'
    )
    src = _write(tmp_path, "in.jsonl", body)
    proc = subprocess.run(
        [sys.executable, "-m", "eval_harness.cli", "validate", str(src)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "provenance.cost_usd" in combined
    assert "must be finite" in combined


def test_error_message_never_carries_a_raw_unencodable_character(tmp_path: Path) -> None:
    """The offending key is itself unencodable, so a message that interpolated it
    verbatim would crash the *reporting* path when written to a UTF-8 stream."""
    body = (
        '{"id":"qa_001","input":"x","expected_outputs":[{"kind":"exact","value":"v"}],'
        '"dataset_version":"v0.1","provenance":{"a\\ud800b":1}}\n'
    )
    src = _write(tmp_path, "in.jsonl", body)
    with pytest.raises(DatasetLoadError) as exc:
        load_jsonl(src)
    # The whole rendered exception must survive a UTF-8 encode.
    str(exc.value).encode("utf-8")


def test_shipped_fixtures_are_unaffected() -> None:
    """No already-published dataset moves: the reference fixture still loads and
    `broken.jsonl` still produces exactly its four pre-existing finding codes."""
    root = Path(__file__).resolve().parents[1]
    ok = validate_dataset(root / "fixtures" / "sample_factuality_v1.jsonl")
    assert ok.ok
    assert ok.n_valid == 10

    broken = validate_dataset(root / "fixtures" / "broken.jsonl")
    assert [f.code for f in broken.findings] == [
        "parse",
        "schema",
        "duplicate_id",
        "version_drift",
    ]
