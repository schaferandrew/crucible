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


def _context(n) -> str:
    return f"{n // 1000}k ctx" if isinstance(n, int) and n >= 1000 else ""


def catalog_ollama() -> list[tuple[str, str]]:
    """(model, detail) pairs for the model picker; raises when ollama is unreachable."""
    out = []
    for m in _get_json(f"{OLLAMA_BASE_URL}/api/tags").get("models", []):
        d = m.get("details") or {}
        out.append((m["name"], " · ".join(x for x in (d.get("parameter_size"), d.get("quantization_level")) if x)))
    return out


def catalog_lmstudio() -> list[tuple[str, str]]:
    """(model, detail) pairs; LM Studio's v0 API says what is loaded, v1 is the fallback."""
    base = LMSTUDIO_BASE_URL.removesuffix("/v1")
    try:
        data = _get_json(f"{base}/api/v0/models").get("data", [])
    except Exception:
        return [(m, "") for m in (m["id"] for m in _get_json(f"{LMSTUDIO_BASE_URL}/models").get("data", []))]
    out = []
    for m in data:
        if m.get("type") not in (None, "llm", "vlm"):
            continue   # embedding models can't be benchmarked
        loaded = m.get("state") == "loaded"
        ctx = _context(m.get("loaded_context_length") if loaded else m.get("max_context_length"))
        out.append((m["id"], " · ".join(x for x in ("loaded" if loaded else "", ctx) if x)))
    return out


def catalog_openrouter() -> list[tuple[str, str]]:
    """(model, detail) pairs; OpenRouter's model list is public, so no key is needed to browse."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    out = []
    for m in _get_json(f"{OPENROUTER_BASE_URL}/models", headers=headers).get("data", []):
        price = ""
        try:
            p_in, p_out = (float(m["pricing"][k]) * 1e6 for k in ("prompt", "completion"))
            price = "free" if p_in == p_out == 0 else f"${p_in:.2f}/${p_out:.2f} per M"
        except (KeyError, TypeError, ValueError):
            pass
        out.append((m["id"], " · ".join(x for x in (_context(m.get("context_length")), price) if x)))
    return out


def fetch_openrouter_key_usage() -> float | None:
    """Total USD billed to OPENROUTER_API_KEY so far (None without a key or when unreachable)."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None
    try:
        usage = _get_json(f"{OPENROUTER_BASE_URL}/key",
                          headers={"Authorization": f"Bearer {api_key}"}).get("data", {}).get("usage")
        return float(usage) if usage is not None else None
    except Exception:
        return None


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
    catalog: Callable[[], list[tuple[str, str]]]   # (model_id, detail) for the picker; raises if unreachable


# Lambdas look the functions up at call time, so tests can patch them.
PROVIDERS: dict[str, Provider] = {p.name: p for p in (
    Provider("ollama", lambda: fetch_ollama_models(),
             lambda *a: _call_ollama(*a), fuzzy_match=False,
             empty_hint="No ollama models found. Run 'ollama pull <model>' first.",
             catalog=lambda: catalog_ollama()),
    Provider("lmstudio", lambda: fetch_lmstudio_models(),
             lambda *a: _call_lmstudio(*a), fuzzy_match=True,
             empty_hint="No LM Studio models found. Start LM Studio and load a model first.",
             catalog=lambda: catalog_lmstudio()),
    Provider("openrouter", lambda: fetch_openrouter_models(),
             lambda *a: _call_openrouter(*a), fuzzy_match=True,
             empty_hint="No openrouter models found (check OPENROUTER_API_KEY).",
             catalog=lambda: catalog_openrouter()),
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
