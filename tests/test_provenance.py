"""Run identity and provenance in meta.json, model variant fields and the cloud endpoint."""
import json
import os
import re

from crucible import environment, provenance, providers, runner


def test_machine_id_is_minted_once(tmp_path, monkeypatch):
    path = tmp_path / "home" / "machine.json"
    monkeypatch.setenv("CRUCIBLE_MACHINE_FILE", str(path))
    first = provenance.machine_id()
    assert re.fullmatch(r"m_[0-9a-f]{12}", first)
    assert provenance.machine_id() == first
    assert json.loads(path.read_text())["machine_id"] == first


def test_capture_in_this_checkout():
    record = provenance.capture()
    assert set(record) == {"crucible_version", "crucible_commit", "crucible_dirty", "machine_id"}
    assert record["crucible_version"]
    if provenance._in_checkout():
        assert re.fullmatch(r"[0-9a-f]{7,}", record["crucible_commit"])
        assert isinstance(record["crucible_dirty"], bool)


def test_outside_git_commit_and_dirty_are_none(monkeypatch):
    monkeypatch.setattr(provenance, "_git", lambda *args: None)
    record = provenance.capture()
    assert record["crucible_commit"] is None and record["crucible_dirty"] is None


def test_ollama_publisher_from_namespace():
    assert environment.ollama_publisher("hf.co/unsloth/Qwen3-8B-GGUF:Q4_K_M") == "unsloth"
    assert environment.ollama_publisher("library/qwen3:8b") == "library"
    assert environment.ollama_publisher("qwen3:30b-a3b") is None


def test_requested_reasoning_level_is_the_resolved_one():
    assert environment.reasoning_resolved("openrouter/openai/gpt-x", "off") == "off"
    assert environment.reasoning_resolved("openrouter/openai/gpt-x", "default") is None  # can't be told


def test_lmstudio_default_reasoning_is_read_from_the_server(monkeypatch):
    listing = {"models": [{"key": "meta/muse", "variants": ["meta/muse@q4_k_m"],
                           "capabilities": {"reasoning": {"allowed_options": ["low", "high"], "default": "high"}}},
                          {"key": "mlx-community/plain", "capabilities": {}}]}
    monkeypatch.setattr(environment, "_get", lambda url, body=None: listing)
    assert environment.reasoning_resolved("lmstudio/meta/muse", "default") == "high"
    assert environment.reasoning_resolved("lmstudio/mlx-community/plain", "default") is None


def test_openrouter_endpoint(tmp_path, monkeypatch):
    (tmp_path / "direct-response.json").write_text(json.dumps(
        {"generation_id": "gen-1", "served_model": "openai/gpt-x-2026-10-01", "served_provider": "OpenAI"}))
    monkeypatch.setattr(providers, "fetch_openrouter_generation",
                        lambda gid: {"provider_name": "Azure", "model": "openai/gpt-x-2026-10-01"})
    assert environment.endpoint("openrouter/openai/gpt-x", tmp_path) == {
        "upstream": {"name": "Azure", "quant": None}, "resolved_model": "openai/gpt-x-2026-10-01"}
    # The generation endpoint unreachable: the stream's own record
    monkeypatch.setattr(providers, "fetch_openrouter_generation", lambda gid: None)
    assert environment.endpoint("openrouter/openai/gpt-x", tmp_path)["upstream"] == {"name": "OpenAI", "quant": None}
    # Nothing recorded (an agent harness, or a local model): nulls, never an error
    assert environment.endpoint("openrouter/openai/gpt-x", tmp_path / "none") == {"upstream": None, "resolved_model": None}
    assert environment.endpoint("lmstudio/qwen/qwen3.5-9b", tmp_path) == {"upstream": None, "resolved_model": None}


def test_model_variant(monkeypatch):
    monkeypatch.setattr(environment, "reasoning_resolved", lambda model, level: "off" if level == "off" else None)
    local = runner.model_variant("lmstudio/qwen/qwen3.5-9b", "off",
                                 {"publisher": "lmstudio-community", "format": "gguf", "quantization": "Q4_K_M"})
    assert local == {"publisher": "lmstudio-community", "format": "gguf", "quant": "Q4_K_M", "reasoning_resolved": "off"}
    cloud = runner.model_variant("openrouter/openai/gpt-x", "default", {"provider": "openrouter", "local": False})
    assert cloud == {"publisher": "openai", "format": None, "quant": None, "reasoning_resolved": None}


def test_hardware_key_only_for_local_runs():
    machine = {"hostname": "Ironwood", "cpu": "Apple M1 Pro", "gpu": None, "ram_gb": 32.0}
    assert runner.hardware_key({"machine": machine, "inference": {"local": True, "same_machine": True}}) == "m1-pro-32gb"
    served = {"local": True, "same_machine": False, "device": "Whitehall"}
    assert runner.hardware_key({"machine": machine, "inference": served}) == "rtx-5070-ti-16gb"
    assert runner.hardware_key({"machine": machine, "inference": {"local": False}}) is None
    unknown_peer = {"local": True, "same_machine": False, "device": "somebox"}
    assert runner.hardware_key({"machine": machine, "inference": unknown_peer}) is None


def test_machine_file_is_isolated_in_tests():
    assert os.environ["CRUCIBLE_MACHINE_FILE"] != str(provenance.Path.home() / ".crucible" / "machine.json")
