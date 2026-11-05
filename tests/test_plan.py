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


def _done(tmp_path, *, model=MODEL, requested="default", quant=None, publisher=None, resolved=None,
          variants=None, unloaded=False, expected_variant=None):
    variant = {"quant": quant, "variants": variants or [], "publisher": publisher, "reasoning": resolved}
    if unloaded:
        variant.update(unloaded=True, expected_variant=expected_variant)
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


class TestLoadedVariants:
    """One LM Studio key, two variants loaded on different devices: each run matches its own weights."""

    def test_a_loaded_sibling_does_not_hide_the_runs_weights(self, tmp_path):
        _write_run(tmp_path, quant="4bit", publisher="qwen")
        both = [{"quant": "mlx-4bit"}, {"quant": "mlx-6bit"}]
        assert _done(tmp_path, variants=both)
        # Only the 6bit sibling loaded: the 4bit weights really aren't loaded, so it isn't done
        assert not _done(tmp_path, variants=[{"quant": "mlx-6bit"}])

    def test_a_run_on_another_loaded_variant_does_not_count(self, tmp_path):
        _write_run(tmp_path, quant="6bit", publisher="qwen")
        both = [{"quant": "mlx-4bit"}, {"quant": "mlx-6bit"}]
        assert _done(tmp_path, variants=both)
        assert not _done(tmp_path, variants=[{"quant": "mlx-4bit"}])

    def test_an_unknown_loaded_set_falls_back_to_the_single_quant(self, tmp_path):
        _write_run(tmp_path, quant="6bit", publisher="qwen")
        assert _done(tmp_path, quant="6bit", variants=[])
        assert not _done(tmp_path, quant="4bit", variants=[])

    def test_weights_note_names_both_sides(self, tmp_path):
        _write_run(tmp_path, quant="4bit", publisher="qwen", reasoning="off", resolved="off")
        note = plan.weights_note(tmp_path, MODEL, "off",
                                 {"variants": [{"quant": "mlx-6bit", "artifact": "org/X-MLX-6bit"}]})
        assert "mlx-4bit" in note and "mlx-6bit" in note and "org/X-MLX-6bit" in note

    def test_weights_note_is_silent_when_the_runs_weights_are_loaded(self, tmp_path):
        _write_run(tmp_path, quant="4bit", publisher="qwen", reasoning="off", resolved="off")
        assert plan.weights_note(tmp_path, MODEL, "off", {"variants": [{"quant": "mlx-4bit"}]}) is None


class TestUnloadedPreferredVariant:
    def test_unloaded_preferred_weights_skip_matching_history_not_sibling(self, tmp_path):
        _write_run(tmp_path, quant="Q4_K_M", publisher="qwen", reasoning="off", resolved="off")
        preferred = {"quant": "q4_k_m", "publisher": "qwen"}
        # The v0 API's unloaded default says 8bit; the preferred-device resolver says Q4_K_M.
        assert _done(tmp_path, requested="off", quant="8bit", publisher="qwen", resolved="off",
                     unloaded=True, expected_variant=preferred)
        sibling = tmp_path / "sibling"
        _write_run(sibling, quant="8bit", publisher="qwen", reasoning="off", resolved="off")
        assert not _done(sibling, requested="off", quant="8bit", publisher="qwen", resolved="off",
                         unloaded=True, expected_variant=preferred)

    def test_ambiguous_unloaded_route_never_skips_on_api_default(self, tmp_path):
        _write_run(tmp_path, quant="Q4_K_M", publisher="qwen", reasoning="off", resolved="off")
        assert not _done(tmp_path, requested="off", quant=None, unloaded=True, expected_variant=None)

    def test_unloaded_weights_note_does_not_claim_weights_are_loaded(self, tmp_path):
        _write_run(tmp_path, quant="8bit", publisher="qwen", reasoning="off", resolved="off")
        note = plan.weights_note(tmp_path, MODEL, "off", {
            "unloaded": True, "expected_variant": {"quant": "q4_k_m", "device_name": "Whitehall"},
        })
        assert "mlx-8bit" in note and "will resolve to q4_k_m on Whitehall" in note
        assert "server has" not in note


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
        monkeypatch.setattr(environment, "reasoning_resolved", lambda model, level: ("on", "server"))
        assert plan.current_variant(MODEL) == {"quant": "q4_k_m", "variants": [], "publisher": "qwen",
                                               "reasoning": "on"}

    def test_explicit_reasoning_needs_no_provider_call(self, monkeypatch):
        monkeypatch.setattr(environment, "inference",
                            lambda model, device=True: {"quantization": "4bit", "publisher": "qwen"})
        monkeypatch.setattr(environment, "reasoning_resolved",
                            lambda model, level: pytest.fail("asked for the default level"))
        assert plan.current_variant(MODEL, "off") == {"quant": "mlx-4bit", "variants": [], "publisher": "qwen",
                                                      "reasoning": "off"}

    def test_current_variant_reads_the_loaded_variant(self, monkeypatch):
        monkeypatch.setattr(environment, "_get",
                            lambda url, body=None: {"quantization": "4bit", "publisher": "qwen"})
        monkeypatch.setattr(environment, "_lms_json", lambda *args: [
            {"identifier": "qwen/qwen3.6-35b-a3b", "modelKey": "qwen/qwen3.6-35b-a3b@6bit",
             "quantization": {"name": "6bit", "bits": 6}}])
        monkeypatch.setattr(environment, "reasoning_resolved", lambda model, level: ("on", "server"))
        assert plan.current_variant("lmstudio/qwen/qwen3.6-35b-a3b") == {
            "quant": "mlx-6bit", "variants": [{"quant": "mlx-6bit", "artifact": None, "bits": 6, "device": None}],
            "publisher": "qwen", "reasoning": "on"}

    def test_current_variant_prefers_resolved_unloaded_weights_over_api_default(self, monkeypatch):
        monkeypatch.setattr(environment, "inference", lambda model, device=True: {
            "state": "not-loaded", "quantization": "8bit", "publisher": "qwen",
            "expected_variant": {"quant": "Q4_K_M", "publisher": "Qwen", "device_name": "Whitehall"},
        })
        found = plan.current_variant(MODEL, "off")
        assert found == {
            "quant": "q4_k_m", "variants": [], "publisher": "qwen", "reasoning": "off",
            "unloaded": True,
            "expected_variant": {"quant": "q4_k_m", "publisher": "qwen", "device_name": "Whitehall"},
        }

    def test_current_variant_marks_unresolved_unloaded_route_unknown(self, monkeypatch):
        monkeypatch.setattr(environment, "inference", lambda model, device=True: {
            "state": "not-loaded", "quantization": "8bit", "publisher": "qwen", "expected_variant": None,
        })
        found = plan.current_variant(MODEL, "off")
        assert found["unloaded"] and found["expected_variant"] is None
        assert found["quant"] is None and found["publisher"] is None

    def test_unloaded_preferred_peer_skips_its_weights_not_api_sibling(self, monkeypatch, tmp_path):
        link = {"deviceIdentifier": "ironwood", "deviceName": "Ironwood",
                "preferredDeviceIdentifier": "whitehall",
                "peers": [{"deviceIdentifier": "whitehall", "deviceName": "Whitehall", "status": "connected"},
                          {"deviceIdentifier": "duskfall", "deviceName": "Duskfall", "status": "connected"}]}
        available = [
            {"modelKey": "qwen/qwen3.5-9b@4bit", "quantization": {"name": "4bit"},
             "publisher": "qwen", "format": "safetensors", "deviceIdentifier": None,
             "indexedModelIdentifier": "qwen/qwen3.5-9b@org/X-MLX-4bit"},
            {"modelKey": "qwen/qwen3.5-9b@q4_k_m", "quantization": {"name": "Q4_K_M"},
             "publisher": "qwen", "format": "gguf", "deviceIdentifier": "whitehall",
             "indexedModelIdentifier": "whitehall:qwen/qwen3.5-9b@org/X-GGUF-Q4_K_M"},
            {"modelKey": "qwen/qwen3.5-9b@8bit", "quantization": {"name": "8bit"},
             "publisher": "qwen", "format": "safetensors", "deviceIdentifier": "duskfall",
             "indexedModelIdentifier": "duskfall:qwen/qwen3.5-9b@org/X-MLX-8bit"},
        ]
        def fake_lms(*args):
            return {("ps",): [], ("link", "status"): link,
                    ("ls", "qwen/qwen3.5-9b"): available}.get(args)
        monkeypatch.setattr(environment, "_get", lambda url, body=None: {
            "quantization": "8bit", "publisher": "qwen", "state": "not-loaded"})
        monkeypatch.setattr(environment, "_lms_json", fake_lms)

        current = plan.current_variant(MODEL, "off")
        assert current["quant"] == "q4_k_m" and current["expected_variant"]["device_name"] == "Whitehall"
        _write_run(tmp_path, quant="Q4_K_M", publisher="qwen", reasoning="off", resolved="off")
        assert plan.has_current_run(tmp_path, MODEL, TASK, _prompt(), "direct", "off", current)

        sibling = tmp_path / "sibling"
        _write_run(sibling, quant="8bit", publisher="qwen", reasoning="off", resolved="off")
        assert not plan.has_current_run(sibling, MODEL, TASK, _prompt(), "direct", "off", current)

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

    def test_lmstudio_unloaded_model_uses_unique_preferred_device_variant(self, monkeypatch):
        link = {"deviceIdentifier": "ironwood", "deviceName": "Ironwood",
                "preferredDeviceIdentifier": "whitehall",
                "peers": [{"deviceIdentifier": "whitehall", "deviceName": "Whitehall", "status": "connected"},
                          {"deviceIdentifier": "duskfall", "deviceName": "Duskfall", "status": "connected"}]}
        available = [
            {"modelKey": "qwen/x@4bit", "quantization": {"name": "4bit"}, "publisher": "qwen",
             "format": "safetensors", "indexedModelIdentifier": "qwen/x@org/X-MLX-4bit",
             "deviceIdentifier": None},
            {"modelKey": "qwen/x@q4_k_m", "quantization": {"name": "Q4_K_M"}, "publisher": "qwen",
             "format": "gguf", "indexedModelIdentifier": "whitehall:qwen/x@org/X-GGUF-Q4_K_M",
             "deviceIdentifier": "whitehall"},
            {"modelKey": "qwen/x@8bit", "quantization": {"name": "8bit"}, "publisher": "qwen",
             "format": "safetensors", "indexedModelIdentifier": "duskfall:qwen/x@org/X-MLX-8bit",
             "deviceIdentifier": "duskfall"},
        ]

        def fake_lms(*args):
            return {("ps",): [], ("link", "status"): link, ("ls", "qwen/x"): available}.get(args)

        monkeypatch.setattr(environment, "_get", lambda url, body=None: {
            "quantization": "8bit", "publisher": "qwen", "state": "not-loaded"})
        monkeypatch.setattr(environment, "_lms_json", fake_lms)
        found = environment._lmstudio("qwen/x", device=False)
        assert found["quantization"] == "8bit"  # raw API default remains available for diagnostics
        assert found["expected_variant"]["quant"] == "Q4_K_M"
        assert found["expected_variant"]["device_name"] == "Whitehall"
        assert found["expected_variant"]["resolution"] == "preferred"

    def test_lmstudio_unloaded_ambiguous_preferred_variants_stay_unknown(self, monkeypatch):
        link = {"deviceIdentifier": "ironwood", "preferredDeviceIdentifier": "whitehall",
                "peers": [{"deviceIdentifier": "whitehall", "status": "connected"}]}
        available = [
            {"modelKey": "qwen/x@4bit", "quantization": {"name": "4bit"}, "publisher": "qwen",
             "deviceIdentifier": "whitehall", "indexedModelIdentifier": "whitehall:qwen/x@org/X4"},
            {"modelKey": "qwen/x@6bit", "quantization": {"name": "6bit"}, "publisher": "qwen",
             "deviceIdentifier": "whitehall", "indexedModelIdentifier": "whitehall:qwen/x@org/X6"},
        ]
        def fake_lms(*args):
            return {("ps",): [], ("link", "status"): link, ("ls", "qwen/x"): available}.get(args)
        monkeypatch.setattr(environment, "_get", lambda url, body=None: {
            "quantization": "8bit", "publisher": "qwen", "state": "not-loaded"})
        monkeypatch.setattr(environment, "_lms_json", fake_lms)
        found = environment._lmstudio("qwen/x", device=False)
        assert found["expected_variant"] is None

    def test_lmstudio_unloaded_disconnected_copy_is_not_a_resolution(self, monkeypatch):
        link = {"deviceIdentifier": "ironwood", "peers": [
            {"deviceIdentifier": "offline", "status": "disconnected"}]}
        available = [{"modelKey": "qwen/x@q4_k_m", "quantization": {"name": "Q4_K_M"},
                      "publisher": "qwen", "deviceIdentifier": "offline",
                      "indexedModelIdentifier": "offline:qwen/x@org/X-Q4_K_M"}]
        def fake_lms(*args):
            return {("ps",): [], ("link", "status"): link, ("ls", "qwen/x"): available}.get(args)
        monkeypatch.setattr(environment, "_get", lambda url, body=None: {
            "quantization": "Q4_K_M", "publisher": "qwen", "state": "not-loaded"})
        monkeypatch.setattr(environment, "_lms_json", fake_lms)
        found = environment._lmstudio("qwen/x", device=False)
        assert found["expected_variant"] is None

    def test_lmstudio_unloaded_unique_local_copy_is_resolvable_when_preference_has_no_copy(self, monkeypatch):
        link = {"deviceIdentifier": "ironwood", "deviceName": "Ironwood",
                "preferredDeviceIdentifier": "whitehall",
                "peers": [{"deviceIdentifier": "whitehall", "deviceName": "Whitehall", "status": "connected"}]}
        available = [{"modelKey": "google/gemma-4-e4b@4bit", "quantization": {"name": "4bit"},
                      "publisher": "google", "deviceIdentifier": None,
                      "indexedModelIdentifier": "google/gemma-4-e4b@org/Gemma-E4B-MLX-4bit"}]
        def fake_lms(*args):
            return {("ps",): [], ("link", "status"): link,
                    ("ls", "google/gemma-4-e4b"): available}.get(args)
        monkeypatch.setattr(environment, "_get", lambda url, body=None: {
            "quantization": "4bit", "publisher": "google", "state": "not-loaded"})
        monkeypatch.setattr(environment, "_lms_json", fake_lms)
        found = environment._lmstudio("google/gemma-4-e4b", device=False)
        assert found["expected_variant"]["quant"] == "4bit"
        assert found["expected_variant"]["resolution"] == "unique"

    def test_lmstudio_ambiguous_loaded_quants_use_api_quant(self, monkeypatch):
        monkeypatch.setattr(environment, "_get",
                            lambda url, body=None: {"quantization": "4bit", "publisher": "qwen"})
        monkeypatch.setattr(environment, "_lms_json", lambda *args: [
            {"identifier": "qwen/x", "modelKey": "qwen/x@4bit", "quantization": {"name": "4bit"}},
            {"identifier": "qwen/x", "modelKey": "qwen/x@6bit", "quantization": {"name": "6bit"}}])
        assert environment._lmstudio("qwen/x", device=False)["quantization"] == "4bit"

    def test_lmstudio_lists_every_loaded_variant_of_a_key(self, monkeypatch):
        monkeypatch.setattr(environment, "_get",
                            lambda url, body=None: {"quantization": "4bit", "publisher": "qwen"})
        monkeypatch.setattr(environment, "_lms_json", lambda *args: [
            {"identifier": "qwen/x", "modelKey": "qwen/x", "quantization": {"name": "4bit", "bits": 4},
             "sizeBytes": 20429364306},
            {"identifier": "qwen/x", "modelKey": "qwen/x@6bit", "quantization": {"name": "6bit", "bits": 6},
             "sizeBytes": 29088963084,
             "indexedModelIdentifier": "hash:qwen/x@lmstudio-community/X-MLX-6bit"}])
        found = environment._lmstudio("qwen/x", device=False)
        # The base key's own API quant stays for provenance, and both loaded variants are comparable
        assert found["quantization"] == "4bit"
        assert [w["quant"] for w in found["variants"]] == ["4bit", "6bit"]
        assert [w["bits"] for w in found["variants"]] == [4, 6]
        assert found["variants"][1]["artifact"] == "lmstudio-community/X-MLX-6bit"
        # The base key's artifact stays unknown: two variants means the API's pick names neither
        assert "artifact" not in found or found["artifact"] is None

    def test_lmstudio_weights_names_the_repo_over_lm_link(self, monkeypatch):
        monkeypatch.setattr(environment, "_get",
                            lambda url, body=None: {"quantization": "4bit", "publisher": "qwen"})
        monkeypatch.setattr(environment, "_lms_json", lambda *args: [
            {"identifier": "qwen/x", "modelKey": "qwen/x@6bit", "quantization": {"name": "6bit", "bits": 6},
             "deviceIdentifier": "peer",
             "indexedModelIdentifier": "peer:qwen/x@lmstudio-community/X-MLX-6bit"}])
        found = environment._lmstudio("qwen/x", device=False)
        # Served over LM Link, so no local file: the repo still names the weights that ran
        assert found["quantization"] == "6bit"
        assert found["artifact"] == "lmstudio-community/X-MLX-6bit"

    def test_lmstudio_device_picks_the_variant_that_answers(self, monkeypatch):
        link = {"deviceIdentifier": "local", "deviceName": "Ironwood",
                "peers": [{"deviceIdentifier": "peer", "deviceName": "Duskfall"}]}
        loaded = [{"identifier": "qwen/x", "modelKey": "qwen/x", "deviceIdentifier": None,
                   "quantization": {"name": "4bit"}},
                  {"identifier": "qwen/x", "modelKey": "qwen/x@6bit", "deviceIdentifier": "peer",
                   "quantization": {"name": "6bit"}}]

        def fake_lms(*args):
            return {("ps",): loaded, ("link", "status"): link}.get(args) or []

        monkeypatch.setattr(environment, "_get",
                            lambda url, body=None: {"quantization": "4bit", "publisher": "qwen"})
        monkeypatch.setattr(environment, "_lms_json", fake_lms)
        found = environment._lmstudio("qwen/x")
        assert (found["quantization"], found["device"], found["same_machine"]) == ("4bit", "Ironwood", True)

    def test_lmstudio_variant_key_uses_the_loaded_publisher(self, monkeypatch):
        monkeypatch.setattr(environment, "_get", lambda url, body=None: {})
        monkeypatch.setattr(environment, "_lms_json", lambda *args: [
            {"identifier": "qwen/x", "modelKey": "qwen/x@6bit", "publisher": "qwen",
             "quantization": {"name": "6bit"}}] if args == ("ps",) else [])
        found = environment._lmstudio("qwen/x@6bit", device=False)
        assert (found["quantization"], found["publisher"]) == ("6bit", "qwen")

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
