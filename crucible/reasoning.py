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
