"""Tests for the clean_base_model function."""
import pytest
from crucible import runrecord


@pytest.mark.parametrize("model_id,expected", [
    # Basic cases
    ("qwen/qwen3.5-9b", ("qwen/qwen3.5-9b", None, None, None)),
    ("openai/gpt-4", ("openai/gpt-4", None, None, None)),
    
    # Provider prefixes
    ("lmstudio/qwen/qwen3.5-9b", ("qwen/qwen3.5-9b", None, None, None)),
    ("ollama/qwen3:30b", ("qwen3:30b", None, None, None)),
    ("openrouter/deepseek/deepseek-v4-flash", ("deepseek/deepseek-v4-flash", None, None, None)),
    
    # Date suffixes
    ("qwen/qwen3.5-9b-2026-10-31", ("qwen/qwen3.5-9b", None, None, None)),
    ("qwen/qwen3.5-9b-20261031", ("qwen/qwen3.5-9b", None, None, None)),
    
    # Leading ~ (OpenRouter latest alias)
    ("~openai/gpt-luna-latest", ("gpt-luna-latest", None, None, None)),
    ("~deepseek/deepseek-v4-flash", ("deepseek-v4-flash", None, None, None)),
    
    # Provider suffixes
    ("deepseek-v4.1-flash-free", ("deepseek-v4.1-flash", None, None, None)),
    ("deepseek/deepseek-v4.1-flash-free", ("deepseek/deepseek-v4.1-flash", None, None, None)),
    ("nvidia/nemotron-3-ultra-550b-a55b:free", ("nvidia/nemotron-3-ultra-550b-a55b", None, None, None)),
    
    # Quant/format tags
    ("granite-4.2-3b-mlx@4bit", ("granite-4.2-3b", "mlx", "4bit", None)),
    ("granite-4.2-3b-mlx@8bit", ("granite-4.2-3b", "mlx", "8bit", None)),
    ("model-mlx", ("model", "mlx", None, None)),
    ("model-gguf", ("model", "gguf", None, None)),
    ("model-qat", ("model", "qat", None, None)),
    
    # Google gemma with qat
    ("google/gemma-4-12b-qat", ("google/gemma-4-12b", "qat", None, None)),
    ("google/gemma-4-26b-a4b-qat", ("google/gemma-4-26b-a4b", "qat", None, None)),
    
    # Packager prefixes
    ("mlx-community/muse-glimmer-30b", ("muse-glimmer-30b", None, None, "mlx-community")),
    ("lmstudio-community/qwen3.5-9b", ("qwen3.5-9b", None, None, "lmstudio-community")),
    ("unsloth/model", ("model", None, None, "unsloth")),
    ("bartowski/model", ("model", None, None, "bartowski")),
    
    # Models without maker prefix
    ("qwen2.5-0.5b-instruct", ("qwen2.5-0.5b-instruct", None, None, None)),
    ("qwen2.5-1.5b-instruct", ("qwen2.5-1.5b-instruct", None, None, None)),
    
    # Combined cases
    ("lmstudio/mlx-community/muse-glimmer-30b", ("muse-glimmer-30b", None, None, "mlx-community")),
    ("~lmstudio/qwen/qwen3.5-9b", ("qwen/qwen3.5-9b", None, None, None)),
    
    # Edge cases
    ("", (None, None, None, None)),
    (None, (None, None, None, None)),
])
def test_clean_base_model(model_id, expected):
    result = runrecord.clean_base_model(model_id)
    assert result == expected, f"For {model_id!r}: expected {expected!r}, got {result!r}"


def test_clean_base_model_with_multiple_tags():
    """Test that multiple tags are handled correctly."""
    # Model with both quant and format
    result = runrecord.clean_base_model("model-mlx@4bit")
    # Should extract @4bit first (quant=4bit, fmt=mlx), then -mlx (fmt=mlx again)
    # The @4bit takes precedence
    assert result[0] == "model"
    assert result[2] == "4bit"  # quant
    assert result[1] == "mlx"  # format


def test_model_record_uses_clean_base():
    """Test that model_record uses the clean_base_model function."""
    result = runrecord.model_record("granite-4.2-3b-mlx@4bit", "default", None, {})
    assert result["base"] == "granite-4.2-3b"
    assert result["format"] == "mlx"
    assert result["quant"] == "4bit"


def test_model_record_with_publisher():
    """Test that model_record extracts publisher from packager prefix."""
    result = runrecord.model_record("mlx-community/muse-glimmer-30b", "default", None, {})
    assert result["base"] == "muse-glimmer-30b"
    assert result["publisher"] == "mlx-community"


def test_model_record_with_provider_suffix():
    """Test that model_record strips provider suffixes."""
    result = runrecord.model_record("deepseek-v4.1-flash-free", "default", None, {})
    assert result["base"] == "deepseek-v4.1-flash"


def test_model_record_with_tilde():
    """Test that model_record strips leading ~."""
    result = runrecord.model_record("~openai/gpt-luna-latest", "default", None, {})
    assert result["base"] == "gpt-luna-latest"
