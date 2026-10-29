"""crucible export: a score counts only on the current test and rubric versions."""
import json

from crucible import exporter, workspace


def _run(tmp_path, test_version, rubric_version, agent_overall=8.0, inference=None):
    run_dir = tmp_path / "m" / "everyday" / "KNOW-1" / "20260101_000000"
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(json.dumps({
        "run_id": "m/everyday/KNOW-1/20260101_000000", "test_id": "KNOW-1", "agent": "direct",
        "model": "lmstudio/m", "status": "COMPLETE", "timed_out": False, "elapsed_time": 1.0,
        "started_at": "2026-01-01T00:00:00+00:00",
        "test": {"version": test_version},
        "environment": {"machine": {"hostname": "Ironwood", "cpu": "Apple MATH-1 Pro", "ram_gb": 32.0},
                        "inference": inference or {"provider": "lmstudio", "local": True, "same_machine": True,
                                                   "endpoint_host": "10.0.0.5", "quantization": "Q4_0",
                                                   "context_length": 8192}},
        "metrics": {"tokens_out": 12},
    }))
    (run_dir / "agent_results.json").write_text(json.dumps({
        "scores": {"_overall": agent_overall}, "rubric_version": rubric_version, "summary": "fine",
        "scorer": {"type": "agent", "model": "claude-opus-5-5", "prompt_version": 1}}))
    return tmp_path


def test_current_run_counts(tmp_path):
    p = workspace.load_prompt("KNOW-1")
    data = exporter.export(_run(tmp_path, p["version"], p["rubric_version"]))
    (run,) = data["runs"]
    assert run["counts"] and run["agent_score"] == 8.0 and run["tokens_out"] == 12
    assert run["hardware"]["hostname"] == "Ironwood"
    assert run["inference"]["quantization"] == "Q4_0"
    # The endpoint's address never leaves the machine
    assert "endpoint_host" not in run["inference"]
    test = next(t for t in data["tests"] if t["id"] == "KNOW-1")
    assert test["tier"] and test["version"] == p["version"]


def test_lm_link_run_reports_the_serving_machine(tmp_path):
    p = workspace.load_prompt("KNOW-1")
    served = {"provider": "lmstudio", "local": True, "same_machine": False, "served_via": "LM Link",
              "device": "Whitehall", "quantization": "Q4_K_M"}
    (run,) = exporter.export(_run(tmp_path, p["version"], p["rubric_version"], inference=served))["runs"]
    assert run["hardware"]["hostname"] == "Whitehall"
    assert run["inference"]["device"] == "Whitehall"


def test_older_test_version_does_not_count(tmp_path):
    p = workspace.load_prompt("KNOW-1")
    (run,) = exporter.export(_run(tmp_path, p["version"] - 1 or None, p["rubric_version"]))["runs"]
    assert not run["counts"] and run["agent_score"] is None


def test_stale_rubric_score_dropped(tmp_path):
    p = workspace.load_prompt("KNOW-1")
    (run,) = exporter.export(_run(tmp_path, p["version"], p["rubric_version"] + 1))["runs"]
    assert run["counts"] and run["agent_score"] is None


def test_invalid_run_is_left_out(tmp_path):
    p = workspace.load_prompt("KNOW-1")
    runs = _run(tmp_path, p["version"], p["rubric_version"])
    (meta_path,) = runs.glob("*/*/*/*/meta.json")
    meta = json.loads(meta_path.read_text())
    meta["invalid"] = {"reason": "stale server on the fixture port"}
    meta_path.write_text(json.dumps(meta))
    assert exporter.export(runs)["runs"] == []


def test_tests_carry_the_full_prompt():
    t = next(t for t in exporter.export_tests() if t["id"] == "HIST-2")
    assert t["prompt"] == workspace.load_prompt("HIST-2")["prompt"].strip()
    assert t["prompt"].startswith(t["summary"])


def test_cloud_run_exports_no_hardware(tmp_path):
    """The laptop that sent the request didn't run the model."""
    p = workspace.load_prompt("KNOW-1")
    cloud = {"provider": "openrouter", "local": False, "same_machine": None, "endpoint_host": "openrouter.ai"}
    (run,) = exporter.export(_run(tmp_path, p["version"], p["rubric_version"], inference=cloud))["runs"]
    assert run["hardware"] is None and run["hardware_key"] is None


def test_runs_before_2_4_export_null_identity(tmp_path):
    from crucible import bundle
    p = workspace.load_prompt("KNOW-1")
    data = exporter.export(_run(tmp_path, p["version"], p["rubric_version"]))
    (run,) = data["runs"]
    for key in ("run_uuid", "provenance", "model_variant", "hardware_key", "endpoint"):
        assert run[key] is None
    assert data["format_version"] == 2
    assert bundle.problems(data) == []


def test_new_runs_export_identity_and_variant(tmp_path):
    from crucible import bundle
    p = workspace.load_prompt("KNOW-1")
    runs = _run(tmp_path, p["version"], p["rubric_version"])
    (meta_path,) = runs.glob("*/*/*/*/meta.json")
    meta = json.loads(meta_path.read_text())
    meta.update({
        "run_uuid": "0b6f1d0c-5d5e-4f7f-9d2a-3c1f7b0e8a41",
        "provenance": {"crucible_version": "2.4.0", "crucible_commit": "ee2b9e1", "crucible_dirty": False,
                       "machine_id": "m_7c41e2aa0b1c"},
        "model_variant": {"publisher": "lmstudio-community", "format": "gguf", "quant": "Q4_0",
                          "reasoning_resolved": None},
        "hardware_key": "m1-pro-32gb",
        "endpoint": {"upstream": None, "resolved_model": None},
    })
    meta_path.write_text(json.dumps(meta))
    data = exporter.export(runs)
    (run,) = data["runs"]
    assert run["run_uuid"] == meta["run_uuid"] and run["hardware_key"] == "m1-pro-32gb"
    assert run["model_variant"]["format"] == "gguf" and run["provenance"]["crucible_dirty"] is False
    assert bundle.problems(data) == []
    run["provenance"]["crucible_dirty"] = "no"
    assert any("provenance.crucible_dirty" in p for p in bundle.problems(data))
