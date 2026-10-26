"""Canonical OpenRouter model IDs for well-known models.

Use these exact strings with `--model openrouter/<id>` to skip fuzzy lookup.
Update as new models are released.
"""

OPENROUTER_MODELS = {
    # Qwen
    "qwen3.8-27b": "qwen/qwen3.8-27b",
    "qwen3.6-35b": "qwen/qwen3.6-35b",
    "qwen3.5-9b": "qwen/qwen3.5-9b",
    "qwen3.5-35b-a3b": "qwen/qwen3.5-35b-a3b",

    # Nemotron
    "nemotron-3-ultra-550b": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nemotron-3.5-lightning": "nvidia/nemotron-3.5-lightning:free",

    # Laguna
    "laguna-xs-2.1": "prism-ml/laguna-xs-2.1",

    # GPT-OSS
    "gpt-oss-20b": "openai/gpt-oss-20b",

    # Gemma
    "gemma-2-24b": "google/gemma-2-24b",
    "gemma-2-9b": "google/gemma-2-9b",
    "gemma-4-12b-qat": "google/gemma-4-12b-qat",
    "gemma-4-26b-a4b-qat": "google/gemma-4-26b-a4b-qat",

    # GLM
    "glm-4.7-flash": "zai-org/glm-4.7-flash",

    # Others seen in runs
    "flint": "recursivesi/flint",
    "bonsai-27b": "prism-ml/bonsai-27b",
    "lfm2-24b-a2b": "liquid/lfm2-24b-a2b",
}


def resolve_known(model: str) -> str | None:
    """Return canonical OpenRouter ID if model is a known alias, else None."""
    return OPENROUTER_MODELS.get(model.lower().replace("_", "-"))