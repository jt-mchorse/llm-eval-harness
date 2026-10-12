"""A judge client that cannot be built is an auth failure at exit 2 (#338).

A named `ANTHROPIC_PROFILE` that does not resolve fails inside
`anthropic.Anthropic(...)`, in `AnthropicBackend.__init__`, before the
request-time path #194 classifies. Both CLI construction sites caught only
`ImportError`. Measured on main with anthropic 0.116.0, no key, an empty HOME:

    ANTHROPIC_PROFILE=nope eval-harness run ...
      anthropic.AnthropicError: Config file not found at ... (profile 'nope')
      rc=1        (the control, without the profile: rc=2)
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from eval_harness.judge import AnthropicBackend, JudgeAuthError, is_auth_error

REPO = Path(__file__).resolve().parent.parent
DATASET = REPO / "fixtures" / "sample_factuality_v1.jsonl"


class _ConfigError(Exception):
    pass


def _sdk_whose_constructor_raises(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    class _Anthropic:
        def __init__(self, **_kwargs: object) -> None:
            raise exc

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake)


def test_a_constructor_failure_is_a_judge_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cause = _ConfigError("Config file not found ... (profile 'nope')")
    _sdk_whose_constructor_raises(monkeypatch, cause)
    with pytest.raises(
        JudgeAuthError, match=r"could not set up its Anthropic client \(_ConfigError: Config"
    ) as e:
        AnthropicBackend()
    assert e.value.__cause__ is cause
    assert "ANTHROPIC_PROFILE" in str(e.value)


def test_a_constructor_that_works_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[dict] = []

    class _Anthropic:
        def __init__(self, **kwargs: object) -> None:
            made.append(kwargs)

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    AnthropicBackend()
    assert made == [{"max_retries": 0}]


@pytest.mark.parametrize(
    "name", ["CredentialsError", "IdentityTokenFileError", "WorkloadIdentityError"]
)
def test_the_sdk_credential_classes_are_auth_errors(name: str) -> None:
    assert is_auth_error(type(name, (Exception,), {})("no credential"))


def _cli(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    base = {
        k: v
        for k, v in os.environ.items()
        if k not in {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
    }
    return subprocess.run(
        [sys.executable, "-m", "eval_harness.cli", *args],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={**base, **env},
    )


@pytest.mark.parametrize("command", ["run", "calibrate"])
def test_a_profile_that_does_not_resolve_exits_2_with_one_error_line(
    command: str, tmp_path: Path
) -> None:
    pytest.importorskip("anthropic")
    import anthropic

    probe_env = {"HOME": str(tmp_path), "ANTHROPIC_PROFILE": "nope"}
    # Only meaningful on an SDK that resolves profiles at construction.
    saved = {
        k: os.environ.get(k)
        for k in ("HOME", "ANTHROPIC_PROFILE", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
    }
    try:
        os.environ.update(probe_env)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        try:
            anthropic.Anthropic(max_retries=0)
        except Exception:
            pass
        else:
            pytest.skip("this anthropic SDK does not resolve ANTHROPIC_PROFILE at construction")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    if command == "run":
        args = ["run", "--suite", "s", "--dataset", str(DATASET), "--db", str(tmp_path / "r.db")]
    else:
        args = [
            "calibrate",
            "--calibration",
            str(REPO / "fixtures" / "calibration.jsonl"),
            "--report",
            str(tmp_path / "rep.md"),
        ]
    proc = _cli(*args, **probe_env)
    assert proc.returncode == 2, proc.stderr[-2000:]
    assert "Traceback" not in proc.stderr
    assert "could not set up its Anthropic client" in proc.stdout + proc.stderr
