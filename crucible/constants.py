#!/usr/bin/env python3
"""Shared constants for API endpoints across Crucible modules.

Centralised here so that ``direct_runner``, ``runner``, and ``llm_judge``
all reference the same single source of truth for endpoint URLs.
No module-level imports from other ``crucible`` packages — safe from
circular imports.
"""
from __future__ import annotations

import os

# Ollama base URL (HTTP API, not OpenAI-compatible)
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# OpenAI-compatible endpoints
OLLAMA_OPENAI_API = OLLAMA_BASE_URL.rstrip("/") + "/v1"
OPENROUTER_API = "https://openrouter.ai/api/v1"
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
