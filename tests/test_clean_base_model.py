"""Model key cleanup (runrecord.clean_base_model), the corrections file, and `crucible coverage`."""
from pathlib import Path

import pytest

from crucible import bundle, coverage, runrecord, suites


@pytest.mark.parametrize("model_id,expected", [
    ("qwen/qwen3.5-9b", ("qwen/qwen3.5-9b", None, None, None)),
    # Provider prefixes go; the maker stays
    ("lmstudio/qwen/qwen3.5-9b", ("qwen/qwen3.5-9b", None, None, None)),
    ("ollama/qwen3:30b", ("qwen3:30b", None, None, None)),
    ("openrouter/deepseek/deepseek-v4-flash", ("deepseek/deepseek-v4-flash", None, None, None)),
    # Date suffixes
    ("qwen/qwen3.5-9b-2026-10-31", ("qwen/qwen3.5-9b", None, None, None)),
    ("qwen/qwen3.5-9b-20261031", ("qwen/qwen3.5-9b", None, None, None)),
    # OpenRouter's ~ latest alias: the ~ goes, the maker stays
    ("openrouter/~openai/gpt-luna-latest", ("openai/gpt-luna-latest", None, None, None)),
    ("~deepseek/deepseek-v4-flash", ("deepseek/deepseek-v4-flash", None, None, None)),
    # Only the :free tier suffix; a name that ends in -free is a name
    ("openrouter/nvidia/nemotron-3-ultra-550b-a55b:free", ("nvidia/nemotron-3-ultra-550b-a55b", None, None, None)),
    ("acme/sugar-free", ("acme/sugar-free", None, None, None)),
    # Format and quant tags
    ("lmstudio/granite-4.2-3b-mlx@4bit", ("granite-4.2-3b", "mlx", "4bit", None)),
    ("qwen/qwen3-8b-mlx-8bit", ("qwen/qwen3-8b", "mlx", "8bit", None)),
    ("acme/model-gguf", ("acme/model", "gguf", None, None)),
    # Training variants are part of the model
    ("google/gemma-4-12b-qat", ("google/gemma-4-12b-qat", None, None, None)),
    ("google/gemma-3-qat-27b", ("google/gemma-3-qat-27b", None, None, None)),
    # Packager namespaces move to the publisher; the maker isn't guessed
    ("lmstudio/mlx-community/muse-glimmer-30b", ("muse-glimmer-30b", None, None, "mlx-community")),
    ("unsloth/model-gguf", ("model", "gguf", None, "unsloth")),
    ("qwen2.5-0.5b-instruct", ("qwen2.5-0.5b-instruct", None, None, None)),
    ("", (None, None, None, None)),
    (None, (None, None, None, None)),
])
def test_clean_base_model(model_id, expected):
    assert runrecord.clean_base_model(model_id) == expected


def test_model_record_cleans_the_base():
    r = runrecord.model_record("lmstudio/granite-4.2-3b-mlx@4bit", "default", None, {})
    assert (r["base"], r["format"], r["quant"]) == ("granite-4.2-3b", "mlx", "4bit")
    assert r["reasoning"] == {"requested": "default", "resolved": None, "resolved_source": "unknown"}
    r = runrecord.model_record("openrouter/~openai/gpt-luna-latest", "high", "high", {"where": "cloud"})
    assert (r["base"], r["publisher"]) == ("openai/gpt-luna-latest", "openai")
    assert r["reasoning"]["resolved_source"] == "requested"
    r = runrecord.model_record("lmstudio/mlx-community/muse-glimmer-30b", "default", None, {})
    assert (r["base"], r["publisher"], r["format"]) == ("muse-glimmer-30b", "mlx-community", "mlx")


@pytest.mark.parametrize("base,flagged", [
    ("qwen/qwen3.5-9b", False), ("google/gemma-4-26b-a4b-qat", False),
    ("granite-4.2-3b-mlx@4bit", True), ("mlx-community/muse-glimmer-30b", True), ("~openai/gpt-luna-latest", True),
    ("nvidia/nemotron-3-ultra-550b-a55b:free", True), ("deepseek-v4.1-flash-free", True), ("laguna-xs-2.1", True),
])
def test_unnormalized(base, flagged):
    assert bool(bundle.unnormalized(base)) is flagged


def test_corrections_file_is_valid_and_every_entry_is_normalized():
    data = bundle.corrections()
    assert bundle.record_problems("corrections", data) == []
    for m in data["models"]:
        assert bundle.unnormalized(m["base"]), f"{m['base']} needs no correction"
        assert bundle.unnormalized(m["to_base"]) == [], m["to_base"]
        assert m["to_base"].split("/")[0] == m["maker"]


def test_publish_writes_corrections_and_check_warns_only_for_uncorrected(tmp_path):
    import json
    to = tmp_path / "_data" / "crucible"
    pub = bundle.Publisher(to, tmp_path / "out")
    pub.add_corrections()
    assert pub.counts["corrections"] == 1 and (to / "corrections.json").exists()
    pub.add_corrections()
    assert pub.counts["corrections"] == 1  # unchanged: not rewritten
    for i, base in enumerate(["granite-4.2-3b-mlx@4bit", "acme-model-gguf", "qwen/qwen3.5-9b"]):
        (to / "runs" / "2026-11").mkdir(parents=True, exist_ok=True)
        (to / "runs" / "2026-11" / f"{i}.json").write_text(json.dumps({"model": {"base": base}}))
    warnings = bundle.base_warnings(to)
    assert len(warnings) == 1 and "acme-model-gguf" in warnings[0]


def test_coverage_counts_like_the_dashboard(tmp_path):
    from tests.records import run_meta, write_run
    suite = suites.latest()
    pins = suites.pins(suite)
    chat = next(t for t in pins.values() if t["id"] == "capitals-not-largest-city")
    runs = tmp_path / "runs"

    def run(i, version, **extra):
        meta = run_meta(chat["id"], version, chat["rubric_version"], run_uuid=f"00000000-0000-4000-8000-00000000000{i}",
                        run_path=f"lmstudio_m/{chat['id']}/2026010{i}_000000")
        meta.update(extra)
        return write_run(runs / meta["run_path"], meta, "answer")

    run(1, chat["version"] + 1)  # not the pinned version
    result = coverage.coverage(runs, suite)
    (setup,) = result["setups"]
    assert setup["tasks_done"] == 0 and chat["id"] in setup["tasks_missing"]
    assert setup["command"].startswith("crucible run ") and setup["command"].endswith("--skip-done")
    run_dir = run(2, chat["version"])
    assert coverage.coverage(runs, suite)["setups"][0]["tasks_done"] == 1
    runrecord.add_status(run_dir, "00000000-0000-4000-8000-000000000002", invalid={"reason": "test"})
    assert coverage.coverage(runs, suite)["setups"][0]["tasks_done"] == 0
    assert result["total_tasks"] == len(pins)


def test_skip_done_reads_the_resolved_level_not_its_source(monkeypatch):
    from crucible import environment, plan
    monkeypatch.setattr(environment, "inference", lambda model, device=False: {"variants": None})
    monkeypatch.setattr(environment, "reasoning_resolved", lambda model, requested: ("high", "server"))
    assert plan.current_variant("lmstudio/meta/muse", "default")["reasoning"] == "high"
