"""Provider adapters for the code-review eval.

The harness defines two single-method protocols - `Backend.complete(system, user)`
for the judge and `AnswerSource.answer(example)` for the model under test - so
swapping providers is an adapter, not a rewrite. Three are wired here:

    anthropic  Claude via the Anthropic SDK
    zai        GLM via z.ai's OpenAI-compatible endpoint
    ollama     a local model via Ollama's NATIVE /api/chat

Ollama deliberately does not go through the OpenAI-compatible endpoint. That
endpoint has no way to express `num_ctx`, so it silently inherits Ollama's 4096
default no matter what the model supports - and a truncated judge prompt loses
the rubric before it loses anything else. `think=False` is set because the eval
scores the verdict, not the reasoning.
"""

from __future__ import annotations

import inspect
import os

DEFAULT_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

PROVIDERS = {
    "anthropic": {"model": "claude-opus-5"},
    "zai": {
        "model": "glm-4.6",
        "base_url": "https://api.z.ai/api/paas/v4",
        "key_env": "ZAI_API_KEY",
    },
    "ollama": {
        "model": "qwen3.8:27b",
        "base_url": f"{DEFAULT_OLLAMA_HOST}/v1",
        "key_env": None,
    },
}


# Deterministic scoring. The Modelfile default for both local models is
# temperature 1, which makes the same review score differently on repeated runs
# - unusable for an eval. And Ollama's own default num_ctx is 4096 regardless of
# what the model supports, so a long judge prompt (diff + full review + rubric)
# silently truncates from the FRONT, which is where the rubric lives. Both are
# set explicitly on every request rather than trusted.
TEMPERATURE = 0.0
NUM_CTX = 16384
MAX_OUTPUT = 2048


class _Ollama:
    """Native /api/chat client.

    The OpenAI-compatible endpoint cannot express num_ctx, so it is not usable
    for this eval - the context default is exactly the bug we are fixing.
    """

    def __init__(self, model: str, base_url: str, key_env=None, timeout: float = 900.0):
        import httpx

        self._url = base_url.rstrip("/").removesuffix("/v1") + "/api/chat"
        self._model = model
        self._http = httpx.Client(timeout=timeout)

    def _chat(self, system: str, user: str) -> str:
        r = self._http.post(
            self._url,
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "think": False,
                "options": {
                    "temperature": TEMPERATURE,
                    "num_ctx": NUM_CTX,
                    "num_predict": MAX_OUTPUT,
                },
            },
        )
        r.raise_for_status()
        return (r.json().get("message", {}).get("content") or "").strip()


class _OpenAICompat:
    """Shared client for OpenAI-compatible endpoints (z.ai)."""

    def __init__(self, model: str, base_url: str, key_env: str | None, timeout: float = 600.0):
        from openai import OpenAI

        key = os.environ.get(key_env) if key_env else None
        if key_env and not key:
            raise RuntimeError(f"{key_env} is not set")
        self._client = OpenAI(api_key=key or "local", base_url=base_url, timeout=timeout)
        self._model = model

    def _chat(self, system: str, user: str) -> str:
        r = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=MAX_OUTPUT,
            temperature=TEMPERATURE,
        )
        return (r.choices[0].message.content or "").strip()


def _mk(provider: str):
    """Ollama needs the native client (num_ctx); everything else is OpenAI-shaped."""
    return _Ollama if provider == "ollama" else _OpenAICompat


def _backend_cls(provider):
    base = _mk(provider)

    class Backend(base):
        def complete(self, system: str, user: str) -> str:
            return self._chat(system, user)

    return Backend


def _source_cls(provider):
    base = _mk(provider)

    class Source(base):
        def __init__(self, model, base_url, key_env, system: str, **kw):
            super().__init__(model, base_url, key_env, **kw)
            self._system = system

        def answer(self, example) -> str:
            return self._chat(self._system, example.input)

    return Source


class AnthropicBackend:
    def __init__(self, model: str):
        import anthropic

        self._c = anthropic.Anthropic()
        self._model = model
        self._extra = (
            {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
            if "fallbacks" in inspect.signature(self._c.beta.messages.create).parameters
            else {}
        )

    def _call(self, system: str, user: str) -> str:
        msg = self._c.beta.messages.create(
            model=self._model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            **self._extra,
        )
        if msg.stop_reason == "refusal":
            return "REFUSED"
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")

    def complete(self, system: str, user: str) -> str:
        return self._call(system, user)


class AnthropicSource(AnthropicBackend):
    def __init__(self, model: str, system: str):
        super().__init__(model)
        self._system = system

    def answer(self, example) -> str:
        return self._call(self._system, example.input)


def make_judge_backend(provider: str, model: str | None = None):
    cfg = PROVIDERS[provider]
    m = model or cfg["model"]
    if provider == "anthropic":
        return AnthropicBackend(m)
    return _backend_cls(provider)(m, cfg["base_url"], cfg["key_env"])


def make_source(provider: str, system: str, model: str | None = None):
    cfg = PROVIDERS[provider]
    m = model or cfg["model"]
    if provider == "anthropic":
        return AnthropicSource(m, system)
    return _source_cls(provider)(m, cfg["base_url"], cfg["key_env"], system)
