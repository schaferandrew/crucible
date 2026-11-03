"""`--skip-done`: a run only counts for the same task version, harness, reasoning level and weights."""
import pytest

from crucible import environment, plan, versioning, workspace
from tests.records import run_meta, write_run

MODEL = "lmstudio/qwen/qwen3.5-9b"
TASK = "fire-truck-color"


def _prompt() -> dict:
    return workspace.load_task(TASK)


def _write_run(tmp_path, *, quant=None, publisher=None, reasoning="default", resolved=None,
               model=MODEL, harness="direct"):
    """A valid run of the task's current version in a temp runs dir."""
    inference = {"provider": "lmstudio", "local": True, "same_machine": True}
    if quant is not None:
        inference["quantization"] = quant
    if publisher is not None:
        inference["publisher"] = publisher
    meta = run_meta(TASK, model=model, harness=harness, inference=inference)
    meta["task"]["content_hash"] = versioning.content_hash(_prompt())
    meta["model"]["reasoning"] = {"requested": reasoning, "resolved": resolved}
    run_dir = tmp_path / workspace.model_slug(model, reasoning) / TASK / "20260101_000000"
    write_run(run_dir, meta)
    return run_dir


def _done(tmp_path, *, model=MODEL, requested="default", quant=None, publisher=None, resolved=None):
    variant = {"quant": quant, "publisher": publisher, "reasoning": resolved}
    return plan.has_current_run(tmp_path, model, TASK, _prompt(), "direct", requested, variant)


class TestQuant:
    def test_same_quant_is_done(self, tmp_path):
        _write_run(tmp_path, quant="Q4_K_M", publisher="qwen")
        assert _done(tmp_path, quant="q4_k_m", publisher="qwen")

    def test_mlx_4bit_and_gguf_q4_k_m_are_different(self, tmp_path):
        # Both are "4-bit" weights, but different artifacts: 4bit -> mlx-4bit, Q4_K_M -> q4_k_m
        _write_run(tmp_path, quant="4bit", publisher="qwen")
        assert not _done(tmp_path, quant="Q4_K_M", publisher="qwen")
        assert _done(tmp_path, quant="4bit", publisher="qwen")

    def test_different_quant_is_not_done(self, tmp_path):
        _write_run(tmp_path, quant="Q4_K_M")
        assert not _done(tmp_path, quant="8bit")

    def test_unknown_recorded_quant_matches(self, tmp_path):
        _write_run(tmp_path)
        assert _done(tmp_path, quant="q4_k_m")

    def test_unknown_live_quant_matches(self, tmp_path):
        _write_run(tmp_path, quant="Q4_K_M")
        assert _done(tmp_path, quant=None)


class TestPublisher:
    def test_different_publisher_is_not_done(self, tmp_path):
        _write_run(tmp_path, quant="Q4_K_M", publisher="lmstudio-community")
        assert not _done(tmp_path, quant="q4_k_m", publisher="unsloth")

    def test_publisher_case_is_ignored(self, tmp_path):
        _write_run(tmp_path, quant="Q4_K_M", publisher="Qwen")
        assert _done(tmp_path, quant="q4_k_m", publisher="qwen")

    def test_unknown_publisher_matches(self, tmp_path):
        _write_run(tmp_path, quant="Q4_K_M")
        assert _done(tmp_path, quant="q4_k_m", publisher="unsloth")
        _write_run(tmp_path, quant="Q4_K_M", publisher="unsloth")
        assert _done(tmp_path, quant="q4_k_m", publisher=None)


class TestReasoning:
    def test_different_resolved_level_is_not_done(self, tmp_path):
        _write_run(tmp_path, quant="Q4_K_M", resolved="on")
        assert not _done(tmp_path, quant="q4_k_m", resolved="high")

    def test_unknown_resolved_level_matches(self, tmp_path):
        _write_run(tmp_path, quant="Q4_K_M", resolved=None)
        assert _done(tmp_path, quant="q4_k_m", resolved="high")

    def test_different_requested_level_is_not_done(self, tmp_path):
        _write_run(tmp_path, quant="Q4_K_M", reasoning="off", resolved="off")
        assert _done(tmp_path, quant="q4_k_m", requested="off")
        assert not _done(tmp_path, quant="q4_k_m", requested="default")


class TestCloud:
    def test_cloud_run_has_nothing_to_compare(self, tmp_path):
        _write_run(tmp_path, model="openrouter/qwen/qwen3.8-flash")
        assert _done(tmp_path, model="openrouter/qwen/qwen3.8-flash")


class TestProbe:
    def test_current_variant_normalizes_and_resolves(self, monkeypatch):
        monkeypatch.setattr(environment, "inference",
                            lambda model, device=True: {"quantization": "Q4_K_M", "publisher": "Qwen"})
        monkeypatch.setattr(environment, "reasoning_resolved", lambda model, level: "on")
        assert plan.current_variant(MODEL) == {"quant": "q4_k_m", "publisher": "qwen", "reasoning": "on"}

    def test_explicit_reasoning_needs_no_provider_call(self, monkeypatch):
        monkeypatch.setattr(environment, "inference",
                            lambda model, device=True: {"quantization": "4bit", "publisher": "qwen"})
        monkeypatch.setattr(environment, "reasoning_resolved",
                            lambda model, level: pytest.fail("asked for the default level"))
        assert plan.current_variant(MODEL, "off") == {"quant": "mlx-4bit", "publisher": "qwen", "reasoning": "off"}

    def test_current_variant_reads_the_loaded_variant(self, monkeypatch):
        monkeypatch.setattr(environment, "_get",
                            lambda url, body=None: {"quantization": "4bit", "publisher": "qwen"})
        monkeypatch.setattr(environment, "_lms_json", lambda *args: [
            {"identifier": "qwen/qwen3.6-35b-a3b", "modelKey": "qwen/qwen3.6-35b-a3b@6bit",
             "quantization": {"name": "6bit", "bits": 6}}])
        monkeypatch.setattr(environment, "reasoning_resolved", lambda model, level: "on")
        assert plan.current_variant("lmstudio/qwen/qwen3.6-35b-a3b") == {
            "quant": "mlx-6bit", "publisher": "qwen", "reasoning": "on"}

    def test_lmstudio_loaded_variant_wins(self, monkeypatch):
        monkeypatch.setattr(environment, "_get",
                            lambda url, body=None: {"quantization": "4bit", "publisher": "qwen",
                                                    "compatibility_type": "mlx"})
        monkeypatch.setattr(environment, "_lms_json", lambda *args: [
            {"identifier": "qwen/qwen3.6-35b-a3b", "modelKey": "qwen/qwen3.6-35b-a3b@6bit",
             "quantization": {"name": "6bit", "bits": 6}}])
        found = environment._lmstudio("qwen/qwen3.6-35b-a3b", device=False)
        assert found["quantization"] == "6bit"

    def test_lmstudio_unloaded_model_uses_api_quant(self, monkeypatch):
        monkeypatch.setattr(environment, "_get",
                            lambda url, body=None: {"quantization": "4bit", "publisher": "qwen"})
        monkeypatch.setattr(environment, "_lms_json", lambda *args: [])
        assert environment._lmstudio("qwen/qwen3.6-35b-a3b", device=False)["quantization"] == "4bit"

    def test_lmstudio_ambiguous_loaded_quants_use_api_quant(self, monkeypatch):
        monkeypatch.setattr(environment, "_get",
                            lambda url, body=None: {"quantization": "4bit", "publisher": "qwen"})
        monkeypatch.setattr(environment, "_lms_json", lambda *args: [
            {"identifier": "qwen/x", "modelKey": "qwen/x@4bit", "quantization": {"name": "4bit"}},
            {"identifier": "qwen/x", "modelKey": "qwen/x@6bit", "quantization": {"name": "6bit"}}])
        assert environment._lmstudio("qwen/x", device=False)["quantization"] == "4bit"

    def test_lmstudio_variant_probe_skips_device_calls(self, monkeypatch):
        calls = []

        def fake_lms(*args):
            calls.append(args)
            return ([{"identifier": "qwen/qwen3.5-9b", "modelKey": "qwen/qwen3.5-9b@4bit",
                      "quantization": {"name": "4bit"}}] if args == ("ps",) else [])

        monkeypatch.setattr(environment, "_get",
                            lambda url, body=None: {"quantization": "4bit", "publisher": "qwen",
                                                    "compatibility_type": "mlx"})
        monkeypatch.setattr(environment, "_lms_json", fake_lms)
        found = environment._lmstudio("qwen/qwen3.5-9b", device=False)
        assert (found["quantization"], found["publisher"], found["format"]) == ("4bit", "qwen", "mlx")
        assert ("ps",) in calls
        assert ("link", "status") not in calls and ("ls",) not in calls

    def test_build_probes_once_for_the_whole_sweep(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(plan, "current_variant",
                            lambda model, reasoning="default": calls.append(model) or {"quant": "q4_k_m"})
        _write_run(tmp_path, quant="Q4_K_M", publisher="qwen")
        built = plan.build(MODEL, [TASK], skip_done=True, runs_dir=tmp_path)
        assert calls == [MODEL] and built.skipped_done == [TASK]

    def test_build_does_not_probe_without_runs(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(plan, "current_variant", lambda model, reasoning="default": calls.append(model) or {})
        built = plan.build(MODEL, [TASK], skip_done=True, runs_dir=tmp_path)
        assert calls == [] and built.steps

    def test_direct_caller_probes_the_live_variant(self, monkeypatch, tmp_path):
        _write_run(tmp_path, quant="Q4_K_M", publisher="qwen")
        monkeypatch.setattr(plan, "current_variant", lambda model, reasoning="default": {"quant": "4bit"})
        assert not plan.has_current_run(tmp_path, MODEL, TASK, _prompt(), "direct")
        monkeypatch.setattr(plan, "current_variant", lambda model, reasoning="default": {"quant": "q4_k_m"})
        assert plan.has_current_run(tmp_path, MODEL, TASK, _prompt(), "direct")
