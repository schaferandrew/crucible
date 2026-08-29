#!/usr/bin/env python3
"""Direct API runner for text-only prompts (no opencode overhead).

Supports Ollama local and OpenRouter cloud models via stdlib urllib.
"""
from __future__ import annotations
import json
import os
import urllib.request
from pathlib import Path
from typing import Any


def _parse_model(model: str) -> tuple[str, str]:
    """Parse 'provider/model' or 'provider/model:tag' into (provider, model_id)."""
    if model.startswith("ollama/"):
        return "ollama", model[len("ollama/"):]
    if model.startswith("openrouter/"):
        return "openrouter", model[len("openrouter/"):]
    raise ValueError(f"Unsupported model prefix for direct mode: {model}. Use ollama/... or openrouter/...")


def _inline_fixtures(prompt_text: str, fixtures: list[str], fixtures_dir: Path) -> str:
    """Append fixture contents to the prompt so the model can see them inline."""
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
        "http://localhost:11434/api/generate",
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
    if provider == "openrouter":
        return _call_openrouter(model_id, full_prompt, timeout)
    raise ValueError(f"Unknown provider: {provider}")
