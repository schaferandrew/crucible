"""Model providers crucible talks to directly: Ollama, LM Studio, OpenRouter.

One table (PROVIDERS) says, per provider, how to list its models, whether
model lookups match exactly or fuzzily, and how to stream a completion. It
backs both model resolution (crucible.models) and --agent direct.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable

LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


# --------------------------------------------------------------------------
# Model listing
# --------------------------------------------------------------------------

def _get_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def fetch_ollama_models() -> list[str]:
    """Model names from the local ollama instance ([] when unreachable)."""
    try:
        return [m["name"] for m in _get_json(f"{OLLAMA_BASE_URL}/api/tags").get("models", [])]
    except Exception:
        return []


def fetch_lmstudio_models() -> list[str]:
    """Model IDs from LM Studio's OpenAI-compatible server ([] when unreachable)."""
    try:
        data = _get_json(f"{LMSTUDIO_BASE_URL}/models").get("data", [])
        return [m["id"] for m in data if m.get("id")]
    except Exception:
        return []


def fetch_openrouter_models() -> list[str]:
    """Model IDs from OpenRouter ([] without OPENROUTER_API_KEY or when unreachable)."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return []
    try:
        data = _get_json(f"{OPENROUTER_BASE_URL}/models",
                         headers={"Authorization": f"Bearer {api_key}"}).get("data", [])
        return [m["id"] for m in data]
    except Exception:
        return []


# --------------------------------------------------------------------------
# Streaming completions (time to first token + token usage)
# --------------------------------------------------------------------------

class _StreamTimer:
    """Wall-clock timing for one streamed response."""

    def __init__(self):
        self.start = time.monotonic()
        self.first_token: float | None = None

    def token(self):
        if self.first_token is None:
            self.first_token = time.monotonic()

    def result(self, text: str, tokens_in: int | None, tokens_out: int | None) -> dict:
        return {
            "text": text,
            "ttft_s": self.first_token - self.start if self.first_token is not None else None,
            "duration_s": time.monotonic() - self.start,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }


def _call_ollama(model_id: str, prompt: str, timeout: int = 300) -> dict:
    """Streams /api/generate (NDJSON); the final chunk carries token counts."""
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=json.dumps({"model": model_id, "prompt": prompt, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timer = _StreamTimer()
    parts: list[str] = []
    tokens_in = tokens_out = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            if not raw.strip():
                continue
            chunk = json.loads(raw)
            if chunk.get("response") or chunk.get("thinking"):
                timer.token()
                parts.append(chunk.get("response") or "")
            if chunk.get("done"):
                tokens_in = chunk.get("prompt_eval_count")
                tokens_out = chunk.get("eval_count")
    return timer.result("".join(parts), tokens_in, tokens_out)


def _call_openai_compatible(url: str, model_id: str, prompt: str, timeout: int,
                            headers: dict | None = None, extra: dict | None = None) -> dict:
    """Streams /chat/completions (SSE), asking for usage in the final chunk."""
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
        **(extra or {}),
    }
    req = urllib.request.Request(
        f"{url}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    timer = _StreamTimer()
    parts: list[str] = []
    tokens_in = tokens_out = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            if chunk.get("error"):
                raise RuntimeError(f"Provider error: {chunk['error']}")
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if isinstance(content, list):
                    content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                if content or delta.get("reasoning") or delta.get("reasoning_content"):
                    timer.token()
                if content:
                    parts.append(content)
            usage = chunk.get("usage") or {}
            if usage:
                tokens_in = usage.get("prompt_tokens")
                tokens_out = usage.get("completion_tokens")
    return timer.result("".join(parts), tokens_in, tokens_out)


def _call_lmstudio(model_id: str, prompt: str, timeout: int = 300) -> dict:
    return _call_openai_compatible(LMSTUDIO_BASE_URL, model_id, prompt, timeout,
                                   extra={"temperature": 0.2})


def _call_openrouter(model_id: str, prompt: str, timeout: int = 300) -> dict:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY env var required for openrouter direct mode")
    return _call_openai_compatible(OPENROUTER_BASE_URL, model_id, prompt, timeout,
                                   headers={"Authorization": f"Bearer {api_key}"})


# --------------------------------------------------------------------------
# Provider table
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Provider:
    name: str
    list_models: Callable[[], list[str]]
    complete: Callable[[str, str, int], dict]   # (model_id, prompt, timeout)
    fuzzy_match: bool                           # False: exact name only
    empty_hint: str


# Lambdas look the functions up at call time, so tests can patch them.
PROVIDERS: dict[str, Provider] = {p.name: p for p in (
    Provider("ollama", lambda: fetch_ollama_models(),
             lambda *a: _call_ollama(*a), fuzzy_match=False,
             empty_hint="No ollama models found. Run 'ollama pull <model>' first."),
    Provider("lmstudio", lambda: fetch_lmstudio_models(),
             lambda *a: _call_lmstudio(*a), fuzzy_match=True,
             empty_hint="No LM Studio models found. Start LM Studio and load a model first."),
    Provider("openrouter", lambda: fetch_openrouter_models(),
             lambda *a: _call_openrouter(*a), fuzzy_match=True,
             empty_hint="No openrouter models found (check OPENROUTER_API_KEY)."),
)}


def split_model(model: str) -> tuple[Provider, str]:
    """'provider/model[:tag]' -> (Provider, model_id); ValueError if unsupported."""
    name, _, model_id = model.partition("/")
    if name not in PROVIDERS or not model_id:
        raise ValueError(f"Unsupported model '{model}'. Use one of: "
                         + ", ".join(f"{n}/<model>" for n in PROVIDERS))
    return PROVIDERS[name], model_id


def _fuzzy_matches(query: str, candidates: list[str]) -> list[str]:
    """Candidates containing the query, or any of its ':'/space-separated parts.

    e.g. 'qwen3.5:9b' matches 'qwen/qwen3.5-9b' via the 'qwen3.5' part.
    """
    parts = [query] + query.replace(":", " ").split()
    return [c for c in candidates if any(p.lower() in c.lower() for p in parts if p)]


def find_model_matches(query: str) -> list[str]:
    """'provider/model' strings matching a bare model name across providers."""
    matches = []
    for provider in PROVIDERS.values():
        models = provider.list_models()
        found = _fuzzy_matches(query, models) if provider.fuzzy_match else \
            [m for m in models if m == query]
        matches += [f"{provider.name}/{m}" for m in found]
    return matches


def complete(model: str, prompt: str, timeout: int = 300) -> dict:
    """Stream one completion for 'provider/model'.

    Returns {"text", "ttft_s", "duration_s", "tokens_in", "tokens_out"};
    timing/token fields are None when the provider does not report them.
    """
    provider, model_id = split_model(model)
    return provider.complete(model_id, prompt, timeout)
