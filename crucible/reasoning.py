#!/usr/bin/env python3
"""Reasoning (thinking) levels: part of what a model *is* in a run.

The same weights with thinking off and with thinking on high are different models for
benchmarking purposes (Artificial Analysis lists them as separate rows), so the level is
recorded in every run, kept in its own run folder, and shown as its own model on the dashboard.

"default" sends nothing and leaves the choice to the provider and model.
"""
from __future__ import annotations

LEVELS = ("default", "off", "low", "medium", "high")
LABELS = {"default": "model default", "off": "reasoning off", "low": "reasoning low",
          "medium": "reasoning medium", "high": "reasoning high"}


def validate(level: str) -> str:
    if level not in LEVELS:
        raise ValueError(f"Unknown reasoning level '{level}'; expected one of {list(LEVELS)}")
    return level


def slug_suffix(level: str) -> str:
    """Appended to a run folder's model name, so each level keeps its own runs."""
    return "" if level == "default" else f"@reasoning-{level}"


def request_params(provider: str, level: str) -> dict:
    """Extra request fields for a direct API call (verified against each provider)."""
    if level == "default":
        return {}
    if provider == "lmstudio":
        # LM Studio honors the OpenAI field; "none" turns thinking off (enable_thinking and
        # /no_think are ignored there)
        return {"reasoning_effort": "none" if level == "off" else level}
    if provider == "openrouter":
        return {"reasoning": {"enabled": False} if level == "off" else {"effort": level}}
    if provider == "ollama":
        return {"think": False if level == "off" else level}
    return {}


# --------------------------------------------------------------------------
# Does this model reason at all? (so a run only asks about levels when they mean something)
# --------------------------------------------------------------------------

def supports(model: str) -> bool | None:
    """True if the model can reason (think), False if it can't, None when that can't be told.

    OpenRouter lists `reasoning` among a model's supported parameters and Ollama reports a
    `thinking` capability. LM Studio reports neither, so a loaded model is asked a one-line
    question and watched for reasoning; a model that isn't loaded can't be told.
    """
    import json
    import urllib.request
    from crucible import providers
    provider, _, model_id = model.partition("/")
    try:
        if provider == "openrouter":
            data = providers._get_json(f"{providers.OPENROUTER_BASE_URL}/models").get("data", [])
            found = next((m for m in data if m["id"] == model_id), None)
            return None if found is None else "reasoning" in (found.get("supported_parameters") or [])
        if provider == "ollama":
            req = urllib.request.Request(f"{providers.OLLAMA_BASE_URL}/api/show",
                                         data=json.dumps({"model": model_id}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            return "thinking" in (json.loads(urllib.request.urlopen(req, timeout=10).read()).get("capabilities") or [])
        if provider == "lmstudio":
            return _lmstudio_reasons(model_id)
    except Exception:
        return None
    return None


def _lmstudio_reasons(model_id: str) -> bool | None:
    """Ask a loaded LM Studio model a trivial question and see whether any reasoning streams back."""
    import json
    import urllib.request
    from crucible import providers
    base = providers.LMSTUDIO_BASE_URL
    loaded = {m.get("id") for m in providers._get_json(f"{base.removesuffix('/v1')}/api/v0/models").get("data", [])
              if m.get("state") == "loaded"}
    if model_id not in loaded:
        return None  # probing would load it, perhaps on this machine instead of the remote one
    body = {"model": model_id, "messages": [{"role": "user", "content": "What is 2 + 2?"}],
            "stream": True, "max_tokens": 48}
    req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            for choice in json.loads(line[5:]).get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("reasoning") or delta.get("reasoning_content"):
                    return True
                if delta.get("content"):
                    return False  # answered without thinking first
    return False
