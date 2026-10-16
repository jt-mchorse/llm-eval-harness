"""A relative `--output-dir` opens the report instead of crashing (#390).

`webbrowser.open(stable_html.as_uri())`: `Path.as_uri()` refuses a relative
path, so on main a relative `--output-dir` ran both stages, copied the report,
then raised "relative paths can't be expressed as file URIs" at exit 1. Every
other capture-demo test passes `--no-open`, so this branch never ran.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from tests.test_capture_demo_smoke import _load_capture_module


def _run(capture_demo, output_dir: str, opened: list[str]) -> int:  # type: ignore[no-untyped-def]
    with redirect_stdout(io.StringIO()):
        return capture_demo.main(
            ["--pause-seconds", "0", "--output-dir", output_dir, "--skip-sticky-cheatsheet"]
        )


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: calls.append(url) or True)
    return calls


def test_a_relative_output_dir_opens_the_absolute_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opened: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    capture_demo = _load_capture_module()
    rc = _run(capture_demo, "demo-out", opened)
    assert rc == 0
    report = (tmp_path / "demo-out" / "drift_report.html").resolve()
    assert report.exists()
    assert opened == [report.as_uri()]


def test_an_absolute_output_dir_is_unchanged(tmp_path: Path, opened: list[str]) -> None:
    capture_demo = _load_capture_module()
    rc = _run(capture_demo, str(tmp_path), opened)
    assert rc == 0
    assert opened == [(tmp_path / "drift_report.html").resolve().as_uri()]
