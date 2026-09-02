#!/usr/bin/env python3
"""Direct API runner for text-only prompts (no opencode overhead).

Supports Ollama, LM Studio, and OpenRouter via stdlib urllib.
"""
from __future__ import annotations
import json
import os
import urllib.request
from pathlib import Path
from typing import Any


LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def _parse_model(model: str) -> tuple[str, str]:
    """Parse 'provider/model' or 'provider/model:tag' into (provider, model_id)."""
    if model.startswith("ollama/"):
        return "ollama", model[len("ollama/") :]
    if model.startswith("openrouter/"):
        return "openrouter", model[len("openrouter/") :]
    if model.startswith("lmstudio/"):
        return "lmstudio", model[len("lmstudio/") :]
    raise ValueError(f"Unsupported model prefix for direct mode: {model}. Use ollama/... , lmstudio/... , or openrouter/...")


def fetch_ollama_models() -> list[str]:
    """Fetch available model names from local ollama instance."""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def fetch_lmstudio_models() -> list[str]:
    """Fetch available model names from a local LM Studio OpenAI-compatible endpoint."""
    try:
        req = urllib.request.Request(f"{LMSTUDIO_BASE_URL}/models", method="GET")
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except Exception:
        return []


def fetch_openrouter_models() -> list[str]:
    """Fetch model IDs from OpenRouter API."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return []
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return [m["id"] for m in data.get("data", [])]
    except Exception:
        return []


def find_model_matches(model_query: str) -> list[str]:
    """Return list of 'provider/model' strings matching query across providers."""
    matches = []

    # Exact match on ollama
    ollama_models = fetch_ollama_models()
    if model_query in ollama_models:
        matches.append(f"ollama/{model_query}")

    # Fuzzy match on LM Studio
    lmstudio_models = fetch_lmstudio_models()
    query_lower = model_query.lower()
    for model_name in lmstudio_models:
        model_name_lower = model_name.lower()
        if query_lower in model_name_lower:
            matches.append(f"lmstudio/{model_name}")
            continue
        # Also match on colon-separated parts (e.g., qwen3.5:9b matches qwen/qwen-2.5-7b)
        for part in query_lower.replace(":", " ").split():
            if part and part in model_name_lower:
                matches.append(f"lmstudio/{model_name}")
                break

    # Fuzzy match on OpenRouter
    openrouter_models = fetch_openrouter_models()
    for om in openrouter_models:
        om_lower = om.lower()
        if query_lower in om_lower:
            matches.append(f"openrouter/{om}")
            continue
        # Also match on colon-separated parts (e.g., qwen3.5:9b matches qwen/qwen-2.5-7b)
        for part in query_lower.replace(":", " ").split():
            if part and part in om_lower:
                matches.append(f"openrouter/{om}")
                break

    return matches


def _inline_fixtures(prompt_text: str, fixtures: list[str] | str, fixtures_dir: Path) -> str:
    """Append fixture contents to the prompt so the model can see them inline."""
    if isinstance(fixtures, str):
        fixtures = [fixtures]
    lines = [prompt_text.rstrip()]
    for fixture_name in fixtures:
        src = fixtures_dir / fixture_name
        if not src.exists():
            lines.append(f"\n[Fixture not found: {fixture_name}]")
            continue
        if src.is_dir():
            lines.append(f"\n[Fixture is a directory: {fixture_name}]")
            continue
        lines.append(f"\n---")
        lines.append(f"FIXTURE: {fixture_name}")
        lines.append(f"---")
        lines.append(src.read_text())
    return "\n".join(lines)


def _call_ollama(model_id: str, prompt: str, timeout: int = 300) -> str:
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=json.dumps({
            "model": model_id,
            "prompt": prompt,
            "stream": False,
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    data = json.loads(resp.read())
    return data.get("response", "")


def _call_lmstudio(model_id: str, prompt: str, timeout: int = 300) -> str:
    req = urllib.request.Request(
        f"{LMSTUDIO_BASE_URL}/chat/completions",
        data=json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "stream": False,
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    data = json.loads(resp.read())
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(f"No choices in response: {data}")
    message = choices[0].get("message", {})
    if isinstance(message.get("content"), list):
        return "".join(part.get("text", "") for part in message["content"] if isinstance(part, dict))
    return message.get("content", "")


def _call_openrouter(model_id: str, prompt: str, timeout: int = 300) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY env var required for openrouter direct mode")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    data = json.loads(resp.read())
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(f"No choices in response: {data}")
    return choices[0]["message"]["content"]


def run_direct(
    prompt_text: str,
    model: str,
    fixtures: list[str],
    fixtures_dir: Path,
    timeout: int = 300,
) -> str:
    """Run a text-only prompt via direct API. Returns the model's text response."""
    provider, model_id = _parse_model(model)
    full_prompt = _inline_fixtures(prompt_text, fixtures, fixtures_dir)
    if provider == "ollama":
        return _call_ollama(model_id, full_prompt, timeout)
    if provider == "lmstudio":
        return _call_lmstudio(model_id, full_prompt, timeout)
    if provider == "openrouter":
        return _call_openrouter(model_id, full_prompt, timeout)
    raise ValueError(f"Unknown provider: {provider}")
