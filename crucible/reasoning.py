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

def levels(model: str) -> tuple[str, ...] | None:
    """The reasoning levels this model accepts, always starting with "default"; ("default",) for a
    model that doesn't reason, None when that can't be told.

    LM Studio's /api/v1/models lists each model's reasoning options (qwen3.5: off/on, gpt-oss:
    low/medium/high), so only those are offered; a loaded model with no reasoning info (some
    community MLX conversions) is asked a one-line question instead. OpenRouter lists `reasoning`
    among a model's supported parameters, and Ollama reports a `thinking` capability.
    """
    import json
    import urllib.request
    from crucible import providers
    provider, _, model_id = model.partition("/")
    try:
        if provider == "openrouter":
            data = providers._get_json(f"{providers.OPENROUTER_BASE_URL}/models").get("data", [])
            found = next((m for m in data if m["id"] == model_id), None)
            if found is None:
                return None
            return LEVELS if "reasoning" in (found.get("supported_parameters") or []) else ("default",)
        if provider == "ollama":
            req = urllib.request.Request(f"{providers.OLLAMA_BASE_URL}/api/show",
                                         data=json.dumps({"model": model_id}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            caps = json.loads(urllib.request.urlopen(req, timeout=10).read()).get("capabilities") or []
            return ("default", "off") if "thinking" in caps else ("default",)
        if provider == "lmstudio":
            return _lmstudio_levels(model_id)
    except Exception:
        return None
    return None


def supports(model: str) -> bool | None:
    """True if the model can reason, False if it can't, None when that can't be told."""
    allowed = levels(model)
    return None if allowed is None else len(allowed) > 1


def lmstudio_options_to_levels(options: list[str]) -> tuple[str, ...]:
    """LM Studio's reasoning options as crucible levels: "on" is the default, and levels crucible
    doesn't have (xhigh) are left out."""
    return ("default", *(level for level in ("off", "low", "medium", "high") if level in options))


def _lmstudio_levels(model_id: str) -> tuple[str, ...] | None:
    from crucible import providers
    base = providers.LMSTUDIO_BASE_URL.removesuffix("/v1")
    for m in providers._get_json(f"{base}/api/v1/models").get("models", []):
        ids = {m.get("key"), *(m.get("variants") or []), *(i.get("id") for i in m.get("loaded_instances") or [])}
        if model_id not in ids:
            continue
        reasoning = (m.get("capabilities") or {}).get("reasoning")
        if reasoning:
            return lmstudio_options_to_levels(reasoning.get("allowed_options") or [])
        break
    # No reasoning info: ask the model, if it's loaded (probing an unloaded one would load it)
    thinks = _lmstudio_reasons(model_id)
    return None if thinks is None else (LEVELS if thinks else ("default",))


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
